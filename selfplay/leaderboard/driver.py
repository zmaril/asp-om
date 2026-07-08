#!/usr/bin/env python3
"""Self-competition driver for the incumbent leaderboard (Loop 3).

Feeds a stream of candidate solutions into the incumbent store
(store.py), logs every submission and every incumbent improvement, and
renders the leaderboard as a markdown table.

INVARIANT: every candidate is one of OUR OWN solutions and must pass
the canonical validator (harness/validate.py) -- store.submit() enforces
this, and this driver additionally discards perturbation candidates that
fail validation at generation time. External solutions are never
submitted; the only place external data may appear is the clearly-marked
read-only comparison column of the markdown table (--external), which is
display-only and never feeds the store or any training loop.

Candidate sources (all self-generated):
  1. solver adapters (--adapter NAME=CMD, same contract as
     harness/bench.py: `CMD puzzle.json` -> plan JSON on stdout, exit 0);
  2. the hand-written reference plans in harness/tests/plans/ (these are
     part of this repo's own harness, not external leaderboard
     solutions; disable with --no-reference);
  3. validated perturbations of the plans from 1-2 (wait-shifts and
     post-completion junk rotations), which are deliberately WORSE:
     they exist so a short run demonstrably shows incumbents being
     beaten when the better originals arrive.

Submission order is worst-first (sorted by descending instructions +
makespan) for the same demonstrational reason; the store itself is
order-independent.

Usage:
    python3 selfplay/leaderboard/driver.py \
        --adapter clingo="python3 harness/adapters/clingo/adapter.py" \
        --store selfplay/leaderboard/incumbents.json \
        --out selfplay/leaderboard/LEADERBOARD.md
"""

import argparse
import copy
import glob
import json
import os
import shlex
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "harness"))
sys.path.insert(0, HERE)
from metrics import METRICS, compute_metrics, leaderboard_metrics  # noqa: E402
from store import IncumbentStore  # noqa: E402

from validate import Invalid, Malformed, validate  # noqa: E402

PLANS_DIR = os.path.join(REPO, "harness", "tests", "plans")


# ---------------------------------------------------------------------------
# Candidate generation (all self-generated; every candidate validated)
# ---------------------------------------------------------------------------
def is_valid(puzzle, plan):
    try:
        validate(puzzle, plan)
        return True
    except (Invalid, Malformed):
        return False


def reference_candidates(puzzle):
    path = os.path.join(PLANS_DIR, puzzle["name"] + "_good.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [("reference plan", json.load(f))]


def adapter_candidates(puzzle, puzzle_path, adapters, timeout):
    out = []
    for name, cmd in adapters:
        argv = [*shlex.split(cmd), puzzle_path]
        t0 = time.time()
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"  [{name}] timeout after {timeout}s on {puzzle['name']}", file=sys.stderr)
            continue
        if proc.returncode != 0:
            print(f"  [{name}] exit {proc.returncode} on {puzzle['name']}", file=sys.stderr)
            continue
        try:
            plan = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            print(f"  [{name}] unparseable plan JSON ({e})", file=sys.stderr)
            continue
        print(f"  [{name}] solved {puzzle['name']} in {time.time() - t0:.1f}s", file=sys.stderr)
        out.append((f"solver:{name}", plan))
    return out


def perturbations(puzzle, source, plan):
    """Deliberately wasteful, still-valid variants of a valid plan.

    Only variants that pass the canonical validator are returned;
    everything else is discarded (and counted by the caller).
    """
    t_max = puzzle["t_max"]
    arms = [pl["id"] for pl in plan.get("placements", []) if pl.get("type") == "arm"]
    used_t = {ins["t"] for ins in plan.get("instructions", [])}
    out = []

    # (a) wait-shift by k: same instructions, worse makespan
    for k in (1, 2):
        shifted = copy.deepcopy(plan)
        for ins in shifted["instructions"]:
            ins["t"] += k
        if any(ins["t"] >= t_max for ins in shifted["instructions"]):
            continue
        out.append((f"{source}+wait-shift({k})", shifted))

    # (b) junk rotations in free tail timesteps: worse instructions
    #     (they run after completion, so @V metrics are untouched)
    free_tail = [t for t in range(t_max) if t not in used_t and t > max(used_t, default=-1)]
    junk = copy.deepcopy(plan)
    for n, t in enumerate(free_tail, start=1):
        junk = copy.deepcopy(junk)
        junk["instructions"].append({"t": t, "arm": arms[0], "action": "rot_cw"})
        out.append((f"{source}+junk-rot(x{n})", junk))
    return out


