#!/usr/bin/env python3
"""Canonical validator for the multi-solver Opus Magnum harness.

Replays a plan JSON against a puzzle JSON under the shared world semantics
(see harness/SPEC.md) and prints PASS/FAIL with a clear error message.
Pure Python, no dependencies, no solver code shared: a descendant of
master's proven validate.py replay, generalized to the common formats.

Usage:
    python3 harness/validate.py <puzzle.json> <plan.json> [--verbose]

Exit status: 0 = PASS, 1 = FAIL (bad plan), 2 = malformed input.

Importable API:
    validate(puzzle: dict, plan: dict, log=None, on_state=None) -> dict
        (raises Invalid; returns {product id: completion time};
         on_state(t, snapshot) is called once per replay state t=0..t_max
         with a copy of the world state -- see the docstring of validate)
    plan_length(plan) -> int                               (non-wait instructions)
"""

import argparse
import json
from typing import Any

DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]  # clockwise
ELEMENTAL = {"air", "earth", "fire", "water"}
ELEMENTS = ELEMENTAL | {"salt"}
ACTIONS = {"grab", "drop", "rot_cw", "rot_ccw", "wait"}


class Invalid(Exception):
    """The plan is illegal / does not solve the puzzle."""


class Malformed(Exception):
    """The puzzle or plan JSON does not conform to the format."""


def rot_cw(q, r):
    return (-r, q + r)


def rot_ccw(q, r):
    return (q + r, -q)


def rot_k(q, r, k):
    for _ in range(k % 6):
        q, r = rot_cw(q, r)
    return (q, r)


def transform(pos, rotation, offset):
    oq, or_ = rot_k(offset[0], offset[1], rotation)
    return (pos[0] + oq, pos[1] + or_)


def on_board(h, radius):
    return abs(h[0]) <= radius and abs(h[1]) <= radius and abs(h[0] + h[1]) <= radius


# ---------------------------------------------------------------------------
# Format checking / loading
# ---------------------------------------------------------------------------
def _hex(v, what):
    if not isinstance(v, (list, tuple)) or len(v) != 2 or not all(isinstance(c, int) for c in v):
        raise Malformed(f"{what}: expected [q, r] integer pair, got {v!r}")
    return (v[0], v[1])


def _molecule(m, what):
    atoms = m.get("atoms")
    if not isinstance(atoms, list) or not atoms:
        raise Malformed(f"{what}: needs a non-empty 'atoms' list")
    out_atoms = []
    for i, a in enumerate(atoms):
        el = a.get("element")
        if el not in ELEMENTS:
            raise Malformed(
                f"{what} atom {i}: unknown element {el!r} (supported: {sorted(ELEMENTS)})"
            )
        out_atoms.append((el, _hex(a.get("pos"), f"{what} atom {i} pos")))
    seen: dict[tuple[int, int], int] = {}
    for i, (_, h) in enumerate(out_atoms):
        if h in seen:
            raise Malformed(f"{what}: atoms {seen[h]} and {i} share hex {h}")
        seen[h] = i
    bonds = set()
    for b in m.get("bonds", []):
        if (
            not isinstance(b, list)
            or len(b) != 2
            or not all(isinstance(x, int) for x in b)
            or not all(0 <= x < len(out_atoms) for x in b)
            or b[0] == b[1]
        ):
            raise Malformed(f"{what}: bad bond {b!r}")
        bonds.add(frozenset(b))
    return out_atoms, bonds


def check_puzzle(puzzle):
    for key in ("name", "board_radius", "t_max", "reagents", "products", "parts"):
        if key not in puzzle:
            raise Malformed(f"puzzle: missing required key {key!r}")
    if not isinstance(puzzle["board_radius"], int) or puzzle["board_radius"] < 1:
        raise Malformed("puzzle: board_radius must be an integer >= 1")
    if not isinstance(puzzle["t_max"], int) or puzzle["t_max"] < 1:
        raise Malformed("puzzle: t_max must be an integer >= 1")
    for kind in ("reagents", "products"):
        ids = [m.get("id") for m in puzzle[kind]]
        if len(set(ids)) != len(ids) or None in ids:
            raise Malformed(f"puzzle: {kind} ids must be unique strings")
        for m in puzzle[kind]:
            _molecule(m, f"{kind[:-1]} {m['id']}")
        if kind == "reagents":
            for m in puzzle[kind]:
                if not isinstance(m.get("pool"), int) or m["pool"] < 1:
                    raise Malformed(f"reagent {m['id']}: pool must be int >= 1")
    part_ids = [p.get("id") for p in puzzle["parts"]]
    if len(set(part_ids)) != len(part_ids) or None in part_ids:
        raise Malformed("puzzle: part ids must be unique strings")
    for p in puzzle["parts"]:
        if p.get("type") not in ("arm", "calcifier", "bonder"):
            raise Malformed(f"puzzle part {p.get('id')}: unsupported type {p.get('type')!r}")
        if p["type"] == "arm" and (not isinstance(p.get("length"), int) or p["length"] < 1):
            raise Malformed(f"arm {p['id']}: length must be an integer >= 1")


