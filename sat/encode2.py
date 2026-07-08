"""Planning-as-SAT encoding of the Opus Magnum phase-2 fragment
(Stabilized Water).

Replicates the clingo arm's asp/core2.lp semantics (branch
stabilized-water) for a SINGLE arm of length 1:

  * rigid molecule motion: rotating the arm while holding an atom rotates
    the atom's whole bond-connected component 60 degrees about the arm
    base ((q,r) -> (-r, q+r) cw, (q,r) -> (q+r, -q) ccw, translated to the
    base); a swing that would leave the board is illegal;
  * atom element types (water/salt suffice here, encoded as one bit
    salt(x,t)); glyph of calcification: an elemental atom sitting on the
    glyph hex at t is salt from t+1 on (held or not);
  * glyph of bonding: whenever both cells are occupied the occupants bond;
    bonds are symmetric and persist forever;
  * respawning reagent inputs: per input a bounded pool r(i,1..P);
    r(i,1) is on the spawn hex at t=0; r(i,n+1) appears on the spawn hex
    at the first t+1 when no atom that already existed at t sits there
    (exactly clingo's occ_old rule);
  * arm base blocks atoms; no two atoms share a hex; atoms stay on-board;
  * exactly one instruction per step from rot_cw/rot_ccw/grab/drop/wait
    (clingo's `{do(M,A,T)} 1` with idle == wait);
  * goal at the horizon T: an exact salt--water dimer -- some water atom
    W and salt atom S with bond(W,S), no other bonds on either, both
    unheld (and, if the instance fixes product hexes, resting exactly
    there).  asp/stabilized_water.lp accepts the dimer at ANY time <= t_max;
    that is equivalent at the same horizon because a completed unheld
    dimer persists under trailing waits (spawns cannot re-bond or move it,
    parts do not overlap), so min makespan and min instruction count agree.

Layout handling mirrors phase 1: one CNF with layout decision variables
(arm base, initial orientation, per-input spawn hex, calcifier hex, bonder
cell+direction with dir<3 for mirror symmetry breaking, all subject to
OM's part-non-overlap rule, exactly as asp/layout.lp); --fixed-layout pins
them with unit assumptions.  Arm length is fixed at 1, matching the clingo
free-layout SW instance (place_arm(m1,1)).

Variable families (pysat IDPool):
  base(h) spawn(i,h) cpos(h) gpos(h) gdir(d<3)   layout      [exactly-one]
  do(a,t)                                        instructions [EO per step]
  orient(d,t) grip(h,t)                          arm state
  ex(x,t) at(x,h,t) hold(x,t) salt(x,t)          atom state
  bond(p,t)                                      unordered pair p bonded
  eo(h,t) exw(x,h,t)      "hex h holds an atom at t that existed at t-1"
  bf(x,y,h,d,t) cw(x,h,t) ck(k,x,y,t)            Tseitin witnesses
  comp(k,x,t) mv(x,t)                            held component / moved
  sel(s,w)                                       goal dimer selector
"""

import argparse
import sys
import time

from pysat.formula import CNF, IDPool

try:
    from instances import SW_CASES, DIRS, hex_ball, sw_scaled
except ImportError:
    from sat.instances import SW_CASES, DIRS, hex_ball, sw_scaled

ACTIONS2 = ["rot_cw", "rot_ccw", "grab", "drop", "wait"]


def rot_about(base, h, cw):
    q, r = h[0] - base[0], h[1] - base[1]
    if cw:  # dir D -> D+1
        return (base[0] - r, base[1] + q + r)
    return (base[0] + q + r, base[1] - q)


