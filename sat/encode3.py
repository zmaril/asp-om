"""Harness-conformant planning-as-SAT encoder (see harness/SPEC.md on the
`harness` branch).

Generalizes sat/encode2.py to the shared puzzle JSON:

  * parts are instance-driven: one arm (any fixed length), an optional
    calcifier, an optional bonder;
  * every reagent is a placeable input part (single-atom reagents only --
    the shared instances have no multi-atom reagents; the adapter rejects
    them honestly);
  * the product is a placeable OUTPUT part (position + rotation decision
    variables); its footprint participates in the part-non-overlap rule;
    the goal requires the exact product molecule (elements, bonds, exact
    degrees, unheld) to rest exactly on the output hexes at the horizon.
    (harness accepts completion at any t <= t_max; completion persists
    under trailing waits, so goal-at-horizon has the same feasibility and
    the same minimum non-wait instruction count.)
  * atom elements: each atom's birth element is its reagent's element;
    the only dynamic change is calcification (elemental -> salt), encoded
    as one bit salt(x,t) with salt(x,0) = (birth element == salt).

Any puzzle field may pin a placement (position/rotation); pins become
unit clauses.  Everything else (semantics of motion, grabbing,
calcification/spawn/bond timing, collision rules) is identical to
sat/encode2.py == harness SPEC section 5.
"""

import time

from pysat.formula import CNF, IDPool

try:
    from instances import DIRS, hex_ball
except ImportError:
    from sat.instances import DIRS, hex_ball

ACTIONS2 = ["rot_cw", "rot_ccw", "grab", "drop", "wait"]

ELEMENTAL = {"air", "earth", "fire", "water"}


def rot_about(base, h, cw):
    q, r = h[0] - base[0], h[1] - base[1]
    if cw:
        return (base[0] - r, base[1] + q + r)
    return (base[0] + q + r, base[1] - q)


def rot_k(offset, k):
    """rot_cw applied k times to a relative offset."""
    q, r = offset
    for _ in range(k % 6):
        q, r = -r, q + r
    return (q, r)


class HarnessPuzzle:
    """Parsed harness puzzle JSON, restricted to the supported subset."""

    def __init__(self, data):
        self.name = data["name"]
        self.radius = data["board_radius"]
        self.t_max = data["t_max"]
        if len(data["products"]) != 1:
            raise ValueError("only single-product puzzles supported")
        self.product = data["products"][0]
        if not 1 <= len(self.product["atoms"]) <= 2:
            raise ValueError("only 1- or 2-atom products supported")
        self.reagents = data["reagents"]
        for rg in self.reagents:
            if len(rg["atoms"]) != 1:
                raise ValueError("only single-atom reagents supported")
        arms = [p for p in data["parts"] if p["type"] == "arm"]
        if len(arms) != 1:
            raise ValueError("exactly one arm supported")
        self.arm = arms[0]
        self.arm_len = self.arm.get("length", 1)
        calcs = [p for p in data["parts"] if p["type"] == "calcifier"]
        bonders = [p for p in data["parts"] if p["type"] == "bonder"]
        if len(calcs) > 1 or len(bonders) > 1:
            raise ValueError("at most one calcifier and one bonder")
        self.calcifier = calcs[0] if calcs else None
        self.bonder = bonders[0] if bonders else None
        unknown = [p for p in data["parts"] if p["type"] not in ("arm", "calcifier", "bonder")]
        if unknown:
            raise ValueError(f"unsupported part types: {[p['type'] for p in unknown]}")
        # atoms (i, n): reagent index i (1-based), pool copy n
        self.pools = tuple(rg["pool"] for rg in self.reagents)
        self.elem0 = {}
        for i, rg in enumerate(self.reagents, 1):
            for n in range(1, rg["pool"] + 1):
                self.elem0[(i, n)] = rg["atoms"][0]["element"]

    @property
    def atoms(self):
        return tuple((i, n) for i, p in enumerate(self.pools, 1) for n in range(1, p + 1))


