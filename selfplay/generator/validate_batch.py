#!/usr/bin/env python3
"""Re-validate every generated (puzzle, plan) pair in a batch directory
through the canonical harness validator (harness/validate.py).

The generator already validates each pair before writing it; this script
re-checks the files on disk from scratch (nothing from the generation run
is trusted), so it can be used by consumers of a batch, in CI, or after
hand-editing pairs.

Usage:
    python3 selfplay/generator/validate_batch.py BATCH_DIR [--verbose]

BATCH_DIR must contain puzzles/NAME.json and plans/NAME.json (the layout
written by generator.py). Exit 0 iff every pair passes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from model import load_harness_validator


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate a generated batch with harness/validate.py.")
    ap.add_argument("batch", type=Path, help="batch directory")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    hval = load_harness_validator()
    puzzles = sorted((args.batch / "puzzles").glob("*.json"))
    if not puzzles:
        print(f"no puzzles found under {args.batch / 'puzzles'}")
        return 2
    fails = 0
    for pz_path in puzzles:
        pl_path = args.batch / "plans" / pz_path.name
        puzzle = json.loads(pz_path.read_text())
        try:
            plan = json.loads(pl_path.read_text())
        except FileNotFoundError:
            fails += 1
            print(f"FAIL  {pz_path.name}: no matching plan {pl_path}")
            continue
        try:
            complete_at = hval.validate(puzzle, plan)
        except (hval.Invalid, hval.Malformed) as e:
            fails += 1
            print(f"FAIL  {pz_path.name}: {e}")
            continue
        if args.verbose:
            done = ", ".join(f"{pid}@t={t}"
                             for pid, t in sorted(complete_at.items()))
            print(f"PASS  {pz_path.name}: plan length "
                  f"{hval.plan_length(plan)}, complete: {done}")
    n = len(puzzles)
    print(f"{n - fails}/{n} pairs PASS (canonical harness validator)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
