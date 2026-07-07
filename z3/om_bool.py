#!/usr/bin/env python3
"""Pure-boolean / one-hot Z3 variant of the v1 encoding (comparison study).

Instead of Int coordinates, every state fact is a Bool:
  at[i][h][t]      atom i on hex index h at state t   (one-hot over 19 hexes)
  orient[d][t]     arm orientation is d               (one-hot over 6)
  actv[a][t]       instruction at step t is a         (one-hot over 5)
  held[i][t]       atom i is held
  bonded[t]        the (single) bondable pair is bonded

Deliberately v1-only, single-arm, FIXED layout (the study only needs test1
and test2 -- enough to compare against the Int encoding).  Semantics are the
same as om_solver.py's v1 path / asp/core.lp.
"""

import argparse
import time

import z3

from om_solver import INSTANCES, DIRS

ACTS = ["rot_cw", "rot_ccw", "grab", "drop", "wait"]
A_CW, A_CCW, A_GRAB, A_DROP, A_WAIT = range(5)


def hexes(radius):
    return [(q, r) for q in range(-radius, radius + 1)
            for r in range(-radius, radius + 1) if abs(q + r) <= radius]


class BoolEncoder:
    def __init__(self, inst, t_max=None):
        assert inst["semantics"] == "v1", "bool variant is v1-only"
        assert len(inst["arms"]) == 1
        self.inst = inst
        self.T = t_max if t_max is not None else inst["t_max"]
        self.hexes = hexes(inst["radius"])
        self.hidx = {h: k for k, h in enumerate(self.hexes)}
        self.cons = []
        self._build()

    def _build(self):
        inst, T, C = self.inst, self.T, self.cons
        H = len(self.hexes)
        n = len(inst["atoms"])
        arm = inst["arms"][0]
        base = arm["base"]
        # gripper hex for each orientation d (fixed base -> fixed hex)
        grip_hex = [self.hidx[(base[0] + dq, base[1] + dr)]
                    for (dq, dr) in DIRS]

        Bool = z3.Bool
        self.at = [[[Bool(f"at_{i}_{h}_{t}") for t in range(T + 1)]
                    for h in range(H)] for i in range(n)]
        self.orient = [[Bool(f"or_{d}_{t}") for t in range(T + 1)]
                       for d in range(6)]
        self.actv = [[Bool(f"act_{a}_{t}") for t in range(T)]
                     for a in range(5)]
        self.held = [[Bool(f"held_{i}_{t}") for t in range(T + 1)]
                     for i in range(n)]
        self.pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
        self.b = {p: [Bool(f"b_{p[0]}_{p[1]}_{t}") for t in range(T + 1)]
                  for p in self.pairs} if inst["glyph_bonds"] else {}

        def exactly_one(lits):
            C.append(z3.Or(lits))
            for x in range(len(lits)):
                for y in range(x + 1, len(lits)):
                    C.append(z3.Or(z3.Not(lits[x]), z3.Not(lits[y])))

        # initial state
        for i, atom in enumerate(inst["atoms"]):
            h0 = self.hidx[atom["pos"]]
            for h in range(H):
                C.append(self.at[i][h][0] if h == h0
                         else z3.Not(self.at[i][h][0]))
            C.append(z3.Not(self.held[i][0]))
        for d in range(6):
            C.append(self.orient[d][0] if d == arm["init_orient"]
                     else z3.Not(self.orient[d][0]))

        def at_grip(i, t):
            return z3.Or([z3.And(self.orient[d][t],
                                 self.at[i][grip_hex[d]][t])
                          for d in range(6)])

        # bond formation trigger (fixed glyph hexes)
        gpairs = [(self.hidx[g1], self.hidx[g2])
                  for (g1, g2) in inst["glyph_bonds"]]

        def form(i, j, t):
            return z3.Or([z3.Or(z3.And(self.at[i][h1][t], self.at[j][h2][t]),
                                z3.And(self.at[i][h2][t], self.at[j][h1][t]))
                          for (h1, h2) in gpairs]) if gpairs \
                else z3.BoolVal(False)

        # per-state invariants
        for t in range(T + 1):
            exactly_one([self.orient[d][t] for d in range(6)])
            for i in range(n):
                exactly_one([self.at[i][h][t] for h in range(H)])
            for (i, j) in self.pairs:  # no collisions
                for h in range(H):
                    C.append(z3.Or(z3.Not(self.at[i][h][t]),
                                   z3.Not(self.at[j][h][t])))
            for p in self.pairs:
                if not self.b:
                    break
                prev = z3.BoolVal(False) if t == 0 else self.b[p][t - 1]
                C.append(self.b[p][t] == z3.Or(prev, form(*p, t)))

        # transitions
        for t in range(T):
            exactly_one([self.actv[a][t] for a in range(5)])
            cw, ccw = self.actv[A_CW][t], self.actv[A_CCW][t]
            grab, drop = self.actv[A_GRAB][t], self.actv[A_DROP][t]
            # orientation
            for d in range(6):
                C.append(self.orient[d][t + 1] == z3.Or(
                    z3.And(cw, self.orient[(d - 1) % 6][t]),
                    z3.And(ccw, self.orient[(d + 1) % 6][t]),
                    z3.And(z3.Not(cw), z3.Not(ccw), self.orient[d][t])))
            # grab / drop legality
            armfull = z3.Or([self.held[i][t] for i in range(n)])
            C.append(z3.Implies(grab, z3.And(
                z3.Not(armfull),
                z3.Or([at_grip(i, t) for i in range(n)]))))
            C.append(z3.Implies(drop, armfull))
            # held update
            for i in range(n):
                C.append(self.held[i][t + 1] == z3.Or(
                    z3.And(grab, at_grip(i, t)),
                    z3.And(self.held[i][t], z3.Not(drop))))
            # forbid rotating while holding a bonded atom (test 2)
            if inst["forbid_rot_holding_bonded"] and self.b:
                for i in range(n):
                    bondpart = z3.Or([self.b[(min(i, j), max(i, j))][t]
                                      for j in range(n) if j != i])
                    C.append(z3.Implies(z3.Or(cw, ccw),
                                        z3.Not(z3.And(self.held[i][t],
                                                      bondpart))))
            # positions: held atoms ride the gripper, free atoms are inert
            for i in range(n):
                hj = self.held[i][t + 1]
                for h in range(H):
                    if h in grip_hex:
                        d = grip_hex.index(h)
                        ride = z3.And(hj, self.orient[d][t + 1])
                    else:
                        ride = z3.BoolVal(False)
                    C.append(self.at[i][h][t + 1] == z3.Or(
                        ride, z3.And(z3.Not(hj), self.at[i][h][t])))

        # cost
        self.cost = z3.Int("cost")
        C.append(self.cost == z3.Sum(
            [z3.If(self.actv[A_WAIT][t], 0, 1) for t in range(T)]))

    def goal(self):
        inst, T = self.inst, self.T
        name2idx = {a["name"]: i for i, a in enumerate(inst["atoms"])}
        conj = []
        for (name, pos) in inst["products"]:
            i = name2idx[name]
            conj += [self.at[i][self.hidx[pos]][T],
                     z3.Not(self.held[i][T])]
        if inst["require_end_bond"]:
            conj.append(z3.Or([self.b[p][T] for p in self.pairs
                               if p in self.b]))
        return z3.And(conj)


