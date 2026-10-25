"""Try header byte candidates that might set the boost duration (via kermi_ecotimer.write_raw).

  python boost_duration_probe.py <climate entity> <boost switch> <remaining sensor>
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

URL = os.environ["HA_URL"]
TOKEN = Path.home().joinpath(".ha_token").read_text().strip()

# byte 6 = 0x18: boost bit + DST bit, as the device reports it while boosting
CANDIDATES = [
    ("byte7 = 3 (app enum 120 min)", {6: 0x18, 7: 3}),
    ("byte7 = 2 (app enum 90 min)", {6: 0x18, 7: 2}),
    ("byte7 = 0 (app enum 30 min)", {6: 0x18, 7: 0}),
    ("byte5 = 120", {6: 0x18, 5: 120}),
    ("byte5 = 3", {6: 0x18, 5: 3}),
    ("byte5 = 2 / byte7 = 120", {6: 0x18, 5: 2, 7: 120}),
    ("byte6 bits1-2 set, byte7 = 3", {6: 0x1E, 7: 3}),
    ("byte8 high bits = 3", {6: 0x18, 8: 0x30}),
]


def api(path: str, body: dict | None = None):
    req = urllib.request.Request(
        URL + path, data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def main(climate: str, switch: str, remaining: str) -> None:
    state = lambda e: api(f"/api/states/{e}")["state"]  # noqa: E731
    try:
        for label, patches in CANDIDATES:
            api("/api/services/switch/turn_off", {"entity_id": switch})
            time.sleep(4)
            api("/api/services/kermi_ecotimer/write_raw", {"entity_id": climate, "patches": patches})
            time.sleep(4)
            print(f"{label:32s} -> boost={state(switch)} remaining={state(remaining)} min", flush=True)
    finally:
        api("/api/services/switch/turn_off", {"entity_id": switch})


if __name__ == "__main__":
    main(*sys.argv[1:4])