# ---------------------------------------------------------------------------
# Placement resolution
# ---------------------------------------------------------------------------
class Layout:
    def __init__(self):
        self.arms = {}  # id -> {"base","length","rotation"}
        self.inputs = {}  # reagent id -> {"position","rotation"}
        self.outputs = {}  # product id -> {"position","rotation"}
        self.calcifiers = {}  # id -> hex
        self.bonders = {}  # id -> (hex, hex)


def _pinned(spec, got_pos, got_rot, what, rot_matters=True):
    if "position" in spec and _hex(spec["position"], what) != got_pos:
        raise Invalid(
            f"{what}: puzzle pins position {tuple(spec['position'])}, plan places it at {got_pos}"
        )
    if rot_matters and "rotation" in spec and spec["rotation"] % 6 != got_rot:
        raise Invalid(f"{what}: puzzle pins rotation {spec['rotation']}, plan uses {got_rot}")


def resolve_layout(puzzle, plan):
    radius = puzzle["board_radius"]
    lay = Layout()
    reagents = {m["id"]: m for m in puzzle["reagents"]}
    products = {m["id"]: m for m in puzzle["products"]}
    parts = {p["id"]: p for p in puzzle["parts"]}

    placements = plan.get("placements")
    if not isinstance(placements, list):
        raise Malformed("plan: missing 'placements' list")
    for pl in placements:
        ptype, pid = pl.get("type"), pl.get("id")
        what = f"placement {ptype}/{pid}"
        pos = _hex(pl.get("position"), f"{what} position")
        rot = pl.get("rotation", 0)
        if not isinstance(rot, int) or not 0 <= rot <= 5:
            raise Malformed(f"{what}: rotation must be an integer in 0..5")
        if ptype == "input":
            if pid not in reagents:
                raise Invalid(f"{what}: no reagent {pid!r} in the puzzle")
            if pid in lay.inputs:
                raise Invalid(f"{what}: placed twice")
            _pinned(reagents[pid], pos, rot, what)
            lay.inputs[pid] = {"position": pos, "rotation": rot}
        elif ptype == "output":
            if pid not in products:
                raise Invalid(f"{what}: no product {pid!r} in the puzzle")
            if pid in lay.outputs:
                raise Invalid(f"{what}: placed twice")
            _pinned(products[pid], pos, rot, what)
            lay.outputs[pid] = {"position": pos, "rotation": rot}
        elif ptype in ("arm", "calcifier", "bonder"):
            spec = parts.get(pid)
            if spec is None or spec["type"] != ptype:
                raise Invalid(f"{what}: puzzle has no {ptype} part {pid!r}")
            if pid in lay.arms or pid in lay.calcifiers or pid in lay.bonders:
                raise Invalid(f"{what}: placed twice")
            if ptype == "arm":
                length = spec["length"]
                if "length" in pl and pl["length"] != length:
                    raise Invalid(f"{what}: length {pl['length']} != puzzle length {length}")
                _pinned(spec, pos, rot, what)
                lay.arms[pid] = {"base": pos, "length": length, "rotation": rot}
            elif ptype == "calcifier":
                _pinned(spec, pos, rot, what, rot_matters=False)
                lay.calcifiers[pid] = pos
            else:  # bonder
                other = (pos[0] + DIRS[rot][0], pos[1] + DIRS[rot][1])
                if "position" in spec:
                    prot = spec.get("rotation", 0) % 6
                    ppos = _hex(spec["position"], what)
                    pinned = {ppos, (ppos[0] + DIRS[prot][0], ppos[1] + DIRS[prot][1])}
                    if {pos, other} != pinned:
                        raise Invalid(
                            f"{what}: puzzle pins hexes "
                            f"{sorted(pinned)}, plan uses "
                            f"{sorted({pos, other})}"
                        )
                lay.bonders[pid] = (pos, other)
        else:
            raise Malformed(f"placement with unknown type {ptype!r}")

    for pid, spec in parts.items():
        placed = {"arm": lay.arms, "calcifier": lay.calcifiers, "bonder": lay.bonders}[spec["type"]]
        if pid not in placed:
            raise Invalid(f"plan never places {spec['type']} part {pid!r}")
    for rid in reagents:
        if rid not in lay.inputs:
            raise Invalid(f"plan never places an input for reagent {rid!r}")
    for pid in products:
        if pid not in lay.outputs:
            raise Invalid(f"plan never places an output for product {pid!r}")

    # footprints: on board + pairwise disjoint
    feet = []  # (owner, hex)
    for mid, a in lay.arms.items():
        feet.append((f"arm {mid}", a["base"]))
    for rid, ipl in lay.inputs.items():
        for _, off in _molecule(reagents[rid], f"reagent {rid}")[0]:
            feet.append((f"input {rid}", transform(ipl["position"], ipl["rotation"], off)))
    for pid, opl in lay.outputs.items():
        for _, off in _molecule(products[pid], f"product {pid}")[0]:
            feet.append((f"output {pid}", transform(opl["position"], opl["rotation"], off)))
    for cid, h in lay.calcifiers.items():
        feet.append((f"calcifier {cid}", h))
    for bid, (h1, h2) in lay.bonders.items():
        feet.append((f"bonder {bid}", h1))
        feet.append((f"bonder {bid}", h2))
    seen: dict[tuple[int, int], str] = {}
    for owner, h in feet:
        if not on_board(h, radius):
            raise Invalid(f"{owner}: footprint hex {h} is off the board (radius {radius})")
        if h in seen and seen[h] != owner:
            raise Invalid(f"part footprints overlap at {h}: {seen[h]} and {owner}")
        seen[h] = owner
    for mid, a in lay.arms.items():
        g = transform(
            a["base"],
            0,
            (a["length"] * DIRS[a["rotation"]][0], a["length"] * DIRS[a["rotation"]][1]),
        )
        if not on_board(g, radius):
            raise Invalid(f"arm {mid}: initial gripper hex {g} is off the board")
    return lay


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------
def read_instructions(puzzle, plan, lay):
    t_max = puzzle["t_max"]
    instrs = plan.get("instructions")
    if not isinstance(instrs, list):
        raise Malformed("plan: missing 'instructions' list")
    by_t = {}
    for ins in instrs:
        t, arm, act = ins.get("t"), ins.get("arm"), ins.get("action")
        if not isinstance(t, int):
            raise Malformed(f"instruction {ins!r}: t must be an integer")
        if act not in ACTIONS:
            raise Invalid(f"instruction at t={t}: unknown action {act!r}")
        if not 0 <= t < t_max:
            raise Invalid(f"instruction at t={t}: outside the horizon 0..{t_max - 1}")
        if act != "wait" and arm not in lay.arms:
            raise Invalid(f"instruction at t={t}: unknown arm {arm!r}")
        if t in by_t:
            raise Invalid(
                f"two instructions at t={t} (sequential-arm rule: "
                f"at most one instruction per timestep)"
            )
        by_t[t] = (arm, act)
    return by_t


