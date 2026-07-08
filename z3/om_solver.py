#!/usr/bin/env python3
"""Z3 bounded-model-checking encoding of the asp-om Opus Magnum fragment.

Mirrors the clingo encodings in asp/ on the main branch:
  - asp/core.lp   (v1 semantics: one arm, exactly one instruction per step,
                   held atom rides the gripper, no rigid molecule motion)
  - asp/core2.lp  (v2 semantics: multi-arm serialized (<=1 action/step
                   globally), rigid rotation of the bond-connected component,
                   arm bases block hexes, calcification glyph)

Shared world model (identical to the clingo arm, apples-to-apples):
  - Axial hex coords (q,r), board radius 2: |q|<=2, |r|<=2, |q+r|<=2.
  - Direction table, clockwise:
      dir 0=( 1, 0)  1=( 0, 1)  2=(-1, 1)  3=(-1, 0)  4=( 0,-1)  5=( 1,-1)
  - rot_cw about origin: (q,r) -> (-r, q+r);  rot_ccw: (q,r) -> (q+r, -q).
  - Arm: base hex, length L (tests use 1), orientation 0..5,
    gripper = base + L*dir(orientation).
  - Discrete steps 0..T-1 acting on states 0..T.
  - Objective: minimize the number of non-wait instructions over the FULL
    horizon T (exactly clingo's #minimize{1,T : do(A,T), A != wait}).

Primary encoding: Z3 Int variables for coordinates / orientation / action,
Bool for held/bond flags.  A pure-boolean one-hot variant lives in om_bool.py.

Layout modes:
  - fixed: arm base, initial orientation and glyph hexes pinned to the
    instance values (this is what the clingo instances do -> the comparable
    numbers).
  - free:  arm base hex, initial orientation and glyph hexes are
    solver-chosen, subject to sanity constraints:
      * base on the board, bases pairwise distinct;
      * glyph_bond hexes on the board and adjacent to each other;
      * initial atom positions and product/goal hexes stay FIXED (they define
        the puzzle: reagent spawn hexes and product target hexes);
      * v2 only (as in core2.lp): no atom may ever sit on an arm base, which
        in free mode also forbids placing the base on a reagent hex.  v1 has
        no base-blocking (mirroring core.lp, where the base does not block).
"""

import argparse
import json
import os
import time

import z3

DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]
ARM_ACTIONS = ["rot_cw", "rot_ccw", "grab", "drop"]  # code 1+4*arm+idx; 0=wait


# ---------------------------------------------------------------------------
# Instances (exact mirrors of asp/{trivial,bond,rigid}_instance.lp)
# ---------------------------------------------------------------------------

