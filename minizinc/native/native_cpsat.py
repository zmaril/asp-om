#!/usr/bin/env python3
"""Native OR-Tools CP-SAT re-implementation of minizinc/om.mzn (+ om_fixed.mzn).

Faithful port of the MiniZinc model semantics (see om.mzn header):
  * bounded hex board, axial (Q,R), |Q|,|R|,|Q+R| <= radius
  * clockwise dirs 0..5, dir 0 = (1,0)
  * time 0..T, at most one (arm, action) per step from
    {rot_cw, rot_ccw, grab, drop}
  * gripper = base + len*dir(orient); arm bases block hexes
  * rigid rotation of the bond-connected component of the held atom
  * bonding glyphs (bond forms when both hexes occupied; bonds persist)
  * calcification glyph (elemental -> salt)
  * goal: product atoms unheld on target hexes (opt. type / any-bond)
  * objective: minimize number of actions
  * layout (arm bases + glyph hexes) is a decision variable; --fixed pins it
    to the given_* instance parameters (matches the clingo instances)
  * single-arm wait-compaction dominance constraint (same gate as om.mzn)

Reads the same .dzn instance files as the MiniZinc model (tiny parser for
the literal subset used). Prints objective, build/solve wall times and a
per-timestep trace; --json FILE dumps a solution object in the exact shape
of `minizinc --output-mode json`, so minizinc/trace.py --check --dzn works
on it unchanged.

Usage:
  python3 native_cpsat.py instances/t2_bond.dzn --fixed --threads 1
  python3 native_cpsat.py instances/t2_bond.dzn --free --json sol.json
"""
import argparse
import json
import re
import sys
import time

from ortools.sat.python import cp_model

# clockwise directions, dir 0 = (1,0)  (matches om.mzn DQ/DR)
DQ = [1, 0, -1, -1, 0, 1]
DR = [0, 1, 1, 0, -1, -1]
TYPE_NAME = {1: "salt", 2: "air", 3: "earth", 4: "fire", 5: "water"}


