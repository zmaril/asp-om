#!/usr/bin/env python3
"""Benchmark driver for the MiniZinc Opus Magnum model.

Runs instance x variant x solver combinations, parses `minizinc -s`
statistics, and appends rows to a CSV:

  instance,variant,engine,threads,status,objective,solve_s,flatten_s,wall_s,notes

status: OPTIMAL (proved), SATISFIED (incumbent at timeout), UNKNOWN
(timeout, no solution), UNSAT, or ERROR (flattening/solver failure).

Usage examples:
  python3 minizinc/bench.py --out minizinc/results/benchmarks.csv
  python3 minizinc/bench.py --instances stabilized_water --variants free \
      --solvers cp-sat --threads 8 --timeout 600 --append --out ...
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = {"fixed": os.path.join(HERE, "om_fixed.mzn"),
         "free": os.path.join(HERE, "om.mzn")}
DEFAULT_INSTANCES = ["t1_transport", "t2_bond", "t3_rigid", "t4_calc",
                     "stabilized_water"]
DEFAULT_SOLVERS = ["gecode", "chuffed", "cp-sat", "highs", "coin-bc"]


def run_one(instance, variant, solver, threads, timeout_s, dzn_dir):
    dzn = os.path.join(dzn_dir, instance + ".dzn")
    cmd = ["minizinc", "--solver", solver, "--time-limit",
           str(timeout_s * 1000), "-s", "--output-mode", "json",
           "--output-objective", MODEL[variant], dzn]
    if threads is not None:
        cmd[3:3] = ["-p", str(threads)]
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout_s + 120)
        out, err, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) \
            else (e.stdout or "")
        err, rc = "hard timeout (minizinc did not stop itself)", -9
    wall = time.monotonic() - t0

    stats = dict(re.findall(r"%%%mzn-stat: ([\w.]+)=([^\n]+)", out))
    objs = re.findall(r'"_objective"\s*:\s*(-?\d+)', out)
    objective = objs[-1] if objs else ""

    if "==========" in out:
        status = "OPTIMAL"
    elif "----------" in out:
        status = "SATISFIED"
    elif "=====UNSATISFIABLE=====" in out:
        status = "UNSAT"
    elif rc != 0:
        status = "ERROR"
    else:
        status = "UNKNOWN"

    notes = ""
    if status == "ERROR":
        first = next((l for l in (err or out).splitlines() if l.strip()), "")
        notes = first[:160]
    elif status in ("SATISFIED", "UNKNOWN"):
        notes = f"timeout {timeout_s}s" + \
            (f", best={objective}" if objective else ", no solution")

    return {
        "instance": instance, "variant": variant, "engine": solver,
        "threads": threads if threads is not None else "default",
        "status": status, "objective": objective,
        "solve_s": stats.get("solveTime", ""),
        "flatten_s": stats.get("flatTime", ""),
        "wall_s": f"{wall:.2f}", "notes": notes,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--instances", nargs="+", default=DEFAULT_INSTANCES)
    ap.add_argument("--variants", nargs="+", default=["fixed", "free"])
    ap.add_argument("--solvers", nargs="+", default=DEFAULT_SOLVERS)
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=300, help="seconds")
    ap.add_argument("--append", action="store_true")
    ap.add_argument("--dzn-dir", default=os.path.join(HERE, "instances"))
    args = ap.parse_args()

    fields = ["instance", "variant", "engine", "threads", "status",
              "objective", "solve_s", "flatten_s", "wall_s", "notes"]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    mode = "a" if args.append else "w"
    with open(args.out, mode, newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if mode == "w" or f.tell() == 0:
            w.writeheader()
        for inst in args.instances:
            for var in args.variants:
                for sol in args.solvers:
                    row = run_one(inst, var, sol, args.threads,
                                  args.timeout, args.dzn_dir)
                    w.writerow(row)
                    f.flush()
                    print(",".join(str(row[k]) for k in fields), flush=True)


if __name__ == "__main__":
    main()