INSTANCES = {
    # asp/trivial_instance.lp + core.lp, t_max=10
    "trivial": {
        "semantics": "v1",
        "t_max": 10,
        "radius": 2,
        "arms": [{"name": "m1", "base": (0, 0), "length": 1, "init_orient": 0}],
        "atoms": [{"name": "a1", "pos": (1, 0), "type": "salt"}],
        "init_bonds": [],
        "glyph_bonds": [],
        "glyph_calcs": [],
        "products": [("a1", (-1, 0))],
        "require_end_bond": False,
        "forbid_rot_holding_bonded": False,
        "expected_opt": 5,
    },
    # asp/bond_instance.lp + core.lp, t_max=16
    "bond": {
        "semantics": "v1",
        "t_max": 16,
        "radius": 2,
        "arms": [{"name": "m1", "base": (0, 0), "length": 1, "init_orient": 0}],
        "atoms": [
            {"name": "a1", "pos": (1, 0), "type": "salt"},
            {"name": "a2", "pos": (0, 1), "type": "salt"},
        ],
        "init_bonds": [],
        "glyph_bonds": [((-1, 0), (0, -1))],
        "glyph_calcs": [],
        "products": [("a1", (-1, 0)), ("a2", (0, -1))],
        "require_end_bond": True,  # goal_bond in bond_instance.lp
        "forbid_rot_holding_bonded": True,  # phase-1 v1 simplification
        "expected_opt": 12,
    },
    # asp/rigid_instance.lp + core2.lp, t_max=10
    "rigid": {
        "semantics": "v2",
        "t_max": 10,
        "radius": 2,
        "arms": [{"name": "m1", "base": (0, 0), "length": 1, "init_orient": 0}],
        "atoms": [
            {"name": "a1", "pos": (1, 0), "type": "salt"},
            {"name": "a2", "pos": (2, 0), "type": "salt"},
        ],
        "init_bonds": [("a1", "a2")],
        "glyph_bonds": [],
        "glyph_calcs": [],
        "products": [("a1", (-1, 1)), ("a2", (-2, 2))],  # goal_met: at + unheld
        "require_end_bond": False,
        "forbid_rot_holding_bonded": False,  # v2 does rigid motion instead
        "expected_opt": 4,
    },
    # Stabilized Water (omsim P007), modelled in the simplified v2 semantics.
    # Instance defined by us (no clingo instance exists); choices documented
    # in NOTES.md.  Two 1-atom WATER reagents; the product is a 2-atom
    # molecule salt--water on the two product slots, formed via the
    # calcification glyph + bonding glyph.  Reagent pools: core2's spawn/
    # nreagent machinery with nreagent=1 per spawn hex degenerates to a
    # pre-placed atom (r(1) at t=0, no respawn since output_scale=1 needs
    # only one product), so the two inputs are modelled as two init_at
    # water atoms on the two spawn hexes.
    "water": {
        "semantics": "v2",
        "t_max": 12,
        "radius": 2,
        "arms": [{"name": "m1", "base": (0, 0), "length": 1, "init_orient": 0}],
        "atoms": [
            {"name": "w1", "pos": (1, 0), "type": "water"},
            {"name": "w2", "pos": (1, -1), "type": "water"},
        ],
        "init_bonds": [],
        "glyph_bonds": [((-1, 0), (0, -1))],
        "glyph_calcs": [(-1, 1)],
        "products": [],
        # product molecule: salt on (-1,0) bonded to water on (0,-1);
        # slots are anonymous (any atom may fill either slot).
        "product_slots": [((-1, 0), "salt"), ((0, -1), "water")],
        "require_end_bond": True,
        "forbid_rot_holding_bonded": False,
        "expected_opt": 10,  # hand plan; see NOTES.md (solver confirms)
        "expected_opt_free": 3,  # solver-found+proven: glyphs under reagents
    },
}

# Element enum for calcification support (core2's elemental()/salt).
ELEMENTS = ["salt", "air", "earth", "fire", "water"]
ELEM_IDX = {e: i for i, e in enumerate(ELEMENTS)}
ELEMENTAL = [ELEM_IDX[e] for e in ("air", "earth", "fire", "water")]


def dir_component(o, table):
    """Nested-If lookup of DIRS[o][axis] for a z3 Int o in 0..5."""
    expr = z3.IntVal(table[5])
    for d in range(4, -1, -1):
        expr = z3.If(o == d, table[d], expr)
    return expr