# ---------------------------------------------------------------------------
# .dzn parsing (the literal subset used by minizinc/instances/*.dzn)
# ---------------------------------------------------------------------------
def parse_dzn(path):
    src = open(path).read()
    src = re.sub(r"%.*", "", src)
    out = {}
    for stmt in src.split(";"):
        if "=" not in stmt:
            continue
        name, val = stmt.split("=", 1)
        name, val = name.strip(), val.strip()
        if val in ("true", "false"):
            out[name] = val == "true"
        elif re.fullmatch(r"-?\d+", val):
            out[name] = int(val)
        elif val.startswith("[|"):                       # 2d literal
            rows = val[2:-2].strip()
            out[name] = [
                [int(x) for x in row.split(",") if x.strip()]
                for row in rows.split("|") if row.strip()
            ] if rows else []
        elif val.startswith("array2d"):                  # (empty) array2d
            inner = re.search(r"\[(.*)\]", val, re.S).group(1)
            flat = [int(x) for x in inner.split(",") if x.strip()]
            m = re.match(r"array2d\s*\(\s*1\.\.(\d+)\s*,\s*1\.\.(\d+)", val)
            if m and int(m.group(1)) > 0:
                ncol = int(m.group(2))
                out[name] = [flat[i:i + ncol] for i in range(0, len(flat), ncol)]
            else:
                out[name] = []
        elif val.startswith("["):
            out[name] = [int(x) for x in val[1:-1].split(",") if x.strip()]
        else:
            raise ValueError(f"unhandled dzn value for {name}: {val[:40]}")
    return out


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------
class OmModel:
    def __init__(self, d, fixed_layout):
        self.d = d
        self.m = cp_model.CpModel()
        self._nb = 0
        self._false = None
        self.build(fixed_layout)

    # -- reification helpers -------------------------------------------------
    def newb(self, tag=""):
        self._nb += 1
        return self.m.NewBoolVar(f"b{self._nb}_{tag}")

    def false(self):
        if self._false is None:
            self._false = self.newb("false")
            self.m.Add(self._false == 0)
        return self._false

    def eq_reif(self, x, y, tag=""):
        """b <-> (x == y) for int vars / linear exprs."""
        b = self.newb(tag)
        self.m.Add(x == y).OnlyEnforceIf(b)
        self.m.Add(x != y).OnlyEnforceIf(b.Not())
        return b

    def and_reif(self, lits, tag=""):
        lits = list(lits)
        if not lits:
            raise ValueError("and of nothing")
        if len(lits) == 1:
            return lits[0]
        b = self.newb(tag)
        self.m.AddBoolAnd(lits).OnlyEnforceIf(b)
        self.m.AddBoolOr([l.Not() for l in lits]).OnlyEnforceIf(b.Not())
        return b

    def or_reif(self, lits, tag=""):
        lits = list(lits)
        if not lits:
            return self.false()
        if len(lits) == 1:
            return lits[0]
        b = self.newb(tag)
        self.m.AddBoolOr(lits).OnlyEnforceIf(b)
        self.m.AddBoolAnd([l.Not() for l in lits]).OnlyEnforceIf(b.Not())
        return b

    # -- the model ------------------------------------------------------------
    def build(self, fixed_layout):
        m, d = self.m, self.d
        T, R, nA, nM = d["T"], d["radius"], d["nA"], d["nM"]
        nB, nC = d["nBonder"], d["nCalc"]
        TIME, STEP = range(T + 1), range(T)
        ATOM, ARM = range(nA), range(nM)
        W = 2 * R + 1

        def cell(q, r):                       # linearised cell id (linear expr)
            return (q + R) * W + (r + R)

        def board(q, r):                      # |q+r| <= R  (bounds give |q|,|r|)
            m.Add(q + r <= R)
            m.Add(q + r >= -R)

        iv = lambda tag: m.NewIntVar(-R, R, tag)

        # ---- layout decision variables ----
        base_q = [iv(f"base_q{a}") for a in ARM]
        base_r = [iv(f"base_r{a}") for a in ARM]
        for k in ARM:
            board(base_q[k], base_r[k])
        bonder_q1 = [iv(f"bq1_{g}") for g in range(nB)]
        bonder_r1 = [iv(f"br1_{g}") for g in range(nB)]
        bonder_q2 = [iv(f"bq2_{g}") for g in range(nB)]
        bonder_r2 = [iv(f"br2_{g}") for g in range(nB)]
        for g in range(nB):
            board(bonder_q1[g], bonder_r1[g])
            board(bonder_q2[g], bonder_r2[g])
            # the two glyph hexes are adjacent (exists d in 0..5)
            adj = []
            for k in range(6):
                adj.append(self.and_reif(
                    [self.eq_reif(bonder_q2[g], bonder_q1[g] + DQ[k]),
                     self.eq_reif(bonder_r2[g], bonder_r1[g] + DR[k])],
                    f"badj{g}_{k}"))
            m.AddBoolOr(adj)
        calc_q = [iv(f"cq{g}") for g in range(nC)]
        calc_r = [iv(f"cr{g}") for g in range(nC)]
        for g in range(nC):
            board(calc_q[g], calc_r[g])

        part_cells = ([cell(base_q[k], base_r[k]) for k in ARM] +
                      [cell(bonder_q1[g], bonder_r1[g]) for g in range(nB)] +
                      [cell(bonder_q2[g], bonder_r2[g]) for g in range(nB)] +
                      [cell(calc_q[g], calc_r[g]) for g in range(nC)])
        if len(part_cells) > 1:
            m.AddAllDifferent(part_cells)

        if fixed_layout:
            for k in ARM:
                m.Add(base_q[k] == d["given_base_q"][k])
                m.Add(base_r[k] == d["given_base_r"][k])
            for g in range(nB):
                gb = d["given_bonder"][g]
                m.Add(bonder_q1[g] == gb[0])
                m.Add(bonder_r1[g] == gb[1])
                m.Add(bonder_q2[g] == gb[2])
                m.Add(bonder_r2[g] == gb[3])
            for g in range(nC):
                gc = d["given_calc"][g]
                m.Add(calc_q[g] == gc[0])
                m.Add(calc_r[g] == gc[1])

        # ---- state variables ----
        aq = [[iv(f"aq{t}_{a}") for a in ATOM] for t in TIME]
        ar = [[iv(f"ar{t}_{a}") for a in ATOM] for t in TIME]
        for t in TIME:
            for a in ATOM:
                board(aq[t][a], ar[t][a])
        held = [[m.NewIntVar(0, nM, f"held{t}_{a}") for a in ATOM] for t in TIME]
        typ = [[m.NewIntVar(1, 5, f"typ{t}_{a}") for a in ATOM] for t in TIME]
        ori = [[m.NewIntVar(0, 5, f"ori{t}_{k}") for k in ARM] for t in TIME]
        gq = [[iv(f"gq{t}_{k}") for k in ARM] for t in TIME]
        gr = [[iv(f"gr{t}_{k}") for k in ARM] for t in TIME]
        for t in TIME:
            for k in ARM:
                board(gq[t][k], gr[t][k])

        # bonds: only a<b stored
        bonded = {}
        for t in TIME:
            for a in ATOM:
                for b in ATOM:
                    if a < b:
                        bonded[t, a, b] = self.newb(f"bond{t}_{a}_{b}")

        def bnd(t, a, b):
            return bonded[t, min(a, b), max(a, b)]

        # ---- actions ----
        doCW = [[self.newb(f"cw{t}_{k}") for k in ARM] for t in STEP]
        doCCW = [[self.newb(f"ccw{t}_{k}") for k in ARM] for t in STEP]
        doGrab = [[self.newb(f"grab{t}_{k}") for k in ARM] for t in STEP]
        doDrop = [[self.newb(f"drop{t}_{k}") for k in ARM] for t in STEP]
        for t in STEP:
            m.Add(sum(doCW[t]) + sum(doCCW[t]) +
                  sum(doGrab[t]) + sum(doDrop[t]) <= 1)

        # ---- initial state ----
        for a in ATOM:
            m.Add(aq[0][a] == d["init_q"][a])
            m.Add(ar[0][a] == d["init_r"][a])
            m.Add(held[0][a] == 0)
            m.Add(typ[0][a] == d["init_type"][a])
        for k in ARM:
            m.Add(ori[0][k] == d["init_ori"][k])
        init_pairs = {(min(p) - 1, max(p) - 1) for p in d["init_bond"]}

        # ---- gripper geometry: gripper = base + len*dir(orient) ----
        for t in TIME:
            for k in ARM:
                dqv = m.NewIntVar(-1, 1, f"dq{t}_{k}")
                drv = m.NewIntVar(-1, 1, f"dr{t}_{k}")
                m.AddElement(ori[t][k], DQ, dqv)
                m.AddElement(ori[t][k], DR, drv)
                ln = d["arm_len"][k]
                m.Add(gq[t][k] == base_q[k] + ln * dqv)
                m.Add(gr[t][k] == base_r[k] + ln * drv)

        # heldEq[t][a][k] <-> held[t,a] == k+1 ;  held0[t][a] <-> held[t,a] == 0
        heldEq = [[[self.eq_reif(held[t][a], k + 1, f"he{t}_{a}_{k}")
                    for k in ARM] for a in ATOM] for t in TIME]
        held0 = [[self.eq_reif(held[t][a], 0, f"h0{t}_{a}")
                  for a in ATOM] for t in TIME]

        # redundant channel: held atom sits on its holder's gripper hex
        for t in TIME:
            for a in ATOM:
                for k in ARM:
                    m.Add(aq[t][a] == gq[t][k]).OnlyEnforceIf(heldEq[t][a][k])
                    m.Add(ar[t][a] == gr[t][k]).OnlyEnforceIf(heldEq[t][a][k])

        # ---- orientation transition: ori' = (ori + cw - ccw + 6) mod 6 ----
        for t in STEP:
            for k in ARM:
                e = m.NewIntVar(5, 12, f"orie{t}_{k}")
                m.Add(e == ori[t][k] + doCW[t][k] - doCCW[t][k] + 6)
                m.AddModuloEquality(ori[t + 1][k], e, 6)

        # ---- bond formation and persistence ----
        # on-glyph-hex reified equalities, cached per (t, atom, glyph, side)
        onb = {}
        for t in TIME:
            for a in ATOM:
                for g in range(nB):
                    onb[t, a, g, 1] = self.and_reif(
                        [self.eq_reif(aq[t][a], bonder_q1[g]),
                         self.eq_reif(ar[t][a], bonder_r1[g])], f"on1_{t}_{a}_{g}")
                    onb[t, a, g, 2] = self.and_reif(
                        [self.eq_reif(aq[t][a], bonder_q2[g]),
                         self.eq_reif(ar[t][a], bonder_r2[g])], f"on2_{t}_{a}_{g}")

        def formed(t, a, b):                  # var bool (or_reif) expression
            lits = []
            for g in range(nB):
                lits.append(self.and_reif([onb[t, a, g, 1], onb[t, b, g, 2]]))
                lits.append(self.and_reif([onb[t, a, g, 2], onb[t, b, g, 1]]))
            return self.or_reif(lits, f"formed{t}_{a}_{b}")

        for a in ATOM:
            for b in ATOM:
                if a < b:
                    if (a, b) in init_pairs:
                        m.Add(bonded[0, a, b] == 1)
                    else:
                        m.Add(bonded[0, a, b] == formed(0, a, b))
        for t in STEP:
            for a in ATOM:
                for b in ATOM:
                    if a < b:
                        m.Add(bonded[t + 1, a, b] ==
                              self.or_reif([bonded[t, a, b],
                                            formed(t + 1, a, b)]))

        # ---- held connected component (nA-1 stage unrolling) ----
        # compS[t][k][a][0] = heldEq ; stage j = stage j-1 OR neighbour in j-1
        comp = [[[None] * nA for _ in ARM] for _ in STEP]
        for t in STEP:
            for k in ARM:
                stage = [heldEq[t][a][k] for a in ATOM]
                for _ in range(1, nA):
                    nxt = []
                    for a in ATOM:
                        lits = [stage[a]]
                        for b in ATOM:
                            if b != a:
                                lits.append(self.and_reif(
                                    [stage[b], bnd(t, a, b)]))
                        nxt.append(self.or_reif(lits, f"comp{t}_{k}_{a}"))
                    stage = nxt
                for a in ATOM:
                    comp[t][k][a] = stage[a]

        # rot[t][k] <-> doCW or doCCW
        rot = [[self.or_reif([doCW[t][k], doCCW[t][k]], f"rot{t}_{k}")
                for k in ARM] for t in STEP]

        # a rotation may not tear an atom out of another arm's hand
        for t in STEP:
            for k in ARM:
                for a in ATOM:
                    m.AddBoolOr([held0[t][a], heldEq[t][a][k]]).OnlyEnforceIf(
                        [rot[t][k], comp[t][k][a]])

        # ---- grab / drop legality + held transition ----
        grabA = [[[None] * nA for _ in ARM] for _ in STEP]
        for t in STEP:
            for k in ARM:
                for a in ATOM:
                    at_grip = self.and_reif(
                        [self.eq_reif(aq[t][a], gq[t][k]),
                         self.eq_reif(ar[t][a], gr[t][k])], f"ag{t}_{k}_{a}")
                    grabA[t][k][a] = self.and_reif(
                        [doGrab[t][k], at_grip], f"grabA{t}_{k}_{a}")
        for t in STEP:
            for k in ARM:
                for a in ATOM:                          # hand empty
                    m.AddImplication(doGrab[t][k], heldEq[t][a][k].Not())
                m.AddBoolOr(grabA[t][k]).OnlyEnforceIf(doGrab[t][k])  # sth there
                for a in ATOM:                          # target is free
                    m.AddImplication(grabA[t][k][a], held0[t][a])
                # something held when dropping
                m.AddBoolOr([heldEq[t][a][k] for a in ATOM]).OnlyEnforceIf(
                    doDrop[t][k])

        dropA = [[self.or_reif(
            [self.and_reif([doDrop[t][k], heldEq[t][a][k]]) for k in ARM],
            f"dropA{t}_{a}") for a in ATOM] for t in STEP]

        for t in STEP:
            for a in ATOM:
                for k in ARM:
                    m.Add(held[t + 1][a] == k + 1).OnlyEnforceIf(grabA[t][k][a])
                m.Add(held[t + 1][a] == 0).OnlyEnforceIf(dropA[t][a])
                frame = [dropA[t][a].Not()] + \
                        [grabA[t][k][a].Not() for k in ARM]
                m.Add(held[t + 1][a] == held[t][a]).OnlyEnforceIf(frame)

        # ---- motion: rigid rotation of the held component; else inert ----
        movedA = [[self.or_reif(
            [self.and_reif([rot[t][k], comp[t][k][a]]) for k in ARM],
            f"moved{t}_{a}") for a in ATOM] for t in STEP]
        for t in STEP:
            for k in ARM:
                for a in ATOM:
                    # cw about (BQ,BR): (Q,R) -> (BQ+BR-R, Q+R-BQ)
                    m.Add(aq[t + 1][a] == base_q[k] + base_r[k] - ar[t][a]
                          ).OnlyEnforceIf([doCW[t][k], comp[t][k][a]])
                    m.Add(ar[t + 1][a] == aq[t][a] + ar[t][a] - base_q[k]
                          ).OnlyEnforceIf([doCW[t][k], comp[t][k][a]])
                    # ccw about (BQ,BR): (Q,R) -> (Q+R-BR, BQ+BR-Q)
                    m.Add(aq[t + 1][a] == aq[t][a] + ar[t][a] - base_r[k]
                          ).OnlyEnforceIf([doCCW[t][k], comp[t][k][a]])
                    m.Add(ar[t + 1][a] == base_q[k] + base_r[k] - aq[t][a]
                          ).OnlyEnforceIf([doCCW[t][k], comp[t][k][a]])
            for a in ATOM:
                m.Add(aq[t + 1][a] == aq[t][a]).OnlyEnforceIf(movedA[t][a].Not())
                m.Add(ar[t + 1][a] == ar[t][a]).OnlyEnforceIf(movedA[t][a].Not())

        # ---- occupancy ----
        for t in TIME:
            if nA > 1:
                m.AddAllDifferent([cell(aq[t][a], ar[t][a]) for a in ATOM])
            for a in ATOM:
                for k in ARM:
                    m.AddBoolOr([self.eq_reif(aq[t][a], base_q[k]).Not(),
                                 self.eq_reif(ar[t][a], base_r[k]).Not()])

        # ---- calcification ----
        for t in STEP:
            for a in ATOM:
                ge2 = self.newb(f"ge2_{t}_{a}")
                m.Add(typ[t][a] >= 2).OnlyEnforceIf(ge2)
                m.Add(typ[t][a] <= 1).OnlyEnforceIf(ge2.Not())
                onc = self.or_reif(
                    [self.and_reif([self.eq_reif(aq[t][a], calc_q[g]),
                                    self.eq_reif(ar[t][a], calc_r[g])])
                     for g in range(nC)], f"onc{t}_{a}")
                cal = self.and_reif([ge2, onc], f"calc{t}_{a}")
                m.Add(typ[t + 1][a] == 1).OnlyEnforceIf(cal)
                m.Add(typ[t + 1][a] == typ[t][a]).OnlyEnforceIf(cal.Not())

        # ---- goal at time T ----
        for j in range(d["nProd"]):
            a = d["prod_atom"][j] - 1
            m.Add(aq[T][a] == d["prod_q"][j])
            m.Add(ar[T][a] == d["prod_r"][j])
            m.Add(held[T][a] == 0)
            if d["prod_type"][j]:
                m.Add(typ[T][a] == d["prod_type"][j])
        if d["require_any_bond"]:
            m.AddBoolOr([bonded[T, a, b]
                         for a in ATOM for b in ATOM if a < b])

        # ---- objective ----
        total = m.NewIntVar(0, T, "total_actions")
        m.Add(total == sum(doCW[t][k] + doCCW[t][k] +
                           doGrab[t][k] + doDrop[t][k]
                           for t in STEP for k in ARM))
        m.Minimize(total)

        # ---- single-arm wait-compaction dominance (same gate as om.mzn) ----
        acted = [self.or_reif(doCW[t] + doCCW[t] + doGrab[t] + doDrop[t],
                              f"acted{t}") for t in STEP]
        if nM == 1:
            for t in range(1, T):
                m.AddImplication(acted[t], acted[t - 1])

        # keep handles for output
        self.vars = dict(
            aq=aq, ar=ar, held=held, typ=typ, ori=ori, gq=gq, gr=gr,
            bonded=bonded, doCW=doCW, doCCW=doCCW, doGrab=doGrab,
            doDrop=doDrop, base_q=base_q, base_r=base_r,
            bonder_q1=bonder_q1, bonder_r1=bonder_r1,
            bonder_q2=bonder_q2, bonder_r2=bonder_r2,
            calc_q=calc_q, calc_r=calc_r, total_actions=total)


