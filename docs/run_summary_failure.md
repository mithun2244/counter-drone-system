# Run summary failure: stale server process

## Reproduction and confirmed cause

The dashboard at `http://127.0.0.1:8021/` was still running Python PID 12532, started
2026-11-15 14:42:44. `server.py` containing the summary route was saved later (15:20:54).
Python handlers remain loaded until restart, while StaticFiles serves newer JavaScript from
disk. The new frontend requested an API route that the old process did not have.

The existing completed recorded-media run was `s1_seed1001_069`. A fresh reproduction,
`s1_seed1001_070`, used S1 / Fictional Processing Plant, Recorded media enabled, 5×. It ended
at 120.0 s, evidence head 10. Immediately after its ended WebSocket event:

```text
GET http://127.0.0.1:8021/api/run/summary
HTTP 404
{"detail":"Not Found"}
```

A repeat request returned the same response. This is route-level Not Found, not the current
handler's `{"detail":"No run"}` response. The old server had neither the new route nor the
new live summary collector, so no new summary was being made available for run 070. This was
not a summary-generation timing race. Its evidence files remain intact.

The old server used Uvicorn `log_level="warning"`; HTTP access lines were suppressed. There
is no matching old 404 access line to recover. The original HTTP response and final frame are
captured in `runs/summary-http-before.json`; do not mistake client capture for a server log.

## Fix

Restarted the ended, stale process on the same port with current code. The replacement runs
unbuffered and captures stdout/stderr under `runs/summary-server.*.log`. Uvicorn now logs HTTP
access requests. Summary requests carry `?run_id=...` so request logs identify the run; the
backend returns 409 if that ID is no longer current. The frontend now shows HTTP status/body,
an explicit server-restart message for 404, and a Retry summary action instead of permanently
caching a generic error with no recovery control. No pipeline or existing media behavior changed.

Static page refresh does not reload Python. After changing dashboard Python code, restart the
server after the current run ends, then refresh the page. A restart cannot reconstruct the
old process's in-memory collector: start a fresh run for a new summary.

## Live verification after restart

All cases used the same real server on port 8021, Recorded media enabled, speed set to 5×.
HTTP requests were made as soon as the ended WebSocket event arrived, then repeated.

| Run | End | First summary response | Alerted tracks | Evidence records |
| --- | --- | --- | --- | --- |
| s1_seed1001_071 | completed, 120.0 s | 200 | 3 | 10 |
| s2_seed2002_058 | completed, 120.0 s | 200 | 1 | 2 |
| s1_seed1001_072 | manually stopped, 0.2 s | 200 | 0 | 0 |

S1 response body:

```json
{"run_id":"s1_seed1001_071","scenario":"Processing plant watch","scenario_id":"s1","state":"ended","ended_reason":"completed","elapsed_s":120.0,"active_alerts":0,"unique_alert_tracks":3,"evidence_records":10,"latest_detection":{"t":109.80000000000001,"sensor":"st1.thermal","track_id":null},"last_position":{"x":-64.98230849818486,"y":134.84632331411655,"z":121.48315746551516,"t":113.0,"track_id":"trk-6"}}
```

Matching server log, in `runs/summary-server.stdout.log`:

```text
run s1_seed1001_071 ended: control digest sha256:d03086c5efe3714c6a2e24dbee1a0bfb6852f7e3ea7ab37c0d4532257af1fdb7
  10 evidence records; check: uv run cuas verify D:\Counter Drone Ditection System\cuas-demo\runs\s1_seed1001_071
INFO:     127.0.0.1:52561 - "GET /api/run/summary?run_id=s1_seed1001_071 HTTP/1.1" 200 OK
INFO:     127.0.0.1:52561 - "GET /api/run/summary?run_id=s1_seed1001_071 HTTP/1.1" 200 OK
```

S1's latest sensor detection remains unassociated: track/classification/peak are explicitly
Unavailable, and trk-6's estimate is shown separately as Historical with its own 113.0 s time.
S2's latest RGB detection is backend-linked to trk-2 at 114.8 s, classified drone, peak red;
its last estimate is at 118.0 s. Manual stop has no detections and no historical pin.

Raw URLs, HTTP statuses, full bodies and final frames are saved in:

- `runs/summary-http-s1-fixed.json`
- `runs/summary-http-s2-fixed.json`
- `runs/summary-http-stop-fixed.json`

Each has a corresponding `.download.json` containing the verified summary payload. Production
summary rendering and the Blob/download click handler were tested with these exact payloads
using DOM/drawing/URL stubs. Counts, historical-pin data and downloaded JSON match. This tests
the action logic, not Chrome's download UI or canvas pixels.

128 dashboard/live-run tests passed; Ruff lint/format, JavaScript syntax and diff whitespace
checks passed. Existing S1 handoff and S2 acoustic/player regressions remain included. The
browser tool still returned **The browser access host is unavailable**. Actual Chrome summary
layout, historical-pin appearance and clicking the download button remain visually unverified.

To repeat the live checks while no other run is active:

```text
uv run python scripts/check_summary_http.py --out runs/summary-http-s1-fixed.json
uv run python scripts/check_summary_http.py --scenario s2 --out runs/summary-http-s2-fixed.json
uv run python scripts/check_summary_http.py --stop --out runs/summary-http-stop-fixed.json
node tests/dashboard/summary_ui.cjs runs/summary-http-s1-fixed.download.json
```

The updated server is already running at `http://127.0.0.1:8021/`. Hard-refresh the page before
the next rehearsal. These run artifacts/logs remain ignored by Git; existing uncommitted work
was preserved.
