"""Patch single header bytes of the 188-byte image, write it back and watch the result.

  python ecotimer_poke.py <MAC> 6=0x88 [7=30 ...] [--watch 15]

The week program is written back unchanged.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from bleak import BleakClient, BleakScanner

import ecotimer_protocol as proto
from ecotimer_writetest import show, write_image


async def main(address: str, patches: dict[int, int], watch: float) -> None:
    device = await BleakScanner.find_device_by_address(address, timeout=20)
    if device is None:
        print("not found")
        return
    async with BleakClient(device, timeout=30) as client:
        image = bytearray(await client.read_gatt_char(proto.THERMO_CHAR))
        show("before", bytes(image))
        for offset, value in patches.items():
            if not 0 <= offset < proto.SCHEDULE_OFFSET:
                raise ValueError("only header bytes 0..19 may be patched")
            image[offset] = value
        print(f"{datetime.now():%H:%M:%S} patch {patches} -> {bytes(image[:20]).hex(' ')}", flush=True)
        await write_image(client, bytes(image))
        loop = asyncio.get_running_loop()
        end = loop.time() + watch
        while loop.time() < end:
            await asyncio.sleep(2)
            show("after", bytes(await client.read_gatt_char(proto.THERMO_CHAR)))


if __name__ == "__main__":
    args = sys.argv[1:]
    watch = 15.0
    if "--watch" in args:
        i = args.index("--watch")
        watch = float(args[i + 1])
        del args[i:i + 2]
    patches = {int(k): int(v, 0) for k, v in (a.split("=") for a in args[1:])}
    asyncio.run(main(args[0], patches, watch))
