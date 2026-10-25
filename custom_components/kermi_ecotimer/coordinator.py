"""Polling coordinator for one EcoTimer."""

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
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import protocol as proto
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .device import EcoTimerClient

_LOGGER = logging.getLogger(__name__)

BLE_ERRORS = (BleakError, TimeoutError)

type EcoTimerConfigEntry = ConfigEntry[EcoTimerCoordinator]


class EcoTimerCoordinator(DataUpdateCoordinator[proto.EcoTimerState]):
    """Polls the device; connections are short so the vendor app can still connect."""

    config_entry: EcoTimerConfigEntry

    def __init__(self, hass: HomeAssistant, entry: EcoTimerConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=timedelta(minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.address: str = entry.unique_id
        self.client = EcoTimerClient(entry.title)
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
    def current_temperature(self) -> float:
        return round(self.data.actual + self.temperature_offset, 1)

    def _ble_device(self) -> BLEDevice | None:
        return bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)

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
        if (ble_device := self._ble_device()) is None:
            raise UpdateFailed(f"{self.address} is not in range of a connectable Bluetooth adapter or proxy")
        try:
            state = await self.client.async_read(ble_device, dt_util.now().replace(tzinfo=None))
        except BLE_ERRORS as err:
            raise UpdateFailed(f"Reading {self.address} failed: {err}") from err
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

    async def async_write(self, **changes: Any) -> None:
        if (ble_device := self._ble_device()) is None:
            raise HomeAssistantError(f"{self.address} is not in range of a connectable Bluetooth adapter or proxy")
        try:
            state = await self.client.async_write(ble_device, **changes)
        except BLE_ERRORS as err:
            raise HomeAssistantError(f"Writing to {self.address} failed: {err}") from err
        self.async_set_updated_data(state)
