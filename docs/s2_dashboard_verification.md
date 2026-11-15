# S2 automatic video and acoustic cue — 2026-11-15

The dashed yellow “Last heard from” wedge now follows the track whose Zoom video opens
automatically. A selected alert overrides automatic focus. Only that track's backend `heard`
bearings are used; labels retain station, direction and observation time. Acoustic sectors
controls both this wedge and the separate solid amber unconfirmed sectors. No detection,
association or scenario ordering was changed. A video can precede the first linked microphone
bearing: the yellow wedge appears when that bearing arrives, never before.

S2 plays once per run. After the final cut it holds the last frame, keeps SAMPLE and the
Svanström source caption visible, and shows **Sample clip ended** with **Replay**. Updates,
collapse/expand and alert selection do not restart a completed sequence. Replay resets to
the first cut; starting another run also resets playback. S1 continues to loop and hand off
between Zoom and Wide RGB as before.

All 17 local held-out RGB drone clips were inspected for duration and representative opening
frames. Durations range from 10.000 to 10.933 seconds; no long continuous recording exists
among those clips. `V_DRONE_102` (test group V_DRONE_102, F450, 10.167 s) provides a visibly
different blue-sky shot. Frames at 0, 2, 4, 6, 8 and 10 seconds were inspected before adding
it as the final shot. `V_DRONE_005` has multiple drone types and was not added. The original
three cuts remain in their original order.

| Cut | Used duration |
| --- | --- |
| V_DRONE_027 | 10.233 s |
| V_DRONE_033, 0–4 s | 4.000 s |
| V_DRONE_032, 2–9 s | 7.000 s |
| V_DRONE_102 | 10.167 s |
| Total | 31.400 s |

Three 0.6 s crossfades give approximately 29.6 s of playback, subject to browser event timing.
The additional clip uses its existing manifest SHA-256, test split and dataset attribution.
No training or evaluation was run and the manifest was not changed.

Automated checks cover automatic/manual acoustic focus, both wedge styles, sector toggle,
sequence end, held-frame state, Replay, new-run reset, no restart on routine updates, retained
SAMPLE/source caption, and the S1 handoff/player regressions. Browser verification was attempted
but the tool returned **The browser access host is unavailable**. Simultaneous visual video/wedge
display, browser video decoding, actual final-frame rendering and S1 visual handoff remain
unverified. Node tests simulate video events and drawing calls; they are not browser playback.

Results: 112 dashboard tests passed, including S1 handoff and source stability regressions.
Repository ruff lint/format, JavaScript syntax and diff whitespace checks passed. The existing
Starlette/httpx deprecation warning remains. No dependency was added.

To rehearse:

1. Restart the local dashboard server to load the new clip config:
   `uv run python scripts/run_demo.py --dashboard --port 8021`.
2. Hard-refresh `http://127.0.0.1:8021/`. Choose S2, enable Recorded media and Acoustic sectors,
   Start, then choose 2×. Do not click an alert: video opens automatically; its yellow wedge
   follows when the backend supplies a linked microphone bearing. Check station and timestamp.
3. Select another live alert if one is available: its linked wedge takes priority. An alert
   without a linked microphone bearing must not borrow another track's wedge. Toggle Acoustic
   sectors off/on and confirm both yellow and amber sectors hide/reappear.
4. Wait about 30 wall seconds after playback starts. Check the held frame, SAMPLE/source
   caption and **Sample clip ended**. Wait through further dashboard updates, then click
   Replay and confirm playback starts from the first overcast shot.
5. Stop, choose S1 with Recorded media off. Verify acoustic → camera text → Zoom opening,
   then Zoom/Wide RGB handoff around 01:25. See `handoff_verification.md` for prior measurements.

Commands: `uv run pytest tests/dashboard -q`, `node tests/dashboard/s2_player.cjs`,
`uv run ruff check .`, `uv run ruff format --check .`.
