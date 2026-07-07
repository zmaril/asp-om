#!/usr/bin/env python3
"""clingo reference adapter for the multi-solver Opus Magnum harness.

Wraps the existing (unmodified) ASP encodings on master -- asp/core2.lp
(world semantics) and asp/layout.lp (free machine layout) -- behind the
harness adapter contract:

    python3 harness/adapters/clingo/adapter.py <puzzle.json> [--out FILE]
        [--time-limit SECONDS]

Reads the common puzzle JSON, generates the instance facts + goal rules
(including a placeable OUTPUT part, which the original clingo instances
did not have), solves with the clingo Python module (best model within
the time limit under core2's #minimize on instruction count), and writes
the common plan JSON to stdout (or --out). Exit 0 = solved, 1 = no plan
found (UNSAT or timeout without a model), 2 = puzzle unsupported/bad.

Environment: HARNESS_CLINGO_TIME_LIMIT overrides the default time limit.

Limitations (of the wrapped encoding, not the formats): single-atom
reagents only; elements air/earth/fire/water/salt.
"""
import argparse
import json
import os
import sys

import clingo

HERE = os.path.dirname(os.path.abspath(__file__))
ASP = os.path.join(HERE, "..", "..", "..", "asp")

DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]


def rot_k(q, r, k):
    for _ in range(k % 6):
        q, r = -r, q + r
    return (q, r)


