#!/usr/bin/env python3
"""Tractability frontier for the Stabilized Water instance.

Scales the board radius and the horizon t_max for both encodings and both
layout modes, solving to a PROVEN optimum with the descend-cost strategy
under a wall-clock budget (default 120 s per configuration, solver timeout
set to the remaining budget before each check).  Writes
z3/results-frontier.md.

Statuses:
  opt        proven optimal (descended to UNSAT)
  timeout(k) budget exhausted; k = best cost found so far (not proven)
  timeout    budget exhausted before any model was found
"""

import argparse
import os
import time

import z3

from om_bool import BoolEncoder
from om_solver import INSTANCES, Encoder

HERE = os.path.dirname(os.path.abspath(__file__))

CONFIGS = [
    # (encoding, mode, radius, t_max)
    ("bool", "fixed", 2, 12),
    ("bool", "fixed", 2, 16),
    ("bool", "fixed", 2, 20),
    ("bool", "fixed", 2, 24),
    ("bool", "fixed", 2, 30),
    ("bool", "fixed", 3, 12),
    ("bool", "fixed", 3, 16),
    ("bool", "fixed", 3, 20),
    ("int", "fixed", 2, 12),
    ("int", "fixed", 2, 16),
    ("int", "fixed", 2, 20),
    ("int", "free", 2, 12),
    ("int", "free", 2, 16),
    ("int", "free", 2, 20),
    ("int", "free", 3, 12),
    ("int", "free", 3, 16),
]


def descend_with_budget(cons, goal, cost, budget):
    """descend-cost under a wall budget; returns (status, cost, solve_s)."""
    s = z3.Solver()
    s.add(cons)
    s.add(goal)
    t0 = time.perf_counter()
    best = None
    while True:
        remaining = budget - (time.perf_counter() - t0)
        if remaining <= 0:
            return (f"timeout({best})" if best is not None else "timeout",
                    best, time.perf_counter() - t0)
        s.set("timeout", int(remaining * 1000))
        res = s.check()
        if res == z3.sat:
            best = s.model().eval(cost).as_long()
            s.add(cost <= best - 1)
        elif res == z3.unsat:
            return (("opt" if best is not None else "unsat"), best,
                    time.perf_counter() - t0)
        else:  # unknown = solver timeout
            return (f"timeout({best})" if best is not None else "timeout",
                    best, time.perf_counter() - t0)


def run(encoding, mode, radius, t_max, budget):
    inst = INSTANCES["water"]
    t0 = time.perf_counter()
    if encoding == "bool":
        assert mode == "fixed"
        enc = BoolEncoder(inst, t_max=t_max, radius=radius)
        goal = enc.goal()
    else:
        enc = Encoder(inst, t_max=t_max, free_layout=(mode == "free"),
                      radius=radius)
        goal = enc.goal(t_max)
    build = time.perf_counter() - t0
    status, cost, solve = descend_with_budget(enc.cons, goal, enc.cost,
                                              budget)
    return dict(encoding=encoding, mode=mode, radius=radius, t_max=t_max,
                status=status, cost=cost, build=build, solve=solve)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=120.0,
                    help="wall-clock budget per configuration (s)")
    args = ap.parse_args()

    rows = []
    for cfg in CONFIGS:
        r = run(*cfg, args.budget)
        print(r)
        rows.append(r)

    lines = [
        "# Stabilized Water tractability frontier (Z3)",
        "",
        f"Instance `water` (see NOTES.md), descend-cost to proven optimum, "
        f"budget {args.budget:.0f}s per configuration "
        f"(z3-solver {z3.get_version_string()}).  Fixed-layout optimum is "
        "10; free-layout optimum is 3.  `timeout(k)` = best (unproven) "
        "cost k when the budget ran out.",
        "",
        "| encoding | layout | radius | t_max | status | cost | build s | "
        "solve s |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['encoding']} | {r['mode']} | {r['radius']} | "
            f"{r['t_max']} | {r['status']} | {r['cost']} | "
            f"{r['build']:.2f} | {r['solve']:.2f} |")
    lines.append("")
    with open(os.path.join(HERE, "results-frontier.md"), "w") as f:
        f.write("\n".join(lines))
    print(f"wrote {os.path.join(HERE, 'results-frontier.md')}")


if __name__ == "__main__":
    main()