def plan_length(plan):
    return sum(1 for i in plan.get("instructions", []) if i.get("action") != "wait")


# ---------------------------------------------------------------------------
# Replay (semantics of SPEC.md section 5; descends from master validate.py)
# ---------------------------------------------------------------------------
def validate(puzzle, plan, log=None, on_state=None):
    """Replay `plan` against `puzzle`; raise Invalid/Malformed on any
    problem, return {product id: completion time} on success.

    If `on_state` is given it is called once for every replay state
    t = 0..t_max (after that state's legality checks) as
    `on_state(t, snapshot)` where snapshot is a dict of copies:
    {"pos": {atom: (q, r)}, "typ": {atom: element},
     "orient": {arm: direction index}, "holds": {arm: atom or None}}.
    This is the supported way for metric code (harness/metrics.py) to
    observe the canonical replay without duplicating its semantics.
    """
    log = log or (lambda *a: None)
    check_puzzle(puzzle)
    if plan.get("puzzle") not in (None, puzzle["name"]):
        raise Invalid(f"plan is for puzzle {plan.get('puzzle')!r}, not {puzzle['name']!r}")
    lay = resolve_layout(puzzle, plan)
    by_t = read_instructions(puzzle, plan, lay)

    radius, t_max = puzzle["board_radius"], puzzle["t_max"]
    reagents = {m["id"]: m for m in puzzle["reagents"]}
    products = {m["id"]: m for m in puzzle["products"]}

    pos: dict[Any, tuple[int, int]] = {}  # atom -> hex
    typ: dict[Any, str] = {}  # atom -> element
    bonds = set()  # frozenset({x, y})
    holds = dict.fromkeys(lay.arms)
    orient = {m: a["rotation"] for m, a in lay.arms.items()}
    bases = {a["base"] for a in lay.arms.values()}
    spawned = dict.fromkeys(reagents, 0)

    def gripper(m):
        a = lay.arms[m]
        d = orient[m]
        return (a["base"][0] + a["length"] * DIRS[d][0], a["base"][1] + a["length"] * DIRS[d][1])

    def spawn_hexes(rid):
        ipl = lay.inputs[rid]
        atoms, _ = _molecule(reagents[rid], f"reagent {rid}")
        return [(el, transform(ipl["position"], ipl["rotation"], off)) for el, off in atoms]

    def try_spawn():
        for rid, m in reagents.items():
            if spawned[rid] >= m["pool"]:
                continue
            hx = spawn_hexes(rid)
            if any(h in pos.values() for _, h in hx):
                continue
            n = spawned[rid] = spawned[rid] + 1
            names = []
            for i, (el, h) in enumerate(hx):
                x = f"{rid}#{n}.{i}"
                pos[x], typ[x] = h, el
                names.append(x)
            for b in _molecule(reagents[rid], f"reagent {rid}")[1]:
                i, j = sorted(b)
                bonds.add(frozenset((names[i], names[j])))

    def apply_bonders():
        occ = {h: x for x, h in pos.items()}
        for h1, h2 in lay.bonders.values():
            if h1 in occ and h2 in occ:
                bonds.add(frozenset((occ[h1], occ[h2])))

    def component(x):
        seen, stack = {x}, [x]
        while stack:
            c = stack.pop()
            for b in bonds:
                if c in b:
                    for y in b - {c}:
                        if y not in seen:
                            seen.add(y)
                            stack.append(y)
        return seen

    def static_checks(t):
        for m in lay.arms:
            if not on_board(gripper(m), radius):
                raise Invalid(f"t={t}: gripper of arm {m} at {gripper(m)} is off the board")
        occ: dict[tuple[int, int], Any] = {}
        for x, h in pos.items():
            if not on_board(h, radius):
                raise Invalid(f"t={t}: atom {x} at {h} is off the board")
            if h in occ:
                raise Invalid(f"t={t}: atoms {occ[h]} and {x} collide at {h}")
            occ[h] = x
            if h in bases:
                raise Invalid(f"t={t}: atom {x} rests on an arm base at {h}")

    calc_hexes = set(lay.calcifiers.values())
    complete_at = dict.fromkeys(products)

    def check_goals(t):
        occ = {h: x for x, h in pos.items()}
        held = {x for x in holds.values() if x is not None}
        deg: dict[Any, int] = {}
        for b in bonds:
            for x in b:
                deg[x] = deg.get(x, 0) + 1
        for pid, m in products.items():
            if complete_at[pid] is not None:
                continue
            opl = lay.outputs[pid]
            atoms, pbonds = _molecule(m, f"product {pid}")
            names = []
            ok = True
            for el, off in atoms:
                h = transform(opl["position"], opl["rotation"], off)
                x = occ.get(h)
                if x is None or typ[x] != el or x in held:
                    ok = False
                    break
                names.append(x)
            if ok:
                pdeg = dict.fromkeys(range(len(atoms)), 0)
                for b in pbonds:
                    i, j = sorted(b)
                    pdeg[i] += 1
                    pdeg[j] += 1
                    if frozenset((names[i], names[j])) not in bonds:
                        ok = False
                if ok and any(deg.get(names[i], 0) != pdeg[i] for i in range(len(atoms))):
                    ok = False
            if ok:
                complete_at[pid] = t
                log(f"t={t}: product {pid} complete")

    def notify(t):
        if on_state is not None:
            on_state(
                t,
                {"pos": dict(pos), "typ": dict(typ), "orient": dict(orient), "holds": dict(holds)},
            )

    # ---- t = 0
    try_spawn()
    apply_bonders()
    static_checks(0)
    check_goals(0)
    notify(0)

    for t in range(t_max):
        m, act = by_t.get(t, (None, "wait"))
        log(
            f"t={t}: {m or '-'} {act}  "
            + " ".join(f"{a}:d{orient[a]}" for a in sorted(lay.arms))
            + "  "
            + " ".join(f"{x}/{typ[x]}@{h}" for x, h in sorted(pos.items()))
        )
        oldpos = dict(pos)  # calcification reads positions at t, not t+1
        if act == "grab":
            if holds[m] is not None:
                raise Invalid(f"t={t}: arm {m} grabs with a full hand")
            g = gripper(m)
            x = next((x for x, h in pos.items() if h == g), None)
            if x is None:
                raise Invalid(f"t={t}: arm {m} grabs over empty hex {g}")
            if x in {h for a, h in holds.items() if a != m and h is not None}:
                raise Invalid(f"t={t}: arm {m} grabs atom {x}, which is held by another arm")
            holds[m] = x
        elif act == "drop":
            if holds[m] is None:
                raise Invalid(f"t={t}: arm {m} drops with an empty hand")
            holds[m] = None
        elif act in ("rot_cw", "rot_ccw"):
            rot = rot_cw if act == "rot_cw" else rot_ccw
            b = lay.arms[m]["base"]
            orient[m] = (orient[m] + (1 if act == "rot_cw" else 5)) % 6
            if not on_board(gripper(m), radius):
                raise Invalid(f"t={t}: arm {m} rotates its gripper off the board to {gripper(m)}")
            if holds[m] is not None:
                comp = component(holds[m])
                for a in lay.arms:
                    if a != m and holds[a] in comp:
                        raise Invalid(
                            f"t={t}: arm {m} would tear atom {holds[a]} out of arm {a}'s hand"
                        )
                for x in comp:
                    dq, dr = rot(pos[x][0] - b[0], pos[x][1] - b[1])
                    pos[x] = (b[0] + dq, b[1] + dr)
                    if not on_board(pos[x], radius):
                        raise Invalid(f"t={t}: arm {m} swings atom {x} off the board to {pos[x]}")
        # (act == "wait": no effect)
        # calcification: reads positions at t, retypes at t+1
        for x, h in oldpos.items():
            if h in calc_hexes and typ[x] in ELEMENTAL:
                typ[x] = "salt"
        try_spawn()
        apply_bonders()
        static_checks(t + 1)
        check_goals(t + 1)
        notify(t + 1)

    missing = [pid for pid, t in complete_at.items() if t is None]
    if missing:
        raise Invalid(
            f"goal not reached: product(s) {missing} never complete on "
            f"their output hexes by t_max={t_max} "
            f"(final atoms: "
            + ", ".join(f"{x}/{typ[x]}@{pos[x]}" for x in sorted(pos))
            + f"; bonds: {sorted(tuple(sorted(b)) for b in bonds)})"
        )
    return complete_at


def main():
    ap = argparse.ArgumentParser(description="Validate a plan JSON against a puzzle JSON.")
    ap.add_argument("puzzle")
    ap.add_argument("plan")
    ap.add_argument("--verbose", action="store_true", help="print the replay step by step")
    args = ap.parse_args()
    try:
        with open(args.puzzle) as f:
            puzzle = json.load(f)
        with open(args.plan) as f:
            plan = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"MALFORMED  {e}")
        return 2
    log = print if args.verbose else None
    try:
        complete_at = validate(puzzle, plan, log=log)
    except Malformed as e:
        print(f"MALFORMED  {args.plan}: {e}")
        return 2
    except Invalid as e:
        print(f"FAIL  {puzzle.get('name', args.puzzle)}: {e}")
        return 1
    done = ", ".join(f"{pid}@t={t}" for pid, t in sorted(complete_at.items()))
    print(
        f"PASS  {puzzle['name']}: plan length {plan_length(plan)} "
        f"(non-wait instructions), products complete: {done}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