class Encoder:
    """Builds the Int-based BMC encoding for one instance."""

    def __init__(self, inst, t_max=None, free_layout=False, radius=None):
        self.inst = inst
        self.T = t_max if t_max is not None else inst["t_max"]
        self.radius = radius if radius is not None else inst["radius"]
        self.free = free_layout
        self.cons = []  # all constraints except the goal
        self.n_arm = len(inst["arms"])
        self.n_atom = len(inst["atoms"])
        self.atom_names = [a["name"] for a in inst["atoms"]]
        self.pairs = [(i, j) for i in range(self.n_atom) for j in range(i + 1, self.n_atom)]
        self._build()

    # -- small helpers -----------------------------------------------------
    def on_board(self, q, r):
        rad = self.radius
        return z3.And(q >= -rad, q <= rad, r >= -rad, r <= rad, q + r >= -rad, q + r <= rad)

    def code(self, m, aname):
        return 1 + 4 * m + ARM_ACTIONS.index(aname)

    def is_act(self, t, m, aname):
        return self.act[t] == self.code(m, aname)

    def bond_var(self, i, j, t):
        if i == j:
            return z3.BoolVal(False)
        key = (min(i, j), max(i, j))
        return self.b[key][t] if key in self.b else z3.BoolVal(False)

    def held_any(self, i, t):
        return z3.Or([self.held[m][i][t] for m in range(self.n_arm)])

    def at_grip(self, i, m, t):
        return z3.And(self.q[i][t] == self.gq[m][t], self.r[i][t] == self.gr[m][t])

    # -- build -------------------------------------------------------------
    def _build(self):
        inst, T, C = self.inst, self.T, self.cons
        v2 = inst["semantics"] == "v2"
        n_arm, n_atom = self.n_arm, self.n_atom
        Int, Bool = z3.Int, z3.Bool

        # ---- layout variables ----
        self.baseq = [Int(f"baseq_{m}") for m in range(n_arm)]
        self.baser = [Int(f"baser_{m}") for m in range(n_arm)]
        self.glyphs = []  # list of (g1q, g1r, g2q, g2r) Int 4-tuples
        for gi, _ in enumerate(inst["glyph_bonds"]):
            self.glyphs.append(tuple(Int(f"gb{gi}_{k}") for k in ("q1", "r1", "q2", "r2")))
        self.calcs = []
        for gi, _ in enumerate(inst["glyph_calcs"]):
            self.calcs.append((Int(f"gc{gi}_q"), Int(f"gc{gi}_r")))

        # ---- state variables ----
        self.orient = [[Int(f"or_{m}_{t}") for t in range(T + 1)] for m in range(n_arm)]
        self.act = [Int(f"act_{t}") for t in range(T)]
        self.q = [[Int(f"q_{i}_{t}") for t in range(T + 1)] for i in range(n_atom)]
        self.r = [[Int(f"r_{i}_{t}") for t in range(T + 1)] for i in range(n_atom)]
        self.held = [
            [[Bool(f"held_{m}_{i}_{t}") for t in range(T + 1)] for i in range(n_atom)]
            for m in range(n_arm)
        ]
        # gripper positions as defined aux Ints (shared subterms)
        self.gq = [[Int(f"gq_{m}_{t}") for t in range(T + 1)] for m in range(n_arm)]
        self.gr = [[Int(f"gr_{m}_{t}") for t in range(T + 1)] for m in range(n_arm)]
        # bonds: only materialize if anything can ever be bonded
        need_bonds = bool(inst["init_bonds"] or inst["glyph_bonds"])
        self.b = {}
        if need_bonds:
            for i, j in self.pairs:
                self.b[(i, j)] = [Bool(f"b_{i}_{j}_{t}") for t in range(T + 1)]
        # element types (only when a calcification glyph is present)
        self.typ = None
        if inst["glyph_calcs"]:
            self.typ = [[Int(f"ty_{i}_{t}") for t in range(T + 1)] for i in range(n_atom)]
        # rigid components (v2): aux Bool comp[m][i][t]
        self.comp = None
        if v2:
            self.comp = [
                [[Bool(f"comp_{m}_{i}_{t}") for t in range(T + 1)] for i in range(n_atom)]
                for m in range(n_arm)
            ]

        # ---- layout constraints ----
        for m, arm in enumerate(inst["arms"]):
            if self.free:
                C.append(self.on_board(self.baseq[m], self.baser[m]))
                C.append(z3.And(self.orient[m][0] >= 0, self.orient[m][0] <= 5))
            else:
                C.append(self.baseq[m] == arm["base"][0])
                C.append(self.baser[m] == arm["base"][1])
                C.append(self.orient[m][0] == arm["init_orient"])
        if self.free:
            for m1 in range(n_arm):
                for m2 in range(m1 + 1, n_arm):
                    C.append(
                        z3.Or(self.baseq[m1] != self.baseq[m2], self.baser[m1] != self.baser[m2])
                    )
        for gi, ((q1, r1), (q2, r2)) in enumerate(inst["glyph_bonds"]):
            g = self.glyphs[gi]
            if self.free:
                C.append(self.on_board(g[0], g[1]))
                C.append(self.on_board(g[2], g[3]))
                C.append(z3.Or([z3.And(g[2] == g[0] + dq, g[3] == g[1] + dr) for (dq, dr) in DIRS]))
            else:
                C += [g[0] == q1, g[1] == r1, g[2] == q2, g[3] == r2]
        for gi, (q1, r1) in enumerate(inst["glyph_calcs"]):
            g = self.calcs[gi]
            if self.free:
                C.append(self.on_board(g[0], g[1]))
            else:
                C += [g[0] == q1, g[1] == r1]

        # ---- initial state ----
        for i, atom in enumerate(inst["atoms"]):
            C.append(self.q[i][0] == atom["pos"][0])
            C.append(self.r[i][0] == atom["pos"][1])
            if self.typ is not None:
                C.append(self.typ[i][0] == ELEM_IDX[atom.get("type", "salt")])
        for m in range(n_arm):
            for i in range(n_atom):
                C.append(z3.Not(self.held[m][i][0]))

        # ---- per-state invariants and definitions (t = 0..T) ----
        name2idx = {a["name"]: i for i, a in enumerate(inst["atoms"])}
        init_bond_set = {
            (min(name2idx[x], name2idx[y]), max(name2idx[x], name2idx[y]))
            for (x, y) in inst["init_bonds"]
        }

        def form(i, j, t):
            """Bond-formation trigger at state t (glyph_bond occupancy)."""
            disj = []
            for g in self.glyphs:
                a_on_1 = z3.And(self.q[i][t] == g[0], self.r[i][t] == g[1])
                b_on_2 = z3.And(self.q[j][t] == g[2], self.r[j][t] == g[3])
                a_on_2 = z3.And(self.q[i][t] == g[2], self.r[i][t] == g[3])
                b_on_1 = z3.And(self.q[j][t] == g[0], self.r[j][t] == g[1])
                disj.append(z3.Or(z3.And(a_on_1, b_on_2), z3.And(a_on_2, b_on_1)))
            return z3.Or(disj) if disj else z3.BoolVal(False)

        for t in range(T + 1):
            for m, arm in enumerate(inst["arms"]):
                C.append(z3.And(self.orient[m][t] >= 0, self.orient[m][t] <= 5))
                L = arm["length"]
                C.append(
                    self.gq[m][t]
                    == self.baseq[m] + L * dir_component(self.orient[m][t], [d[0] for d in DIRS])
                )
                C.append(
                    self.gr[m][t]
                    == self.baser[m] + L * dir_component(self.orient[m][t], [d[1] for d in DIRS])
                )
                C.append(self.on_board(self.gq[m][t], self.gr[m][t]))
            for i in range(n_atom):
                C.append(self.on_board(self.q[i][t], self.r[i][t]))
                if v2:  # arm bases block hexes (core2 only)
                    for m in range(n_arm):
                        C.append(
                            z3.Or(self.q[i][t] != self.baseq[m], self.r[i][t] != self.baser[m])
                        )
            for i, j in self.pairs:  # no two atoms share a hex
                C.append(z3.Or(self.q[i][t] != self.q[j][t], self.r[i][t] != self.r[j][t]))
            # at most one holder per atom (relevant for multi-arm)
            if n_arm > 1:
                for i in range(n_atom):
                    for m1 in range(n_arm):
                        for m2 in range(m1 + 1, n_arm):
                            C.append(z3.Not(z3.And(self.held[m1][i][t], self.held[m2][i][t])))
            # bonds: persistence + glyph formation (fires at every state,
            # even while held -- exactly as in the clingo rules)
            for i, j in self.pairs:
                if not self.b:
                    break
                base = z3.BoolVal((i, j) in init_bond_set) if t == 0 else self.b[(i, j)][t - 1]
                C.append(self.b[(i, j)][t] == z3.Or(base, form(i, j, t)))
            # v2 rigid components: comp = closure of bonds from held atoms
            if v2:
                assert self.comp is not None
                for m in range(n_arm):
                    cur = [self.held[m][i][t] for i in range(n_atom)]
                    for _ in range(max(0, n_atom - 1)):
                        cur = [
                            z3.Or(
                                [cur[i]]
                                + [
                                    z3.And(cur[j], self.bond_var(i, j, t))
                                    for j in range(n_atom)
                                    if j != i
                                ]
                            )
                            for i in range(n_atom)
                        ]
                    for i in range(n_atom):
                        C.append(self.comp[m][i][t] == cur[i])

        # ---- transitions (t = 0..T-1) ----
        for t in range(T):
            C.append(z3.And(self.act[t] >= 0, self.act[t] <= 4 * n_arm))
            for m in range(n_arm):
                cw = self.is_act(t, m, "rot_cw")
                ccw = self.is_act(t, m, "rot_ccw")
                grab = self.is_act(t, m, "grab")
                drop = self.is_act(t, m, "drop")
                o = self.orient[m][t]
                C.append(
                    self.orient[m][t + 1]
                    == z3.If(cw, z3.If(o == 5, 0, o + 1), z3.If(ccw, z3.If(o == 0, 5, o - 1), o))
                )
                # grab/drop legality
                armfull = z3.Or([self.held[m][i][t] for i in range(n_atom)])
                grabbable = z3.Or([self.at_grip(i, m, t) for i in range(n_atom)])
                C.append(z3.Implies(grab, z3.And(z3.Not(armfull), grabbable)))
                C.append(z3.Implies(drop, armfull))
                if v2 and n_arm > 1:
                    # can't grab an atom held by another arm
                    for i in range(n_atom):
                        C.append(
                            z3.Implies(
                                z3.And(grab, self.at_grip(i, m, t)), z3.Not(self.held_any(i, t))
                            )
                        )
                    # a rotation may not tear an atom from another arm
                    assert self.comp is not None
                    for i in range(n_atom):
                        others = z3.Or([self.held[m2][i][t] for m2 in range(n_arm) if m2 != m])
                        C.append(
                            z3.Implies(z3.And(z3.Or(cw, ccw), self.comp[m][i][t]), z3.Not(others))
                        )
                # held update
                for i in range(n_atom):
                    C.append(
                        self.held[m][i][t + 1]
                        == z3.Or(
                            z3.And(grab, self.at_grip(i, m, t)),
                            z3.And(self.held[m][i][t], z3.Not(drop)),
                        )
                    )
            # v1 phase-1 simplification (bond_instance.lp): no rotating
            # while holding an atom that is part of a bond
            if inst["forbid_rot_holding_bonded"] and self.b:
                for m in range(n_arm):
                    rot = z3.Or(self.is_act(t, m, "rot_cw"), self.is_act(t, m, "rot_ccw"))
                    for i in range(n_atom):
                        bondpart = z3.Or([self.bond_var(i, j, t) for j in range(n_atom) if j != i])
                        C.append(z3.Implies(rot, z3.Not(z3.And(self.held[m][i][t], bondpart))))
            # position updates
            for i in range(n_atom):
                if v2:
                    assert self.comp is not None
                    eq, er = self.q[i][t], self.r[i][t]
                    for m in range(n_arm):
                        BQ, BR = self.baseq[m], self.baser[m]
                        cw = z3.And(self.is_act(t, m, "rot_cw"), self.comp[m][i][t])
                        ccw = z3.And(self.is_act(t, m, "rot_ccw"), self.comp[m][i][t])
                        dq, dr = self.q[i][t] - BQ, self.r[i][t] - BR
                        eq = z3.If(cw, BQ - dr, z3.If(ccw, BQ + dq + dr, eq))
                        er = z3.If(cw, BR + dq + dr, z3.If(ccw, BR - dq, er))
                    C.append(self.q[i][t + 1] == eq)
                    C.append(self.r[i][t + 1] == er)
                else:
                    eq, er = self.q[i][t], self.r[i][t]
                    for m in range(n_arm):
                        h = self.held[m][i][t + 1]
                        eq = z3.If(h, self.gq[m][t + 1], eq)
                        er = z3.If(h, self.gr[m][t + 1], er)
                    C.append(self.q[i][t + 1] == eq)
                    C.append(self.r[i][t + 1] == er)
            # calcification (core2): elemental atom on the glyph -> salt
            if self.typ is not None:
                for i in range(n_atom):
                    on_calc = z3.Or(
                        [z3.And(self.q[i][t] == g[0], self.r[i][t] == g[1]) for g in self.calcs]
                    )
                    elemental = z3.Or([self.typ[i][t] == e for e in ELEMENTAL])
                    C.append(
                        self.typ[i][t + 1]
                        == z3.If(z3.And(on_calc, elemental), ELEM_IDX["salt"], self.typ[i][t])
                    )

        # cost = number of non-wait instructions over the full horizon
        self.cost = z3.Int("cost")
        C.append(self.cost == z3.Sum([z3.If(self.act[t] != 0, 1, 0) for t in range(T)]))

    def goal(self, h):
        """Goal formula evaluated at state h (h = T for the standard goal)."""
        inst = self.inst
        name2idx = {a["name"]: i for i, a in enumerate(inst["atoms"])}
        conj = []
        for name, (tq, tr) in inst["products"]:
            i = name2idx[name]
            conj += [self.q[i][h] == tq, self.r[i][h] == tr, z3.Not(self.held_any(i, h))]
        if inst["require_end_bond"]:
            conj.append(z3.Or([self.b[p][h] for p in self.pairs if p in self.b]))
        # goal-of-record salt requirements (used in later phases)
        for name, ty in inst.get("product_types", []):
            assert self.typ is not None
            i = name2idx[name]
            conj.append(self.typ[i][h] == ELEM_IDX[ty])
        # anonymous product slots: some injective assignment of atoms to
        # slots puts an atom of the right element, unheld, on each slot hex
        # (the OM product is a molecule pattern, not named atoms)
        slots = inst.get("product_slots", [])
        if slots:
            import itertools

            assigns = []
            for perm in itertools.permutations(range(self.n_atom), len(slots)):
                terms = []
                for si, ((tq, tr), ty) in enumerate(slots):
                    i = perm[si]
                    terms += [self.q[i][h] == tq, self.r[i][h] == tr, z3.Not(self.held_any(i, h))]
                    if self.typ is not None:
                        terms.append(self.typ[i][h] == ELEM_IDX[ty])
                assigns.append(z3.And(terms))
            conj.append(z3.Or(assigns))
        return z3.And(conj)


