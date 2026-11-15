# Post-run operator summary

For the subsequently reproduced stale-server 404 and successful recorded-media HTTP checks,
see `run_summary_failure.md`. Static page refresh does not reload Python handlers: restart the
server after dashboard backend changes, then start a fresh run. Current requests include the
run ID, reject a mismatched current run with 409, and show HTTP error details plus Retry.

S1 and S2 now retain a server-side run history until the next run starts. At completion the
operator page replaces the queue with **Run complete**, scenario, elapsed simulation time,
active-alert count, unique tracks that raised alerts, and evidence-record count. A manual stop
shows **Run stopped**; failures show **Run failed**. The camera panel is hidden, live camera
notes cleared and playback/audio paused. A historical pin replaces live map overlays.

`GET /api/run/summary` returns the current run's summary and survives browser reconnection.
The latest detection comes from accepted BearingDetection/PicketAlert bus messages, using its
own simulation timestamp and sensor/station. Recorded microphone or snapshot associations may
supply a track ID; no association is guessed. Classification and peak alert level are shown
when available. Missing fields say **Unavailable**. Linked positions use the Track message's
timestamp, independently of detection time. If the latest detection is unassociated, a separate
last-known track estimate is shown and pinned, explicitly labelled as having unavailable
association to the latest detection. No detections yields **No detections recorded**.

**Export run summary** downloads the displayed data as local JSON. It does not generate an
evidence hand-off or modify the closed evidence chain. The existing evidence keeper still
exports hand-offs at run end. Existing live label/export API behavior is unchanged.

Measured with the default scenario seeds, simulator-only runs via the local TestClient:

| Scenario | End time | Active alerts | Unique alerted tracks | Evidence records | Most recent sensor detection | Last estimated position |
| --- | --- | --- | --- | --- | --- | --- |
| S1 / 1001 | 120.0 s | 0 | 3 | 10 | 109.8 s, st1.thermal | trk-6 at 113.0 s, (-64.9823, 134.8463, 121.4832) m ENU |
| S2 / 2002 | 120.0 s | 0 | 1 | 2 | 114.8 s, st1.rgb | trk-2 at 118.0 s, (-241.0396, 108.1317, 62.0604) m ENU |

In both, the latest raw detection has no retained track association. Track/classification/peak
fields therefore show unavailable rather than borrowing the final estimate's identity.
The test compares detection time, unique-track count and last-position time against actual
bus messages and evidence count against the written chain, not against hard-coded metrics.

Automated verification: dashboard/live-run suite, summary rendering with DOM/video/drawing
stubs, no-detection response, manual stop, repeated summary reads and new-run reset. Existing
S1 handoff and S2 wedge/player regressions remain included. Chrome verification was attempted,
but the browser tool returned **The browser access host is unavailable**. Actual Chrome layout,
end-of-run transitions and playback smoke checks remain unverified. The measured S2 summary
above is simulator-only; a recorded-media S2 browser rehearsal remains to be done.

128 dashboard/live-run tests passed. Ruff lint/format, JavaScript syntax and diff whitespace
checks passed. The existing Starlette/httpx deprecation warning remains.

Rehearse:

1. Restart `uv run python scripts/run_demo.py --dashboard --port 8021`, open
   `http://127.0.0.1:8021/` in Chrome and hard-refresh.
2. Run S1, Recorded media off, at 5×. Check the existing handoff around 01:25, then let it
   end naturally. Check the summary against the S1 row above and the historical pin.
3. Export the summary JSON. Confirm live Zoom status has disappeared. Wait or reconnect:
   the summary should remain. Start S2 and confirm the S1 summary clears immediately.
4. Run S2 without recorded media to compare with the row above. Repeat with Recorded media
   on to smoke-test automatic yellow wedge and once-only sample playback before completion;
   recorded-media results may differ from the simulator-only row.
5. Start another run and stop immediately, before any detection. Expect **Run stopped**,
   **No detections recorded**, separate zero counts, and no historical pin.
6. A naturally completed no-detection case is covered with controlled API/UI states; do not
   alter S1/S2 detection generation to manufacture it.

Checks: `uv run pytest tests/dashboard tests/test_live_runs.py -q`, `uv run ruff check .`,
`uv run ruff format --check .`, `node --check src/cuas/dashboard/static/app/app.js`.
