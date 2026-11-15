"""Measure live S1 contract frames at both demo speeds; no scenario edits."""

import asyncio
import json
import time
from pathlib import Path

import httpx
import websockets


async def main() -> None:
    results = []
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8021", timeout=60
    ) as client:
        for speed in (2, 5):
            async with websockets.connect("ws://127.0.0.1:8021/ws") as ws:
                hello = json.loads(await ws.recv())
                profile = next(
                    p
                    for p in hello["profiles"]
                    if any(s["scenario_id"] == "s1" for s in p["scenarios"])
                )
                response = await client.post(
                    "/api/runs",
                    json={"profile_id": profile["profile_id"], "scenario_id": "s1"},
                )
                response.raise_for_status()
                run_id = response.json()["run_id"]
                response = await client.post(
                    "/api/run/control", json={"action": "speed", "speed": speed}
                )
                response.raise_for_status()
                started = time.monotonic()
                frames = []
                while True:
                    message = json.loads(await ws.recv())
                    if message.get("run_id") != run_id:
                        continue
                    if message["type"] == "frame":
                        frames.append(message)
                    if message["type"] == "run" and message["state"] == "ended":
                        break
                results.append(
                    {
                        "speed": speed,
                        "run_id": run_id,
                        "wall_s": time.monotonic() - started,
                        "frames": frames,
                    }
                )
                print(speed, run_id, len(frames), flush=True)
    path = Path("runs/handoff-live.json")
    path.write_text(json.dumps(results), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
