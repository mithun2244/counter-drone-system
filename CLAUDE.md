# C-UAS Detection Demo

Software demo of a passive counter-drone detection system (cameras + microphones, no radar/RF).
Detect and report only. Never write mitigation code.

## Always loaded
@docs/rules.md
@docs/memory.md

## Read when relevant (not auto-loaded, to save context)
- Requirements and scenarios: `docs/prd.md`
- Components, folders, messages, stack: `docs/architecture.md`
- Algorithms and dashboard design: `docs/design.md`
- Phase tasks and acceptance checks: `docs/phases.md`
- Dashboard API, WebSocket messages and examples: `docs/dashboard_contract.md`
- GitHub branch, push and documentation workflow: `GITHUB.md`

## Commands
- Install: `uv sync`
- Regular tests: `uv run pytest --ignore=tests/test_decision.py`. The frozen Phase 4 gate is recorded in `docs/memory.md`.
- Lint: `uv run ruff check . && uv run ruff format --check .`
- Run a scenario in real time: `uv run python scripts/run_demo.py --scenario s1`
- Run a scenario as fast as possible: add `--fast`
- Start the dashboard: `uv run python scripts/run_demo.py --dashboard`
- Verify evidence: `uv run cuas verify runs/<run_id>`, substituting the actual run folder name

## Workflow
1. Read memory.md and the current phase in phases.md.
2. Plan, get approval, then code in small commits.
3. Run tests and lint before saying a task is done.
4. Update `docs/memory.md` at the end of the session.
5. Before publishing changes to GitHub, apply the documentation check in `docs/rules.md` §8.

## Workflow rules with Superpowers
- Use `docs/phases.md` and `docs/rules.md` as the project's workflow.
- Plan one phase at a time in Plan Mode, and wait for approval before implementation.
- Use one branch per phase.
- Ask before creating a separate worktree or using subagents.
- Use Superpowers for focused debugging, testing and code review when useful.
- Skip Superpowers brainstorming and writing-plans for this project. Use our existing phase plan and approval process in Plan Mode.
- Keep plans in the existing project docs.
- Follow the repo's existing test rules.
