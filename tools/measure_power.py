"""Measure the power draw of a heater by toggling its boost and watching a power meter.

  python measure_power.py <boost switch> <heating binary_sensor> [cycles]

HA_URL and ~/.ha_token as in ha_ws.py. Uses the Shelly Pro 3EM phase sensors below.
"""

import json
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path

URL = os.environ["HA_URL"]
TOKEN = Path.home().joinpath(".ha_token").read_text().strip()
METER = "sensor.shellypro3em_2cbcbba65a64"
SENSORS = {p: f"{METER}_phase_{p}_active_power" for p in "abc"} | {"total": f"{METER}_total_active_power"}
PHASE_SECONDS = 25


def api(path: str, body: dict | None = None):
    req = urllib.request.Request(
        URL + path, data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def sample(seconds: float) -> dict[str, float]:
    values: dict[str, list[float]] = {k: [] for k in SENSORS}
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        for key, entity in SENSORS.items():
            try:
                values[key].append(float(api(f"/api/states/{entity}")["state"]))
            except ValueError:
                pass
        time.sleep(1)
    return {k: statistics.median(v) for k, v in values.items()}


def wait_heating(sensor: str, on: bool, timeout: float = 30) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if (api(f"/api/states/{sensor}")["state"] == "on") == on:
            return True
        time.sleep(1)
    return False


def main(switch: str, heating: str, cycles: int) -> None:
    deltas: dict[str, list[float]] = {k: [] for k in SENSORS}
    try:
        for cycle in range(1, cycles + 1):
            off = sample(PHASE_SECONDS)
            api("/api/services/switch/turn_on", {"entity_id": switch})
            if not wait_heating(heating, True):
                print("relay did not switch on")
                return
            time.sleep(3)
            on = sample(PHASE_SECONDS)
            api("/api/services/switch/turn_off", {"entity_id": switch})
            wait_heating(heating, False)
            time.sleep(3)
            for k in SENSORS:
                deltas[k].append(on[k] - off[k])
            print(f"cycle {cycle}: " + "  ".join(f"{k}={on[k] - off[k]:+.0f} W" for k in SENSORS), flush=True)
    finally:
        api("/api/services/switch/turn_off", {"entity_id": switch})
    print("median: " + "  ".join(f"{k}={statistics.median(v):+.0f} W" for k, v in deltas.items()))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 3)