# ---------------------------------------------------------------------------
# Solution extraction (same JSON shape as `minizinc --output-mode json`)
# ---------------------------------------------------------------------------
def extract(model, solver):
    d, v = model.d, model.vars
    T, nA, nM = d["T"], d["nA"], d["nM"]
    val = solver.Value

    def grid2(x):
        return [[val(c) for c in row] for row in x]

    sol = {
        "total_actions": val(v["total_actions"]),
        "base_q": [val(x) for x in v["base_q"]],
        "base_r": [val(x) for x in v["base_r"]],
        "bonder_q1": [val(x) for x in v["bonder_q1"]],
        "bonder_r1": [val(x) for x in v["bonder_r1"]],
        "bonder_q2": [val(x) for x in v["bonder_q2"]],
        "bonder_r2": [val(x) for x in v["bonder_r2"]],
        "calc_q": [val(x) for x in v["calc_q"]],
        "calc_r": [val(x) for x in v["calc_r"]],
        "aq": grid2(v["aq"]), "ar": grid2(v["ar"]),
        "held": grid2(v["held"]), "typ": grid2(v["typ"]),
        "ori": grid2(v["ori"]), "gq": grid2(v["gq"]), "gr": grid2(v["gr"]),
        "doCW": [[bool(val(c)) for c in row] for row in v["doCW"]],
        "doCCW": [[bool(val(c)) for c in row] for row in v["doCCW"]],
        "doGrab": [[bool(val(c)) for c in row] for row in v["doGrab"]],
        "doDrop": [[bool(val(c)) for c in row] for row in v["doDrop"]],
        "bonded": [[[bool(val(v["bonded"][t, a, b])) if a < b else False
                     for b in range(nA)] for a in range(nA)]
                   for t in range(T + 1)],
    }
    return sol