def gather_candidates(puzzle, puzzle_path, adapters, timeout, use_reference):
    """All candidates for one puzzle, worst-first, every one validated."""
    base = []
    if use_reference:
        base += reference_candidates(puzzle)
    base += adapter_candidates(puzzle, puzzle_path, adapters, timeout)

    kept, discarded = [], 0
    for source, plan in base:
        if not is_valid(puzzle, plan):
            discarded += 1
            print(f"  [gen] DISCARDED invalid base plan from {source}", file=sys.stderr)
            continue
        kept.append((source, plan))
        for psource, pplan in perturbations(puzzle, source, plan):
            if is_valid(puzzle, pplan):
                kept.append((psource, pplan))
            else:
                discarded += 1
                print(f"  [gen] DISCARDED invalid perturbation {psource}", file=sys.stderr)

    def badness(item):
        m = compute_metrics(puzzle, item[1])
        return m["instructions"] + m["makespan"]

    kept.sort(key=badness, reverse=True)  # worst-first
    return kept, discarded


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def leaderboard_markdown(store, external=None):
    """Markdown leaderboard: our incumbents per (puzzle, metric).

    `external` is an optional {puzzle: {metric: value}} dict rendered in
    a clearly-labeled READ-ONLY comparison column. It is display-only:
    nothing reads it back, and it never touches the incumbent store or
    any training loop.
    """
    external = external or {}
    lines = [
        "# Self-competition leaderboard",
        "",
        "Every incumbent below is one of this system's OWN solutions,",
        "verified by the canonical validator (`harness/validate.py`) at",
        "submission time. The external column is read-only comparison",
        "data only -- never a training target, never an incumbent.",
        "",
        f"Store: {store.submissions} submissions processed.",
        "",
    ]
    for puzzle_name in sorted(store.records):
        lines += [
            f"## {puzzle_name}",
            "",
            "| metric | our best | source | submission # | "
            "external best (read-only, comparison only) |",
            "|---|---|---|---|---|",
        ]
        per_puzzle = store.records[puzzle_name]
        for metric in leaderboard_metrics():
            rec = per_puzzle.get(metric)
            ext = external.get(puzzle_name, {}).get(metric, "-")
            if rec is None:
                lines.append(f"| {metric} | - | - | - | {ext} |")
            else:
                lines.append(
                    f"| {metric} | {rec['score']} | {rec['source']} | {rec['submission']} | {ext} |"
                )
        lines.append("")
    stubbed = sorted(m.name for m in METRICS.values() if m.stubbed)
    lines += [f"Stubbed metrics (not yet computed, not on the board): {', '.join(stubbed)}.", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--adapter",
        action="append",
        default=[],
        metavar="NAME=CMD",
        help='e.g. clingo="python3 harness/adapters/clingo/adapter.py"',
    )
    ap.add_argument(
        "--puzzle",
        action="append",
        default=None,
        help="puzzle JSON path (default: harness/puzzles/*.json)",
    )
    ap.add_argument(
        "--store", default=os.path.join(HERE, "incumbents.json"), help="incumbent store JSON path"
    )
    ap.add_argument("--out", help="write the leaderboard markdown here")
    ap.add_argument(
        "--external",
        metavar="JSON",
        help="optional {puzzle: {metric: value}} file for the "
        "READ-ONLY external comparison column "
        "(display-only; never trains anything)",
    )
    ap.add_argument(
        "--no-reference", action="store_true", help="do not seed from harness/tests/plans/"
    )
    ap.add_argument("--timeout", type=float, default=120, help="per-adapter-run timeout in seconds")
    ap.add_argument(
        "--fresh", action="store_true", help="start from an empty store (delete existing file)"
    )
    args = ap.parse_args()

    adapters = []
    for spec in args.adapter:
        if "=" not in spec:
            ap.error(f"--adapter must be NAME=CMD, got {spec!r}")
        adapters.append(tuple(spec.split("=", 1)))
    puzzle_paths = args.puzzle or sorted(
        glob.glob(os.path.join(REPO, "harness", "puzzles", "*.json"))
    )

    if args.fresh and args.store and os.path.exists(args.store):
        os.remove(args.store)
    store = IncumbentStore(args.store)
    external = None
    if args.external:
        with open(args.external) as f:
            external = json.load(f)

    total = {"submitted": 0, "accepted": 0, "improvements": 0, "beaten": 0, "discarded": 0}
    for path in puzzle_paths:
        with open(path) as f:
            puzzle = json.load(f)
        print(f"== {puzzle['name']}", file=sys.stderr)
        candidates, discarded = gather_candidates(
            puzzle, path, adapters, args.timeout, use_reference=not args.no_reference
        )
        total["discarded"] += discarded
        for source, plan in candidates:
            result = store.submit(puzzle, plan, source=source)
            total["submitted"] += 1
            if not result["accepted"]:
                print(f"  REJECTED  {source}: {result['reason']}", file=sys.stderr)
                continue
            total["accepted"] += 1
            firsts = [i for i in result["improved"] if i["old"] is None]
            beats = [i for i in result["improved"] if i["old"] is not None]
            total["improvements"] += len(result["improved"])
            total["beaten"] += len(beats)
            desc = []
            if firsts:
                desc.append(f"{len(firsts)} first records")
            for i in beats:
                desc.append(f"BEAT {i['metric']} {i['old']} -> {i['new']} (delta {i['delta']})")
            print(
                f"  accepted  {source}: " + ("; ".join(desc) if desc else "no improvement"),
                file=sys.stderr,
            )

    md = leaderboard_markdown(store, external)
    print()
    print(md)
    if args.out:
        with open(args.out, "w") as f:
            f.write(md)
    print(
        f"[driver] {total['submitted']} submitted, {total['accepted']} "
        f"accepted (all validator-checked), {total['discarded']} "
        f"generated candidates discarded pre-submission, "
        f"{total['improvements']} incumbent updates of which "
        f"{total['beaten']} beat an existing incumbent.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
