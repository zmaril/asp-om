"""Planning-as-SAT encoding of the Opus Magnum phase-1 fragment.

Builds one CNF over boolean variables for
  (i)  the machine layout: arm base hex, arm length, initial orientation,
       and (case b) bonding-glyph position/orientation, all chosen from the
       board's hex ball; and
  (ii) the per-timestep instruction program (exactly one of
       rot_cw/rot_ccw/grab/drop/wait per step) with transition and frame
       axioms tying layout to execution, and the product goal asserted at
       the horizon T.

The same CNF serves both modes:
  * free layout   : the solver chooses the layout variables;
  * --fixed-layout: the clingo arm's layout is pinned via unit assumptions
    on the layout variables (pysat `assumptions=`; for kissat the units are
    appended to the DIMACS dump).

Mechanics semantics replicate asp/core.lp + asp/bond_instance.lp exactly
(see the design brief): held atoms ride the gripper, free atoms are inert,
no two atoms share a hex, gripper stays on the board, grab needs an empty
hand and an atom under the gripper, drop needs a held atom, bonds form
whenever both glyph cells are occupied and persist forever, and rotating
while holding a bonded atom is forbidden (phase-1 rigid-motion restriction).

Variable families (via pysat IDPool):
  base(q,r)         arm base position           [exactly-one]
  alen(l)           arm length 1..max_arm_len   [exactly-one]
  gpos(q,r),gdir(d) glyph placement (case b)    [exactly-one each]
  do(a,t)           instruction at step t       [exactly-one per step]
  orient(d,t)       arm orientation             [exactly-one per time]
  grip(q,r,t)       gripper hex (derived)       [at-most-one per time]
  at(x,q,r,t)       atom position               [exactly-one per (x,t)]
  hold(x,t)         arm holds atom x            [at-most-one per time]
  bond(p,t)         unordered atom pair bonded
  bf(x,y,h,d,t)     bond-formation witness (Tseitin, for completion)
"""

import argparse
import os
import sys
import time

from pysat.formula import CNF, IDPool

try:
    from instances import ACTIONS, CASES, DIRS, Instance, hex_ball
except ImportError:  # imported as sat.encode
    from sat.instances import ACTIONS, CASES, DIRS, Instance, hex_ball  # noqa: F401


