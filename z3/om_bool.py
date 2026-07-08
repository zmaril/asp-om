#!/usr/bin/env python3
"""Pure-boolean / one-hot Z3 variant of the encoding (comparison study).

Instead of Int coordinates, every state fact is a Bool:
  at[i][h][t]      atom i on hex index h at state t   (one-hot over the board)
  orient[d][t]     arm orientation is d               (one-hot over 6)
  actv[a][t]       instruction at step t is a         (one-hot over 5)
  held[i][t]       atom i is held
  b[(i,j)][t]      atoms i,j are bonded
  salt[i][t]       atom i has been calcified to salt  (v2, only if a
                   calcification glyph is present)

Single-arm, FIXED layout only (free layout stays in the Int encoding,
om_solver.py).  Supports both semantics:
  - v1 (asp/core.lp): held atom rides the gripper, no rigid motion, no
    base blocking (tests 1 and 2).
  - v2 (asp/core2.lp), single arm: rigid rotation of the held atom's
    bond-connected component about the (fixed) base -- a precomputed hex
    permutation per rotation direction -- plus calcification and base
    blocking (Stabilized Water).  A single serialized arm makes v2's
    "<=1 action per step" the same 5-action one-hot row as v1.

Element note: the only element types appearing in these instances are
water (elemental) and salt, so one Bool per atom ("is salt") suffices;
calcification is salt[t+1] = salt[t] OR on-calc-glyph[t] (correct for any
elemental input, which is all we have).
"""

import argparse
import time

from om_solver import DIRS, INSTANCES

import z3

ACTS = ["rot_cw", "rot_ccw", "grab", "drop", "wait"]
A_CW, A_CCW, A_GRAB, A_DROP, A_WAIT = range(5)


def hexes(radius):
    return [
        (q, r)
        for q in range(-radius, radius + 1)
        for r in range(-radius, radius + 1)
        if abs(q + r) <= radius
    ]


def rot_cw(p, b):
    """(q,r) rotated clockwise (dir d -> d+1) about base b."""
    dq, dr = p[0] - b[0], p[1] - b[1]
    return (b[0] - dr, b[1] + dq + dr)


def rot_ccw(p, b):
    dq, dr = p[0] - b[0], p[1] - b[1]
    return (b[0] + dq + dr, b[1] - dq)


