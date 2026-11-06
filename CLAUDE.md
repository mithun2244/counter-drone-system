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

## Commands
- Install: `uv sync`
- Tests: `uv run pytest`
- Lint: `uv run ruff check . && uv run ruff format --check .`
- Run a scenario: `uv run python scripts/run_demo.py --scenario s1`

## Workflow
1. Read memory.md and the current phase in phases.md.
2. Plan, get approval, then code in small commits.
3. Run tests and lint before saying a task is done.
4. Update memory.md at the end of the session.
