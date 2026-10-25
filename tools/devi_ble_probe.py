"""BLE probe for reverse engineering the DEVIreg Room thermostat.

Usage:
  python devi_ble_probe.py                      # scan 15 s, list all devices
  python devi_ble_probe.py --watch 120          # log advertisement changes (turn the dial meanwhile)
  python devi_ble_probe.py <MAC> --listen 60    # dump GATT, read values, log notifications
  python devi_ble_probe.py <MAC> --pair --listen 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

KEYWORDS = ("devi", "danfoss", "dvi", "room")


def _hex(data: bytes | bytearray) -> str:
    return data.hex(" ")


def _adv_summary(adv: AdvertisementData) -> dict:
    return {
        "name": adv.local_name,
        "rssi": adv.rssi,
        "manufacturer_data": {f"0x{k:04x}": _hex(v) for k, v in adv.manufacturer_data.items()},
        "service_data": {k: _hex(v) for k, v in adv.service_data.items()},
        "service_uuids": adv.service_uuids,
        "tx_power": adv.tx_power,
    }


def _is_candidate(device: BLEDevice, adv: AdvertisementData) -> bool:
    name = (adv.local_name or device.name or "").lower()
    return any(k in name for k in KEYWORDS)


async def scan(seconds: float) -> None:
    print(f"Scanning {seconds:.0f} s ...")
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    rows = sorted(found.values(), key=lambda da: da[1].rssi, reverse=True)
    for device, adv in rows:
        mark = "  <== candidate" if _is_candidate(device, adv) else ""
        print(f"{device.address}  rssi={adv.rssi:4d}  name={adv.local_name or device.name!r}{mark}")
        info = _adv_summary(adv)
        for key in ("manufacturer_data", "service_data", "service_uuids"):
            if info[key]:
                print(f"    {key}: {info[key]}")


async def watch(seconds: float, address: str | None) -> None:
    """Print every advertisement whose payload changes (to see if values are broadcast)."""
    last: dict[str, str] = {}
    log: list[dict] = []

    def on_adv(device: BLEDevice, adv: AdvertisementData) -> None:
        if address and device.address.upper() != address.upper():
            return
        if not address and not _is_candidate(device, adv):
            return
        info = _adv_summary(adv)
        payload = json.dumps({k: info[k] for k in ("manufacturer_data", "service_data", "service_uuids")})
        if last.get(device.address) != payload:
            last[device.address] = payload
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"{ts} {device.address} rssi={adv.rssi} {payload}")
            log.append({"time": ts, "address": device.address, **info})

    print(f"Watching advertisements for {seconds:.0f} s (turn the dial now) ...")
    async with BleakScanner(on_adv):
        await asyncio.sleep(seconds)
    if log:
        fname = f"devi_adv_{int(time.time())}.json"
        with open(fname, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        print(f"Saved {fname}")


async def probe(address: str, pair: bool, listen: float) -> None:
    dump: dict = {"address": address, "time": datetime.now().isoformat(), "services": [], "notifications": []}

    device = await BleakScanner.find_device_by_address(address, timeout=20)
    if device is None:
        print("Device not found while scanning.")
        return

    async with BleakClient(device, timeout=30) as client:
        print(f"Connected: {client.is_connected}")
        if pair:
            print("Pairing ...")
            try:
                print(f"pair() -> {await client.pair()}")
            except Exception as err:  # noqa: BLE001 - report everything while probing
                print(f"pair() failed: {err!r}")

        for service in client.services:
            svc = {"uuid": service.uuid, "description": service.description, "characteristics": []}
            print(f"\n[Service] {service.uuid}  {service.description}")
            for char in service.characteristics:
                entry = {"uuid": char.uuid, "handle": char.handle, "properties": char.properties,
                         "description": char.description, "descriptors": [d.uuid for d in char.descriptors]}
                line = f"  [Char] {char.uuid} h=0x{char.handle:04x} {','.join(char.properties)}  {char.description}"
                if "read" in char.properties:
                    try:
                        value = await client.read_gatt_char(char)
                        entry["value"] = _hex(value)
                        text = value.decode("utf-8", errors="replace") if value and all(32 <= b < 127 for b in value) else ""
                        line += f"\n         = {_hex(value)}" + (f"  ({text!r})" if text else "")
                    except Exception as err:  # noqa: BLE001
                        entry["read_error"] = repr(err)
                        line += f"\n         ! read failed: {err!r}"
                print(line)
                svc["characteristics"].append(entry)
            dump["services"].append(svc)

        if listen > 0:
            def make_handler(uuid: str):
                def handler(_sender, data: bytearray) -> None:
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    print(f"{ts} NOTIFY {uuid}: {_hex(data)}")
                    dump["notifications"].append({"time": ts, "uuid": uuid, "value": _hex(data)})
                return handler

            subscribed = 0
            for service in client.services:
                for char in service.characteristics:
                    if {"notify", "indicate"} & set(char.properties):
                        try:
                            await client.start_notify(char, make_handler(char.uuid))
                            subscribed += 1
                        except Exception as err:  # noqa: BLE001
                            print(f"start_notify {char.uuid} failed: {err!r}")
            print(f"\nSubscribed to {subscribed} characteristics, listening {listen:.0f} s (turn the dial now) ...")
            await asyncio.sleep(listen)

    fname = f"devi_dump_{address.replace(':', '')}.json"
    with open(fname, "w", encoding="utf-8") as fh:
        json.dump(dump, fh, indent=2)
    print(f"\nSaved {fname}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("address", nargs="?")
    parser.add_argument("--scan", type=float, default=15)
    parser.add_argument("--watch", type=float, default=0)
    parser.add_argument("--listen", type=float, default=0)
    parser.add_argument("--pair", action="store_true")
    args = parser.parse_args()

    if args.watch:
        asyncio.run(watch(args.watch, args.address))
    elif args.address:
        asyncio.run(probe(args.address, args.pair, args.listen))
    else:
        asyncio.run(scan(args.scan))


if __name__ == "__main__":
    main()
