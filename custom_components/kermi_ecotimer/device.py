"""BLE access to a single EcoTimer. Connects per operation so the vendor app keeps working."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from . import protocol as proto
from .const import CLOCK_TOLERANCE_SECONDS

_LOGGER = logging.getLogger(__name__)


class EcoTimerClient:
    """Reads and writes the 188-byte state image."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = asyncio.Lock()
        self.software_version: str | None = None

    async def _connect(self, ble_device: BLEDevice) -> BleakClientWithServiceCache:
        return await establish_connection(BleakClientWithServiceCache, ble_device, self._name, max_attempts=3)

    async def _read_image(self, client: BleakClientWithServiceCache) -> bytes:
        raw = bytes(await client.read_gatt_char(proto.THERMO_CHAR))
        _LOGGER.debug("%s: read %s", self._name, raw.hex(" "))
        return raw

    async def _sync_clock(self, client: BleakClientWithServiceCache, now: datetime) -> None:
        try:
            clock = proto.decode_time(await client.read_gatt_char(proto.CURRENT_TIME_CHAR))
            drift = abs((clock - now).total_seconds())
        except ValueError:  # device never set (invalid date)
            clock, drift = None, float("inf")
        if drift > CLOCK_TOLERANCE_SECONDS:
            _LOGGER.debug("%s: setting clock %s -> %s", self._name, clock, now)
            await client.write_gatt_char(proto.CURRENT_TIME_CHAR, proto.encode_time(now), response=True)

    async def async_read(self, ble_device: BLEDevice, now: datetime) -> proto.EcoTimerState:
        """Read the state and keep the device clock in sync with Home Assistant."""
        async with self._lock:
            client = await self._connect(ble_device)
            try:
                if self.software_version is None:
                    self.software_version = (
                        await client.read_gatt_char(proto.SOFTWARE_REVISION_CHAR)
                    ).decode(errors="replace")
                await self._sync_clock(client, now)
                return proto.parse(await self._read_image(client))
            finally:
                await client.disconnect()

    async def async_write(self, ble_device: BLEDevice, *, boost: bool | None = None,
                          eco_offset: float | None = None,
                          program: proto.Program | None = None) -> proto.EcoTimerState:
        """Read the current image, apply the changes, write it back and return the new state."""
        async with self._lock:
            client = await self._connect(ble_device)
            try:
                state = proto.parse(await self._read_image(client))
                image = proto.build_image(state, boost=boost, eco_offset=eco_offset, program=program)
                for fragment in proto.fragments(image):
                    _LOGGER.debug("%s: write %s", self._name, fragment.hex(" "))
                    await client.write_gatt_char(proto.THERMO_CHAR, fragment, response=True)
                await asyncio.sleep(0.5)
                return proto.parse(await self._read_image(client))
            finally:
                await client.disconnect()
