#!/usr/bin/env python3
"""Scaling experiments: solver behavior vs horizon, grid radius, product size.

Runs a battery of (instance, t_max, radius) combinations through the clingo
CLI (`python3 -m clingo`, JSON output) under a hard external timeout, and
prints a markdown table with grounding size, grounding time, time to best
model, total solve time, and the optimization result.

    python3 experiments.py                    # full battery
    python3 experiments.py --time-limit 60    # quicker
"""
import argparse
import json
import subprocess
import sys
import time


def clingo_json(files, tmax, radius, extra, hard_timeout):
    cmd = [sys.executable, "-m", "clingo", "--outf=2", "--stats=2",
           "--quiet=1", "-c", f"t_max={tmax}"]
    if radius:
        cmd += ["-c", f"radius={radius}"]
    cmd += list(extra) + list(files)
    t0 = time.time()
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=hard_timeout).stdout
    except subprocess.TimeoutExpired as e:
        return None, time.time() - t0
    try:
        return json.loads(out), time.time() - t0
    except json.JSONDecodeError:
        return None, time.time() - t0


def run_one(name, files, tmax, radius=None, time_limit=300):
    # solving run under a hard wall-clock cap (pyclingo's --time-limit is
    # unreliable in this environment, so we rely on the subprocess timeout)
    d, wall = clingo_json(files, tmax, radius, [], hard_timeout=time_limit)
    if d is None:
        # timed out: re-run grounding only (--solve-limit=0) for LP stats
        g, _ = clingo_json(files, tmax, radius, ["--solve-limit=0"],
                           hard_timeout=120)
        lp = (g or {}).get("Stats", {}).get("LP", {})
        return {"name": name, "tmax": tmax, "radius": radius or 2,
                "rules": lp.get("Rules", {}).get("Original", 0),
                "atoms": lp.get("Atoms", 0),
                "ground_s": (g or {}).get("Time", {}).get("Total", 0)
                if g else None,
                "best_model_s": None, "solve_s": wall,
                "result": f"TIMEOUT(>{time_limit:.0f}s)"}
    lp = d.get("Stats", {}).get("LP", {})
    times = d.get("Time", {})
    res = d.get("Result", "?")
    cost = None
    for call in d.get("Call", []):
        for w in call.get("Witnesses", []):
            if "Costs" in w:
                cost = w["Costs"]
    if res == "OPTIMUM FOUND":
        res = f"OPTIMUM cost={cost[0]}"
    elif res == "SATISFIABLE" and cost is not None:
        res = f"SAT cost={cost[0]}"
    return {
        "name": name, "tmax": tmax, "radius": radius or 2,
        "rules": lp.get("Rules", {}).get("Original", 0),
        "atoms": lp.get("Atoms", 0),
        "ground_s": times.get("Total", 0) - times.get("Solve", 0),
        "best_model_s": times.get("Model", None),
        "solve_s": times.get("Total", 0),
        "result": res,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--time-limit", type=float, default=300)
    args = ap.parse_args()
    tl = args.time_limit

    core1 = ["asp/core.lp"]
    core2 = ["asp/core2.lp"]
    rows = []

    def go(*a, **kw):
        row = run_one(*a, **kw)
        rows.append(row)
        print(f"  done: {row['name']} T={row['tmax']} r={row['radius']} "
              f"-> {row['result']} ({row['solve_s']:.2f}s)", flush=True)

    # 1. horizon scaling, trivial 1-atom instance (phase-1 core)
    for t in (10, 20, 40, 80):
        go("trivial (1 atom)", core1 + ["asp/trivial_instance.lp"], t,
           time_limit=tl)

    # 2. radius scaling, trivial instance at T=20
    for r in (2, 3, 4):
        go("trivial (1 atom)", core1 + ["asp/trivial_instance.lp"], 20,
           radius=r, time_limit=tl)

    # 3. product size scaling
    go("bond 2 atoms (v1 core)", core1 + ["asp/bond_instance.lp"], 16,
       time_limit=tl)
    go("rigid dimer move (v2)", core2 + ["asp/rigid_instance.lp"], 10,
       time_limit=tl)
    go("STABILIZED WATER (true spec)", core2 + ["asp/stabilized_water.lp"],
       10, time_limit=tl)
    go("STABILIZED WATER, free layout",
       core2 + ["asp/layout.lp", "asp/stabilized_water_free.lp"], 10,
       time_limit=tl)
    go("STABILIZED WATER, slack T=20", core2 + ["asp/stabilized_water.lp"],
       20, time_limit=tl)
    go("STABILIZED WATER, slack T=40", core2 + ["asp/stabilized_water.lp"],
       40, time_limit=tl)
    go("SW bent 3-atom, 1 arm", core2 + ["asp/sw_bent.lp"], 25,
       time_limit=tl)
    go("SW bent 3-atom, slack T=30", core2 + ["asp/sw_bent.lp"], 30,
       time_limit=tl)
    go("SW linear 3-atom, 2 arms", core2 + ["asp/sw_linear.lp"], 36,
       time_limit=tl)

    # 4. UNSAT probes
    go("SW bent, T=24 (<optimum)", core2 + ["asp/sw_bent.lp"], 24,
       time_limit=tl)
    go("SW linear 1 arm (impossible)", core2 + ["asp/sw_linear_1arm.lp"],
       25, time_limit=tl)

    print()
    print("| instance | t_max | radius | ground rules | ground atoms | "
          "ground s | best model s | total s | result |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        bm = "-" if r["best_model_s"] is None else f"{r['best_model_s']:.2f}"
        gs = "-" if r["ground_s"] is None else f"{r['ground_s']:.2f}"
        print(f"| {r['name']} | {r['tmax']} | {r['radius']} | "
              f"{r['rules']} | {r['atoms']} | {gs} | "
              f"{bm} | {r['solve_s']:.2f} | {r['result']} |")


if __name__ == "__main__":
    main()
