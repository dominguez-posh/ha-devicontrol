"""Coordinator for one EcoTimer: persistent connection, fast polling plus notifications."""

from __future__ import annotations

import logging
from datetime import timedelta
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
    CONF_POLL_SECONDS,
    CONF_RATED_POWER,
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

    async def _async_setup(self) -> None:
        if data := await self._store.async_load():
            self.program = data.get("program")
            self.temperature_offset = data.get("temperature_offset", 0.0)

    @property
    def rated_power(self) -> int:
        return self.config_entry.options.get(CONF_RATED_POWER, DEFAULT_RATED_POWER)

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
        return state

    async def _async_save(self) -> None:
        await self._store.async_save({"program": self.program, "temperature_offset": self.temperature_offset})

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
        ble_device = self._ble_device()
        try:
            state = await self.client.async_write(ble_device, **changes)
        except BLE_ERRORS as err:
            await self.client.async_disconnect()
            raise HomeAssistantError(f"Writing to {self.address} failed: {err}") from err
        self.async_set_updated_data(state)
