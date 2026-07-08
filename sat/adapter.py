"""Harness adapter for the SAT arm (see harness/README.md on the
`harness` branch).

Usage:  python3 sat/adapter.py <puzzle.json>

Reads a harness puzzle JSON, encodes it with sat/encode3.py at the
puzzle's t_max horizon, solves with Cadical195, then minimizes the number
of non-wait instructions by downward linear search over cardinality
bounds within the time budget (env HARNESS_SAT_TIME_LIMIT seconds,
default 60; the best plan found so far is emitted when the budget runs
out).  Emits the plan JSON on stdout, logs to stderr; exit 0 = solved,
nonzero = no plan (UNSAT / timeout before any plan / unsupported puzzle
feature).
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pysat.card import CardEnc, EncType
from pysat.formula import CNF

from encode3 import Encoder3, HarnessPuzzle, ACTIONS2
from instances import DIRS
from solvers import solve


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def decode_plan(pz, enc, model):
    true = set(l for l in model if l > 0)

    def tv(*key):
        return enc.v(*key) in true

    T = enc.T
    placements = [
        {"type": "arm", "id": pz.arm["id"],
         "position": list(next(h for h in enc.hexes if tv("base", h))),
         "rotation": next(d for d in range(6) if tv("orient", d, 0))},
    ]
    for i, rg in enumerate(pz.reagents, 1):
        placements.append(
            {"type": "input", "id": rg["id"],
             "position": list(next(h for h in enc.hexes
                                   if tv("spawn", i, h))),
             "rotation": 0})
    placements.append(
        {"type": "output", "id": pz.product["id"],
         "position": list(next(h for h in enc.hexes if tv("opos", h))),
         "rotation": next(k for k in enc.orots if tv("orot", k))})
    if pz.calcifier:
        placements.append(
            {"type": "calcifier", "id": pz.calcifier["id"],
             "position": list(next(h for h in enc.hexes if tv("cpos", h)))})
    if pz.bonder:
        placements.append(
            {"type": "bonder", "id": pz.bonder["id"],
             "position": list(next(h for h in enc.hexes if tv("gpos", h))),
             "rotation": next(d for d in range(3) if tv("gdir", d))})
    instructions = []
    for t in range(T):
        act = next(a for a in ACTIONS2 if tv("do", a, t))
        if act != "wait":
            instructions.append(
                {"t": t, "arm": pz.arm["id"], "action": act})
    return {"puzzle": pz.name,
            "solver": "sat (PySAT Cadical195, sat/encode3.py)",
            "placements": placements,
            "instructions": instructions}


def main():
    if len(sys.argv) != 2:
        log("usage: adapter.py <puzzle.json>")
        return 2
    budget = float(os.environ.get("HARNESS_SAT_TIME_LIMIT", "60"))
    deadline = time.monotonic() + budget
    try:
        with open(sys.argv[1]) as f:
            data = json.load(f)
        pz = HarnessPuzzle(data)
    except (ValueError, KeyError) as e:
        log(f"unsupported puzzle: {e}")
        return 3

    enc = Encoder3(pz)
    log(f"{pz.name}: T={enc.T} {enc.nvars} vars {enc.nclauses} clauses "
        f"(encode {enc.encode_time:.2f}s)")
    remaining = max(1.0, deadline - time.monotonic())
    sat, model, st = solve("cadical195", enc.cnf, timeout=remaining)
    if sat is None:
        log(f"first solve timed out after {st:.1f}s")
        return 1
    if not sat:
        log(f"UNSAT at t_max={enc.T} ({st:.2f}s)")
        return 1
    lits = enc.non_wait_literals()

    def cost_of(m):
        tr = set(l for l in m if l > 0)
        return sum(1 for l in lits if -l not in tr)

    best, best_cost = model, cost_of(model)
    log(f"first plan: {best_cost} non-wait in {st:.2f}s; minimizing...")
    k = best_cost - 1
    while k >= 0:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            log(f"budget exhausted; best bound not proved below "
                f"{best_cost}")
            break
        bounded = CNF()
        bounded.extend(enc.cnf.clauses)
        card = CardEnc.atmost(lits=lits, bound=k, top_id=enc.pool.top,
                              encoding=EncType.seqcounter)
        bounded.extend(card.clauses)
        sat, model, st = solve("cadical195", bounded, timeout=remaining)
        if sat is None:
            log(f"minimization timed out at bound {k}; "
                f"emitting best={best_cost}")
            break
        if not sat:
            log(f"proved optimal: {best_cost} non-wait instructions")
            break
        best, best_cost = model, cost_of(model)
        k = best_cost - 1
    plan = decode_plan(pz, enc, best)
    json.dump(plan, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
