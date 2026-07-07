#!/usr/bin/env python3
"""Independent plan-legality validator for the Z3 arm's solution JSONs.

Replays each plan in z3/solutions/*.json with plain Python (NO z3 import,
no reuse of the encoders' transition functions): the semantics below are
re-implemented directly from the clingo specification files
asp/core.lp (v1) and asp/core2.lp (v2) plus the instance files.  Every
step is checked for legality, every state for its invariants, and the
goal at the final state; the JSON's reported trajectories, orientations,
held flags, bond timelines and cost are cross-checked against the replay.

Usage: python3 z3/validate.py [solution.json ...]
       (defaults to every JSON under z3/solutions/)
"""

import glob
import json
import os
import sys

DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]
ELEMENTAL = {"air", "earth", "fire", "water"}

# --------------------------------------------------------------------------
# Instance data, re-declared from the spec (asp/*_instance.lp,
# z3/stabilized_water.lp) rather than imported from the encoders.
# Layout facts (bases, orientations, glyph hexes) are NOT taken from here
# at replay time -- they come from each solution's own layout section, so
# free-layout solutions validate against their chosen layout.
# --------------------------------------------------------------------------
SPEC = {
    "trivial": dict(  # asp/trivial_instance.lp + core.lp
        semantics="v1", radius=2,
        atoms={"a1": dict(pos=(1, 0), type="salt")},
        init_bonds=[],
        products=[("a1", (-1, 0))],
        product_slots=[], require_end_bond=False,
        forbid_rot_holding_bonded=False,
    ),
    "bond": dict(  # asp/bond_instance.lp + core.lp
        semantics="v1", radius=2,
        atoms={"a1": dict(pos=(1, 0), type="salt"),
               "a2": dict(pos=(0, 1), type="salt")},
        init_bonds=[],
        products=[("a1", (-1, 0)), ("a2", (0, -1))],
        product_slots=[], require_end_bond=True,
        forbid_rot_holding_bonded=True,
    ),
    "rigid": dict(  # asp/rigid_instance.lp + core2.lp
        semantics="v2", radius=2,
        atoms={"a1": dict(pos=(1, 0), type="salt"),
               "a2": dict(pos=(2, 0), type="salt")},
        init_bonds=[("a1", "a2")],
        products=[("a1", (-1, 1)), ("a2", (-2, 2))],
        product_slots=[], require_end_bond=False,
        forbid_rot_holding_bonded=False,
    ),
    "water": dict(  # z3/stabilized_water.lp + core2.lp (Stabilized Water)
        semantics="v2", radius=2,
        atoms={"w1": dict(pos=(1, 0), type="water"),
               "w2": dict(pos=(1, -1), type="water")},
        init_bonds=[],
        products=[],
        product_slots=[((-1, 0), "salt"), ((0, -1), "water")],
        require_end_bond=True,
        forbid_rot_holding_bonded=False,
    ),
}


class Illegal(Exception):
    pass


def on_board(p, radius):
    q, r = p
    return abs(q) <= radius and abs(r) <= radius and abs(q + r) <= radius


def rot_cw(p, b):
    """Axial rotation clockwise (dir d -> d+1) about base b (core2 rule)."""
    dq, dr = p[0] - b[0], p[1] - b[1]
    return (b[0] - dr, b[1] + dq + dr)


def rot_ccw(p, b):
    dq, dr = p[0] - b[0], p[1] - b[1]
    return (b[0] + dq + dr, b[1] - dq)


