# S1 camera handoff verification — 2026-11-15

Live simulator runs, seed 1001, Recorded media off, one Zoom per station:

| Speed | Run | Measured wall duration |
| --- | --- | --- |
| 2× | s1_seed1001_064 | 59.906 s |
| 5× | s1_seed1001_065 | 23.969 s |

Both produced the same transitions for the first picket engagement (linked to `trk-3`).
Measured live frames, replayed through the production JavaScript camera state machine:

| Simulation clock | Mode | Latest linked RGB observation |
| --- | --- | --- |
| 01:06.4 | Zoom first in view | 01:06.2 |
| 01:23.6 | Wide RGB | 01:23.6 |
| 01:24.0 | Zoom | 01:24.0 |
| 01:24.8 | Wide RGB | 01:24.8 |
| 01:25.2 | Wide RGB | 01:25.2 |
| 01:25.6 | Zoom | 01:25.6 |
| 01:26.0 | Wide RGB | 01:26.0 |
| 01:26.4 | Zoom | 01:26.4 |
| 01:26.8 | Wide RGB | 01:26.8 |
| 01:40.8 | Target out of camera view | none current |

Wide mode displays “Wide RGB · Zoom repositioning” while a Zoom task remains assigned.
Near the FOV boundary the simulator genuinely alternates visibility; no hysteresis or changed
detections were introduced. Ordinary frames reuse the player's source key and do not reload it.
Map tracking and alert selection are independent of this display choice.

The natural run covers Zoom → RGB → Zoom. Separately, the controlled JavaScript regression
tests opening → Zoom → RGB → repeated RGB → out-of-view → Zoom and alert/run resets.
That test supplies visibility booleans; it is not a second measured scenario or a browser replay.

All three S1 DVIDS cuts exist locally (228680, 236461, 248136 bytes). Wide RGB reuses
`shadow_contrails`, the distant approach, as an illustrative STAND-IN, credited to DVIDS /
Tech. Sgt. Michael McGhee. It is not synchronized wide/zoom footage of this track.
The Wide clip and all three unchanged S2 MP4 endpoints returned HTTP 200 / video/mp4.

Browser visual rendering, video decoding, audio, and an actual S2 playback session remain
unverified: the browser automation tool returned “The browser access host is unavailable”.
The Node tests verify handoff decisions and source-key playback stability, not video decoding.

Validation: **111 dashboard tests passed**; `ruff check .`, `ruff format --check .`, JavaScript
syntax check and `git diff --check` passed. The suite emits the existing Starlette/httpx
deprecation warning. No dependency was added.

Rehearse locally:

1. Run `uv run python scripts/run_demo.py --dashboard --port 8021`.
2. Open `http://127.0.0.1:8021/`, hard refresh, choose S1, leave Recorded media off, Start,
   then choose 2×. Preserve the acoustic → camera text → Zoom opening.
3. After alerts appear select the card linked to the first engagement (`trk-3` in these runs).
   Watch 01:23–01:27. Confirm Wide RGB status, STAND-IN / DVIDS credit and return to Zoom.
4. Stop; repeat at 5×. Around 01:41 check out-of-view status and the estimated map track.
5. Stop; select S2, enable Recorded media, Start. Check all four current sample cuts play and audio
   still works. S2 has no automatic RGB handoff.
6. For reproducible API measurements with this port free of an active run:
   `uv run python scripts/check_handoff_live.py`, then `node scripts/report_handoff.cjs`.
   Raw live frames are saved to `runs/handoff-live.json` (untracked).
7. Regression checks: `uv run pytest tests/dashboard -q`, `uv run ruff check .`,
   `uv run ruff format --check .`, `node --check src/cuas/dashboard/static/app/app.js`.

No held-out evaluations or frozen decision gate were run. Pipeline detection generation,
classification, and evidence behavior are unchanged. Contract samples were regenerated for
the additive display field; they do not represent new detector results.
