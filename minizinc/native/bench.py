#!/usr/bin/env python3
"""Benchmark: native CP-SAT (native_cpsat.py) vs MiniZinc --solver cp-sat
on the om.mzn / om_fixed.mzn instances. Single-threaded primary comparison,
300 s timeout, N repeats, median reported. Writes bench_results.csv.

Models and instances are taken from the parent minizinc/ directory
(../om.mzn, ../om_fixed.mzn, ../instances/*.dzn).
"""

import csv
import os
import re
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # minizinc/: om.mzn, om_fixed.mzn, instances/
INSTANCES = ["t1_transport", "t2_bond", "t3_rigid", "t4_calc"]
VARIANTS = ["fixed", "free"]
REPEATS = 3
TIMEOUT_S = 300

rows = []


def run(cmd, timeout):
    t0 = time.perf_counter()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 60, cwd=ROOT)
    wall = time.perf_counter() - t0
    return p.stdout + p.stderr, wall


def bench_native(inst, variant, threads):
    outs = []
    for _ in range(REPEATS):
        out, wall = run(
            [
                sys.executable,
                os.path.join(HERE, "native_cpsat.py"),
                f"instances/{inst}.dzn",
                f"--{variant}",
                "--threads",
                str(threads),
                "--quiet",
                "--timeout",
                str(TIMEOUT_S),
            ],
            TIMEOUT_S,
        )
        m = re.search(
            r"status=(\S+) objective=(\d+) build_s=([\d.]+) "
            r"solve_s=([\d.]+)",
            out,
        )
        assert m, out[-500:]
        outs.append(
            {
                "status": m.group(1),
                "obj": int(m.group(2)),
                "build": float(m.group(3)),
                "solve": float(m.group(4)),
                "wall": wall,
            }
        )

    def med(k):
        return statistics.median(o[k] for o in outs)

    assert len({o["obj"] for o in outs}) == 1
    return {
        "status": outs[0]["status"],
        "obj": outs[0]["obj"],
        "build": med("build"),
        "solve": med("solve"),
        "wall": med("wall"),
    }


def bench_mzn(inst, variant, threads):
    model = "om_fixed.mzn" if variant == "fixed" else "om.mzn"
    outs = []
    for _ in range(REPEATS):
        out, wall = run(
            [
                "minizinc",
                "--solver",
                "cp-sat",
                "-p",
                str(threads),
                "-s",
                "--time-limit",
                str(TIMEOUT_S * 1000),
                model,
                f"instances/{inst}.dzn",
            ],
            TIMEOUT_S,
        )
        flat = re.search(r"flatTime=([\d.]+)", out)
        solve = re.findall(r"solveTime=([\d.eE+-]+)", out)
        objs = re.findall(r"total_actions = (\d+)", out)
        status = "OPTIMAL" if "==========" in out else ("FEASIBLE" if objs else "UNKNOWN")
        outs.append(
            {
                "status": status,
                "obj": int(objs[-1]) if objs else -1,
                "flat": float(flat.group(1)) if flat else -1.0,
                "solve": float(solve[-1]) if solve else -1.0,
                "wall": wall,
            }
        )

    def med(k):
        return statistics.median(o[k] for o in outs)

    assert len({o["obj"] for o in outs}) == 1
    return {
        "status": outs[0]["status"],
        "obj": outs[0]["obj"],
        "flat": med("flat"),
        "solve": med("solve"),
        "wall": med("wall"),
    }


def main():
    for inst in INSTANCES:
        for variant in VARIANTS:
            nat = bench_native(inst, variant, 1)
            mzn = bench_mzn(inst, variant, 1)
            rows.append(
                {
                    "instance": inst,
                    "variant": variant,
                    "threads": 1,
                    "native_status": nat["status"],
                    "native_obj": nat["obj"],
                    "native_build_s": round(nat["build"], 3),
                    "native_solve_s": round(nat["solve"], 3),
                    "native_wall_s": round(nat["wall"], 3),
                    "mzn_status": mzn["status"],
                    "mzn_obj": mzn["obj"],
                    "mzn_flatten_s": round(mzn["flat"], 3),
                    "mzn_solve_s": round(mzn["solve"], 3),
                    "mzn_wall_s": round(mzn["wall"], 3),
                }
            )
            print(rows[-1], flush=True)

    # one multithreaded data point on the hardest instance
    for inst, variant in [("t2_bond", "free")]:
        nat = bench_native(inst, variant, 8)
        mzn = bench_mzn(inst, variant, 8)
        rows.append(
            {
                "instance": inst,
                "variant": variant,
                "threads": 8,
                "native_status": nat["status"],
                "native_obj": nat["obj"],
                "native_build_s": round(nat["build"], 3),
                "native_solve_s": round(nat["solve"], 3),
                "native_wall_s": round(nat["wall"], 3),
                "mzn_status": mzn["status"],
                "mzn_obj": mzn["obj"],
                "mzn_flatten_s": round(mzn["flat"], 3),
                "mzn_solve_s": round(mzn["solve"], 3),
                "mzn_wall_s": round(mzn["wall"], 3),
            }
        )
        print(rows[-1], flush=True)

    with open(os.path.join(HERE, "bench_results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote bench_results.csv")


if __name__ == "__main__":
    main()