def print_trace(sol):
    T = len(sol["aq"]) - 1
    nA, nM = len(sol["aq"][0]), len(sol["ori"][0])
    print(f"total_actions = {sol['total_actions']}")
    for k in range(nM):
        print(f"arm {k+1}: base=({sol['base_q'][k]},{sol['base_r'][k]})")
    for g in range(len(sol["bonder_q1"])):
        print(f"bonder {g+1}: ({sol['bonder_q1'][g]},{sol['bonder_r1'][g]})"
              f"-({sol['bonder_q2'][g]},{sol['bonder_r2'][g]})")
    for g in range(len(sol["calc_q"])):
        print(f"calc {g+1}: ({sol['calc_q'][g]},{sol['calc_r'][g]})")
    for t in range(T + 1):
        arms = " ".join(f"arm{k+1} dir={sol['ori'][t][k]} "
                        f"grip=({sol['gq'][t][k]},{sol['gr'][t][k]})"
                        for k in range(nM))
        atoms = " ".join(
            f"a{a+1}@({sol['aq'][t][a]},{sol['ar'][t][a]})"
            + (f"[held:{sol['held'][t][a]}]" if sol["held"][t][a] else "")
            + (f"[{TYPE_NAME[sol['typ'][t][a]]}]"
               if sol["typ"][t][a] != 1 else "")
            for a in range(nA))
        line = f"t={t:>2}  {arms}  {atoms}"
        if t < T:
            for k in range(nM):
                for name, key in (("rot_cw", "doCW"), ("rot_ccw", "doCCW"),
                                  ("grab", "doGrab"), ("drop", "doDrop")):
                    if sol[key][t][k]:
                        line += f"  action: arm{k+1} {name}"
        print(line)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dzn", help="instance .dzn file")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fixed", action="store_true",
                      help="pin layout to given_* params (om_fixed.mzn)")
    mode.add_argument("--free", action="store_true",
                      help="layout is a decision variable (om.mzn, default)")
    ap.add_argument("--threads", type=int, default=1,
                    help="CP-SAT num_workers (default 1)")
    ap.add_argument("--timeout", type=float, default=300.0,
                    help="max solve seconds (default 300)")
    ap.add_argument("--json", metavar="FILE",
                    help="dump the solution as minizinc-style JSON")
    ap.add_argument("--quiet", action="store_true", help="no trace print")
    args = ap.parse_args()

    d = parse_dzn(args.dzn)
    t0 = time.perf_counter()
    om = OmModel(d, fixed_layout=args.fixed)
    build_s = time.perf_counter() - t0

    solver = cp_model.CpSolver()
    solver.parameters.num_workers = args.threads
    solver.parameters.max_time_in_seconds = args.timeout
    t0 = time.perf_counter()
    status = solver.Solve(om.m)
    solve_wall = time.perf_counter() - t0

    sname = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"status={sname} build_s={build_s:.3f} solve_s={solve_wall:.3f}")
        sys.exit(2)

    sol = extract(om, solver)
    if not args.quiet:
        print_trace(sol)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(sol, f)
    print(f"status={sname} objective={sol['total_actions']} "
          f"build_s={build_s:.3f} solve_s={solve_wall:.3f} "
          f"solver_wall_s={solver.WallTime():.3f} "
          f"booleans={om._nb} branches={solver.NumBranches()} "
          f"conflicts={solver.NumConflicts()}")


if __name__ == "__main__":
    main()
