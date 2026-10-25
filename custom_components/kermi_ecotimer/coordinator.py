"""Coordinator for one EcoTimer: persistent connection, fast polling plus notifications."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import protocol as proto
from .const import (
    CLOCK_CHECK_INTERVAL,
    CONF_DIAL_TIMER,
    CONF_POLL_SECONDS,
    CONF_RATED_POWER,
    DEFAULT_BOOST_MINUTES,
    DEFAULT_POLL_SECONDS,
    DEFAULT_RATED_POWER,
    DOMAIN,
)
from .device import EcoTimerClient

_LOGGER = logging.getLogger(__name__)

BLE_ERRORS = (BleakError, TimeoutError)

type EcoTimerConfigEntry = ConfigEntry[EcoTimerCoordinator]


class EcoTimerCoordinator(DataUpdateCoordinator[proto.EcoTimerState]):
    """Keeps the connection open; the vendor app cannot connect while Home Assistant is connected."""

    config_entry: EcoTimerConfigEntry

    def __init__(self, hass: HomeAssistant, entry: EcoTimerConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=timedelta(seconds=entry.options.get(CONF_POLL_SECONDS, DEFAULT_POLL_SECONDS)),
        )
        self.address: str = entry.unique_id
        self.client = EcoTimerClient(entry.title, self._async_handle_notification)
        self._last_clock_check = None
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        # Last user-defined week program, restored by the "program" preset.
        self.program: proto.Program | None = None
        # Calibration added to the measured temperature (Home Assistant only).
        self.temperature_offset: float = 0.0
        # Boost length wanted by the user; the device itself always runs 60 min, Home Assistant
        # restarts it when it runs out early and stops it at the wanted end.
        self.boost_duration: int = DEFAULT_BOOST_MINUTES
        self.boost_start: datetime | None = None
        self._last_boost_remaining: int | None = None

    async def _async_setup(self) -> None:
        if data := await self._store.async_load():
            self.program = data.get("program")
            self.temperature_offset = data.get("temperature_offset", 0.0)
            self.boost_duration = data.get("boost_duration", DEFAULT_BOOST_MINUTES)
            if start := data.get("boost_start"):
                self.boost_start = dt_util.parse_datetime(start)

    @property
    def rated_power(self) -> int:
        return self.config_entry.options.get(CONF_RATED_POWER, DEFAULT_RATED_POWER)

    @property
    def dial_timer_active(self) -> bool:
        """Mode off with the dial-timer option: the dial sets the boost duration."""
        return (
            self.config_entry.options.get(CONF_DIAL_TIMER, False)
            and self.data is not None
            and self.data.uniform_mode() == proto.MODE_ANTIFREEZE
        )

    @property
    def effective_boost_duration(self) -> int:
        if self.dial_timer_active:
            return proto.dial_timer_minutes(self.data.dial_percent)
        return self.boost_duration

    @property
    def boost_end(self) -> datetime | None:
        if self.boost_start is None:
            return None
        return self.boost_start + timedelta(minutes=self.effective_boost_duration)

    @property
    def boost_remaining(self) -> int:
        """Minutes until the boost wanted in Home Assistant ends (device value as fallback)."""
        if self.boost_end is not None:
            return max(0, math.ceil((self.boost_end - dt_util.utcnow()).total_seconds() / 60))
        return self.data.boost_remaining if self.data.boost else 0

    @property
    def current_temperature(self) -> float:
        return round(self.data.actual + self.temperature_offset, 1)

    def _ble_device(self) -> BLEDevice | None:
        """BLE device to connect to; not needed while connected (the device may stop advertising)."""
        device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if device is None and not self.client.connected:
            raise HomeAssistantError(f"{self.address} is not in range of a connectable Bluetooth adapter or proxy")
        return device

    def _async_handle_notification(self, state: proto.EcoTimerState) -> None:
        self.async_set_updated_data(state)

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.client.async_disconnect()

    @property
    def adapter_name(self) -> str | None:
        """Adapter or proxy that currently receives the device best."""
        info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
        if info is None:
            return None
        scanner = bluetooth.async_scanner_by_source(self.hass, info.source)
        return scanner.name if scanner else info.source

    @property
    def rssi(self) -> int | None:
        info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
        return info.rssi if info else None

    async def _async_update_data(self) -> proto.EcoTimerState:
        now = dt_util.now()
        sync_clock = self._last_clock_check is None or now - self._last_clock_check > CLOCK_CHECK_INTERVAL
        try:
            state = await self.client.async_read(
                self._ble_device(), now.replace(tzinfo=None) if sync_clock else None
            )
        except HomeAssistantError as err:
            raise UpdateFailed(str(err)) from err
        except BLE_ERRORS as err:
            await self.client.async_disconnect()
            raise UpdateFailed(f"Reading {self.address} failed: {err}") from err
        if sync_clock:
            self._last_clock_check = now
        if self.program is None and state.uniform_mode() is None:
            await self.async_save_program(state.program)
        try:
            return await self._async_manage_boost(state)
        except BLE_ERRORS as err:
            await self.client.async_disconnect()
            raise UpdateFailed(f"Writing boost to {self.address} failed: {err}") from err

    async def _async_manage_boost(self, state: proto.EcoTimerState) -> proto.EcoTimerState:
        """Stretch or shorten the device's fixed 60 min boost to the wanted duration."""
        self.data = state
        now = dt_util.utcnow()
        if state.boost and self.boost_start is None:
            # started with the button on the device: count from its actual start
            elapsed = max(proto.BOOST_MINUTES - state.boost_remaining, 0)
            self.boost_start = now - timedelta(minutes=elapsed)
            await self._async_save()
        elif self.boost_start is not None:
            if now >= self.boost_end:
                self.boost_start = None
                await self._async_save()
                if state.boost:
                    state = await self.client.async_write(self._ble_device(), boost=False)
            elif not state.boost:
                if self._last_boost_remaining is not None and self._last_boost_remaining <= 2:
                    _LOGGER.debug("%s: device boost ran out, restarting until %s", self.address, self.boost_end)
                    state = await self.client.async_write(self._ble_device(), boost=True)
                else:
                    # stopped on the device (or while Home Assistant was down): respect it
                    self.boost_start = None
                    await self._async_save()
        self._last_boost_remaining = state.boost_remaining if state.boost else None
        return state

    async def async_set_boost_duration(self, minutes: int) -> None:
        self.boost_duration = minutes
        await self._async_save()
        self.async_update_listeners()

    async def _async_save(self) -> None:
        await self._store.async_save({
            "program": self.program,
            "temperature_offset": self.temperature_offset,
            "boost_duration": self.boost_duration,
            "boost_start": self.boost_start.isoformat() if self.boost_start else None,
        })

    async def async_save_program(self, program: proto.Program) -> None:
        self.program = program
        await self._async_save()

    async def async_set_temperature_offset(self, offset: float) -> None:
        self.temperature_offset = round(offset, 1)
        await self._async_save()
        self.async_update_listeners()

    async def async_rename(self, name: str, device_name: str | None = None) -> None:
        """Rename the Home Assistant device and entry; the thermostat gets device_name (max. 15 bytes)."""
        ble_device = self._ble_device()
        try:
            written = await self.client.async_rename(ble_device, device_name or name)
        except BLE_ERRORS as err:
            await self.client.async_disconnect()
            raise HomeAssistantError(f"Renaming {self.address} failed: {err}") from err
        _LOGGER.debug("%s: device name is now %r", self.address, written)
        self.hass.config_entries.async_update_entry(self.config_entry, title=name)
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            registry.async_update_device(device.id, name=name)

    async def async_write(self, **changes: Any) -> None:
        if changes.get("boost") is True:
            self.boost_start = dt_util.utcnow()
            await self._async_save()
        elif changes.get("boost") is False and self.boost_start is not None:
            self.boost_start = None
            await self._async_save()
        ble_device = self._ble_device()
        try:
            state = await self.client.async_write(ble_device, **changes)
        except BLE_ERRORS as err:
            await self.client.async_disconnect()
            raise HomeAssistantError(f"Writing to {self.address} failed: {err}") from err
        self.async_set_updated_data(state)
