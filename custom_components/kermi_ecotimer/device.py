"""BLE access to a single EcoTimer over a persistent connection."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from . import protocol as proto
from .const import CLOCK_TOLERANCE_SECONDS

_LOGGER = logging.getLogger(__name__)


class EcoTimerClient:
    """Keeps one connection open, reads and writes the 188-byte state image."""

    def __init__(self, name: str, on_state: Callable[[proto.EcoTimerState], None]) -> None:
        self._name = name
        self._on_state = on_state
        self._lock = asyncio.Lock()
        self._client: BleakClientWithServiceCache | None = None
        self.software_version: str | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def _on_disconnect(self, _client: BleakClientWithServiceCache) -> None:
        _LOGGER.debug("%s: disconnected", self._name)
        self._client = None

    def _on_notify(self, _sender: object, data: bytearray) -> None:
        _LOGGER.debug("%s: notify %s", self._name, bytes(data).hex(" "))
        try:
            self._on_state(proto.parse(data))
        except ValueError:
            pass  # partial image (MTU-limited notification); the next poll reads the full image

    async def _ensure_connected(self, ble_device: BLEDevice) -> BleakClientWithServiceCache:
        if self.connected:
            return self._client
        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, self._name,
            disconnected_callback=self._on_disconnect, max_attempts=3,
        )
        try:
            if self.software_version is None:
                self.software_version = (
                    await client.read_gatt_char(proto.SOFTWARE_REVISION_CHAR)
                ).decode(errors="replace")
            await client.start_notify(proto.THERMO_CHAR, self._on_notify)
        except Exception:
            await client.disconnect()
            raise
        _LOGGER.debug("%s: connected", self._name)
        self._client = client
        return client

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

    async def async_read(self, ble_device: BLEDevice, now: datetime | None = None) -> proto.EcoTimerState:
        """Read the state; with `now` the device clock is synchronised as well."""
        async with self._lock:
            client = await self._ensure_connected(ble_device)
            if now is not None:
                await self._sync_clock(client, now)
            return proto.parse(await self._read_image(client))

    async def async_write(self, ble_device: BLEDevice, *, boost: bool | None = None,
                          eco_offset: float | None = None,
                          program: proto.Program | None = None) -> proto.EcoTimerState:
        """Read the current image, apply the changes, write it back and return the new state."""
        async with self._lock:
            client = await self._ensure_connected(ble_device)
            state = proto.parse(await self._read_image(client))
            image = proto.build_image(state, boost=boost, eco_offset=eco_offset, program=program)
            for fragment in proto.fragments(image):
                _LOGGER.debug("%s: write %s", self._name, fragment.hex(" "))
                await client.write_gatt_char(proto.THERMO_CHAR, fragment, response=True)
            await asyncio.sleep(0.5)
            return proto.parse(await self._read_image(client))

    async def async_rename(self, ble_device: BLEDevice, name: str) -> str:
        """Write the GAP device name (as the app does) and return the name read back."""
        async with self._lock:
            client = await self._ensure_connected(ble_device)
            await client.write_gatt_char(proto.DEVICE_NAME_CHAR, proto.device_name_bytes(name), response=True)
            return (await client.read_gatt_char(proto.DEVICE_NAME_CHAR)).decode(errors="replace")

    async def async_disconnect(self) -> None:
        async with self._lock:
            if self._client is not None:
                client, self._client = self._client, None
                await client.disconnect()
