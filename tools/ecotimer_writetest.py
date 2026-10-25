"""Write test: set clock, switch week program to antifreeze, verify, restore.

  python ecotimer_writetest.py <MAC>
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner

import ecotimer_protocol as proto


def show(tag: str, raw: bytes) -> proto.EcoTimerState:
    s = proto.parse(raw)
    modes = sorted({m for day in s.program for m in day})
    print(f"{datetime.now():%H:%M:%S} {tag:12s} {raw[:20].hex(' ')} | set={s.setpoint} act={s.actual} "
          f"dial={s.dial_percent}% relay={s.relay} boost={s.boost} rem={s.boost_remaining} "
          f"schedule_modes={[proto.MODES[m] for m in modes]}", flush=True)
    return s


async def write_image(client: BleakClient, image: bytes) -> None:
    for frag in proto.fragments(image):
        print(f"  write {len(frag)} bytes: {frag[:6].hex(' ')} ...", flush=True)
        await client.write_gatt_char(proto.THERMO_CHAR, frag, response=True)


async def main(address: str, test_mode: int = 0) -> None:
    device = await BleakScanner.find_device_by_address(address, timeout=20)
    if device is None:
        print("not found")
        return
    async with BleakClient(device, timeout=30) as client:
        # 1. clock
        before = proto.decode_time(await client.read_gatt_char(proto.CURRENT_TIME_CHAR))
        await client.write_gatt_char(proto.CURRENT_TIME_CHAR, proto.encode_time(datetime.now()), response=True)
        after = proto.decode_time(await client.read_gatt_char(proto.CURRENT_TIME_CHAR))
        print(f"clock: {before} -> {after}", flush=True)

        # 2. backup + antifreeze program
        original = bytes(await client.read_gatt_char(proto.THERMO_CHAR))
        backup = Path(f"ecotimer_backup_{address.replace(':', '')}_{datetime.now():%Y%m%d_%H%M%S}.bin")
        backup.write_bytes(original)
        print(f"backup -> {backup}", flush=True)
        state = show("original", original)

        frost = [[test_mode] * proto.SLOTS_PER_DAY for _ in range(7)]
        await write_image(client, proto.build_image(state, program=frost))
        for i in range(6):
            await asyncio.sleep(3 if i else 1)
            show(proto.MODES[test_mode], bytes(await client.read_gatt_char(proto.THERMO_CHAR)))

        # 3. restore original program
        current = proto.parse(bytes(await client.read_gatt_char(proto.THERMO_CHAR)))
        await write_image(client, proto.build_image(current, program=state.program))
        for i in range(4):
            await asyncio.sleep(3 if i else 1)
            restored = bytes(await client.read_gatt_char(proto.THERMO_CHAR))
            show("restored", restored)
        print("schedule restored:", restored[proto.SCHEDULE_OFFSET:] == original[proto.SCHEDULE_OFFSET:])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0))