class Encoder2:
    def __init__(self, inst, horizon):
        self.inst = inst
        self.T = horizon
        self.hexes = hex_ball(inst.radius)
        self.hexset = set(self.hexes)
        self.atoms = list(inst.atoms)
        self.pool = IDPool()
        self.cnf = CNF()
        t0 = time.perf_counter()
        self._build()
        self.encode_time = time.perf_counter() - t0

    def v(self, *key):
        return self.pool.id(key)

    def add(self, clause):
        self.cnf.append(clause)

    def at_most_one(self, lits):
        for i in range(len(lits)):
            for j in range(i + 1, len(lits)):
                self.add([-lits[i], -lits[j]])

    def exactly_one(self, lits):
        self.add(list(lits))
        self.at_most_one(lits)

    # ------------------------------------------------------------------
    def _build(self):
        inst, T = self.inst, self.T
        times = range(T + 1)
        steps = range(T)
        X = self.atoms
        ninputs = len(inst.pools)
        GDIRS = range(3)  # bonder direction domain (clingo layout.lp D<3)

        # ---- layout: exactly-one placement per part ----
        self.exactly_one([self.v("base", h) for h in self.hexes])
        for i in range(1, ninputs + 1):
            self.exactly_one([self.v("spawn", i, h) for h in self.hexes])
        self.exactly_one([self.v("cpos", h) for h in self.hexes])
        self.exactly_one([self.v("gpos", h) for h in self.hexes])
        self.exactly_one([self.v("gdir", d) for d in GDIRS])
        # bonder's second cell must be on the board
        self.placements = []  # (h1, d, h2), both cells on-board
        for h1 in self.hexes:
            for d in GDIRS:
                h2 = (h1[0] + DIRS[d][0], h1[1] + DIRS[d][1])
                if h2 in self.hexset:
                    self.placements.append((h1, d, h2))
                else:
                    self.add([-self.v("gpos", h1), -self.v("gdir", d)])

        # ---- OM part-non-overlap rule (asp/layout.lp foot/3) ----
        single_parts = ([("base",)]
                        + [("spawn", i) for i in range(1, ninputs + 1)]
                        + [("cpos",)])
        for h in self.hexes:
            self.at_most_one([self.v(*p, h) for p in single_parts])
            # bonder cell 1 is gpos itself
            for p in single_parts:
                self.add([-self.v("gpos", h), -self.v(*p, h)])
        for (h1, d, h2) in self.placements:
            for p in single_parts:
                self.add([-self.v("gpos", h1), -self.v("gdir", d),
                          -self.v(*p, h2)])
        # fixed product hexes model a real output part: nothing overlaps it
        if inst.products:
            prod_hexes = set(inst.products.values())
            for hp in prod_hexes:
                for p in single_parts:
                    self.add([-self.v(*p, hp)])
                self.add([-self.v("gpos", hp)])
                for (h1, d, h2) in self.placements:
                    if h2 == hp:
                        self.add([-self.v("gpos", h1), -self.v("gdir", d)])

        # ---- instructions ----
        for t in steps:
            self.exactly_one([self.v("do", a, t) for a in ACTIONS2])

        # ---- orientation ----
        for t in times:
            self.exactly_one([self.v("orient", d, t) for d in range(6)])
        for t in steps:
            cwl, ccwl = self.v("do", "rot_cw", t), self.v("do", "rot_ccw", t)
            for d in range(6):
                od = self.v("orient", d, t)
                self.add([-od, -cwl, self.v("orient", (d + 1) % 6, t + 1)])
                self.add([-od, -ccwl, self.v("orient", (d + 5) % 6, t + 1)])
                self.add([-od, cwl, ccwl, self.v("orient", d, t + 1)])

        # ---- gripper = base + dir(orient) (length 1), on-board ----
        for t in times:
            for b in self.hexes:
                for d in range(6):
                    g = (b[0] + DIRS[d][0], b[1] + DIRS[d][1])
                    pre = [-self.v("base", b), -self.v("orient", d, t)]
                    if g in self.hexset:
                        self.add(pre + [self.v("grip", g, t)])
                    else:
                        self.add(pre)
            self.at_most_one([self.v("grip", h, t) for h in self.hexes])

        # ---- existence: r(i,1) always; r(i,n+1) spawns when hex clears ----
        for x in X:
            i, n = x
            if n == 1:
                for t in times:
                    self.add([self.v("ex", x, t)])
            else:
                self.add([-self.v("ex", x, 0)])
        # eo(h,t) := some atom that existed at t-1 sits on h at t
        for t in range(1, T + 1):
            for h in self.hexes:
                eo = self.v("eo", h, t)
                wits = []
                for x in X:
                    w = self.v("exw", x, h, t)
                    self.add([-w, self.v("ex", x, t - 1)])
                    self.add([-w, self.v("at", x, h, t)])
                    self.add([w, -self.v("ex", x, t - 1),
                              -self.v("at", x, h, t)])
                    self.add([-w, eo])
                    wits.append(w)
                self.add([-eo] + wits)
        for x in X:
            i, n = x
            if n == 1:
                continue
            pred = (i, n - 1)
            for t in steps:
                e0, e1 = self.v("ex", x, t), self.v("ex", x, t + 1)
                self.add([-e0, e1])  # persistence
                for h in self.hexes:
                    sp = self.v("spawn", i, h)
                    eo = self.v("eo", h, t + 1)
                    # spawn happens when predecessor exists & hex clear
                    self.add([-self.v("ex", pred, t), e0, -sp, eo, e1])
                    # completion: a fresh atom implies hex was clear ...
                    self.add([-e1, e0, -sp, -eo])
                    # ... predecessor existed ...
                    self.add([-e1, e0, self.v("ex", pred, t)])
                    # ... and the atom appears on the spawn hex
                    self.add([-e1, e0, -sp, self.v("at", x, h, t + 1)])

        # ---- atom positions ----
        for i in range(1, ninputs + 1):
            for h in self.hexes:  # r(i,1) starts on input i's hex
                self.add([-self.v("spawn", i, h), self.v("at", (i, 1), h, 0)])
        for t in times:
            for x in X:
                ats = [self.v("at", x, h, t) for h in self.hexes]
                self.at_most_one(ats)
                self.add([-self.v("ex", x, t)] + ats)  # exists -> somewhere
                for a in ats:  # not exists -> nowhere
                    self.add([self.v("ex", x, t), -a])
            for h in self.hexes:  # no two atoms share a hex
                self.at_most_one([self.v("at", x, h, t) for x in X])
                for x in X:  # arm base blocks atoms
                    self.add([-self.v("base", h), -self.v("at", x, h, t)])

        # ---- holding ----
        for x in X:
            self.add([-self.v("hold", x, 0)])
        for t in times:
            self.at_most_one([self.v("hold", x, t) for x in X])
        for t in steps:
            grab, drop = self.v("do", "grab", t), self.v("do", "drop", t)
            for x in X:
                hx, hx1 = self.v("hold", x, t), self.v("hold", x, t + 1)
                for h in self.hexes:
                    self.add([-grab, -self.v("grip", h, t),
                              -self.v("at", x, h, t), hx1])
                self.add([-hx, drop, hx1])
                self.add([-drop, -hx1])
                self.add([-hx1, hx, grab])
                for h in self.hexes:
                    self.add([-hx1, hx, -self.v("grip", h, t),
                              self.v("at", x, h, t)])
                self.add([-grab, -hx])  # hand must be empty
            for h in self.hexes:  # something to grab
                self.add([-grab, -self.v("grip", h, t)]
                         + [self.v("at", x, h, t) for x in X])
            self.add([-drop] + [self.v("hold", x, t) for x in X])
        for t in range(1, T + 1):  # held atom rides the gripper
            for x in X:
                for h in self.hexes:
                    self.add([-self.v("hold", x, t), -self.v("grip", h, t),
                              self.v("at", x, h, t)])

        # ---- types: salt(x,t); calcification ----
        for x in X:
            self.add([-self.v("salt", x, 0)])
        for t in steps:
            for x in X:
                s0, s1 = self.v("salt", x, t), self.v("salt", x, t + 1)
                self.add([-s0, s1])  # persistence
                wits = []
                for h in self.hexes:
                    cp, at = self.v("cpos", h), self.v("at", x, h, t)
                    self.add([-cp, -at, s1])  # on the calcifier -> salt
                    w = self.v("cw", x, h, t)
                    self.add([-w, cp])
                    self.add([-w, at])
                    wits.append(w)
                self.add([-s1, s0] + wits)  # completion

        # ---- bonds ----
        self.pairs = [(X[i], X[j]) for i in range(len(X))
                      for j in range(i + 1, len(X))]

        def pvar(x, y, t):
            p = (x, y) if (x, y) in self.pairs else (y, x)
            return self.v("bond", p, t)

        for t in times:
            for (h1, d, h2) in self.placements:
                for x in X:
                    for y in X:
                        if x == y:
                            continue
                        gp, gd = self.v("gpos", h1), self.v("gdir", d)
                        ax = self.v("at", x, h1, t)
                        ay = self.v("at", y, h2, t)
                        self.add([-gp, -gd, -ax, -ay, pvar(x, y, t)])
                        w = self.v("bf", x, y, h1, d, t)
                        self.add([-w, gp])
                        self.add([-w, gd])
                        self.add([-w, ax])
                        self.add([-w, ay])
        for p in self.pairs:
            for t in times:
                b = self.v("bond", p, t)
                wits = [self.v("bf", u, w2, h1, d, t)
                        for (h1, d, h2) in self.placements
                        for (u, w2) in (p, (p[1], p[0]))]
                if t == 0:
                    self.add([-b] + wits)
                else:
                    self.add([-self.v("bond", p, t - 1), b])
                    self.add([-b, self.v("bond", p, t - 1)] + wits)

        # ---- held bond-connected component (levels; exact closure) ----
        # comp(0,x,t) == hold(x,t); comp(k+1,x,t) == comp(k,x,t) or
        # exists y: comp(k,y,t) and bond(x,y,t).  K = natoms-1 levels.
        K = len(X) - 1

        def compvar(k, x, t):  # level 0 is just "held"
            return self.v("hold", x, t) if k == 0 else self.v("comp", k, x, t)

        for t in steps:
            for k in range(1, K + 1):
                for x in X:
                    ck1 = compvar(k, x, t)
                    prev = compvar(k - 1, x, t)
                    self.add([-prev, ck1])
                    wits = []
                    for y in X:
                        if y == x:
                            continue
                        cy = compvar(k - 1, y, t)
                        b = pvar(x, y, t)
                        w = self.v("ck", k, x, y, t)
                        self.add([-w, cy])
                        self.add([-w, b])
                        self.add([w, -cy, -b])
                        self.add([-w, ck1])
                        wits.append(w)
                    self.add([-ck1, prev] + wits)

        def comp(x, t):
            return compvar(K, x, t)

        # ---- moved(x,t) := turn(t) and comp(x,t) ----
        for t in steps:
            cwl, ccwl = self.v("do", "rot_cw", t), self.v("do", "rot_ccw", t)
            for x in X:
                mv = self.v("mv", x, t)
                self.add([-mv, cwl, ccwl])
                self.add([-mv, comp(x, t)])
                self.add([-cwl, -comp(x, t), mv])
                self.add([-ccwl, -comp(x, t), mv])

        # ---- rigid motion + frame ----
        for t in steps:
            for rot, cw in (("rot_cw", True), ("rot_ccw", False)):
                dl = self.v("do", rot, t)
                for b in self.hexes:
                    bl = self.v("base", b)
                    for h in self.hexes:
                        h2 = rot_about(b, h, cw)
                        for x in X:
                            pre = [-dl, -comp(x, t), -bl,
                                   -self.v("at", x, h, t)]
                            if h2 in self.hexset:
                                self.add(pre + [self.v("at", x, h2, t + 1)])
                            else:  # swing off the board is illegal
                                self.add(pre)
            for x in X:  # frame: unmoved atoms stay put
                mv = self.v("mv", x, t)
                for h in self.hexes:
                    self.add([-self.v("at", x, h, t), mv,
                              self.v("at", x, h, t + 1)])

        # ---- goal at the horizon: exact salt--water dimer ----
        sels = []
        for s in X:  # s = the salt atom, w = the water atom
            for w in X:
                if s == w:
                    continue
                sel = self.v("sel", s, w)
                sels.append(sel)
                self.add([-sel, self.v("ex", s, T)])
                self.add([-sel, self.v("ex", w, T)])
                self.add([-sel, self.v("salt", s, T)])
                self.add([-sel, -self.v("salt", w, T)])
                self.add([-sel, pvar(s, w, T)])
                self.add([-sel, -self.v("hold", s, T)])
                self.add([-sel, -self.v("hold", w, T)])
                for z in X:  # exact degree 1 on both dimer atoms
                    if z in (s, w):
                        continue
                    self.add([-sel, -pvar(s, z, T)])
                    self.add([-sel, -pvar(w, z, T)])
                if inst.products:
                    self.add([-sel,
                              self.v("at", s, inst.products["salt"], T)])
                    self.add([-sel,
                              self.v("at", w, inst.products["water"], T)])
        self.add(sels)

    # ------------------------------------------------------------------
    def layout_assumptions(self):
        inst = self.inst
        lits = [self.v("base", inst.base), self.v("orient", inst.orient0, 0),
                self.v("cpos", inst.calc), self.v("gpos", inst.glyph_pos),
                self.v("gdir", inst.glyph_dir)]
        for i, h in enumerate(inst.spawn_fixed, 1):
            lits.append(self.v("spawn", i, h))
        return lits

    @property
    def nvars(self):
        return self.pool.top

    @property
    def nclauses(self):
        return len(self.cnf.clauses)

    def non_wait_literals(self):
        return [-self.v("do", "wait", t) for t in range(self.T)]


