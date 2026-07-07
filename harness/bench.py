#!/usr/bin/env python3
"""Benchmark runner for the multi-solver Opus Magnum harness.

Runs every solver adapter on every puzzle instance, validates every
produced plan with the canonical validator (harness/validate.py), and
emits a markdown comparison table.

Usage:
    python3 harness/bench.py \
        --adapter clingo="python3 harness/adapters/clingo/adapter.py" \
        [--adapter name=cmd ...] \
        [--puzzle harness/puzzles/foo.json ...] \
        [--timeout 300] [--out bench.md] [--keep-plans DIR]

Adapter contract (see harness/README.md):
    <adapter-cmd> <puzzle.json>
writes the plan JSON to stdout and exits 0 on solve; any nonzero exit (or
timeout, or unparseable stdout) counts as unsolved. Anything the adapter
prints to stderr is passed through for the log. Wall time is measured by
this runner around the whole adapter invocation.
"""
import argparse
import glob
import json
import os
import shlex
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from validate import Invalid, Malformed, plan_length, validate  # noqa: E402


def run_one(name, cmd, puzzle_path, puzzle, timeout, keep_dir):
    argv = shlex.split(cmd) + [puzzle_path]
    t0 = time.time()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout)
        wall = time.time() - t0
        timed_out = False
    except subprocess.TimeoutExpired as e:
        wall = time.time() - t0
        proc, timed_out = e, True
    stderr = (proc.stderr or "")
    if stderr.strip():
        for line in stderr.strip().splitlines():
            print(f"    [{name}] {line}", file=sys.stderr)

    row = {"puzzle": puzzle["name"], "solver": name, "solved": False,
           "valid": None, "wall": wall, "length": None, "note": ""}
    if timed_out:
        row["note"] = f"timeout after {timeout}s"
        return row
    if proc.returncode != 0:
        row["note"] = f"exit {proc.returncode}"
        return row
    try:
        plan = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        row["note"] = f"unparseable plan JSON ({e})"
        return row
    row["solved"] = True
    if keep_dir:
        path = os.path.join(keep_dir, f"{puzzle['name']}.{name}.plan.json")
        with open(path, "w") as f:
            json.dump(plan, f, indent=2)
    try:
        complete_at = validate(puzzle, plan)
        row["valid"] = True
        row["length"] = plan_length(plan)
        done = ", ".join(f"{p}@t={t}" for p, t in sorted(complete_at.items()))
        print(f"    [validator] PASS  {puzzle['name']} x {name}: "
              f"plan length {row['length']}, complete: {done}",
              file=sys.stderr)
    except (Invalid, Malformed) as e:
        row["valid"] = False
        row["note"] = str(e)
        print(f"    [validator] FAIL  {puzzle['name']} x {name}: {e}",
              file=sys.stderr)
    return row


def markdown_table(rows):
    lines = ["| puzzle | solver | solved | valid plan | wall time (s) | "
             "plan length |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        solved = "yes" if r["solved"] else f"no ({r['note']})"
        if r["valid"] is None:
            valid = "-"
        elif r["valid"]:
            valid = "yes"
        else:
            valid = f"NO ({r['note'][:60]})"
        length = r["length"] if r["length"] is not None else "-"
        lines.append(f"| {r['puzzle']} | {r['solver']} | {solved} | {valid} "
                     f"| {r['wall']:.2f} | {length} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapter", action="append", required=True,
                    metavar="NAME=CMD",
                    help='e.g. clingo="python3 harness/adapters/clingo/'
                         'adapter.py"')
    ap.add_argument("--puzzle", action="append", default=None,
                    help="puzzle JSON path (default: harness/puzzles/*.json)")
    ap.add_argument("--timeout", type=float, default=300,
                    help="per-run hard timeout in seconds (default 300)")
    ap.add_argument("--out", help="also write the markdown table here")
    ap.add_argument("--keep-plans", metavar="DIR",
                    help="save every produced plan JSON into DIR")
    args = ap.parse_args()

    adapters = []
    for spec in args.adapter:
        if "=" not in spec:
            ap.error(f"--adapter must be NAME=CMD, got {spec!r}")
        adapters.append(tuple(spec.split("=", 1)))
    puzzle_paths = args.puzzle or sorted(
        glob.glob(os.path.join(HERE, "puzzles", "*.json")))
    if not puzzle_paths:
        ap.error("no puzzle instances found")
    if args.keep_plans:
        os.makedirs(args.keep_plans, exist_ok=True)

    rows = []
    for path in puzzle_paths:
        with open(path) as f:
            puzzle = json.load(f)
        for name, cmd in adapters:
            print(f"== {puzzle['name']} x {name}", file=sys.stderr)
            rows.append(run_one(name, cmd, path, puzzle, args.timeout,
                                args.keep_plans))

    table = markdown_table(rows)
    print()
    print(table)
    if args.out:
        with open(args.out, "w") as f:
            f.write(table + "\n")
    bad = [r for r in rows if r["valid"] is False]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