class BoolEncoder:
    def __init__(self, inst, t_max=None, radius=None):
        assert len(inst["arms"]) == 1, "bool variant is single-arm only"
        self.inst = inst
        self.v2 = inst["semantics"] == "v2"
        self.T = t_max if t_max is not None else inst["t_max"]
        self.radius = radius if radius is not None else inst["radius"]
        self.hexes = hexes(self.radius)
        self.hidx = {h: k for k, h in enumerate(self.hexes)}
        self.cons = []
        self._build()

    def _build(self):
        inst, T, C = self.inst, self.T, self.cons
        H = len(self.hexes)
        n = len(inst["atoms"])
        arm = inst["arms"][0]
        base = arm["base"]
        L = arm["length"]
        # gripper hex for each orientation d (fixed base -> fixed hex);
        # None if off the board (that orientation is then forbidden)
        grip_hex = [self.hidx.get((base[0] + L * dq, base[1] + L * dr)) for (dq, dr) in DIRS]

        Bool = z3.Bool
        self.at = [
            [[Bool(f"at_{i}_{h}_{t}") for t in range(T + 1)] for h in range(H)] for i in range(n)
        ]
        self.orient = [[Bool(f"or_{d}_{t}") for t in range(T + 1)] for d in range(6)]
        self.actv = [[Bool(f"act_{a}_{t}") for t in range(T)] for a in range(5)]
        self.held = [[Bool(f"held_{i}_{t}") for t in range(T + 1)] for i in range(n)]
        self.pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
        need_bonds = bool(inst["glyph_bonds"] or inst["init_bonds"])
        self.b = (
            {p: [Bool(f"b_{p[0]}_{p[1]}_{t}") for t in range(T + 1)] for p in self.pairs}
            if need_bonds
            else {}
        )
        self.salt = None
        if inst["glyph_calcs"]:
            for a in inst["atoms"]:
                assert a.get("type", "salt") in ("salt", "water"), (
                    "bool variant tracks only salt/elemental"
                )
            self.salt = [[Bool(f"salt_{i}_{t}") for t in range(T + 1)] for i in range(n)]

        name2idx = {a["name"]: i for i, a in enumerate(inst["atoms"])}
        init_bond_set = {
            (min(name2idx[x], name2idx[y]), max(name2idx[x], name2idx[y]))
            for (x, y) in inst["init_bonds"]
        }

        def exactly_one(lits):
            C.append(z3.Or(lits))
            for x in range(len(lits)):
                for y in range(x + 1, len(lits)):
                    C.append(z3.Or(z3.Not(lits[x]), z3.Not(lits[y])))

        # initial state
        for i, atom in enumerate(inst["atoms"]):
            h0 = self.hidx[atom["pos"]]
            for h in range(H):
                C.append(self.at[i][h][0] if h == h0 else z3.Not(self.at[i][h][0]))
            C.append(z3.Not(self.held[i][0]))
            if self.salt is not None:
                s0 = atom.get("type", "salt") == "salt"
                C.append(self.salt[i][0] if s0 else z3.Not(self.salt[i][0]))
        for d in range(6):
            C.append(self.orient[d][0] if d == arm["init_orient"] else z3.Not(self.orient[d][0]))

        def at_grip(i, t):
            return z3.Or(
                [
                    z3.And(self.orient[d][t], self.at[i][g][t])
                    for d, g in enumerate(grip_hex[:6])
                    if g is not None
                ]
            )

        # bond formation trigger (fixed glyph hexes)
        gpairs = [(self.hidx[g1], self.hidx[g2]) for (g1, g2) in inst["glyph_bonds"]]

        def form(i, j, t):
            return (
                z3.Or(
                    [
                        z3.Or(
                            z3.And(self.at[i][h1][t], self.at[j][h2][t]),
                            z3.And(self.at[i][h2][t], self.at[j][h1][t]),
                        )
                        for (h1, h2) in gpairs
                    ]
                )
                if gpairs
                else z3.BoolVal(False)
            )

        def bond(i, j, t):
            key = (min(i, j), max(i, j))
            return self.b[key][t] if key in self.b else z3.BoolVal(False)

        def comp(i, t):
            """i is in the held atom's bond-connected component at t
            (unrolled closure, expression only -- no new variables)."""
            cur = [self.held[k][t] for k in range(n)]
            for _ in range(max(0, n - 1)):
                cur = [
                    z3.Or([cur[k]] + [z3.And(cur[j], bond(k, j, t)) for j in range(n) if j != k])
                    for k in range(n)
                ]
            return cur[i]

        # per-state invariants
        base_h = self.hidx.get(base)
        for t in range(T + 1):
            exactly_one([self.orient[d][t] for d in range(6)])
            for d in range(6):  # gripper must stay on the board
                if grip_hex[d] is None:
                    C.append(z3.Not(self.orient[d][t]))
            for i in range(n):
                exactly_one([self.at[i][h][t] for h in range(H)])
                if self.v2 and base_h is not None:  # bases block hexes
                    C.append(z3.Not(self.at[i][base_h][t]))
            for i, j in self.pairs:  # no collisions
                for h in range(H):
                    C.append(z3.Or(z3.Not(self.at[i][h][t]), z3.Not(self.at[j][h][t])))
            for p in self.pairs:
                if not self.b:
                    break
                prev = z3.BoolVal(p in init_bond_set) if t == 0 else self.b[p][t - 1]
                C.append(self.b[p][t] == z3.Or(prev, form(*p, t)))

        # precomputed rigid-rotation source hexes (v2): the atom that is on
        # hex h at t+1 after a cw rotation about the base was on ccw(h) at t
        cw_src = [self.hidx.get(rot_ccw(h, base)) for h in self.hexes]
        ccw_src = [self.hidx.get(rot_cw(h, base)) for h in self.hexes]

        # transitions
        for t in range(T):
            exactly_one([self.actv[a][t] for a in range(5)])
            cw, ccw = self.actv[A_CW][t], self.actv[A_CCW][t]
            grab, drop = self.actv[A_GRAB][t], self.actv[A_DROP][t]
            # orientation
            for d in range(6):
                C.append(
                    self.orient[d][t + 1]
                    == z3.Or(
                        z3.And(cw, self.orient[(d - 1) % 6][t]),
                        z3.And(ccw, self.orient[(d + 1) % 6][t]),
                        z3.And(z3.Not(cw), z3.Not(ccw), self.orient[d][t]),
                    )
                )
            # grab / drop legality
            armfull = z3.Or([self.held[i][t] for i in range(n)])
            C.append(
                z3.Implies(grab, z3.And(z3.Not(armfull), z3.Or([at_grip(i, t) for i in range(n)])))
            )
            C.append(z3.Implies(drop, armfull))
            # held update
            for i in range(n):
                C.append(
                    self.held[i][t + 1]
                    == z3.Or(z3.And(grab, at_grip(i, t)), z3.And(self.held[i][t], z3.Not(drop)))
                )
            # forbid rotating while holding a bonded atom (v1 test 2 rule)
            if inst["forbid_rot_holding_bonded"] and self.b:
                for i in range(n):
                    bondpart = z3.Or([bond(i, j, t) for j in range(n) if j != i])
                    C.append(z3.Implies(z3.Or(cw, ccw), z3.Not(z3.And(self.held[i][t], bondpart))))
            # positions
            if self.v2:
                # rigid rotation: the held component turns about the base
                # (a fixed hex permutation); everything else is inert.
                # An atom swung off the board has no source hex -> its
                # exactly-one row at t+1 becomes unsatisfiable, which is
                # precisely core2's "stay on the board" legality.
                for i in range(n):
                    ci = comp(i, t)
                    moved = z3.And(z3.Or(cw, ccw), ci)
                    for h in range(H):
                        src_cw, src_ccw = cw_src[h], ccw_src[h]
                        via_cw = (
                            z3.And(cw, ci, self.at[i][src_cw][t])
                            if src_cw is not None
                            else z3.BoolVal(False)
                        )
                        via_ccw = (
                            z3.And(ccw, ci, self.at[i][src_ccw][t])
                            if src_ccw is not None
                            else z3.BoolVal(False)
                        )
                        C.append(
                            self.at[i][h][t + 1]
                            == z3.Or(via_cw, via_ccw, z3.And(z3.Not(moved), self.at[i][h][t]))
                        )
            else:
                # v1: held atoms ride the gripper, free atoms are inert
                for i in range(n):
                    hj = self.held[i][t + 1]
                    for h in range(H):
                        if h in grip_hex:
                            d = grip_hex.index(h)
                            ride = z3.And(hj, self.orient[d][t + 1])
                        else:
                            ride = z3.BoolVal(False)
                        C.append(
                            self.at[i][h][t + 1]
                            == z3.Or(ride, z3.And(z3.Not(hj), self.at[i][h][t]))
                        )
            # calcification: elemental atom on the glyph at t -> salt at t+1
            if self.salt is not None:
                calc_h = [self.hidx[g] for g in inst["glyph_calcs"] if g in self.hidx]
                for i in range(n):
                    on_calc = (
                        z3.Or([self.at[i][h][t] for h in calc_h]) if calc_h else z3.BoolVal(False)
                    )
                    C.append(self.salt[i][t + 1] == z3.Or(self.salt[i][t], on_calc))

        # cost
        self.cost = z3.Int("cost")
        C.append(self.cost == z3.Sum([z3.If(self.actv[A_WAIT][t], 0, 1) for t in range(T)]))

    def goal(self):
        inst, T = self.inst, self.T
        name2idx = {a["name"]: i for i, a in enumerate(inst["atoms"])}
        n = len(inst["atoms"])
        conj = []
        for name, pos in inst["products"]:
            i = name2idx[name]
            conj += [self.at[i][self.hidx[pos]][T], z3.Not(self.held[i][T])]
        if inst["require_end_bond"]:
            conj.append(z3.Or([self.b[p][T] for p in self.pairs if p in self.b]))
        slots = inst.get("product_slots", [])
        if slots:
            import itertools

            assigns = []
            for perm in itertools.permutations(range(n), len(slots)):
                terms = []
                for si, (pos, ty) in enumerate(slots):
                    i = perm[si]
                    terms += [self.at[i][self.hidx[pos]][T], z3.Not(self.held[i][T])]
                    if self.salt is not None:
                        terms.append(self.salt[i][T] if ty == "salt" else z3.Not(self.salt[i][T]))
                assigns.append(z3.And(terms))
            conj.append(z3.Or(assigns))
        return z3.And(conj)