# ---------------------------------------------------------------------------
# Solve strategies
# ---------------------------------------------------------------------------


def solve_optimize(enc):
    """Z3 Optimize: minimize non-wait count at the full horizon (matches
    clingo's global #minimize)."""
    opt = z3.Optimize()
    opt.add(enc.cons)
    opt.add(enc.goal(enc.T))
    opt.minimize(enc.cost)
    t0 = time.perf_counter()
    res = opt.check()
    wall = time.perf_counter() - t0
    if res == z3.sat:
        mdl = opt.model()
        return {
            "status": "sat",
            "cost": mdl.eval(enc.cost).as_long(),
            "model": mdl,
            "time": wall,
            "horizon": enc.T,
        }
    return {"status": str(res), "cost": None, "model": None, "time": wall, "horizon": enc.T}


def solve_ramp_cost(enc):
    """Plain Solver, incremental cost ramp-up: check cost<=k for k=0,1,...
    First SAT k is the proven optimum (all k'<k were UNSAT)."""
    s = z3.Solver()
    s.add(enc.cons)
    s.add(enc.goal(enc.T))
    t0 = time.perf_counter()
    for k in range(enc.T + 1):
        guard = z3.Bool(f"__costle_{k}")
        s.add(z3.Implies(guard, enc.cost <= k))
        if s.check(guard) == z3.sat:
            wall = time.perf_counter() - t0
            mdl = s.model()
            return {
                "status": "sat",
                "cost": mdl.eval(enc.cost).as_long(),
                "model": mdl,
                "time": wall,
                "horizon": enc.T,
            }
    return {
        "status": "unsat",
        "cost": None,
        "model": None,
        "time": time.perf_counter() - t0,
        "horizon": enc.T,
    }


