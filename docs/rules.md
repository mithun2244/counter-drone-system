# Rules — how we work on this repo

> Rules for every human and every Claude Code session. Short on purpose.

## 1. Before you code

- Read `docs/memory.md` first to know the current phase and recent decisions.
- Work **only on the current phase** in `docs/phases.md`. Do not start the next phase early.
- For any task bigger than one file: write a short plan first and wait for approval.
- If a doc is unclear or wrong, stop and ask. Do not guess silently.

## 2. Code style

- Python 3.11+, full type hints, `ruff` for lint and format.
- Small functions (aim for under 40 lines) and small modules with one job each.
- Components talk **only through bus messages** in `src/cuas/schemas/`. No direct imports between `station/`, `gateway/` and `control/` internals.
- No magic numbers in code. Tunable values go in `config/site.yaml` or scenario files.
- Use the single simulated clock (`cuas.clock`) inside the pipeline. Never call `time.time()` there.
- Use the `logging` module, not `print`, except in scripts.
- Use the units from `architecture.md`: metres, seconds, degrees, ENU frame.
- Only `cuas.sim` and `cuas.metrics` may touch simulation ground truth. It never goes on the bus.

## 3. Tests

- Every new module gets tests in `tests/` that mirror `src/`.
- Maths (triangulation, Kalman, threat score) needs tests with known answers.
- Fixed random seeds everywhere, so the same scenario gives the same result.
- `pytest` must pass before a phase is marked done.
- Never weaken or delete a test to make it pass. Fix the code or ask.

## 4. Dependencies

- Ask before adding a new dependency. Say why it is needed and what its licence is.
- Pin versions in the lock file.
- **Licence watch:** Ultralytics YOLO is AGPL-3.0. That is fine for an internal demo, but it needs a commercial licence or a swap to a permissive detector before anything is delivered to the client.

## 5. Data and privacy

- Public datasets only. Record each dataset's name, URL and licence in `data/README.md`.
- Check each licence before use. Some (for example Drone-vs-Bird) are non-commercial only.
- Never commit `data/`, `models/` or `runs/`.
- Never put client footage or Saudi site data in this repo. The real system keeps such data in the Kingdom.
- No secrets, keys or passwords in code or config. Use environment variables.

## 6. Honesty

- Never invent metrics. Report only numbers produced by the metrics script.
- Label simulator results as simulator results.
- If something is stubbed or mocked, mark it with `# MOCK:` and list it in `memory.md`.

## 7. Scope guard

- The system **detects and reports only**. No jamming, takeover or any mitigation code, ever.
- Hand-off is a JSON export in the demo. No real external connections.

## 8. Git

- One small commit per finished task, with a clear message (`tracker: add triangulation with angle check`).
- Work on a branch per phase (`phase-3-tracker`). Merge when its acceptance checks pass.
- Before publishing changes to GitHub, review `README.md`, `CLAUDE.md`, `GITHUB.md` and any other docs the change affects. Update the affected docs on the same branch or pull request before pushing. Check setup and run commands, workflow instructions, contracts, and phase status as applicable.

## 9. End of every session

Update `docs/memory.md`:

- what was done,
- decisions made and why,
- known issues and mocks,
- the exact next step.