class Encoder3:
    def __init__(self, pz, horizon=None):
        self.pz = pz
        self.T = pz.t_max if horizon is None else horizon
        self.hexes = hex_ball(pz.radius)
        self.hexset = set(self.hexes)
        self.atoms = list(pz.atoms)
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
        pz, T = self.pz, self.T
        times = range(T + 1)
        steps = range(T)
        X = self.atoms
        ninputs = len(pz.pools)
        L = pz.arm_len

        # ---- layout variables ----
        self.exactly_one([self.v("base", h) for h in self.hexes])
        for i in range(1, ninputs + 1):
            self.exactly_one([self.v("spawn", i, h) for h in self.hexes])
        if pz.calcifier:
            self.exactly_one([self.v("cpos", h) for h in self.hexes])
        self.placements = []
        if pz.bonder:
            self.exactly_one([self.v("gpos", h) for h in self.hexes])
            self.exactly_one([self.v("gdir", d) for d in range(3)])
            for h1 in self.hexes:
                for d in range(3):
                    h2 = (h1[0] + DIRS[d][0], h1[1] + DIRS[d][1])
                    if h2 in self.hexset:
                        self.placements.append((h1, d, h2))
                    else:
                        self.add([-self.v("gpos", h1), -self.v("gdir", d)])

        # output part: position + rotation; footprint per (p, k)
        self.prod_offsets = [tuple(a["pos"]) for a in pz.product["atoms"]]
        self.orots = range(6) if len(self.prod_offsets) > 1 else range(1)
        self.exactly_one([self.v("opos", h) for h in self.hexes])
        self.exactly_one([self.v("orot", k) for k in self.orots])
        self.out_placements = []  # (p, k, cells)
        for p in self.hexes:
            for k in self.orots:
                cells = tuple(
                    (p[0] + rot_k(o, k)[0], p[1] + rot_k(o, k)[1]) for o in self.prod_offsets
                )
                if all(c in self.hexset for c in cells):
                    self.out_placements.append((p, k, cells))
                else:
                    self.add([-self.v("opos", p), -self.v("orot", k)])

        # ---- part-non-overlap (footprints pairwise disjoint) ----
        single_parts = (
            [("base",)]
            + [("spawn", i) for i in range(1, ninputs + 1)]
            + ([("cpos",)] if pz.calcifier else [])
        )
        for h in self.hexes:
            self.at_most_one([self.v(*p, h) for p in single_parts])
        if pz.bonder:
            for h in self.hexes:
                for p in single_parts:
                    self.add([-self.v("gpos", h), -self.v(*p, h)])
            for h1, d, h2 in self.placements:
                for p in single_parts:
                    self.add([-self.v("gpos", h1), -self.v("gdir", d), -self.v(*p, h2)])
        for p, k, cells in self.out_placements:
            ol = [-self.v("opos", p), -self.v("orot", k)]
            for c in cells:
                for sp in single_parts:
                    self.add([*ol, -self.v(*sp, c)])
                if pz.bonder:
                    self.add([*ol, -self.v("gpos", c)])
            if pz.bonder:
                for h1, d, h2 in self.placements:
                    if h2 in cells:
                        self.add([*ol, -self.v("gpos", h1), -self.v("gdir", d)])

        # ---- pins from the puzzle file ----
        def pin(cond, *lits):
            if cond:
                for lit in lits:
                    self.add([lit])

        for i, rg in enumerate(pz.reagents, 1):
            pin("position" in rg, self.v("spawn", i, tuple(rg.get("position", (0, 0)))))
        pin("position" in pz.arm, self.v("base", tuple(pz.arm.get("position", (0, 0)))))
        if "rotation" in pz.arm:
            self.add([self.v("orient", pz.arm["rotation"], 0)])
        if pz.calcifier and "position" in pz.calcifier:
            self.add([self.v("cpos", tuple(pz.calcifier["position"]))])
        if pz.bonder and "position" in pz.bonder:
            bp = tuple(pz.bonder["position"])
            bk = pz.bonder.get("rotation", 0)
            if bk >= 3:  # normalize to the dir<3 representative
                bp = (bp[0] + DIRS[bk][0], bp[1] + DIRS[bk][1])
                bk = bk - 3
            self.add([self.v("gpos", bp)])
            self.add([self.v("gdir", bk)])
        if "position" in pz.product:
            self.add([self.v("opos", tuple(pz.product["position"]))])
            if len(self.orots) > 1:
                self.add([self.v("orot", pz.product.get("rotation", 0))])

        # ---- instructions / orientation / gripper ----
        for t in steps:
            self.exactly_one([self.v("do", a, t) for a in ACTIONS2])
        for t in times:
            self.exactly_one([self.v("orient", d, t) for d in range(6)])
        for t in steps:
            cwl, ccwl = self.v("do", "rot_cw", t), self.v("do", "rot_ccw", t)
            for d in range(6):
                od = self.v("orient", d, t)
                self.add([-od, -cwl, self.v("orient", (d + 1) % 6, t + 1)])
                self.add([-od, -ccwl, self.v("orient", (d + 5) % 6, t + 1)])
                self.add([-od, cwl, ccwl, self.v("orient", d, t + 1)])
        for t in times:
            for b in self.hexes:
                for d in range(6):
                    g = (b[0] + L * DIRS[d][0], b[1] + L * DIRS[d][1])
                    pre = [-self.v("base", b), -self.v("orient", d, t)]
                    if g in self.hexset:
                        self.add([*pre, self.v("grip", g, t)])
                    else:
                        self.add(pre)
            self.at_most_one([self.v("grip", h, t) for h in self.hexes])

        # ---- existence / spawning (identical to encode2) ----
        for x in X:
            i, n = x
            if n == 1:
                for t in times:
                    self.add([self.v("ex", x, t)])
            else:
                self.add([-self.v("ex", x, 0)])
        for t in range(1, T + 1):
            for h in self.hexes:
                eo = self.v("eo", h, t)
                wits = []
                for x in X:
                    w = self.v("exw", x, h, t)
                    self.add([-w, self.v("ex", x, t - 1)])
                    self.add([-w, self.v("at", x, h, t)])
                    self.add([w, -self.v("ex", x, t - 1), -self.v("at", x, h, t)])
                    self.add([-w, eo])
                    wits.append(w)
                self.add([-eo, *wits])
        for x in X:
            i, n = x
            if n == 1:
                continue
            pred = (i, n - 1)
            for t in steps:
                e0, e1 = self.v("ex", x, t), self.v("ex", x, t + 1)
                self.add([-e0, e1])
                for h in self.hexes:
                    sp = self.v("spawn", i, h)
                    eo = self.v("eo", h, t + 1)
                    self.add([-self.v("ex", pred, t), e0, -sp, eo, e1])
                    self.add([-e1, e0, -sp, -eo])
                    self.add([-e1, e0, self.v("ex", pred, t)])
                    self.add([-e1, e0, -sp, self.v("at", x, h, t + 1)])

        # ---- positions ----
        for i in range(1, ninputs + 1):
            for h in self.hexes:
                self.add([-self.v("spawn", i, h), self.v("at", (i, 1), h, 0)])
        for t in times:
            for x in X:
                ats = [self.v("at", x, h, t) for h in self.hexes]
                self.at_most_one(ats)
                self.add([-self.v("ex", x, t), *ats])
                for a in ats:
                    self.add([self.v("ex", x, t), -a])
            for h in self.hexes:
                self.at_most_one([self.v("at", x, h, t) for x in X])
                for x in X:
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
                    self.add([-grab, -self.v("grip", h, t), -self.v("at", x, h, t), hx1])
                self.add([-hx, drop, hx1])
                self.add([-drop, -hx1])
                self.add([-hx1, hx, grab])
                for h in self.hexes:
                    self.add([-hx1, hx, -self.v("grip", h, t), self.v("at", x, h, t)])
                self.add([-grab, -hx])
            for h in self.hexes:
                self.add([-grab, -self.v("grip", h, t)] + [self.v("at", x, h, t) for x in X])
            self.add([-drop] + [self.v("hold", x, t) for x in X])
        for t in range(1, T + 1):
            for x in X:
                for h in self.hexes:
                    self.add([-self.v("hold", x, t), -self.v("grip", h, t), self.v("at", x, h, t)])

        # ---- element bit: salt(x,t) ----
        for x in X:
            if pz.elem0[x] == "salt":
                self.add([self.v("salt", x, 0)])
            else:
                self.add([-self.v("salt", x, 0)])
        for t in steps:
            for x in X:
                s0, s1 = self.v("salt", x, t), self.v("salt", x, t + 1)
                self.add([-s0, s1])
                wits = []
                if pz.calcifier and pz.elem0[x] in ELEMENTAL:
                    for h in self.hexes:
                        cp, at = self.v("cpos", h), self.v("at", x, h, t)
                        self.add([-cp, -at, s1])
                        w = self.v("cw", x, h, t)
                        self.add([-w, cp])
                        self.add([-w, at])
                        wits.append(w)
                self.add([-s1, s0, *wits])

        # ---- bonds ----
        self.pairs = [(X[i], X[j]) for i in range(len(X)) for j in range(i + 1, len(X))]

        def pvar(x, y, t):
            p = (x, y) if (x, y) in self.pairs else (y, x)
            return self.v("bond", p, t)

        for t in times:
            for h1, d, h2 in self.placements:
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
                wits = [
                    self.v("bf", u, w2, h1, d, t)
                    for (h1, d, h2) in self.placements
                    for (u, w2) in (p, (p[1], p[0]))
                ]
                if t == 0:
                    self.add([-b, *wits])
                else:
                    self.add([-self.v("bond", p, t - 1), b])
                    self.add([-b, self.v("bond", p, t - 1), *wits])

        # ---- held component / rigid motion (identical to encode2) ----
        K = len(X) - 1 if pz.bonder else 0

        def compvar(k, x, t):
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
                    self.add([-ck1, prev, *wits])

        def comp(x, t):
            return compvar(K, x, t)

        for t in steps:
            cwl, ccwl = self.v("do", "rot_cw", t), self.v("do", "rot_ccw", t)
            for x in X:
                mv = self.v("mv", x, t)
                self.add([-mv, cwl, ccwl])
                self.add([-mv, comp(x, t)])
                self.add([-cwl, -comp(x, t), mv])
                self.add([-ccwl, -comp(x, t), mv])
        for t in steps:
            for rot, cw in (("rot_cw", True), ("rot_ccw", False)):
                dl = self.v("do", rot, t)
                for b in self.hexes:
                    bl = self.v("base", b)
                    for h in self.hexes:
                        h2 = rot_about(b, h, cw)
                        for x in X:
                            pre = [-dl, -comp(x, t), -bl, -self.v("at", x, h, t)]
                            if h2 in self.hexset:
                                self.add([*pre, self.v("at", x, h2, t + 1)])
                            else:
                                self.add(pre)
            for x in X:
                mv = self.v("mv", x, t)
                for h in self.hexes:
                    self.add([-self.v("at", x, h, t), mv, self.v("at", x, h, t + 1)])

        # ---- goal: exact product on the output part at the horizon ----
        nslots = len(self.prod_offsets)
        slot_elems = [a["element"] for a in pz.product["atoms"]]
        prod_bonds = {frozenset(b) for b in pz.product.get("bonds", [])}
        sels = []

        # candidate atoms per slot: birth element must be able to reach
        # the slot element (salt slot: anything calcifiable or salt;
        # elemental slot: exactly that birth element)
        def candidates(e):
            if e == "salt":
                return [x for x in X if pz.elem0[x] == "salt" or pz.elem0[x] in ELEMENTAL]
            return [x for x in X if pz.elem0[x] == e]

        if nslots == 1:
            e = slot_elems[0]
            for x in candidates(e):
                sel = self.v("sel", x)
                sels.append(sel)
                self.add([-sel, self.v("ex", x, T)])
                self.add([-sel, -self.v("hold", x, T)])
                lit = self.v("salt", x, T)
                self.add([-sel, lit if e == "salt" else -lit])
                for p2 in self.pairs:  # exact degree 0
                    if x in p2:
                        self.add([-sel, -self.v("bond", p2, T)])
                for p, k, cells in self.out_placements:
                    self.add(
                        [-sel, -self.v("opos", p), -self.v("orot", k), self.v("at", x, cells[0], T)]
                    )
        else:
            b01 = frozenset((0, 1)) in prod_bonds
            for a0 in candidates(slot_elems[0]):
                for a1 in candidates(slot_elems[1]):
                    if a0 == a1:
                        continue
                    sel = self.v("sel", a0, a1)
                    sels.append(sel)
                    for x, e in ((a0, slot_elems[0]), (a1, slot_elems[1])):
                        self.add([-sel, self.v("ex", x, T)])
                        self.add([-sel, -self.v("hold", x, T)])
                        lit = self.v("salt", x, T)
                        self.add([-sel, lit if e == "salt" else -lit])
                    blit = pvar(a0, a1, T)
                    self.add([-sel, blit if b01 else -blit])
                    for x in (a0, a1):  # exact degrees
                        for z in X:
                            if z in (a0, a1) or z == x:
                                continue
                            self.add([-sel, -pvar(x, z, T)])
                    for p, k, cells in self.out_placements:
                        ol = [-sel, -self.v("opos", p), -self.v("orot", k)]
                        self.add([*ol, self.v("at", a0, cells[0], T)])
                        self.add([*ol, self.v("at", a1, cells[1], T)])
        self.add(sels)

    @property
    def nvars(self):
        return self.pool.top

    @property
    def nclauses(self):
        return len(self.cnf.clauses)

    def non_wait_literals(self):
        return [-self.v("do", "wait", t) for t in range(self.T)]