def solve_descend_cost(enc):
    """Incremental descending cost bound: get any SAT plan, then repeatedly
    demand cost <= (best-1) until UNSAT.  Only ONE hard UNSAT proof (at
    opt-1) instead of ramp-cost's opt-many; monotone strengthening, so no
    push/pop needed."""
    s = z3.Solver()
    s.add(enc.cons)
    s.add(enc.goal(enc.T))
    t0 = time.perf_counter()
    best = None
    while s.check() == z3.sat:
        mdl = s.model()
        best = (mdl.eval(enc.cost).as_long(), mdl)
        s.add(enc.cost <= best[0] - 1)
    wall = time.perf_counter() - t0
    if best is None:
        return {"status": "unsat", "cost": None, "model": None, "time": wall, "horizon": enc.T}
    return {"status": "sat", "cost": best[0], "model": best[1], "time": wall, "horizon": enc.T}


def solve_oneshot_sat(enc):
    """Single satisfiability check at the full horizon (no optimality)."""
    s = z3.Solver()
    s.add(enc.cons)
    s.add(enc.goal(enc.T))
    t0 = time.perf_counter()
    res = s.check()
    wall = time.perf_counter() - t0
    if res == z3.sat:
        mdl = s.model()
        return {
            "status": "sat",
            "cost": mdl.eval(enc.cost).as_long(),
            "model": mdl,
            "time": wall,
            "horizon": enc.T,
        }
    return {"status": str(res), "cost": None, "model": None, "time": wall, "horizon": enc.T}