def solve(inst_name, strategy="descend-cost", t_max=None):
    inst = INSTANCES[inst_name]
    t0 = time.perf_counter()
    enc = BoolEncoder(inst, t_max=t_max)
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
        return dict(status=str(res), cost=cost, build=build, time=wall)
    if strategy == "descend-cost":
        s = z3.Solver()
        s.add(enc.cons)
        s.add(enc.goal())
        t0 = time.perf_counter()
        best = None
        while s.check() == z3.sat:
            best = s.model().eval(enc.cost).as_long()
            s.add(enc.cost <= best - 1)
        return dict(status="sat" if best is not None else "unsat",
                    cost=best, build=build, time=time.perf_counter() - t0)
    if strategy == "oneshot":
        s = z3.Solver()
        s.add(enc.cons)
        s.add(enc.goal())
        t0 = time.perf_counter()
        res = s.check()
        wall = time.perf_counter() - t0
        cost = s.model().eval(enc.cost).as_long() if res == z3.sat else None
        return dict(status=str(res), cost=cost, build=build, time=wall)
    raise ValueError(strategy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("instance", choices=["trivial", "bond"])
    ap.add_argument("--strategy", default="descend-cost",
                    choices=["optimize", "descend-cost", "oneshot"])
    ap.add_argument("--tmax", type=int, default=None)
    args = ap.parse_args()
    r = solve(args.instance, args.strategy, args.tmax)
    print(f"bool-encoding instance={args.instance} strategy={args.strategy} "
          f"status={r['status']} cost={r['cost']} "
          f"build={r['build']:.3f}s solve={r['time']:.3f}s")


if __name__ == "__main__":
    main()
