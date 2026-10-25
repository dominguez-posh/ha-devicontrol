"""Send Wi-Fi credentials to a freshly flashed ESPHome device via Improv serial.

  python improv_wifi.py COM3          (reads IMPROV_SSID / IMPROV_PASSWORD from the environment)
"""

import os
import sys
import time

import serial

HEADER = b"IMPROV"
VERSION = 1
TYPE_STATE, TYPE_ERROR, TYPE_RPC, TYPE_RPC_RESULT = 0x01, 0x02, 0x03, 0x04
CMD_WIFI_SETTINGS = 0x01
STATES = {0x02: "authorized", 0x03: "provisioning", 0x04: "provisioned"}


def packet(ptype: int, data: bytes) -> bytes:
    body = HEADER + bytes([VERSION, ptype, len(data)]) + data
    return body + bytes([sum(body) & 0xFF])


def read_packets(port: serial.Serial, seconds: float):
    buf = b""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        buf += port.read(256)
        while (i := buf.find(HEADER)) >= 0 and len(buf) >= i + 9:
            length = buf[i + 8]
            if len(buf) < i + 10 + length:
                break
            ptype, data = buf[i + 7], buf[i + 9:i + 9 + length]
            buf = buf[i + 10 + length:]
            yield ptype, data


def main(port_name: str) -> None:
    ssid = os.environ["IMPROV_SSID"].encode()
    password = os.environ["IMPROV_PASSWORD"].encode()
    payload = bytes([len(ssid)]) + ssid + bytes([len(password)]) + password
    rpc = packet(TYPE_RPC, bytes([CMD_WIFI_SETTINGS, len(payload)]) + payload)
    with serial.Serial(port_name, 115200, timeout=0.2) as port:
        time.sleep(2)  # device may still be booting
        for attempt in range(3):
            port.write(rpc)
            for ptype, data in read_packets(port, 30):
                if ptype == TYPE_STATE:
                    print("state:", STATES.get(data[0], data[0]), flush=True)
                elif ptype == TYPE_ERROR:
                    print("error code:", data[0], flush=True)
                    break
                elif ptype == TYPE_RPC_RESULT:
                    urls, pos = [], 2
                    while pos < len(data):
                        urls.append(data[pos + 1:pos + 1 + data[pos]].decode()); pos += 1 + data[pos]
                    print("provisioned, device URL:", urls or "-", flush=True)
                    return
            print(f"attempt {attempt + 1}: no result, retrying", flush=True)
    sys.exit("provisioning failed")


if __name__ == "__main__":
    main(sys.argv[1])