def die(msg, code=2):
    print(f"adapter error: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Instance program generation
# ---------------------------------------------------------------------------
def canonical_rotations(atoms, bonds):
    """Rotation indices that give geometrically distinct output placements
    (dedupes symmetric products, e.g. a single atom needs only D=0)."""
    keep, seen = [], set()
    for d in range(6):
        cells = [rot_k(q, r, d) for _, (q, r) in atoms]
        anchor = min(cells)
        norm = frozenset(((c[0] - anchor[0], c[1] - anchor[1]), el)
                         for (el, _), c in zip(atoms, cells))
        nbonds = frozenset(
            frozenset(((cells[i][0] - anchor[0], cells[i][1] - anchor[1]),
                       (cells[j][0] - anchor[0], cells[j][1] - anchor[1])))
            for i, j in (sorted(b) for b in bonds))
        key = (norm, nbonds)
        if key not in seen:
            seen.add(key)
            keep.append(d)
    return keep


def molecule(m):
    atoms = [(a["element"], tuple(a["pos"])) for a in m["atoms"]]
    bonds = {frozenset(b) for b in m.get("bonds", [])}
    return atoms, bonds


def generate_instance(puzzle):
    """Return (asp_program_text, name_maps) for core2.lp + layout.lp."""
    lines = []
    arm_ids, calc_ids, bond_ids = {}, {}, {}

    def pin_note(spec):
        return "position" in spec

    # --- arms ---------------------------------------------------------------
    arms = [p for p in puzzle["parts"] if p["type"] == "arm"]
    for i, p in enumerate(arms):
        const = f"m{i}"
        arm_ids[const] = p["id"]
        lines.append(f"place_arm({const},{p['length']}).")
        if pin_note(p):
            q, r = p["position"]
            lines.append(f"base({const},{q},{r}).")
            if "rotation" in p:
                lines.append(f"init_orient({const},{p['rotation'] % 6}).")

    # --- reagent inputs (single-atom only for this encoding) -----------------
    reagent_index = {}
    for i, m in enumerate(puzzle["reagents"], start=1):
        atoms, bonds = molecule(m)
        if len(atoms) != 1 or bonds:
            die(f"reagent {m['id']}: the clingo core2 encoding supports "
                f"single-atom reagents only")
        el = atoms[0][0]
        reagent_index[i] = m["id"]
        lines.append(f"place_input({i},{el},{m['pool']}).")
        if pin_note(m):
            rot = m.get("rotation", 0)
            q, r = tuple(sum(x) for x in
                         zip(m["position"], rot_k(*atoms[0][1], rot)))
            lines.append(f"spawn({i},{q},{r}).")

    # --- glyphs ---------------------------------------------------------------
    for i, p in enumerate(p for p in puzzle["parts"]
                          if p["type"] == "calcifier"):
        const = f"c{i}"
        calc_ids[const] = p["id"]
        lines.append(f"place_calc({const}).")
        if pin_note(p):
            q, r = p["position"]
            lines.append(f"calc_at({const},{q},{r}).")
    for i, p in enumerate(p for p in puzzle["parts"] if p["type"] == "bonder"):
        const = f"b{i}"
        bond_ids[const] = p["id"]
        lines.append(f"place_bond({const}).")
        if pin_note(p):
            q, r = p["position"]
            d = p.get("rotation", 0) % 6
            if d >= 3:  # layout.lp's bond_at choice uses D < 3; flip
                q, r = q + DIRS[d][0], r + DIRS[d][1]
                d -= 3
            lines.append(f"bond_at({const},{q},{r},{d}).")

    # --- outputs: placeable product parts + exact-molecule goals --------------
    lines.append("deg(X,T,N) :- exists(X,T), time(T), "
                 "N = #count { Y : bond(X,Y,T) }.")
    product_index = {}
    for k, m in enumerate(puzzle["products"]):
        product_index[k] = m["id"]
        atoms, bonds = molecule(m)
        for d in canonical_rotations(atoms, bonds):
            for a, (_, (q, r)) in enumerate(atoms):
                dq, dr = rot_k(q, r, d)
                lines.append(f"prodoff({k},{d},{a},{dq},{dr}).")
        lines.append(f"{{ out_at({k},Q,R,D) : hex(Q,R), prodoff({k},D,_,_,_) "
                     f"}} = 1.")
        lines.append(f"out_hex({k},A,Q+DQ,R+DR) :- out_at({k},Q,R,D), "
                     f"prodoff({k},D,A,DQ,DR).")
        lines.append(f":- out_at({k},Q,R,D), prodoff({k},D,A,DQ,DR), "
                     f"not hex(Q+DQ,R+DR).")
        lines.append(f"foot(out({k}),Q,R) :- out_hex({k},_,Q,R).")
        if pin_note(m):
            rot = m.get("rotation", 0) % 6
            q, r = m["position"]
            lines.append(f"out_at({k},{q},{r},{rot}).")
        # exact-molecule completion rule
        pdeg = {i: 0 for i in range(len(atoms))}
        for b in bonds:
            i, j = sorted(b)
            pdeg[i] += 1
            pdeg[j] += 1
        body = []
        for a, (el, _) in enumerate(atoms):
            body += [f"out_hex({k},{a},Q{a},R{a})",
                     f"at(X{a},Q{a},R{a},T)", f"type(X{a},{el},T)",
                     f"deg(X{a},T,{pdeg[a]})", f"not held(X{a},T)"]
        for b in bonds:
            i, j = sorted(b)
            body.append(f"bond(X{i},X{j},T)")
        lines.append(f"complete({k},T) :- " + ", ".join(body) + ".")
        lines.append(f"done({k}) :- complete({k},T).")
    lines.append("goal_met :- " + ", ".join(f"done({k})"
                                            for k in product_index) + ".")
    return "\n".join(lines) + "\n", (arm_ids, reagent_index, calc_ids,
                                     bond_ids, product_index)


# ---------------------------------------------------------------------------
# Solve + extract
# ---------------------------------------------------------------------------
def solve(puzzle, instance_text, time_limit):
    ctl = clingo.Control(["-c", f"t_max={puzzle['t_max']}",
                          "-c", f"radius={puzzle['board_radius']}"])
    ctl.load(os.path.join(ASP, "core2.lp"))
    ctl.load(os.path.join(ASP, "layout.lp"))
    ctl.add("base", [], instance_text)
    ctl.ground([("base", [])])
    best = {"symbols": None, "cost": None}

    def on_model(model):
        best["symbols"] = model.symbols(atoms=True)
        best["cost"] = list(model.cost)

    with ctl.solve(on_model=on_model, async_=True) as handle:
        if not handle.wait(time_limit):
            handle.cancel()
        result = handle.get()
    return result, best


def extract_plan(puzzle, symbols, maps):
    arm_ids, reagent_index, calc_ids, bond_ids, product_index = maps
    lengths = {p["id"]: p["length"] for p in puzzle["parts"]
               if p["type"] == "arm"}
    placements, instructions = [], []
    bases, orients = {}, {}
    for s in symbols:
        a, n = s.arguments, s.name
        if n == "base":
            bases[arm_ids[str(a[0])]] = [a[1].number, a[2].number]
        elif n == "init_orient":
            orients[arm_ids[str(a[0])]] = a[1].number
        elif n == "spawn":
            placements.append({"type": "input",
                               "id": reagent_index[a[0].number],
                               "position": [a[1].number, a[2].number],
                               "rotation": 0})
        elif n == "calc_at":
            placements.append({"type": "calcifier", "id": calc_ids[str(a[0])],
                               "position": [a[1].number, a[2].number]})
        elif n == "bond_at":
            placements.append({"type": "bonder", "id": bond_ids[str(a[0])],
                               "position": [a[1].number, a[2].number],
                               "rotation": a[3].number})
        elif n == "out_at":
            placements.append({"type": "output",
                               "id": product_index[a[0].number],
                               "position": [a[1].number, a[2].number],
                               "rotation": a[3].number})
        elif n == "do" and len(a) == 3:
            instructions.append({"t": a[2].number,
                                 "arm": arm_ids[str(a[0])],
                                 "action": a[1].name})
    for mid, pos in bases.items():
        if mid not in orients:
            die("model has base/3 but no init_orient/2 for an arm", 1)
        placements.append({"type": "arm", "id": mid, "position": pos,
                           "rotation": orients[mid], "length": lengths[mid]})
    order = {"arm": 0, "input": 1, "output": 2, "calcifier": 3, "bonder": 4}
    placements.sort(key=lambda p: (order[p["type"]], p["id"]))
    instructions.sort(key=lambda i: i["t"])
    return {"puzzle": puzzle["name"],
            "solver": "clingo (asp/core2.lp + asp/layout.lp)",
            "placements": placements,
            "instructions": instructions}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("puzzle")
    ap.add_argument("--out", help="write the plan JSON here instead of stdout")
    ap.add_argument("--time-limit", type=float,
                    default=float(os.environ.get("HARNESS_CLINGO_TIME_LIMIT",
                                                 30)))
    args = ap.parse_args()
    try:
        with open(args.puzzle) as f:
            puzzle = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        die(str(e))
    for key in ("name", "board_radius", "t_max", "reagents", "products",
                "parts"):
        if key not in puzzle:
            die(f"puzzle: missing key {key!r}")
    instance_text, maps = generate_instance(puzzle)
    result, best = solve(puzzle, instance_text, args.time_limit)
    if best["symbols"] is None:
        print(f"adapter: no model ({result}) within "
              f"{args.time_limit}s at t_max={puzzle['t_max']}",
              file=sys.stderr)
        sys.exit(1)
    plan = extract_plan(puzzle, best["symbols"], maps)
    print(f"adapter: {result} cost={best['cost']} "
          f"({len(plan['instructions'])} instructions)", file=sys.stderr)
    text = json.dumps(plan, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
    else:
        print(text)
    sys.exit(0)


if __name__ == "__main__":
    main()