def solve_ramp_horizon(enc):
    """Incremental horizon ramp-up over ONE unrolled encoding: assert the
    goal at state h via assumption literals for h=1..T; stop at first SAT.
    NOTE: min horizon is NOT necessarily min instruction count; the reported
    cost is the non-wait count within the first h steps of the found plan
    (not minimized)."""
    s = z3.Solver()
    s.add(enc.cons)
    t0 = time.perf_counter()
    for h in range(1, enc.T + 1):
        guard = z3.Bool(f"__goal_at_{h}")
        s.add(z3.Implies(guard, enc.goal(h)))
        if s.check(guard) == z3.sat:
            wall = time.perf_counter() - t0
            mdl = s.model()
            cost = sum(1 for t in range(h) if mdl.eval(enc.act[t]).as_long() != 0)
            return {"status": "sat", "cost": cost, "model": mdl, "time": wall, "horizon": h}
    return {
        "status": "unsat",
        "cost": None,
        "model": None,
        "time": time.perf_counter() - t0,
        "horizon": None,
    }


STRATEGIES = {
    "optimize": solve_optimize,
    "ramp-cost": solve_ramp_cost,
    "descend-cost": solve_descend_cost,
    "oneshot": solve_oneshot_sat,
    "ramp-horizon": solve_ramp_horizon,
}


