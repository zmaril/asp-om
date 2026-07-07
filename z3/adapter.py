#!/usr/bin/env python3
"""Z3 adapter for the multi-solver Opus Magnum harness.

Harness contract (harness/README.md, harness/SPEC.md):

    python3 z3/adapter.py <puzzle.json> [--out FILE]
        [--strategy descend-cost|ramp-cost|oneshot] [--time-limit S]

Reads the common puzzle JSON, builds a Z3 bounded-model-checking
instance implementing the harness world semantics EXACTLY (the canonical
executable spec is harness/validate.py), solves it, and writes the
common plan JSON to stdout.  Exit 0 = solved (stdout has the plan),
1 = no plan found (UNSAT or time limit hit before any model), 2 =
malformed/unsupported puzzle.  All logs go to stderr.

Environment: HARNESS_Z3_TIME_LIMIT overrides the default time limit
(seconds, default 60).  The default strategy is descend-cost (find any
plan, then tighten the cost bound until UNSAT); when the limit expires
mid-descent the best plan found so far is returned (then optimality is
not proven -- stderr says which).

Encoding note: this is the Int encoding (coordinates / orientation /
action as Z3 Ints), extended from z3/om_solver.py to the harness
semantics.  The faster bool one-hot encoding (z3/om_bool.py) only
supports FIXED layout, and every harness puzzle requires free layout
(solver-placed arms, inputs, outputs and glyphs, with disjoint part
footprints) plus pool-based input respawn, so the Int encoding is used
throughout.  Differences vs the pre-harness z3 encodings are documented
in z3/NOTES.md ("Harness conformance").

Semantics implemented (mirrors harness/validate.py):
  * axial hex board |q|,|r|,|q+r| <= board_radius; clockwise dir table
    0..5 = (1,0),(0,1),(-1,1),(-1,0),(0,-1),(1,-1); rot_cw about origin
    (q,r) -> (-r, q+r);
  * placements are solver decisions unless pinned by the puzzle; the
    footprints of ALL parts (arm bases, input hexes, output hexes,
    calcifier hexes, bonder hexes) are pairwise disjoint and on board;
  * states t = 0..t_max, at most one instruction per timestep across
    all arms; grab/drop/rot_cw/rot_ccw with rigid rotation of the held
    bond-connected component, no tearing, endpoint-only collision;
  * no atom ever rests on an arm base; grippers stay on board;
  * calcification reads positions at t, retypes at t+1; input copy
    spawning is MANDATORY at t+1 whenever copies remain and the input
    hexes are free at t+1; bonders fire on t+1 positions (and at t=0);
    copy 1 of every input spawns at t=0; bonds persist;
  * goal: every product is complete at SOME state t <= t_max (latched):
    exact element per output hex, unheld atoms, exactly the product's
    bonds (total bond degree equality).
"""
import argparse
import itertools
import json
import os
import sys
import time

import z3

DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]
ELEMENTS = ["salt", "air", "earth", "fire", "water"]
ELEM_IDX = {e: i for i, e in enumerate(ELEMENTS)}
ELEMENTAL = ("air", "earth", "fire", "water")
ARM_ACTIONS = ["rot_cw", "rot_ccw", "grab", "drop"]  # code 1+4*m+idx; 0=wait


def log(*a):
    print("adapter:", *a, file=sys.stderr, flush=True)


def die(msg, code=2):
    log("error:", msg)
    sys.exit(code)


def rot_k(q, r, k):
    for _ in range(k % 6):
        q, r = -r, q + r
    return (q, r)


def sel(var, pairs):
    """Nested-If lookup: pairs = [(int_value, expr)] over a z3 Int var."""
    e = pairs[-1][1]
    for v, x in reversed(pairs[:-1]):
        e = z3.If(var == v, x, e)
    return e


def molecule(m):
    atoms = [(a["element"], tuple(a["pos"])) for a in m["atoms"]]
    bonds = sorted({tuple(sorted(b)) for b in m.get("bonds", [])})
    return atoms, bonds