def solve(inst_name, strategy="descend-cost", t_max=None, radius=None):
    inst = INSTANCES[inst_name]
    t0 = time.perf_counter()
    enc = BoolEncoder(inst, t_max=t_max, radius=radius)
    build = time.perf_counter() - t0
    if strategy == "optimize":
        s = z3.Optimize()
        s.add(enc.cons)
        s.add(enc.goal())
        s.minimize(enc.cost)
        t0 = time.perf_counter()
        res = s.check()
        wall = time.perf_counter() - t0
        cost = s.model().eval(enc.cost).as_long() if res == z3.sat else None
        return {"status": str(res), "cost": cost, "build": build, "time": wall}
    if strategy == "descend-cost":
        s = z3.Solver()
        s.add(enc.cons)
        s.add(enc.goal())
        t0 = time.perf_counter()
        best = None
        while s.check() == z3.sat:
            best = s.model().eval(enc.cost).as_long()
            s.add(enc.cost <= best - 1)
        return {
            "status": "sat" if best is not None else "unsat",
            "cost": best,
            "build": build,
            "time": time.perf_counter() - t0,
        }
    if strategy == "oneshot":
        s = z3.Solver()
        s.add(enc.cons)
        s.add(enc.goal())
        t0 = time.perf_counter()
        res = s.check()
        wall = time.perf_counter() - t0
        cost = s.model().eval(enc.cost).as_long() if res == z3.sat else None
        return {"status": str(res), "cost": cost, "build": build, "time": wall}
    raise ValueError(strategy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", choices=["trivial", "bond", "water"])
    ap.add_argument(
        "--strategy", default="descend-cost", choices=["optimize", "descend-cost", "oneshot"]
    )
    ap.add_argument("--tmax", type=int, default=None)
    ap.add_argument("--radius", type=int, default=None)
    args = ap.parse_args()
    r = solve(args.instance, args.strategy, args.tmax, args.radius)
    print(
        f"bool-encoding instance={args.instance} strategy={args.strategy} "
        f"status={r['status']} cost={r['cost']} "
        f"build={r['build']:.3f}s solve={r['time']:.3f}s"
    )


if __name__ == "__main__":
    main()
