"""Exercise the real local server and save request/response evidence under runs/."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx
import websockets


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("s1", "s2"), default="s1")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--out", default="runs/summary-http.json")
    args = parser.parse_args()
    base = "http://127.0.0.1:8021"
    captures = []
    requested_run = None
    async with httpx.AsyncClient(base_url=base, timeout=120) as client:

        async def capture(label: str) -> dict:
            response = await client.get(
                "/api/run/summary",
                params={"run_id": requested_run} if requested_run else None,
            )
            item = {
                "label": label,
                "url": str(response.url),
                "status": response.status_code,
                "body": response.text,
            }
            captures.append(item)
            print(json.dumps(item), flush=True)
            return item

        async with websockets.connect("ws://127.0.0.1:8021/ws") as ws:
            hello = json.loads(await ws.recv())
            initial = hello.get("run")
            print(
                "initial_run",
                json.dumps(
                    initial
                    and {
                        k: initial.get(k)
                        for k in ("run_id", "state", "ended_reason", "recorded_media")
                    }
                ),
                flush=True,
            )
            await capture("before_new_run")
            if initial and initial["state"] != "ended":
                raise RuntimeError("An existing run is active; leaving it untouched")
            profile = next(
                p
                for p in hello["profiles"]
                if any(s["scenario_id"] == args.scenario for s in p["scenarios"])
            )
            response = await client.post(
                "/api/runs",
                json={
                    "profile_id": profile["profile_id"],
                    "scenario_id": args.scenario,
                    "recorded_media": True,
                },
            )
            response.raise_for_status()
            run_id = response.json()["run_id"]
            requested_run = run_id
            (
                await client.post(
                    "/api/run/control", json={"action": "speed", "speed": 5}
                )
            ).raise_for_status()
            print("new_run", run_id, flush=True)
            if args.stop:
                (await client.post("/api/run/stop")).raise_for_status()
            last_frame = None
            while True:
                message = json.loads(await ws.recv())
                if message.get("run_id") != run_id:
                    continue
                if message["type"] == "frame":
                    last_frame = message
                if message["type"] == "run" and message["state"] == "ended":
                    break
            item = await capture("immediately_after_ended")
            await capture("repeat_after_ended")
            report = {
                "run_id": run_id,
                "run": message,
                "final_frame": last_frame,
                "requests": captures,
            }
            if item["status"] == 200:
                summary = json.loads(item["body"])
                assert summary["run_id"] == run_id
                assert summary["ended_reason"] == (
                    "stopped" if args.stop else "completed"
                )
                assert last_frame is not None
                assert summary["evidence_records"] == (
                    last_frame["evidence_head"]["seq"]
                    if last_frame["evidence_head"]
                    else 0
                )
                download = Path(args.out).with_suffix(".download.json")
                download.write_text(json.dumps(summary, indent=2), encoding="utf-8")
                assert json.loads(download.read_text(encoding="utf-8")) == summary
            Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