# ---------------------------------------------------------------------------
# Model extraction / printing / JSON dump
# ---------------------------------------------------------------------------


def decode_action(code, arms):
    if code == 0:
        return ("wait", None)
    m, a = divmod(code - 1, 4)
    return (ARM_ACTIONS[a], arms[m]["name"])


def extract_solution(enc, result):
    mdl = result["model"]
    inst = enc.inst
    h = result["horizon"]

    def ev(e):
        return mdl.eval(e, model_completion=True)

    layout = {
        "arms": [
            {
                "name": arm["name"],
                "base": [ev(enc.baseq[m]).as_long(), ev(enc.baser[m]).as_long()],
                "length": arm["length"],
                "init_orient": ev(enc.orient[m][0]).as_long(),
            }
            for m, arm in enumerate(inst["arms"])
        ],
        "glyph_bonds": [
            [ev(g[0]).as_long(), ev(g[1]).as_long(), ev(g[2]).as_long(), ev(g[3]).as_long()]
            for g in enc.glyphs
        ],
        "glyph_calcs": [[ev(g[0]).as_long(), ev(g[1]).as_long()] for g in enc.calcs],
    }
    actions = []
    for t in range(h):
        aname, arm = decode_action(ev(enc.act[t]).as_long(), inst["arms"])
        actions.append({"t": t, "action": aname, "arm": arm})
    traj = {}
    for i, name in enumerate(enc.atom_names):
        traj[name] = [[ev(enc.q[i][t]).as_long(), ev(enc.r[i][t]).as_long()] for t in range(h + 1)]
    orient = {
        arm["name"]: [ev(enc.orient[m][t]).as_long() for t in range(h + 1)]
        for m, arm in enumerate(inst["arms"])
    }
    held = {}
    for i, name in enumerate(enc.atom_names):
        held[name] = [
            next(
                (
                    inst["arms"][m]["name"]
                    for m in range(enc.n_arm)
                    if z3.is_true(ev(enc.held[m][i][t]))
                ),
                None,
            )
            for t in range(h + 1)
        ]
    bonds = []
    for (i, j), row in enc.b.items():
        bonds.append(
            {
                "atoms": [enc.atom_names[i], enc.atom_names[j]],
                "bonded": [z3.is_true(ev(row[t])) for t in range(h + 1)],
            }
        )
    types = None
    if enc.typ is not None:
        types = {
            name: [ELEMENTS[ev(enc.typ[i][t]).as_long()] for t in range(h + 1)]
            for i, name in enumerate(enc.atom_names)
        }
    return {
        "layout": layout,
        "horizon": h,
        "cost": result["cost"],
        "actions": actions,
        "atom_trajectories": traj,
        "orientations": orient,
        "held": held,
        "bonds": bonds,
        "atom_types": types,
    }


