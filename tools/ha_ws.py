"""Send one Home Assistant WebSocket command and print the JSON result.

  python ha_ws.py '{"type": "config_entries/flow/progress"}'

URL from HA_URL (e.g. https://homeassistant.local:8123), token from ~/.ha_token.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import websockets

URL = os.environ["HA_URL"].replace("http", "ws", 1) + "/api/websocket"


async def main(command: dict) -> None:
    token = Path.home().joinpath(".ha_token").read_text().strip()
    async with websockets.connect(URL, max_size=None) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        if json.loads(await ws.recv())["type"] != "auth_ok":
            sys.exit("auth failed")
        await ws.send(json.dumps({"id": 1, **command}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1 and msg["type"] == "result":
                print(json.dumps(msg.get("result") if msg["success"] else msg.get("error"), indent=2, ensure_ascii=False))
                break
        # subscriptions: print events for EVENT_SECONDS
        loop = asyncio.get_running_loop()
        end = loop.time() + float(os.environ.get("EVENT_SECONDS", "0"))
        while (left := end - loop.time()) > 0:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), left))
            except TimeoutError:
                break
            if msg.get("type") == "event":
                print(json.dumps(msg["event"], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(json.loads(sys.argv[1])))
