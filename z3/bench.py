#!/usr/bin/env python3
"""Timing harness for the Z3 arm.

Runs every (instance, encoding, layout-mode, strategy) combination, writes a
markdown table to z3/results.md and dumps optimal solutions (JSON) to
z3/solutions/.  Fast runs (< 2 s) are repeated REPEATS times and the median
is reported; slow runs are measured once.

Results are cached in z3/results.json keyed by
(instance, encoding, mode, strategy); pass --instances to re-run only a
subset -- the table is regenerated from the merged cache.
"""

import argparse
import json
import os
import statistics
import time

import om_bool
from om_solver import INSTANCES, STRATEGIES, Encoder, extract_solution

import z3

HERE = os.path.dirname(os.path.abspath(__file__))
REPEATS = 5
FAST_CUTOFF = 2.0  # seconds

CLINGO_REFERENCE = {  # measured on this box, clingo 5.8.0, to optimality
    "trivial": 0.009,
    "bond": 0.148,
    "rigid": 0.004,
    "water": 0.060,  # z3/stabilized_water.lp + asp/core2.lp, t_max=12
}

ALL_INSTANCES = ["trivial", "bond", "rigid", "water"]
BOOL_INSTANCES = ["trivial", "bond", "water"]  # single-arm, fixed layout


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
    return {
        "status": r["status"],
        "cost": r["cost"],
        "time": r["time"],
        "build": r["build"],
        "horizon": INSTANCES[name]["t_max"],
        "enc": None,
    }


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", nargs="+", choices=ALL_INSTANCES, default=ALL_INSTANCES)
    args = ap.parse_args()

    cache_path = os.path.join(HERE, "results.json")
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            cache = {tuple(k.split("|")): v for k, v in json.load(f).items()}

    sol_dir = os.path.join(HERE, "solutions")
    os.makedirs(sol_dir, exist_ok=True)

    int_strategies = ["optimize", "ramp-cost", "descend-cost", "oneshot", "ramp-horizon"]
    for name in args.instances:
        for mode in ["fixed", "free"]:
            for strat in int_strategies:
                r = timed(run_int, name, mode, strat)
                inst = INSTANCES[name]
                opt = (
                    inst.get("expected_opt_free", inst["expected_opt"])
                    if mode == "free"
                    else inst["expected_opt"]
                )
                optimal = (r["cost"] == opt) if strat not in ("oneshot", "ramp-horizon") else ""
                row = {
                    "instance": name,
                    "encoding": "int",
                    "mode": mode,
                    "strategy": strat,
                    "status": r["status"],
                    "cost": r["cost"],
                    "horizon": r["horizon"],
                    "build": r["build_med"],
                    "solve": r["time_med"],
                    "n": r["n_runs"],
                    "optimal": optimal,
                }
                cache[(name, "int", mode, strat)] = row
                print(row)
                # dump the canonical optimal solutions as JSON
                if strat == "descend-cost" and r["status"] == "sat":
                    sol = extract_solution(r["enc"], r)
                    meta = {
                        "instance": name,
                        "mode": mode,
                        "strategy": strat,
                        "t_max": r["enc"].T,
                        "radius": r["enc"].radius,
                        "solver": "z3-" + z3.get_version_string(),
                        "solve_time_s": round(r["time"], 4),
                    }
                    path = os.path.join(sol_dir, f"{name}-{mode}.json")
                    with open(path, "w") as f:
                        json.dump(dict(meta=meta, **sol), f, indent=1)

    for name in args.instances:
        if name not in BOOL_INSTANCES:
            continue
        for strat in ["optimize", "descend-cost", "oneshot"]:
            r = timed(run_bool, name, "fixed", strat)
            opt = INSTANCES[name]["expected_opt"]
            optimal = (r["cost"] == opt) if strat != "oneshot" else ""
            row = {
                "instance": name,
                "encoding": "bool",
                "mode": "fixed",
                "strategy": strat,
                "status": r["status"],
                "cost": r["cost"],
                "horizon": r["horizon"],
                "build": r["build_med"],
                "solve": r["time_med"],
                "n": r["n_runs"],
                "optimal": optimal,
            }
            cache[(name, "bool", "fixed", strat)] = row
            print(row)

    with open(cache_path, "w") as f:
        json.dump({"|".join(k): v for k, v in cache.items()}, f, indent=1)

    # ---- write results.md from the merged cache ----
    def order(key):
        name, encoding, mode, strat = key
        return (
            0 if encoding == "int" else 1,
            ALL_INSTANCES.index(name),
            0 if mode == "fixed" else 1,
            ([*int_strategies, "descend-cost"]).index(strat),
        )

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
        + ", ".join(f"{k} {v}s" for k, v in CLINGO_REFERENCE.items())
        + ".",
        "",
        "`water` = Stabilized Water (omsim P007) in the simplified v2 "
        "semantics; fixed-layout optimum is 10, free layout finds a "
        "3-instruction layout (glyphs under the reagent hexes).",
        "",
        "| instance | encoding | layout | strategy | status | cost | "
        "horizon | build s | solve s | runs | proven optimal |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for key in sorted(cache, key=order):
        r = cache[key]
        lines.append(
            f"| {r['instance']} | {r['encoding']} | {r['mode']} | "
            f"{r['strategy']} | {r['status']} | {r['cost']} | "
            f"{r['horizon']} | {r['build']:.3f} | {r['solve']:.3f} | "
            f"{r['n']} | {r['optimal']} |"
        )
    lines.append("")
    with open(os.path.join(HERE, "results.md"), "w") as f:
        f.write("\n".join(lines))
    print(f"wrote {os.path.join(HERE, 'results.md')}")


if __name__ == "__main__":
    main()
