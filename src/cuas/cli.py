"""The ``cuas`` command. ``cuas verify RUN_DIR`` checks a run's evidence chain, every file its
records list, and the recorder's hashes of every recording kept for the run.

It lives outside ``cuas.evidence`` because the recordings check belongs to the station's
recorder, and components may not import each other.
"""

import argparse
import sys
from pathlib import Path

from cuas.evidence.verify import verify_chain
from cuas.station.recorder import verify_recordings

FAILED = 1


def verify(run_dir: Path) -> int:
    report = verify_chain(run_dir)
    problems = report.problems + verify_recordings(run_dir)
    if problems:
        print(f"FAILED {run_dir}: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  {problem}")
        return FAILED
    files = {f.path for r in report.records for f in r.files}
    head = report.records[-1] if report.records else None
    where = (
        "empty chain"
        if head is None
        else f"head seq {head.seq} sha256:{head.record_hash}"
    )
    print(
        f"verified {run_dir}: {len(report.records)} records, {len(files)} files, {where}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cuas", description="C-UAS demo tools")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("verify", help="check a run folder's evidence")
    check.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    return verify(args.run_dir)


if __name__ == "__main__":
    sys.exit(main())