class Sim:
    """Plain re-simulation of the core.lp / core2.lp semantics."""

    def __init__(self, spec, layout, radius):
        self.spec = spec
        self.v2 = spec["semantics"] == "v2"
        self.radius = radius
        self.arms = {a["name"]: dict(base=tuple(a["base"]),
                                     length=a["length"])
                     for a in layout["arms"]}
        self.orient = {a["name"]: a["init_orient"] for a in layout["arms"]}
        self.glyph_bonds = [((g[0], g[1]), (g[2], g[3]))
                            for g in layout["glyph_bonds"]]
        self.glyph_calcs = [tuple(g) for g in layout["glyph_calcs"]]
        self.pos = {x: tuple(d["pos"]) for x, d in spec["atoms"].items()}
        self.typ = {x: d["type"] for x, d in spec["atoms"].items()}
        self.held = {m: None for m in self.arms}   # arm -> atom | None
        self.bonds = set(frozenset(p) for p in spec["init_bonds"])
        self.update_bonds()
        self.check_state()

    # -- helpers ----------------------------------------------------------
    def gripper(self, m):
        base = self.arms[m]["base"]
        L = self.arms[m]["length"]
        d = DIRS[self.orient[m]]
        return (base[0] + L * d[0], base[1] + L * d[1])

    def atom_at(self, p):
        for x, q in self.pos.items():
            if q == p:
                return x
        return None

    def held_by(self, x):
        for m, y in self.held.items():
            if y == x:
                return m
        return None

    def comp(self, m):
        """Bond-connected component of the atom held by arm m (core2)."""
        x = self.held[m]
        if x is None:
            return set()
        seen = {x}
        frontier = [x]
        while frontier:
            y = frontier.pop()
            for b in self.bonds:
                if y in b:
                    (z,) = b - {y}
                    if z not in seen:
                        seen.add(z)
                        frontier.append(z)
        return seen

    def update_bonds(self):
        """bond(X,Y,T) :- glyph_bond(..), at(X,..,T), at(Y,..,T) -- fires
        at EVERY state, even while atoms are held; bonds persist."""
        for (p1, p2) in self.glyph_bonds:
            x, y = self.atom_at(p1), self.atom_at(p2)
            if x is not None and y is not None and x != y:
                self.bonds.add(frozenset((x, y)))

    def check_state(self):
        for x, p in self.pos.items():
            if not on_board(p, self.radius):
                raise Illegal(f"atom {x} off board at {p}")
        if len(set(self.pos.values())) != len(self.pos):
            raise Illegal(f"atom collision: {self.pos}")
        for m in self.arms:
            if not on_board(self.gripper(m), self.radius):
                raise Illegal(f"gripper of {m} off board")
        if self.v2:  # arm bases block hexes (core2 only)
            for m, a in self.arms.items():
                if a["base"] in self.pos.values():
                    raise Illegal(f"atom on arm base {a['base']}")

    # -- one step ---------------------------------------------------------
    def step(self, action, arm):
        # calcification is determined by the PRE-move state of this step,
        # for EVERY step including wait (calcifies(X,T) :- at(X,..,T),
        # step(T); the type changes at T+1)
        calcify = [x for x in self.pos
                   if self.pos[x] in self.glyph_calcs
                   and self.typ[x] in ELEMENTAL] if self.v2 else []
        if action == "wait":
            for x in calcify:
                self.typ[x] = "salt"
            return
        m = arm
        if m not in self.arms:
            raise Illegal(f"unknown arm {m}")

        if action == "grab":
            if self.held[m] is not None:
                raise Illegal("grab with full hand")
            x = self.atom_at(self.gripper(m))
            if x is None:
                raise Illegal("grab on empty hex")
            if self.v2 and self.held_by(x) is not None:
                raise Illegal("grab of atom held by another arm")
            self.held[m] = x
        elif action == "drop":
            if self.held[m] is None:
                raise Illegal("drop with empty hand")
            self.held[m] = None
        elif action in ("rot_cw", "rot_ccw"):
            if self.spec["forbid_rot_holding_bonded"]:
                x = self.held[m]
                if x is not None and any(x in b for b in self.bonds):
                    raise Illegal("rotation while holding a bonded atom")
            if self.v2:
                moved = self.comp(m)
                for x in moved:  # may not tear from another arm's hand
                    hb = self.held_by(x)
                    if hb is not None and hb != m:
                        raise Illegal(f"rotation tears {x} from {hb}")
            self.orient[m] = (self.orient[m]
                              + (1 if action == "rot_cw" else -1)) % 6
            if self.v2:
                # rigid rotation of the held component about the base
                base = self.arms[m]["base"]
                fn = rot_cw if action == "rot_cw" else rot_ccw
                for x in moved:
                    self.pos[x] = fn(self.pos[x], base)
            else:
                # v1: the held atom rides the gripper
                x = self.held[m]
                if x is not None:
                    self.pos[x] = self.gripper(m)
        else:
            raise Illegal(f"unknown action {action}")

        for x in calcify:
            self.typ[x] = "salt"
        self.update_bonds()
        self.check_state()

    # -- goal ---------------------------------------------------------------
    def goal_met(self):
        spec = self.spec
        for (x, p) in spec["products"]:
            if self.pos[x] != tuple(p) or self.held_by(x) is not None:
                return False, f"product {x} not delivered"
        slots = spec["product_slots"]
        if slots:
            import itertools
            ok = False
            for perm in itertools.permutations(self.pos, len(slots)):
                good = all(self.pos[perm[i]] == tuple(sp)
                           and self.typ[perm[i]] == ty
                           and self.held_by(perm[i]) is None
                           for i, (sp, ty) in enumerate(slots))
                if good and spec["require_end_bond"] and len(slots) == 2:
                    good = frozenset(perm[:2]) in self.bonds
                if good:
                    ok = True
                    break
            if not ok:
                return False, "no atom assignment satisfies product slots"
        elif spec["require_end_bond"] and not self.bonds:
            return False, "no bond at the end"
        return True, "ok"


