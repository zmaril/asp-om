#!/usr/bin/env python3
"""Solve an Opus Magnum ASP encoding with clingo and print a readable trace.

Usage:
    python3 run.py asp/core.lp asp/trivial_instance.lp
    python3 run.py asp/core.lp asp/bond_instance.lp --tmax 16
    python3 run.py asp/core2.lp asp/rigid_instance.lp
    python3 run.py asp/core2.lp asp/sw_bent.lp --tmax 25
    python3 run.py asp/core2.lp asp/sw_linear.lp --tmax 36 --time-limit 600

Handles both the phase-1 core (do/2, single arm) and the phase-2 core
(do/3, multiple arms, atom types, respawning reagents).
"""

import argparse
import time as _time
from typing import Any

import clingo


def solve(files, tmax=None, time_limit=None, extra_args=(), consts=()):
    args = ["--stats=2", *list(extra_args)]
    if tmax is not None:
        args += ["-c", f"t_max={tmax}"]
    for c in consts:
        args += ["-c", c]
    ctl = clingo.Control(args)
    for f in files:
        ctl.load(f)
    t0 = _time.time()
    ctl.ground([("base", [])])
    ground_time = _time.time() - t0

    best: dict[str, Any] = {"symbols": None, "cost": None, "model_time": None}

    def on_model(model):
        best["symbols"] = model.symbols(atoms=True)
        best["cost"] = list(model.cost)
        best["model_time"] = _time.time() - t0

    t0 = _time.time()
    with ctl.solve(on_model=on_model, async_=True) as handle:
        finished = handle.wait(time_limit if time_limit else None)
        if not finished:
            handle.cancel()
        result = handle.get()
    solve_time = _time.time() - t0
    return result, best, ground_time, solve_time, ctl.statistics


def parse_model(symbols):
    do: dict[int, tuple[str, str]] = {}
    orient: dict[int, dict[str, int]] = {}
    at: dict[int, dict[str, tuple[int, int]]] = {}
    holding: dict[int, set[str]] = {}
    bonds: dict[int, set[tuple[str, str]]] = {}
    types: dict[int, dict[str, str]] = {}
    complete = set()
    for s in symbols:
        a = s.arguments
        if s.name == "do":
            if len(a) == 2:  # phase-1 core: do(action, t)
                do[a[1].number] = ("arm", a[0].name)
            else:  # phase-2 core: do(arm, action, t)
                do[a[2].number] = (str(a[0]), a[1].name)
        elif s.name == "orient":
            if len(a) == 2:
                orient.setdefault(a[1].number, {})["arm"] = a[0].number
            else:
                orient.setdefault(a[2].number, {})[str(a[0])] = a[1].number
        elif s.name == "at":
            at.setdefault(a[3].number, {})[str(a[0])] = (a[1].number, a[2].number)
        elif s.name == "holding":
            if len(a) == 2:
                holding.setdefault(a[1].number, set()).add(str(a[0]))
            else:
                holding.setdefault(a[2].number, set()).add(str(a[1]))
        elif s.name == "bond":
            x, y = str(a[0]), str(a[1])
            if x < y:
                bonds.setdefault(a[2].number, set()).add((x, y))
        elif s.name == "type":
            types.setdefault(a[2].number, {})[str(a[0])] = a[1].name
        elif s.name == "complete":
            complete.add(a[0].number)
    return do, orient, at, holding, bonds, types, complete


def print_trace(symbols):
    do, orient, at, holding, bonds, types, complete = parse_model(symbols)
    tmax = max(at) if at else 0
    for t in range(tmax + 1):
        ty = types.get(t, {})
        atoms = "  ".join(
            f"{x}{'/' + ty[x] if x in ty else ''}@({q},{r})"
            + ("[held]" if x in holding.get(t, ()) else "")
            for x, (q, r) in sorted(at.get(t, {}).items())
        )
        bond_str = "".join(f"  bond({x},{y})" for x, y in sorted(bonds.get(t, ())))
        arms = " ".join(f"{m}:d{d}" for m, d in sorted(orient.get(t, {}).items()))
        flag = "  <-- PRODUCT COMPLETE" if t in complete else ""
        print(f"t={t:>2}  {arms}  {atoms}{bond_str}{flag}")
        if t in do:
            m, a = do[t]
            print(f"      action: {m} {a}")
    return tmax


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+", help="ASP files (core + instance)")
    ap.add_argument("--tmax", type=int, default=None, help="override t_max")
    ap.add_argument("--time-limit", type=float, default=None, help="solver time limit in seconds")
    ap.add_argument(
        "-c", dest="consts", action="append", default=[], help="extra constant, e.g. -c nreagent=4"
    )
    ap.add_argument("--stats", action="store_true", help="print grounding/solving statistics")
    args = ap.parse_args()

    result, best, ground_time, solve_time, stats = solve(
        args.files, args.tmax, args.time_limit, consts=args.consts
    )
    print(f"Result: {result}  (ground {ground_time:.2f}s, solve {solve_time:.2f}s)")
    if args.stats:
        lp = stats.get("problem", {}).get("lp", {})
        print(
            f"Ground rules: {int(lp.get('rules', 0))}, "
            f"atoms: {int(lp.get('atoms', 0))}, "
            f"bodies: {int(lp.get('bodies', 0))}"
        )
    if best["symbols"] is None:
        print("No model found.")
        return 1
    print(
        f"Optimization cost (instructions): {best['cost']}  "
        f"(first/best model at {best['model_time']:.2f}s)"
    )
    print()
    print_trace(best["symbols"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