def print_plan(sol, name=""):
    lay = sol["layout"]
    print(f"=== plan {name}: cost={sol['cost']} horizon={sol['horizon']} ===")
    for arm in lay["arms"]:
        print(
            f"  arm {arm['name']}: base=({arm['base'][0]},{arm['base'][1]})"
            f" len={arm['length']} init_orient={arm['init_orient']}"
        )
    for g in lay["glyph_bonds"]:
        print(f"  glyph_bond: ({g[0]},{g[1]}) -- ({g[2]},{g[3]})")
    for g in lay["glyph_calcs"]:
        print(f"  glyph_calc: ({g[0]},{g[1]})")
    for a in sol["actions"]:
        who = f" [{a['arm']}]" if a["arm"] else ""
        atoms = "  ".join(
            f"{n}@({sol['atom_trajectories'][n][a['t']][0]},"
            f"{sol['atom_trajectories'][n][a['t']][1]})"
            f"{'*' if sol['held'][n][a['t']] else ''}"
            for n in sol["atom_trajectories"]
        )
        print(f"  t={a['t']:2d}  {a['action']:<8}{who:<6} {atoms}")
    h = sol["horizon"]
    final = "  ".join(
        f"{n}@({sol['atom_trajectories'][n][h][0]},"
        f"{sol['atom_trajectories'][n][h][1]})"
        f"{'*' if sol['held'][n][h] else ''}"
        for n in sol["atom_trajectories"]
    )
    print(f"  t={h:2d}  (final)         {final}   (* = held)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("instance", choices=sorted(INSTANCES))
    ap.add_argument("--free", action="store_true", help="free-layout mode")
    ap.add_argument("--strategy", choices=sorted(STRATEGIES), default="optimize")
    ap.add_argument("--tmax", type=int, default=None)
    ap.add_argument("--radius", type=int, default=None)
    ap.add_argument("--json", metavar="PATH", default=None, help="dump solution JSON here")
    args = ap.parse_args()

    inst = INSTANCES[args.instance]
    t0 = time.perf_counter()
    enc = Encoder(inst, t_max=args.tmax, free_layout=args.free, radius=args.radius)
    build_time = time.perf_counter() - t0
    result = STRATEGIES[args.strategy](enc)
    print(
        f"instance={args.instance} mode={'free' if args.free else 'fixed'} "
        f"strategy={args.strategy} t_max={enc.T}"
    )
    print(
        f"status={result['status']} cost={result['cost']} "
        f"build={build_time:.3f}s solve={result['time']:.3f}s "
        f"(expected optimum, fixed layout: {inst['expected_opt']})"
    )
    if result["status"] == "sat":
        sol = extract_solution(enc, result)
        print_plan(sol, args.instance)
        if args.json:
            os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
            meta = {
                "instance": args.instance,
                "mode": "free" if args.free else "fixed",
                "strategy": args.strategy,
                "t_max": enc.T,
                "radius": enc.radius,
                "solver": "z3-" + z3.get_version_string(),
                "solve_time_s": round(result["time"], 4),
            }
            with open(args.json, "w") as f:
                json.dump(dict(meta=meta, **sol), f, indent=1)
            print(f"wrote {args.json}")


if __name__ == "__main__":
    main()