def main():
    try:
        from solvers import solve as run_solver
        from decode2 import decode_model2, format_plan2
        from validate2 import validate_plan2
    except ImportError:
        from sat.solvers import solve as run_solver
        from sat.decode2 import decode_model2, format_plan2
        from sat.validate2 import validate_plan2

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case", default="sw",
                    help="sw | sw-omsim | sw-rN (scaled board)")
    ap.add_argument("--horizon", type=int, required=True)
    ap.add_argument("--fixed-layout", action="store_true")
    ap.add_argument("--backend", default="cadical195",
                    choices=["cadical195", "glucose42", "kissat"])
    ap.add_argument("--timeout", type=float, default=None)
    args = ap.parse_args()

    if args.case in SW_CASES:
        inst = SW_CASES[args.case]
    elif args.case.startswith("sw-r"):
        inst = sw_scaled(int(args.case[4:]))
    else:
        sys.exit(f"unknown case {args.case}")

    enc = Encoder2(inst, args.horizon)
    assumptions = enc.layout_assumptions() if args.fixed_layout else []
    print(f"case {inst.name} T={args.horizon} "
          f"mode={'fixed' if args.fixed_layout else 'free'}: "
          f"{enc.nvars} vars, {enc.nclauses} clauses, "
          f"encode {enc.encode_time:.3f}s")
    sat, model, solve_t = run_solver(args.backend, enc.cnf, assumptions,
                                     timeout=args.timeout)
    res = "TIMEOUT" if sat is None else ("SAT" if sat else "UNSAT")
    print(f"{args.backend}: {res} in {solve_t:.3f}s")
    if sat:
        plan = decode_model2(enc, model)
        print(format_plan2(plan, inst))
        errors = validate_plan2(inst, plan)
        if errors:
            print("VALIDATION FAILED:")
            for e in errors:
                print("  -", e)
            sys.exit(1)
        print("validator: plan is valid")


if __name__ == "__main__":
    main()
