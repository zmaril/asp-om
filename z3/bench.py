#!/usr/bin/env python3
"""Timing harness for the Z3 arm.

Runs every (instance, encoding, layout-mode, strategy) combination, writes a
markdown table to z3/results.md and dumps optimal solutions (JSON) to
z3/solutions/.  Fast runs (< 2 s) are repeated REPEATS times and the median
is reported; slow runs are measured once.
"""

import json
import os
import statistics
import time

import z3

import om_bool
import om_solver
from om_solver import INSTANCES, Encoder, STRATEGIES, extract_solution

HERE = os.path.dirname(os.path.abspath(__file__))
REPEATS = 5
FAST_CUTOFF = 2.0  # seconds

CLINGO_REFERENCE = {  # measured on this box, clingo 5.8.0, to optimality
    "trivial": 0.009, "bond": 0.148, "rigid": 0.004,
}


def run_int(name, mode, strategy):
    """One (build+solve) run of the Int encoding. Returns result dict."""
    inst = INSTANCES[name]
    t0 = time.perf_counter()
    enc = Encoder(inst, free_layout=(mode == "free"))
    build = time.perf_counter() - t0
    res = STRATEGIES[strategy](enc)
    res["build"] = build
    res["enc"] = enc
    return res


def run_bool(name, mode, strategy):
    assert mode == "fixed"
    r = om_bool.solve(name, strategy)
    return dict(status=r["status"], cost=r["cost"], time=r["time"],
                build=r["build"], horizon=INSTANCES[name]["t_max"], enc=None)


def timed(run_fn, *args):
    """Run once; if fast, rerun to REPEATS total and report median."""
    first = run_fn(*args)
    times = [first["time"]]
    builds = [first["build"]]
    if first["time"] < FAST_CUTOFF:
        for _ in range(REPEATS - 1):
            r = run_fn(*args)
            times.append(r["time"])
            builds.append(r["build"])
    first["time_med"] = statistics.median(times)
    first["build_med"] = statistics.median(builds)
    first["n_runs"] = len(times)
    return first


def main():
    rows = []
    sol_dir = os.path.join(HERE, "solutions")
    os.makedirs(sol_dir, exist_ok=True)

    int_strategies = ["optimize", "ramp-cost", "descend-cost", "oneshot",
                      "ramp-horizon"]
    for name in ["trivial", "bond", "rigid"]:
        for mode in ["fixed", "free"]:
            for strat in int_strategies:
                r = timed(run_int, name, mode, strat)
                opt = INSTANCES[name]["expected_opt"]
                optimal = (r["cost"] == opt) if strat not in (
                    "oneshot", "ramp-horizon") else ""
                rows.append(dict(instance=name, encoding="int", mode=mode,
                                 strategy=strat, status=r["status"],
                                 cost=r["cost"], horizon=r["horizon"],
                                 build=r["build_med"], solve=r["time_med"],
                                 n=r["n_runs"], optimal=optimal))
                print(rows[-1])
                # dump the canonical optimal solutions as JSON
                if strat == "descend-cost" and r["status"] == "sat":
                    sol = extract_solution(r["enc"], r)
                    meta = dict(instance=name, mode=mode,
                                strategy=strat, t_max=r["enc"].T,
                                solver="z3-" + z3.get_version_string(),
                                solve_time_s=round(r["time"], 4))
                    path = os.path.join(sol_dir, f"{name}-{mode}.json")
                    with open(path, "w") as f:
                        json.dump(dict(meta=meta, **sol), f, indent=1)

    for name in ["trivial", "bond"]:
        for strat in ["optimize", "descend-cost", "oneshot"]:
            r = timed(run_bool, name, "fixed", strat)
            opt = INSTANCES[name]["expected_opt"]
            optimal = (r["cost"] == opt) if strat != "oneshot" else ""
            rows.append(dict(instance=name, encoding="bool", mode="fixed",
                             strategy=strat, status=r["status"],
                             cost=r["cost"], horizon=r["horizon"],
                             build=r["build_med"], solve=r["time_med"],
                             n=r["n_runs"], optimal=optimal))
            print(rows[-1])

    # ---- write results.md ----
    lines = [
        "# Z3 arm benchmark results",
        "",
        f"z3-solver {z3.get_version_string()}; times are wall-clock solve "
        f"time in seconds (build/encode time listed separately); fast runs "
        f"are the median of {REPEATS}.",
        "",
        "Strategies: `optimize` = z3.Optimize minimize(cost); `ramp-cost` = "
        "incremental cost<=k for k=0,1,... (first SAT is proven optimum); "
        "`descend-cost` = SAT then tighten cost until UNSAT (proven "
        "optimum); `oneshot` = single SAT check, NO optimality; "
        "`ramp-horizon` = incremental goal-at-h assumptions for h=1..T, "
        "first SAT horizon, cost not minimized.",
        "",
        "Clingo reference (same box, clingo 5.8.0, ground+solve to "
        "optimality, fixed layout): "
        + ", ".join(f"{k} {v}s" for k, v in CLINGO_REFERENCE.items()) + ".",
        "",
        "| instance | encoding | layout | strategy | status | cost | "
        "horizon | build s | solve s | runs | proven optimal |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['instance']} | {r['encoding']} | {r['mode']} | "
            f"{r['strategy']} | {r['status']} | {r['cost']} | "
            f"{r['horizon']} | {r['build']:.3f} | {r['solve']:.3f} | "
            f"{r['n']} | {r['optimal']} |")
    lines.append("")
    with open(os.path.join(HERE, "results.md"), "w") as f:
        f.write("\n".join(lines))
    print(f"wrote {os.path.join(HERE, 'results.md')}")


if __name__ == "__main__":
    main()
