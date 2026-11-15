# Demo changes for branch review

Branch: `phase-5-operator-dashboard`. Publication was explicitly approved by the user.
This update does not accept Phase 5, merge to main, or start Phase 6.

## Included

- S1 same-track Zoom → Wide RGB → Zoom handoff, fresh RGB checks, preserved opening,
  out-of-view status and stable playback. Wide footage is labelled STAND-IN with DVIDS credit.
- S2 automatic linked microphone marker, manual-selection priority, Acoustic sectors toggle,
  once-only sample playback, held final frame and Replay. The existing cuts are followed by
  local held-out V_DRONE_102, with SAMPLE label and source attribution.
- Server-retained post-run summary, natural/manual end states, historical map pin, missing-field
  handling, separate counts and local JSON export. Run-scoped API requests, actionable errors,
  retry and request logging cover the stale-server failure.
- Focused regression tests, live HTTP rehearsal scripts, updated contract schema and generated
  contract fixtures under docs/samples, runbook and verification reports.

## Verification actually completed

128 dashboard/live-run tests passed, including S1 handoff, S2 marker/playback, summary reset,
no-detection/manual-stop and export-handler checks. Ruff lint/format, JavaScript syntax and
diff whitespace checks passed. The existing Starlette/httpx deprecation warning remains.

Live HTTP/WebSocket checks against the running Windows server:

| Check | Result |
| --- | --- |
| S1 at 2× and 5×, simulator-only | Fresh same-track RGB at 84.8/85.2 s; Zoom reacquisition at 85.6 s |
| Recorded-media S1 at 5×, run _071 | Immediate summary HTTP 200, 3 alerted tracks, 10 evidence records |
| Recorded-media S2 at 5×, run _058 | Immediate summary HTTP 200, 1 alerted track, 2 evidence records |
| Recorded-media manual stop, S1 _072 | Immediate HTTP 200 at 0.2 s, no detections, zero counts |
| Summary render/export handlers | Node tests with the actual HTTP payloads; JSON content and historical-pin data match |

**Live browser checks completed for this batch: none.** Browser tools returned “The browser
access host is unavailable.” HTTP traffic is not visual verification, and Node DOM/video/drawing
stubs do not verify decoding or canvas pixels. Chrome checks still needed: S1 opening/handoff,
S2 automatic video/yellow wedge together, manual selection/toggle, final-frame hold/Replay,
post-run layout/historical pin, JSON download interaction and new-run visual reset. Audio and
network-disconnected cold start also remain pending. No frozen gate or held-out evaluation
was rerun.

## Media and excluded artifacts

No new binary media is included. The three existing DVIDS stand-ins remain the only approved
stand-in MP4 exceptions in rules.md §5; this update reuses them. V_DRONE_102 is referenced by
manifest hash and test split in display_clips.yaml, not committed as a raw dataset asset.
Generated runs, full HTTP captures, local server logs, contact sheets, dataset footage and model
weights stay under ignored runs/, data/ and models/. Documentation contains the relevant
measured values and a short diagnostic response/log excerpt, not the generated run directories.

## Review and rehearsal

Start `uv run python scripts/run_demo.py --dashboard` from a fresh server and open
`http://127.0.0.1:8000/`. Follow [the runbook](demo_run_order.md). The optional HTTP rehearsal
scripts use port 8021; launch with `--port 8021` for those scripts. Local recordings/models are
needed for Recorded media; without them, use simulator-only runs and the committed stand-ins.

Detailed evidence and limits: [S1](handoff_verification.md), [S2](s2_dashboard_verification.md),
[post-run summary](run_summary_verification.md), [stale-server diagnosis](run_summary_failure.md).