def validate(path):
    with open(path) as f:
        sol = json.load(f)
    name = sol["meta"]["instance"]
    spec = SPEC[name]
    radius = sol["meta"].get("radius", 2)
    sim = Sim(spec, sol["layout"], radius)
    h = sol["horizon"]
    if len(sol["actions"]) != h:
        return False, f"actions length {len(sol['actions'])} != horizon {h}"

    def cross_check(t):
        for x, tr in sol["atom_trajectories"].items():
            if tuple(tr[t]) != sim.pos[x]:
                raise Illegal(f"t={t}: {x} at {sim.pos[x]}, "
                              f"JSON says {tuple(tr[t])}")
        for m, orl in sol["orientations"].items():
            if orl[t] != sim.orient[m]:
                raise Illegal(f"t={t}: {m} orient {sim.orient[m]}, "
                              f"JSON says {orl[t]}")
        for x, hl in sol["held"].items():
            if hl[t] != sim.held_by(x):
                raise Illegal(f"t={t}: {x} held by {sim.held_by(x)}, "
                              f"JSON says {hl[t]}")
        for entry in sol.get("bonds", []):
            pair = frozenset(entry["atoms"])
            if entry["bonded"][t] != (pair in sim.bonds):
                raise Illegal(f"t={t}: bond {set(pair)} mismatch")

    try:
        cross_check(0)
        for a in sol["actions"]:
            sim.step(a["action"], a["arm"])
            cross_check(a["t"] + 1)
    except Illegal as e:
        return False, str(e)

    met, why = sim.goal_met()
    if not met:
        return False, f"goal not met: {why}"
    n_act = sum(1 for a in sol["actions"] if a["action"] != "wait")
    if n_act != sol["cost"]:
        return False, f"cost mismatch: {n_act} non-wait vs cost {sol['cost']}"
    return True, f"legal plan, goal met, cost {sol['cost']}"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    paths = sys.argv[1:] or sorted(glob.glob(os.path.join(here, "solutions",
                                                          "*.json")))
    failures = 0
    for p in paths:
        ok, why = validate(p)
        print(f"{'PASS' if ok else 'FAIL'}  {os.path.basename(p):<24} {why}")
        failures += 0 if ok else 1
    print(f"{len(paths) - failures}/{len(paths)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
