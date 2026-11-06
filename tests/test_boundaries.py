"""Import rules from docs/rules.md section 2, checked on the source tree itself."""

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src" / "cuas"
WALL_CLOCK_OR_UNSEEDED = {"time", "datetime", "random"}
SEPARATE_COMPONENTS = {"station", "gateway", "control"}
TRUTH_MODULE = "cuas.sim.truth"


def imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def is_under(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def violation(owner: str, module: str) -> str | None:
    """Why ``owner`` (a folder or file directly under ``cuas``) must not import ``module``."""
    if module.split(".")[0] in WALL_CLOCK_OR_UNSEEDED:
        return "use cuas.clock and cuas.sim.rng"
    if is_under(module, "cuas.metrics") and owner != "metrics":
        return "only the composition root may reach the evaluator"
    if is_under(module, "cuas.sim") and owner != "sim":
        if owner == "metrics" and is_under(module, TRUTH_MODULE):
            return None
        return "ground truth is for the evaluator only"
    if owner in SEPARATE_COMPONENTS:
        for other in SEPARATE_COMPONENTS - {owner}:
            if is_under(module, f"cuas.{other}"):
                return "components talk only through bus messages"
    return None


def violations(relative_path: Path, source: str) -> list[str]:
    owner = relative_path.parts[0]
    found = [(module, violation(owner, module)) for module in imported_modules(source)]
    return [f"{relative_path}: {module}: {why}" for module, why in found if why]


def test_source_tree_obeys_the_import_rules() -> None:
    files = sorted(SOURCE.rglob("*.py"))
    assert len(files) > 25  # the walk really found the package
    problems = [
        problem
        for file in files
        for problem in violations(
            file.relative_to(SOURCE), file.read_text(encoding="utf-8")
        )
    ]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("control/x.py", "from cuas.sim.truth import TruthLog"),
        ("control/x.py", "import cuas.sim.engine"),
        ("gateway/x.py", "from cuas import sim"),
        ("station/x.py", "from cuas.sim.scenario import Scenario"),
        ("dashboard/x.py", "from cuas.sim import truth"),
        ("evidence/x.py", "from cuas.sim.truth import TargetState"),
        ("schemas/x.py", "import cuas.sim"),
        ("metrics/x.py", "from cuas.sim.engine import run_scenario"),
        ("sim/x.py", "from cuas.metrics import evaluator"),
        ("control/x.py", "from cuas.metrics.evaluator import summarize"),
        ("sim/x.py", "import time"),
        ("sim/x.py", "from time import time"),
        ("clock.py", "import time"),
        ("sim/x.py", "from datetime import datetime"),
        ("sim/x.py", "import random"),
        ("control/x.py", "from cuas.station.video import detect"),
        ("gateway/x.py", "import cuas.control.tracker"),
    ],
)
def test_forbidden_imports_are_caught(path: str, source: str) -> None:
    assert violations(Path(path), source)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("metrics/x.py", "from cuas.sim.truth import TruthLog"),
        ("sim/x.py", "from cuas.sim.truth import TruthLog"),
        ("control/x.py", "from cuas.schemas import Track"),
        ("control/x.py", "from cuas.geometry import bearing_to"),
        ("control/x.py", "from cuas.config import ScenarioMetadata"),
        ("station/x.py", "from cuas.station.video import detect"),
    ],
)
def test_allowed_imports_pass(path: str, source: str) -> None:
    assert not violations(Path(path), source)