class Encoder:
    def __init__(self, inst, horizon):
        self.inst = inst
        self.T = horizon
        self.hexes = hex_ball(inst.radius)
        self.hexset = set(self.hexes)
        self.lengths = list(range(1, inst.max_arm_len + 1))
        self.pool = IDPool()
        self.cnf = CNF()
        self.encode_time = None
        t0 = time.perf_counter()
        self._build()
        self.encode_time = time.perf_counter() - t0

    # -- variables ----------------------------------------------------------
    def v(self, *key):
        return self.pool.id(key)

    # -- clause helpers ------------------------------------------------------
    def add(self, clause):
        self.cnf.append(clause)

    def at_most_one(self, lits):
        for i in range(len(lits)):
            for j in range(i + 1, len(lits)):
                self.add([-lits[i], -lits[j]])

    def exactly_one(self, lits):
        self.add(list(lits))
        self.at_most_one(lits)

    # -- encoding ------------------------------------------------------------
    def _build(self):
        inst, T = self.inst, self.T
        times = range(T + 1)
        steps = range(T)
        X = inst.atoms

        # ---- layout variables ----
        self.exactly_one([self.v("base", h) for h in self.hexes])
        self.exactly_one([self.v("alen", ln) for ln in self.lengths])
        # initial orientation is orient(d,0); covered by the orient EO below.

        if inst.has_glyph:
            self.exactly_one([self.v("gpos", h) for h in self.hexes])
            self.exactly_one([self.v("gdir", d) for d in range(6)])
            # both glyph cells must be on the board
            for h in self.hexes:
                for d in range(6):
                    h2 = (h[0] + DIRS[d][0], h[1] + DIRS[d][1])
                    if h2 not in self.hexset:
                        self.add([-self.v("gpos", h), -self.v("gdir", d)])

        # ---- instructions: exactly one per step ----
        for t in steps:
            self.exactly_one([self.v("do", a, t) for a in ACTIONS])

        # ---- orientation: exactly one per time, rotation transitions ----
        for t in times:
            self.exactly_one([self.v("orient", d, t) for d in range(6)])
        for t in steps:
            cw, ccw = self.v("do", "rot_cw", t), self.v("do", "rot_ccw", t)
            for d in range(6):
                od = self.v("orient", d, t)
                self.add([-od, -cw, self.v("orient", (d + 1) % 6, t + 1)])
                self.add([-od, -ccw, self.v("orient", (d + 5) % 6, t + 1)])
                self.add([-od, cw, ccw, self.v("orient", d, t + 1)])

        # ---- gripper = base + len*dir(orient); must stay on the board ----
        for t in times:
            for b in self.hexes:
                for ln in self.lengths:
                    for d in range(6):
                        g = (b[0] + ln * DIRS[d][0], b[1] + ln * DIRS[d][1])
                        pre = [-self.v("base", b), -self.v("alen", ln), -self.v("orient", d, t)]
                        if g in self.hexset:
                            self.add([*pre, self.v("grip", g, t)])
                        else:
                            self.add(pre)  # forbidden combo: gripper off-board
            self.at_most_one([self.v("grip", h, t) for h in self.hexes])

        # ---- initial state ----
        for x in X:
            self.add([self.v("at", x, inst.init_at[x], 0)])
            self.add([-self.v("hold", x, 0)])

        # ---- holding: effects, frame, completion, preconditions ----
        for t in steps:
            grab, drop = self.v("do", "grab", t), self.v("do", "drop", t)
            for x in X:
                hx, hx1 = self.v("hold", x, t), self.v("hold", x, t + 1)
                # grab effect: atom under gripper becomes held
                for h in self.hexes:
                    self.add([-grab, -self.v("grip", h, t), -self.v("at", x, h, t), hx1])
                # persistence: held unless dropped
                self.add([-hx, drop, hx1])
                # drop releases
                self.add([-drop, -hx1])
                # completion: newly held only via grab ...
                self.add([-hx1, hx, grab])
                # ... of the atom that sat under the gripper
                for h in self.hexes:
                    self.add([-hx1, hx, -self.v("grip", h, t), self.v("at", x, h, t)])
                # grab precondition: hand empty
                self.add([-grab, -hx])
            # grab precondition: something under the gripper
            for h in self.hexes:
                self.add([-grab, -self.v("grip", h, t)] + [self.v("at", x, h, t) for x in X])
            # drop precondition: holding something
            self.add([-drop] + [self.v("hold", x, t) for x in X])
        # arm holds at most one atom
        for t in times:
            self.at_most_one([self.v("hold", x, t) for x in X])

        # ---- atom positions ----
        for t in times:
            for x in X:
                self.exactly_one([self.v("at", x, h, t) for h in self.hexes])
            for h in self.hexes:  # no two atoms share a hex
                self.at_most_one([self.v("at", x, h, t) for x in X])
        for t in range(1, T + 1):  # held atom rides the gripper
            for x in X:
                for h in self.hexes:
                    self.add([-self.v("hold", x, t), -self.v("grip", h, t), self.v("at", x, h, t)])
        for t in steps:  # free atoms are inert
            for x in X:
                for h in self.hexes:
                    self.add(
                        [
                            -self.v("at", x, h, t),
                            self.v("hold", x, t + 1),
                            self.v("at", x, h, t + 1),
                        ]
                    )

        # ---- bonds (glyph of bonding) ----
        self.pairs = []
        if inst.has_glyph:
            self.pairs = [(X[i], X[j]) for i in range(len(X)) for j in range(i + 1, len(X))]
            placements = []  # (h1, d, h2) with both cells on-board
            for h1 in self.hexes:
                for d in range(6):
                    h2 = (h1[0] + DIRS[d][0], h1[1] + DIRS[d][1])
                    if h2 in self.hexset:
                        placements.append((h1, d, h2))

            def pvar(x, y, t):
                p = (x, y) if (x, y) in self.pairs else (y, x)
                return self.v("bond", p, t)

            for t in times:
                for h1, d, h2 in placements:
                    for x in X:
                        for y in X:
                            if x == y:
                                continue
                            gp, gd = self.v("gpos", h1), self.v("gdir", d)
                            ax = self.v("at", x, h1, t)
                            ay = self.v("at", y, h2, t)
                            # formation: occupants of the glyph cells bond
                            self.add([-gp, -gd, -ax, -ay, pvar(x, y, t)])
                            # witness for completion: bf -> all four literals
                            w = self.v("bf", x, y, h1, d, t)
                            self.add([-w, gp])
                            self.add([-w, gd])
                            self.add([-w, ax])
                            self.add([-w, ay])
            for x, y in self.pairs:
                for t in times:
                    b = self.v("bond", (x, y), t)
                    wits = [
                        self.v("bf", u, v, h1, d, t)
                        for (h1, d, h2) in placements
                        for (u, v) in ((x, y), (y, x))
                    ]
                    if t == 0:
                        self.add([-b, *wits])
                    else:
                        # persistence + completion
                        self.add([-self.v("bond", (x, y), t - 1), b])
                        self.add([-b, self.v("bond", (x, y), t - 1), *wits])
            # phase-1 restriction: no rotation while holding a bonded atom
            for t in steps:
                for rot in ("rot_cw", "rot_ccw"):
                    for x, y in self.pairs:
                        b = self.v("bond", (x, y), t)
                        self.add([-self.v("do", rot, t), -self.v("hold", x, t), -b])
                        self.add([-self.v("do", rot, t), -self.v("hold", y, t), -b])

        # ---- goal at the horizon ----
        for x, h in inst.products.items():
            self.add([self.v("at", x, h, T)])
            self.add([-self.v("hold", x, T)])
        if inst.require_bond:
            self.add([self.v("bond", p, T) for p in self.pairs])

    # -- fixed-layout assumptions ---------------------------------------------
    def layout_assumptions(self):
        """Unit literals pinning the layout to the clingo arm's layout."""
        fl = self.inst.fixed_layout
        lits = [self.v("base", fl.base), self.v("alen", fl.length), self.v("orient", fl.orient, 0)]
        if self.inst.has_glyph:
            lits += [self.v("gpos", fl.glyph_pos), self.v("gdir", fl.glyph_dir)]
        return lits

    # -- stats -----------------------------------------------------------------
    @property
    def nvars(self):
        return self.pool.top

    @property
    def nclauses(self):
        return len(self.cnf.clauses)

    def non_wait_literals(self):
        """Literals that are true iff step t is a non-wait instruction."""
        return [-self.v("do", "wait", t) for t in range(self.T)]


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from sat.decode import decode_model, format_plan
    from sat.solvers import solve as run_solver
    from sat.validate import validate_plan

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case", choices=sorted(CASES), required=True)
    ap.add_argument("--horizon", type=int, required=True)
    ap.add_argument(
        "--fixed-layout", action="store_true", help="pin the layout to the clingo arm's layout"
    )
    ap.add_argument(
        "--backend", default="cadical195", choices=["cadical195", "glucose42", "kissat"]
    )
    ap.add_argument("--dimacs", help="dump DIMACS (assumptions as units) here")
    args = ap.parse_args()

    inst = CASES[args.case]
    enc = Encoder(inst, args.horizon)
    assumptions = enc.layout_assumptions() if args.fixed_layout else []
    print(
        f"case {args.case} T={args.horizon} "
        f"mode={'fixed' if args.fixed_layout else 'free'}: "
        f"{enc.nvars} vars, {enc.nclauses} clauses, "
        f"encode {enc.encode_time:.3f}s"
    )

    if args.dimacs:
        dump = CNF()
        dump.extend(enc.cnf.clauses)
        for lit in assumptions:
            dump.append([lit])
        dump.to_file(args.dimacs)
        print(f"wrote {args.dimacs}")

    sat, model, solve_t = run_solver(args.backend, enc.cnf, assumptions)
    print(f"{args.backend}: {'SAT' if sat else 'UNSAT'} in {solve_t:.3f}s")
    if sat:
        plan = decode_model(enc, model)
        print(format_plan(plan, inst))
        errors = validate_plan(inst, plan)
        if errors:
            print("VALIDATION FAILED:")
            for e in errors:
                print("  -", e)
            sys.exit(1)
        print("validator: plan is valid")


if __name__ == "__main__":
    main()
