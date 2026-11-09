# GitHub workflow

Use the private `mithun2244/counter-drone-system` repository. `main` contains accepted phases. Work on the current phase branch and merge after its acceptance checks pass. See [the phase plan](docs/phases.md) for the active branch and open checks.

## Publish a phase branch

1. From the repository root, check `git status --short --branch` and review the commit diff. Include only the intended changes. Keep recordings, model weights, generated runs, and secrets out of Git.
2. Apply the documentation check below.
3. Push the named phase branch. For Phase 5:

   ```sh
   git push -u origin phase-5-operator-dashboard
   ```

4. Check the branch on GitHub and use it for review. Record test results and pending acceptance checks in [project memory](docs/memory.md).

## Documentation check before pushing

| Change | Documentation to review |
| --- | --- |
| Setup, dependencies, commands, or user-facing behavior | [README.md](README.md) and any affected setup or data notes |
| Commands or workflow for coding agents | [CLAUDE.md](CLAUDE.md) |
| Branching, review, or publishing workflow | [GITHUB.md](GITHUB.md) and [repository rules](docs/rules.md) |
| Architecture, interfaces, or dashboard data | [Architecture](docs/architecture.md), [design](docs/design.md), or the [dashboard contract](docs/dashboard_contract.md) |
| Phase progress, tests, or decisions | [Phase plan](docs/phases.md) and [project memory](docs/memory.md) |

Include updates to the affected docs on the same branch or pull request as the change. See [Git rules](docs/rules.md#8-git).
