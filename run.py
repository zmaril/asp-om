#!/usr/bin/env python3
"""Solve an Opus Magnum ASP encoding with clingo and print a readable trace.

Usage:
    python3 run.py asp/core.lp asp/trivial_instance.lp
    python3 run.py asp/core.lp asp/bond_instance.lp --tmax 16
"""
import argparse
import time as _time

import clingo


def solve(files, tmax):
    args = []
    if tmax is not None:
        args += ["-c", f"t_max={tmax}"]
    ctl = clingo.Control(args)
    for f in files:
        ctl.load(f)
    ctl.ground([("base", [])])

    best = {"symbols": None, "cost": None}

    def on_model(model):
        best["symbols"] = model.symbols(atoms=True)
        best["cost"] = list(model.cost)

    t0 = _time.time()
    result = ctl.solve(on_model=on_model)
    elapsed = _time.time() - t0
    return result, best, elapsed


def parse_model(symbols):
    do, orient, gripper = {}, {}, {}
    at, holding, bonds = {}, {}, {}
    for s in symbols:
        a = s.arguments
        if s.name == "do":
            do[a[1].number] = a[0].name
        elif s.name == "orient":
            orient[a[1].number] = a[0].number
        elif s.name == "gripper":
            gripper[a[2].number] = (a[0].number, a[1].number)
        elif s.name == "at":
            at.setdefault(a[3].number, {})[a[0].name] = (a[1].number, a[2].number)
        elif s.name == "holding":
            holding.setdefault(a[1].number, set()).add(a[0].name)
        elif s.name == "bond":
            bonds.setdefault(a[2].number, set()).add((a[0].name, a[1].name))
    return do, orient, gripper, at, holding, bonds


def print_trace(symbols):
    do, orient, gripper, at, holding, bonds = parse_model(symbols)
    tmax = max(at)
    for t in range(tmax + 1):
        atoms = "  ".join(
            f"{x}@({q},{r})" + ("[held]" if x in holding.get(t, ()) else "")
            for x, (q, r) in sorted(at.get(t, {}).items())
        )
        bond_str = "".join(
            f"  bond({x},{y})" for x, y in sorted(bonds.get(t, ()))
        )
        gq, gr = gripper[t]
        print(
            f"t={t:>2}  arm dir={orient[t]} gripper=({gq},{gr})  {atoms}{bond_str}"
        )
        if t in do:
            print(f"      action: {do[t]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+", help="ASP files (core + instance)")
    ap.add_argument("--tmax", type=int, default=None, help="override t_max")
    args = ap.parse_args()

    result, best, elapsed = solve(args.files, args.tmax)
    print(f"Result: {result}  (wall time {elapsed:.3f}s)")
    if best["symbols"] is None:
        print("No model found.")
        return 1
    print(f"Optimization cost (non-wait instructions): {best['cost']}")
    print()
    print_trace(best["symbols"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
