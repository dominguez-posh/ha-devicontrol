"""Kermi EcoTimer BLE protocol (derived from the EcoTimer 1.9 app, kermi.ecotimer).

This module has no Home Assistant dependencies so it can be used by the tools in
`tools/` as well.

One custom characteristic holds a 188-byte image of the controller state:

  [0]       status code
  [1..3]    two packed 12-bit values: comfort setpoint and actual temperature (1/10 degC)
            the setpoint follows the dial: 7.0 degC (snowflake) .. 27.0 degC (5)
  [4]       dial position in percent (0 = snowflake, 100 = 5), [5] unknown (always 0)
  [6]       bit7 relay, bit6 temperature limit, bit5 window open, bit4 boost,
            bit3 DST Europe, bit0..1 operating mode
  [7]       boost remaining time in minutes
  [8]       bit0..2 active program phase (0 = comfort, 3 = eco, 4 = antifreeze), bit4..6 fil pilote
  [9]       eco offset (1/10 K)
  [10..11]  free-running counter (~8 ticks/s)
  [20..187] week program: 7 days (Mon first) x 96 quarter hours x 2 bit, LSB first

Writes send the whole image back as two fragments prefixed with their start offset
(little-endian int16): (0, bytes 0..19) and (20, bytes 20..187). Verified on firmware
2.12: the device takes the week program, the eco offset and the boost bit (bit4 of
byte 6; setting it starts a boost of fixed 60 min, clearing it stops the boost).
The comfort setpoint can only be changed with the dial.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime

THERMO_SERVICE = "ab5b7cbb-f8af-4684-8186-ef1fe8814b3f"
THERMO_CHAR = "16200ee3-346e-4173-81bb-be256fa0a645"
CURRENT_TIME_CHAR = "00002a2b-0000-1000-8000-00805f9b34fb"
DEVICE_NAME_CHAR = "00002a00-0000-1000-8000-00805f9b34fb"
SOFTWARE_REVISION_CHAR = "00002a28-0000-1000-8000-00805f9b34fb"
MANUFACTURER_ID = 0x0586
MANUFACTURER_DATA = b"sta"

IMAGE_LEN = 188
SCHEDULE_OFFSET = 20
SLOTS_PER_DAY = 96

MODE_ANTIFREEZE = 0
MODE_ECO = 1
MODE_RESERVED = 2
MODE_COMFORT = 3
MODES = {MODE_ANTIFREEZE: "antifreeze", MODE_ECO: "eco", MODE_RESERVED: "reserved", MODE_COMFORT: "comfort"}
MODE_BY_NAME = {name: mode for mode, name in MODES.items()}
# byte 8 bit0..2 as observed on the device
ACTIVE_PHASES = {0: "comfort", 3: "eco", 4: "antifreeze"}

ANTIFREEZE_TEMPERATURE = 7.0
ECO_OFFSET_MIN = 2.0
ECO_OFFSET_MAX = 20.0
BOOST_MINUTES = 60

Program = list[list[int]]  # [day 0=Mon][slot 0..95] -> mode


@dataclass
class EcoTimerState:
    raw: bytes
    status: int
    setpoint: float
    actual: float
    dial_percent: int
    relay: bool
    temperature_limit: bool
    window_open: bool
    boost: bool
    dst_europe: bool
    operating_mode: int
    boost_remaining: int
    active_phase: int
    fil_pilote: int
    eco_offset: float
    program: Program

    @property
    def eco_temperature(self) -> float:
        return round(self.setpoint - self.eco_offset, 1)

    def uniform_mode(self) -> int | None:
        """Return the mode if the whole week uses one mode, else None."""
        modes = {mode for day in self.program for mode in day}
        return modes.pop() if len(modes) == 1 else None

    def mode_at(self, when: datetime) -> int:
        return self.program[when.weekday()][when.hour * 4 + when.minute // 15]

    def temperature_for_mode(self, mode: int) -> float:
        if mode == MODE_COMFORT:
            return self.setpoint
        if mode == MODE_ECO:
            return self.eco_temperature
        return ANTIFREEZE_TEMPERATURE


def parse(data: bytes | bytearray) -> EcoTimerState:
    if len(data) < IMAGE_LEN:
        raise ValueError(f"expected {IMAGE_LEN} bytes, got {len(data)}")
    b6 = data[6]
    return EcoTimerState(
        raw=bytes(data[:IMAGE_LEN]),
        status=data[0],
        setpoint=((data[1] << 4) | (data[2] >> 4)) / 10,
        actual=(((data[2] & 0x0F) << 8) | data[3]) / 10,
        dial_percent=data[4],
        relay=bool(b6 & 0x80),
        temperature_limit=bool(b6 & 0x40),
        window_open=bool(b6 & 0x20),
        boost=bool(b6 & 0x10),
        dst_europe=bool(b6 & 0x08),
        operating_mode=b6 & 0x03,
        boost_remaining=data[7],
        active_phase=data[8] & 0x07,
        fil_pilote=(data[8] >> 4) & 0x07,
        eco_offset=data[9] / 10,
        program=decode_program(data[SCHEDULE_OFFSET:IMAGE_LEN]),
    )


def decode_program(data: bytes | bytearray) -> Program:
    bits = int.from_bytes(data, "little")
    return [
        [(bits >> (2 * (day * SLOTS_PER_DAY + slot))) & 0b11 for slot in range(SLOTS_PER_DAY)]
        for day in range(7)
    ]


def encode_program(program: Program) -> bytes:
    bits = 0
    for day in range(7):
        for slot in range(SLOTS_PER_DAY):
            bits |= (program[day][slot] & 0b11) << (2 * (day * SLOTS_PER_DAY + slot))
    return bits.to_bytes(IMAGE_LEN - SCHEDULE_OFFSET, "little")


def uniform_program(mode: int) -> Program:
    return [[mode] * SLOTS_PER_DAY for _ in range(7)]


def build_image(state: EcoTimerState, *, boost: bool | None = None, eco_offset: float | None = None,
                program: Program | None = None) -> bytes:
    """Return a new image built from the last read state, the same way the app does it."""
    image = bytearray(state.raw)
    on_boost = state.boost if boost is None else boost
    # app: new BitArray(8) -> only bit0 (mode != 0) and bit4 (boost); the device keeps the rest
    image[6] = (0x01 if state.operating_mode else 0) | (0x10 if on_boost else 0)
    if eco_offset is not None:
        image[9] = int(round(min(max(eco_offset, ECO_OFFSET_MIN), ECO_OFFSET_MAX) * 10))
    if program is not None:
        image[SCHEDULE_OFFSET:IMAGE_LEN] = encode_program(program)
    return bytes(image)


def fragments(image: bytes) -> list[bytes]:
    """Split an image into the two offset-prefixed writes the app sends."""
    return [struct.pack("<h", 0) + image[:SCHEDULE_OFFSET],
            struct.pack("<h", SCHEDULE_OFFSET) + image[SCHEDULE_OFFSET:]]


def encode_time(dt: datetime) -> bytes:
    """Current Time Service payload as the app writes it."""
    return struct.pack("<HBBBBBBBB", dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
                       dt.isoweekday(), 0, 0)


def decode_time(data: bytes | bytearray) -> datetime:
    year, month, day, hour, minute, second = struct.unpack_from("<HBBBBB", data)
    return datetime(year, month, day, hour, minute, second)


def slot_label(slot: int) -> str:
    return f"{slot // 4:02d}:{(slot % 4) * 15:02d}"


def parse_slot(value: str) -> int:
    """'06:30' -> 26, '24:00' -> 96. Minutes are rounded down to the quarter hour."""
    hours, minutes = (int(part) for part in value.strip().split(":")[:2])
    if not (0 <= hours <= 24 and 0 <= minutes < 60) or (hours == 24 and minutes):
        raise ValueError(f"invalid time {value!r}")
    return hours * 4 + minutes // 15


def day_summary(day: list[int]) -> list[tuple[str, str, str]]:
    """Compress 96 slots into (start, end, mode) ranges."""
    out: list[tuple[str, str, str]] = []
    start = 0
    for slot in range(1, SLOTS_PER_DAY + 1):
        if slot == SLOTS_PER_DAY or day[slot] != day[start]:
            out.append((slot_label(start), slot_label(slot) if slot < SLOTS_PER_DAY else "24:00",
                        MODES[day[start]]))
            start = slot
    return out