def distinct_rotations(atoms, bonds, translation_free):
    """Rotation indices giving geometrically distinct placements.
    If the position is also free (translation_free), dedupe up to
    translation; if the position is pinned, dedupe on exact cells."""
    keep, seen = [], set()
    for d in range(6):
        cells = [rot_k(q, r, d) for _, (q, r) in atoms]
        if translation_free:
            aq, ar = min(cells)
        else:
            aq, ar = 0, 0
        norm = frozenset(((c[0] - aq, c[1] - ar), el)
                         for (el, _), c in zip(atoms, cells))
        nbonds = frozenset(
            frozenset(((cells[i][0] - aq, cells[i][1] - ar),
                       (cells[j][0] - aq, cells[j][1] - ar)))
            for i, j in bonds)
        key = (norm, nbonds)
        if key not in seen:
            seen.add(key)
            keep.append(d)
    return keep


class HarnessEncoder:
    """Z3 Int-encoding of one harness puzzle (free or pinned layout)."""

    def __init__(self, puzzle):
        self.pz = puzzle
        self.radius = puzzle["board_radius"]
        self.T = puzzle["t_max"]
        self.cons = []
        self._parts()
        self._atoms()
        self._layout()
        self._dynamics()
        self._goal()

    # ------------------------------------------------------------------
    def on_board(self, q, r):
        rad = self.radius
        return z3.And(q >= -rad, q <= rad, r >= -rad, r <= rad,
                      q + r >= -rad, q + r <= rad)

    def _parts(self):
        pz = self.pz
        self.arms = [p for p in pz["parts"] if p["type"] == "arm"]
        self.calcs = [p for p in pz["parts"] if p["type"] == "calcifier"]
        self.bonders = [p for p in pz["parts"] if p["type"] == "bonder"]
        known = {"arm", "calcifier", "bonder"}
        for p in pz["parts"]:
            if p["type"] not in known:
                die(f"unsupported part type {p['type']!r}")
        for m in pz["reagents"] + pz["products"]:
            for el, _ in molecule(m)[0]:
                if el not in ELEM_IDX:
                    die(f"unsupported element {el!r}")
        self.n_arm = len(self.arms)
        if self.n_arm < 1:
            die("puzzle has no arm; nothing can move")

    def _atoms(self):
        """Global atom table: one entry per (reagent, copy, molecule atom)."""
        self.atoms = []   # dicts: rid, copy, aidx, element
        self.copies = []  # (rid, copy, [global atom indices])
        for m in self.pz["reagents"]:
            ratoms, _ = molecule(m)
            for c in range(1, m["pool"] + 1):
                idxs = []
                for a, (el, _) in enumerate(ratoms):
                    idxs.append(len(self.atoms))
                    self.atoms.append(dict(rid=m["id"], copy=c, aidx=a,
                                           element=el))
                self.copies.append((m["id"], c, idxs))
        self.n_atom = len(self.atoms)
        self.pairs = [(i, j) for i in range(self.n_atom)
                      for j in range(i + 1, self.n_atom)]

    # ------------------------------------------------------------------
    def _layout(self):
        pz, C, Int = self.pz, self.cons, z3.Int
        nothing_pinned = not any(
            "position" in x for x in
            pz["parts"] + pz["reagents"] + pz["products"])

        def pos_vars(tag, spec):
            q, r = Int(f"{tag}_q"), Int(f"{tag}_r")
            if "position" in spec:
                C.append(q == spec["position"][0])
                C.append(r == spec["position"][1])
            return q, r

        # arms -----------------------------------------------------------
        self.baseq, self.baser, self.orient0 = [], [], []
        for m, p in enumerate(self.arms):
            q, r = pos_vars(f"arm{m}", p)
            o = Int(f"arm{m}_rot")
            C.append(z3.And(o >= 0, o <= 5))
            if "rotation" in p:
                C.append(o == p["rotation"] % 6)
            self.baseq.append(q)
            self.baser.append(r)
            self.orient0.append(o)
        # global-rotation symmetry breaking: if nothing at all is pinned,
        # the whole board is C6-symmetric about the origin, so WLOG the
        # first arm's base lies in a fundamental domain of that action.
        if nothing_pinned:
            reps = sorted({min(rot_k(q, r, k) for k in range(6))
                           for q in range(-self.radius, self.radius + 1)
                           for r in range(-self.radius, self.radius + 1)
                           if abs(q + r) <= self.radius})
            C.append(z3.Or([z3.And(self.baseq[0] == q, self.baser[0] == r)
                            for q, r in reps]))

        # calcifiers -------------------------------------------------------
        self.calc_hex = []
        for i, p in enumerate(self.calcs):
            self.calc_hex.append(pos_vars(f"calc{i}", p))

        # bonders ----------------------------------------------------------
        self.bonder_hex = []  # ((q1,r1),(q2,r2), rot_var)
        for i, p in enumerate(self.bonders):
            q1, r1 = pos_vars(f"bonder{i}", p)
            rot = Int(f"bonder{i}_rot")
            if "position" in p:
                C.append(rot == p.get("rotation", 0) % 6)
            else:
                # (pos,k) == (pos+dir[k], k+3): WLOG k in 0..2 when free
                C.append(z3.And(rot >= 0, rot <= 2))
            q2 = Int(f"bonder{i}_q2")
            r2 = Int(f"bonder{i}_r2")
            C.append(q2 == q1 + sel(rot, [(d, z3.IntVal(DIRS[d][0]))
                                          for d in range(6)]))
            C.append(r2 == r1 + sel(rot, [(d, z3.IntVal(DIRS[d][1]))
                                          for d in range(6)]))
            self.bonder_hex.append(((q1, r1), (q2, r2), rot))

        # inputs / outputs -------------------------------------------------
        def place_molecule(tag, spec):
            """Returns (q, r, rot_var, allowed_rots, hexes) where hexes[a]
            is the (q,r) expr pair of molecule atom a on the board."""
            atoms, bonds = molecule(spec)
            q, r = pos_vars(tag, spec)
            rot = Int(f"{tag}_rot")
            if "rotation" in spec:
                allowed = [spec["rotation"] % 6]
            else:
                allowed = distinct_rotations(atoms, bonds,
                                             "position" not in spec)
            C.append(z3.Or([rot == d for d in allowed]))
            hexes = []
            for a, (_, (oq, orr)) in enumerate(atoms):
                offs = {d: rot_k(oq, orr, d) for d in allowed}
                hq = q + sel(rot, [(d, z3.IntVal(offs[d][0]))
                                   for d in allowed])
                hr = r + sel(rot, [(d, z3.IntVal(offs[d][1]))
                                   for d in allowed])
                hexes.append((hq, hr))
            return dict(q=q, r=r, rot=rot, hexes=hexes)

        self.inputs = {m["id"]: place_molecule(f"in_{m['id']}", m)
                       for m in pz["reagents"]}
        self.outputs = {m["id"]: place_molecule(f"out_{m['id']}", m)
                        for m in pz["products"]}

        # symmetry breaking: interchangeable unpinned reagents (identical
        # molecule + pool) may WLOG be ordered by input position.
        groups = {}
        for m in pz["reagents"]:
            if "position" in m or "rotation" in m:
                continue
            key = (json.dumps(molecule(m), sort_keys=True), m["pool"])
            groups.setdefault(key, []).append(m["id"])
        for ids in groups.values():
            for a, b in zip(ids, ids[1:]):
                qa, ra = self.inputs[a]["q"], self.inputs[a]["r"]
                qb, rb = self.inputs[b]["q"], self.inputs[b]["r"]
                C.append(z3.Or(qa < qb, z3.And(qa == qb, ra <= rb)))

        # footprints: on board + pairwise disjoint across parts ------------
        feet = []  # (owner_key, hex expr)
        for m in range(self.n_arm):
            feet.append((("arm", m), (self.baseq[m], self.baser[m])))
        for rid, ip in self.inputs.items():
            for h in ip["hexes"]:
                feet.append((("in", rid), h))
        for pid, op in self.outputs.items():
            for h in op["hexes"]:
                feet.append((("out", pid), h))
        for i, h in enumerate(self.calc_hex):
            feet.append((("calc", i), h))
        for i, (h1, h2, _) in enumerate(self.bonder_hex):
            feet.append((("bonder", i), h1))
            feet.append((("bonder", i), h2))
        for _, (q, r) in feet:
            C.append(self.on_board(q, r))
        for a in range(len(feet)):
            for b in range(a + 1, len(feet)):
                if feet[a][0] != feet[b][0]:
                    C.append(z3.Or(feet[a][1][0] != feet[b][1][0],
                                   feet[a][1][1] != feet[b][1][1]))

    # ------------------------------------------------------------------
    def _dynamics(self):
        C, T = self.cons, self.T
        Int, Bool = z3.Int, z3.Bool
        n_arm, n_atom = self.n_arm, self.n_atom

        # state variables ---------------------------------------------------
        self.orient = [[Int(f"or_{m}_{t}") for t in range(T + 1)]
                       for m in range(n_arm)]
        self.act = [Int(f"act_{t}") for t in range(T)]
        self.q = [[Int(f"q_{i}_{t}") for t in range(T + 1)]
                  for i in range(n_atom)]
        self.r = [[Int(f"r_{i}_{t}") for t in range(T + 1)]
                  for i in range(n_atom)]
        self.held = [[[Bool(f"held_{m}_{i}_{t}") for t in range(T + 1)]
                      for i in range(n_atom)] for m in range(n_arm)]
        self.gq = [[Int(f"gq_{m}_{t}") for t in range(T + 1)]
                   for m in range(n_arm)]
        self.gr = [[Int(f"gr_{m}_{t}") for t in range(T + 1)]
                   for m in range(n_arm)]
        # per-copy active (spawned) flags; copy 1 is always active
        self.active = {}
        for rid, c, idxs in self.copies:
            if c == 1:
                self.active[(rid, c)] = [z3.BoolVal(True)] * (T + 1)
            else:
                self.active[(rid, c)] = [Bool(f"act_{rid}_{c}_{t}")
                                         for t in range(T + 1)]
        self.atom_active = [self.active[(a["rid"], a["copy"])]
                            for a in self.atoms]
        # bonds: needed iff any bonder or any reagent internal bond exists
        internal = set()
        for rid, c, idxs in self.copies:
            m = next(m for m in self.pz["reagents"] if m["id"] == rid)
            for i, j in molecule(m)[1]:
                internal.add((min(idxs[i], idxs[j]), max(idxs[i], idxs[j])))
        self.b = {}
        if self.bonder_hex or internal:
            for p in self.pairs:
                self.b[p] = [Bool(f"b_{p[0]}_{p[1]}_{t}")
                             for t in range(T + 1)]
        # element types: dynamic only when a calcifier exists
        self.typ = None
        if self.calc_hex:
            self.typ = [[Int(f"ty_{i}_{t}") for t in range(T + 1)]
                        for i in range(n_atom)]
        # rigid components
        self.comp = [[[Bool(f"comp_{m}_{i}_{t}") for t in range(T + 1)]
                      for i in range(n_atom)] for m in range(n_arm)]

        def bond_var(i, j, t):
            if i == j:
                return z3.BoolVal(False)
            key = (min(i, j), max(i, j))
            return self.b[key][t] if key in self.b else z3.BoolVal(False)
        self.bond_var = bond_var

        def spawn_hex(i):
            a = self.atoms[i]
            return self.inputs[a["rid"]]["hexes"][a["aidx"]]

        # initial state ------------------------------------------------------
        for i in range(n_atom):
            hq, hr = spawn_hex(i)
            C.append(self.q[i][0] == hq)
            C.append(self.r[i][0] == hr)
            if self.typ is not None:
                C.append(self.typ[i][0] == ELEM_IDX[self.atoms[i]["element"]])
        for m in range(n_arm):
            C.append(self.orient[m][0] == self.orient0[m])
            for i in range(n_atom):
                C.append(z3.Not(self.held[m][i][0]))
        for rid, c, _ in self.copies:
            if c > 1:
                C.append(z3.Not(self.active[(rid, c)][0]))

        # per-state invariants and definitions (t = 0..T) ---------------------
        def form(i, j, t):
            disj = []
            act_ij = z3.And(self.atom_active[i][t], self.atom_active[j][t])
            for (h1, h2, _) in self.bonder_hex:
                on = lambda k, h: z3.And(self.q[k][t] == h[0],
                                         self.r[k][t] == h[1])
                disj.append(z3.Or(z3.And(on(i, h1), on(j, h2)),
                                  z3.And(on(i, h2), on(j, h1))))
            return z3.And(act_ij, z3.Or(disj)) if disj else z3.BoolVal(False)

        for t in range(T + 1):
            for m, arm in enumerate(self.arms):
                C.append(z3.And(self.orient[m][t] >= 0,
                                self.orient[m][t] <= 5))
                L = arm["length"]
                C.append(self.gq[m][t] == self.baseq[m]
                         + L * sel(self.orient[m][t],
                                   [(d, z3.IntVal(DIRS[d][0]))
                                    for d in range(6)]))
                C.append(self.gr[m][t] == self.baser[m]
                         + L * sel(self.orient[m][t],
                                   [(d, z3.IntVal(DIRS[d][1]))
                                    for d in range(6)]))
                C.append(self.on_board(self.gq[m][t], self.gr[m][t]))
            for i in range(n_atom):
                act_i = self.atom_active[i][t]
                C.append(z3.Implies(act_i, self.on_board(self.q[i][t],
                                                         self.r[i][t])))
                for m in range(n_arm):  # no atom on any arm base, ever
                    C.append(z3.Implies(act_i,
                                        z3.Or(self.q[i][t] != self.baseq[m],
                                              self.r[i][t] != self.baser[m])))
                    C.append(z3.Implies(self.held[m][i][t], act_i))
            for (i, j) in self.pairs:  # endpoint collision freedom
                C.append(z3.Implies(
                    z3.And(self.atom_active[i][t], self.atom_active[j][t]),
                    z3.Or(self.q[i][t] != self.q[j][t],
                          self.r[i][t] != self.r[j][t])))
            if n_arm > 1:  # at most one holder per atom
                for i in range(n_atom):
                    for m1 in range(n_arm):
                        for m2 in range(m1 + 1, n_arm):
                            C.append(z3.Not(z3.And(self.held[m1][i][t],
                                                   self.held[m2][i][t])))
            # bonds: internal-at-spawn + bonder formation + persistence
            for (i, j) in self.pairs:
                if (i, j) not in self.b:
                    continue
                parts = [form(i, j, t)]
                if t > 0:
                    parts.append(self.b[(i, j)][t - 1])
                if (i, j) in internal:
                    parts.append(self.atom_active[i][t])  # same copy
                C.append(self.b[(i, j)][t] == z3.Or(parts))
            # rigid components: closure of bonds from each arm's held atom
            for m in range(n_arm):
                cur = [self.held[m][i][t] for i in range(n_atom)]
                for _ in range(max(0, n_atom - 1)):
                    cur = [z3.Or([cur[i]] +
                                 [z3.And(cur[j], bond_var(i, j, t))
                                  for j in range(n_atom) if j != i])
                           for i in range(n_atom)]
                for i in range(n_atom):
                    C.append(self.comp[m][i][t] == cur[i])

        # transitions (t = 0..T-1) --------------------------------------------
        def is_act(t, m, name):
            return self.act[t] == 1 + 4 * m + ARM_ACTIONS.index(name)

        for t in range(T):
            C.append(z3.And(self.act[t] >= 0, self.act[t] <= 4 * n_arm))
            for m in range(n_arm):
                cw, ccw = is_act(t, m, "rot_cw"), is_act(t, m, "rot_ccw")
                grab, drop = is_act(t, m, "grab"), is_act(t, m, "drop")
                o = self.orient[m][t]
                C.append(self.orient[m][t + 1] ==
                         z3.If(cw, z3.If(o == 5, 0, o + 1),
                               z3.If(ccw, z3.If(o == 0, 5, o - 1), o)))
                at_grip = lambda i: z3.And(self.q[i][t] == self.gq[m][t],
                                           self.r[i][t] == self.gr[m][t],
                                           self.atom_active[i][t])
                held_other = lambda i: z3.Or(
                    [self.held[m2][i][t] for m2 in range(n_arm) if m2 != m]
                    or [z3.BoolVal(False)])
                armfull = z3.Or([self.held[m][i][t] for i in range(n_atom)])
                C.append(z3.Implies(grab, z3.And(
                    z3.Not(armfull),
                    z3.Or([z3.And(at_grip(i), z3.Not(held_other(i)))
                           for i in range(n_atom)]))))
                C.append(z3.Implies(drop, armfull))
                for i in range(n_atom):
                    # cannot grab an atom held by another arm
                    if n_arm > 1:
                        C.append(z3.Implies(z3.And(grab, at_grip(i)),
                                            z3.Not(held_other(i))))
                        # no tearing: rotating may not move another arm's atom
                        C.append(z3.Implies(
                            z3.And(z3.Or(cw, ccw), self.comp[m][i][t]),
                            z3.Not(held_other(i))))
                    C.append(self.held[m][i][t + 1] == z3.Or(
                        z3.And(grab, at_grip(i)),
                        z3.And(self.held[m][i][t], z3.Not(drop))))
            # positions: rigid rotation of held components; spawn parking
            for i in range(n_atom):
                eq, er = self.q[i][t], self.r[i][t]
                for m in range(n_arm):
                    BQ, BR = self.baseq[m], self.baser[m]
                    cw = z3.And(is_act(t, m, "rot_cw"), self.comp[m][i][t])
                    ccw = z3.And(is_act(t, m, "rot_ccw"), self.comp[m][i][t])
                    dq, dr = self.q[i][t] - BQ, self.r[i][t] - BR
                    eq = z3.If(cw, BQ - dr, z3.If(ccw, BQ + dq + dr, eq))
                    er = z3.If(cw, BR + dq + dr, z3.If(ccw, BR - dq, er))
                hq, hr = spawn_hex(i)
                C.append(self.q[i][t + 1] ==
                         z3.If(self.atom_active[i][t], eq, hq))
                C.append(self.r[i][t + 1] ==
                         z3.If(self.atom_active[i][t], er, hr))
            # calcification: on-glyph at t (pre-motion) => salt at t+1
            if self.typ is not None:
                for i in range(n_atom):
                    on_calc = z3.Or([z3.And(self.q[i][t] == h[0],
                                            self.r[i][t] == h[1])
                                     for h in self.calc_hex])
                    elem = z3.Or([self.typ[i][t] == ELEM_IDX[e]
                                  for e in ELEMENTAL])
                    C.append(self.typ[i][t + 1] == z3.If(
                        z3.And(self.atom_active[i][t], on_calc, elem),
                        ELEM_IDX["salt"], self.typ[i][t]))
            # spawning: MANDATORY next copy when hexes free at t+1
            for rid, c, _ in self.copies:
                if c == 1:
                    continue
                hexes = self.inputs[rid]["hexes"]
                free = z3.And([z3.Implies(
                    self.atom_active[j][t],
                    z3.And([z3.Or(self.q[j][t + 1] != hq,
                                  self.r[j][t + 1] != hr)
                            for hq, hr in hexes]))
                    for j in range(n_atom)])
                C.append(self.active[(rid, c)][t + 1] == z3.Or(
                    self.active[(rid, c)][t],
                    z3.And(self.active[(rid, c - 1)][t], free)))

        # cost ---------------------------------------------------------------
        self.cost = Int("cost")
        C.append(self.cost == z3.Sum([z3.If(self.act[t] != 0, 1, 0)
                                      for t in range(T)]))

    # ------------------------------------------------------------------
    def _goal(self):
        """Latched exact-molecule completion per product; goal = all done."""
        C, T = self.cons, self.T
        held_any = lambda i, t: z3.Or(
            [self.held[m][i][t] for m in range(self.n_arm)])

        def feasible(i, el):
            ai = self.atoms[i]["element"]
            if ai == el:
                return True
            return bool(self.calc_hex) and el == "salt" and ai in ELEMENTAL

        self.done = {}
        for pm in self.pz["products"]:
            pid = pm["id"]
            atoms, bonds = molecule(pm)
            ns = len(atoms)
            hexes = self.outputs[pid]["hexes"]
            partners = {a: set() for a in range(ns)}
            for i, j in bonds:
                partners[i].add(j)
                partners[j].add(i)
            assigns = [perm for perm in
                       itertools.permutations(range(self.n_atom), ns)
                       if all(feasible(perm[a], atoms[a][0])
                              for a in range(ns))]
            if not assigns:
                die(f"product {pid}: no reagent atoms can ever match it", 1)

            def complete_now(t):
                disj = []
                for perm in assigns:
                    terms = []
                    for a in range(ns):
                        i = perm[a]
                        hq, hr = hexes[a]
                        terms += [self.atom_active[i][t],
                                  self.q[i][t] == hq, self.r[i][t] == hr,
                                  z3.Not(held_any(i, t))]
                        if self.typ is not None:
                            terms.append(self.typ[i][t]
                                         == ELEM_IDX[atoms[a][0]])
                        # exact bonds: required present, all others absent
                        allowed = {perm[a2] for a2 in partners[a]}
                        for j in range(self.n_atom):
                            if j == i:
                                continue
                            bv = self.bond_var(i, j, t)
                            if j in allowed:
                                terms.append(bv)
                            elif (min(i, j), max(i, j)) in self.b:
                                terms.append(z3.Not(bv))
                    disj.append(z3.And(terms))
                return z3.Or(disj)

            done = [z3.Bool(f"done_{pid}_{t}") for t in range(T + 1)]
            C.append(done[0] == complete_now(0))
            for t in range(1, T + 1):
                C.append(done[t] == z3.Or(done[t - 1], complete_now(t)))
            self.done[pid] = done
        self.goal = z3.And([d[T] for d in self.done.values()])


