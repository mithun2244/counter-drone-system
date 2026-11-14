# Known issues

Short list of open items for the demo. The full record is in `docs/memory.md` (Known issues) and `REVIEW.md`.

## Next sprint

- **"Running slower than real time" notice.** A recorded-media run can fall behind real time (recorded-media S3 finished 91.7 to 94.6 s against 97.2 s allowed, and runs up to 4.6 s behind in its first seconds, `docs/memory.md`). The clock already measures the lag (`SimClock.behind_s`, commit `9a106c6`), but nothing shows it on screen yet: the dashboard lags silently. Planned: a `behind_real_time` flag on the `run` message with thresholds in `site.yaml`, and a top-bar notice. Skipped for the 2026-11-16 demo by the user's decision on 2026-11-14.
