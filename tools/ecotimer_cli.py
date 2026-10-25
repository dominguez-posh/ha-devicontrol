"""Read-only CLI for Kermi EcoTimer devices.

  python ecotimer_cli.py read <MAC> [<MAC> ...]
  python ecotimer_cli.py poll <MAC> [seconds]
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from bleak import BleakClient, BleakScanner

import ecotimer_protocol as proto

DAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


async def read(address: str) -> None:
    device = await BleakScanner.find_device_by_address(address, timeout=20)
    if device is None:
        print(f"{address}: not found")
        return
    async with BleakClient(device, timeout=30) as client:
        name = (await client.read_gatt_char(proto.DEVICE_NAME_CHAR)).decode(errors="replace")
        clock = proto.decode_time(await client.read_gatt_char(proto.CURRENT_TIME_CHAR))
        raw = await client.read_gatt_char(proto.THERMO_CHAR)
    state = proto.parse(raw)
    print(f"\n== {name} ({address}) clock={clock}")
    print(f"raw[0:20] = {raw[:20].hex(' ')}")
    for key, value in vars(state).items():
        if key not in ("raw", "program"):
            print(f"  {key:26s} {value}")
    print(f"  {'eco_temperature':26s} {state.eco_temperature}")
    for i, day in enumerate(state.program):
        print(f"  {DAYS[i]}: " + ", ".join(f"{a}-{b} {m}" for a, b, m in proto.schedule_summary(day)))


async def poll(address: str, seconds: float, interval: float = 3) -> None:
    """Keep the connection and print every change of the status bytes."""
    device = await BleakScanner.find_device_by_address(address, timeout=20)
    if device is None:
        print(f"{address}: not found")
        return
    last = b""
    async with BleakClient(device, timeout=30) as client:
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        while loop.time() < end:
            raw = bytes(await client.read_gatt_char(proto.THERMO_CHAR))
            if raw[:20] != last:
                last = raw[:20]
                s = proto.parse(raw)
                print(f"{datetime.now():%H:%M:%S} {raw[:20].hex(' ')} | set={s.setpoint} act={s.actual} "
                      f"mode={s.operating_mode} phase={s.active_phase} relay={s.relay} boost={s.boost} "
                      f"rem={s.boost_remaining} dial={s.dial_percent}", flush=True)
            await asyncio.sleep(interval)


async def main(args: list[str]) -> None:
    if len(args) >= 2 and args[0] == "read":
        for address in args[1:]:
            await read(address)
    elif len(args) >= 2 and args[0] == "poll":
        await poll(args[1], float(args[2]) if len(args) > 2 else 120)
    else:
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