# ---------------------------------------------------------------------------
# Solving
# ---------------------------------------------------------------------------
def solve(enc, strategy, time_limit):
    """Returns (model, cost, proven_optimal) or (None, None, False)."""
    s = z3.Solver()
    s.add(enc.cons)
    s.add(enc.goal)
    deadline = time.perf_counter() + time_limit
    best = None
    proven = False

    def remaining_ms():
        return max(1, int((deadline - time.perf_counter()) * 1000))

    if strategy == "ramp-cost":
        for k in range(enc.T + 1):
            if time.perf_counter() >= deadline:
                break
            s.set("timeout", remaining_ms())
            guard = z3.Bool(f"__costle_{k}")
            s.add(z3.Implies(guard, enc.cost <= k))
            res = s.check(guard)
            log(f"ramp-cost: cost<={k}: {res}")
            if res == z3.sat:
                mdl = s.model()
                best, proven = (mdl, mdl.eval(enc.cost).as_long()), True
                break
            if res == z3.unknown:
                break
    elif strategy == "oneshot":
        s.set("timeout", remaining_ms())
        res = s.check()
        log(f"oneshot: {res}")
        if res == z3.sat:
            mdl = s.model()
            best = (mdl, mdl.eval(enc.cost).as_long())
    else:  # descend-cost (default), with a ramp-horizon warm start
        # Phase 1: find SOME plan fast by asking for the goal at state h
        # (waits after h) for h = 1..T over the one unrolled encoding.
        # done[] is a monotone latch, so goal-at-h implies the asserted
        # goal-at-T, and waiting after the goal can never violate an
        # invariant (spawns/bonds/calcification are deterministic and
        # spawning requires free hexes) -- every phase-1 model is a plan.
        # A plan completing at h also completes at every h' > h (waits
        # after the goal are always legal), so goal-at-h checks form a
        # monotone chain: pass (a) sweeps it with small growing time
        # slices, skipping horizons that time out (catches instances
        # whose min-horizon SAT is easy); pass (b) re-grinds the
        # unrefuted horizons to completion, accumulating the UNSAT-proof
        # lemmas that typically make the first SAT horizon cheap.  Only
        # an UNSAT at h = T proves the whole instance infeasible.
        guards = {}

        def goal_at(h):
            if h not in guards:
                guards[h] = z3.Bool(f"__goal_at_{h}")
                s.add(z3.Implies(guards[h], z3.And(
                    [enc.done[p][h] for p in enc.done]
                    + [enc.act[t] == 0 for t in range(h, enc.T)])))
            return guards[h]

        def found(h):
            nonlocal best
            mdl = s.model()
            cost = mdl.eval(enc.cost).as_long()
            best = (mdl, cost)
            log(f"warm start: plan with cost {cost} at horizon {h}, "
                f"descending from <= {cost - 1}")
            s.add(enc.cost <= cost - 1)

        refuted = 0  # all h <= refuted are proven planless
        slice_s = 1.5
        for h in range(1, enc.T + 1):  # pass (a): slice sweep
            if best is not None or time.perf_counter() >= deadline:
                break
            s.set("timeout", min(remaining_ms(), int(slice_s * 1000)))
            res = s.check(goal_at(h))
            if res == z3.sat:
                found(h)
            elif res == z3.unsat:
                if h == enc.T:
                    log("descend-cost: UNSAT -> no plan exists")
                    return None, None, False
                refuted = h
            else:
                slice_s *= 1.6
        if best is None:
            for h in range(refuted + 1, enc.T + 1):  # pass (b): grind
                if time.perf_counter() >= deadline:
                    break
                s.set("timeout", remaining_ms())
                res = s.check(goal_at(h))
                if res == z3.sat:
                    found(h)
                    break
                if res == z3.unsat:
                    if h == enc.T:
                        log("descend-cost: UNSAT -> no plan exists")
                        return None, None, False
                    log(f"warm start: no plan by horizon {h}")
                else:
                    break  # out of time
        # Phase 2: plain cost descent to (attempt to) prove optimality.
        while True:
            if time.perf_counter() >= deadline:
                log("descend-cost: time limit reached")
                break
            s.set("timeout", remaining_ms())
            res = s.check()
            if res == z3.sat:
                mdl = s.model()
                cost = mdl.eval(enc.cost).as_long()
                best = (mdl, cost)
                log(f"descend-cost: found plan with cost {cost}, "
                    f"tightening to <= {cost - 1}")
                s.add(enc.cost <= cost - 1)
            elif res == z3.unsat:
                proven = best is not None
                log("descend-cost: UNSAT -> "
                    + ("optimum proven" if proven else "no plan exists"))
                break
            else:
                log("descend-cost: solver timeout")
                break
    if best is None:
        return None, None, False
    return best[0], best[1], proven


# ---------------------------------------------------------------------------
# Plan extraction
# ---------------------------------------------------------------------------
def extract_plan(enc, mdl):
    ev = lambda e: mdl.eval(e, model_completion=True)
    num = lambda e: ev(e).as_long()
    placements = []
    for m, p in enumerate(enc.arms):
        placements.append({"type": "arm", "id": p["id"],
                           "position": [num(enc.baseq[m]),
                                        num(enc.baser[m])],
                           "rotation": num(enc.orient0[m]),
                           "length": p["length"]})
    for rid, ip in enc.inputs.items():
        placements.append({"type": "input", "id": rid,
                           "position": [num(ip["q"]), num(ip["r"])],
                           "rotation": num(ip["rot"])})
    for pid, op in enc.outputs.items():
        placements.append({"type": "output", "id": pid,
                           "position": [num(op["q"]), num(op["r"])],
                           "rotation": num(op["rot"])})
    for i, p in enumerate(enc.calcs):
        placements.append({"type": "calcifier", "id": p["id"],
                           "position": [num(enc.calc_hex[i][0]),
                                        num(enc.calc_hex[i][1])]})
    for i, p in enumerate(enc.bonders):
        (q1, r1), _, rot = enc.bonder_hex[i]
        placements.append({"type": "bonder", "id": p["id"],
                           "position": [num(q1), num(r1)],
                           "rotation": num(rot)})
    instructions = []
    for t in range(enc.T):
        code = num(enc.act[t])
        if code == 0:
            continue
        m, a = divmod(code - 1, 4)
        instructions.append({"t": t, "arm": enc.arms[m]["id"],
                             "action": ARM_ACTIONS[a]})
    return {"puzzle": enc.pz["name"],
            "solver": "z3 (Int BMC encoding, z3/adapter.py, z3-solver "
                      + z3.get_version_string() + ")",
            "placements": placements,
            "instructions": instructions}


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Z3 adapter for the Opus Magnum harness")
    ap.add_argument("puzzle")
    ap.add_argument("--out", help="write plan JSON here instead of stdout")
    ap.add_argument("--strategy", default="descend-cost",
                    choices=["descend-cost", "ramp-cost", "oneshot"])
    ap.add_argument("--time-limit", type=float,
                    default=float(os.environ.get("HARNESS_Z3_TIME_LIMIT",
                                                 120)))
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

    t0 = time.perf_counter()
    enc = HarnessEncoder(puzzle)
    build = time.perf_counter() - t0
    log(f"built encoding: {len(enc.cons)} constraints, "
        f"{enc.n_atom} atom slots, t_max={enc.T}, {build:.2f}s")
    mdl, cost, proven = solve(enc, args.strategy, args.time_limit)
    total = time.perf_counter() - t0
    if mdl is None:
        log(f"no plan found (strategy={args.strategy}, "
            f"limit={args.time_limit}s, total {total:.2f}s)")
        sys.exit(1)
    plan = extract_plan(enc, mdl)
    log(f"solved: cost={cost} "
        f"({'proven optimal' if proven else 'NOT proven optimal'}), "
        f"build {build:.2f}s, total {total:.2f}s")
    text = json.dumps(plan, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
    else:
        print(text)
    sys.exit(0)


if __name__ == "__main__":
    main()
