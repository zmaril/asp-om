#!/usr/bin/env python3
"""Independent plan-legality checker for the Picat Opus Magnum encodings.

Usage: python3 validate.py <case> <solver-output-file>
Cases: case1 case2 case3 case2_free case2_free_fixed sw sw_free

Reads the plan from the solver's output ("PLAN {m1,grab}" lines from the
v2-engine files, "  1. rot_cw" lines from the phase-1 files) and simulates
it forward under an independent re-implementation of the world rules
(matching asp/core2.lp semantics), checking:
  * chosen layout is legal (cells on board, part-footprint disjointness,
    base not on an atom, gripper on board),
  * one action per timestep, placements only during the setup phase,
  * grabs/drops legal (hand empty/full, atom present, not held elsewhere),
  * rigid rotation: held component swings about the base; every atom stays
    on the board, off arm bases, and no two atoms share a hex,
  * bonds form ONLY via a bonder glyph (both cells occupied), and persist,
  * calcification only on the calc glyph, spawn only at the spawn hex when
    free and the pool is not exhausted,
  * the case's goal holds in the final state.

The instance data is baked in per case (NOT read from the solver's LAYOUT
lines) so the check is independent of the solver's own view of the world;
free-layout placements are taken from the plan's place_* actions and
checked for legality here.
"""
import re
import sys

DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]
ELEMENTAL = {"air", "earth", "fire", "water"}


def hexdist(a, b):
    return (abs(a[0] - b[0]) + abs(a[1] - b[1])
            + abs(a[0] + a[1] - b[0] - b[1])) // 2


CASES = {
    # atoms: name -> (elem, (q,r)); arms: name -> [base, len, dir, held]
    "case1": dict(
        radius=2, arms={"m1": [(0, 0), 1, 0, None]},
        atoms={"a1": ["salt", (1, 0)]}, bonds=set(),
        calc=[], bonders=[], spawn=None, pending=[],
        goal=lambda st: st.atom_is("a1", None, (-1, 0)) and st.all_unheld(["a1"]),
    ),
    "case2": dict(
        radius=2, arms={"m1": [(0, 0), 1, 0, None]},
        atoms={"a1": ["salt", (1, 0)], "a2": ["salt", (0, 1)]}, bonds=set(),
        calc=[], bonders=[((-1, 0), (0, -1))], spawn=None, pending=[],
        goal=lambda st: (st.atom_is("a1", None, (-1, 0))
                         and st.atom_is("a2", None, (0, -1))
                         and st.bonded("a1", "a2") and st.all_unheld(["a1", "a2"])),
    ),
    "case3": dict(
        radius=2, arms={"m1": [(0, 0), 1, 0, None]},
        atoms={"a1": ["salt", (1, 0)], "a2": ["salt", (2, 0)]},
        bonds={frozenset(("a1", "a2"))},
        calc=[], bonders=[], spawn=None, pending=[],
        goal=lambda st: (st.atom_is("a1", "salt", (-1, 1))
                         and st.atom_is("a2", "salt", (-2, 2))
                         and st.all_unheld(["a1", "a2"])),
    ),
    "case2_free": dict(
        radius=2, arms={},
        atoms={"a1": ["salt", (1, 0)], "a2": ["salt", (0, 1)]}, bonds=set(),
        calc=[], bonders=[], spawn=None, pending=["arm", "bonder"],
        io_cells=[],  # bonder may overlap goal/start hexes (case2 parity)
        goal=lambda st: (st.atom_is("a1", None, (-1, 0))
                         and st.atom_is("a2", None, (0, -1))
                         and st.bonded("a1", "a2") and st.all_unheld(["a1", "a2"])),
    ),
    "sw": dict(
        radius=2, arms={"m1": [(0, 0), 1, 0, None]},
        atoms={}, bonds=set(),
        calc=[(0, 1)], bonders=[((-1, 1), (-1, 0))],
        spawn=dict(cell=(1, 0), elem="water", pool=2), pending=[],
        goal=lambda st: st.sw_goal(),
    ),
    "sw_free": dict(
        radius=2, arms={},
        atoms={}, bonds=set(),
        calc=[], bonders=[],
        spawn=dict(cell=(1, 0), elem="water", pool=2),
        pending=["arm", "calc", "bonder"],
        io_cells=[(1, 0), (0, -1), (1, -1)],  # spawn + product output hexes
        goal=lambda st: st.sw_goal(),
    ),
}
CASES["case2_free_fixed"] = dict(CASES["case2_free"],
                                 arms={"m1": [(0, 0), 1, 0, None]},
                                 bonders=[((-1, 0), (0, -1))], pending=[])


class Fail(Exception):
    pass


class State:
    def __init__(self, cfg):
        self.cfg = cfg
        self.radius = cfg["radius"]
        self.arms = {m: list(v) for m, v in cfg["arms"].items()}
        self.atoms = {n: list(v) for n, v in cfg["atoms"].items()}
        self.bonds = set(cfg["bonds"])
        self.calc = list(cfg["calc"])
        self.bonders = list(cfg["bonders"])
        self.spawn = cfg["spawn"]
        self.nspawned = 0
        self.pending = list(cfg["pending"])
        self.check_layout_static()
        self.post()

    # ---------- helpers ----------
    def on_board(self, c):
        return (abs(c[0]) <= self.radius and abs(c[1]) <= self.radius
                and abs(c[0] + c[1]) <= self.radius)

    def gripper(self, m):
        (bq, br), ln, d, _ = self.arms[m]
        return (bq + ln * DIRS[d][0], br + ln * DIRS[d][1])

    def occupant(self, c):
        for n, (_, pos) in self.atoms.items():
            if pos == c:
                return n
        return None

    def atom_is(self, n, elem, pos):
        return (n in self.atoms and self.atoms[n][1] == pos
                and (elem is None or self.atoms[n][0] == elem))

    def bonded(self, x, y):
        return frozenset((x, y)) in self.bonds

    def held_by(self, n):
        return [m for m, a in self.arms.items() if a[3] == n]

    def all_unheld(self, names):
        return all(not self.held_by(n) for n in names)

    def sw_goal(self):
        for x, (ex, px) in self.atoms.items():
            for y, (ey, py) in self.atoms.items():
                if (ex == "salt" and px == (0, -1) and ey == "water"
                        and py == (1, -1) and self.bonded(x, y)
                        and self.all_unheld([x, y])):
                    return True
        return False

    def component(self, n):
        comp, frontier = {n}, [n]
        while frontier:
            x = frontier.pop()
            for b in self.bonds:
                if x in b:
                    for y in b - {x}:
                        if y not in comp:
                            comp.add(y)
                            frontier.append(y)
        return comp

    # ---------- legality ----------
    def check_layout_static(self):
        cells = []
        for m in self.arms:
            base = self.arms[m][0]
            if not self.on_board(base):
                raise Fail(f"arm {m} base {base} off board")
            if not self.on_board(self.gripper(m)):
                raise Fail(f"arm {m} gripper off board")
            cells.append(base)
        for c in self.calc:
            cells.append(c)
        for a, b in self.bonders:
            if hexdist(a, b) != 1:
                raise Fail(f"bonder cells {a},{b} not adjacent")
            cells.extend([a, b])
        if self.spawn:
            cells.append(self.spawn["cell"])
        for c in cells:
            if not self.on_board(c):
                raise Fail(f"part cell {c} off board")
        # part-footprint disjointness where the case demands it
        if "io_cells" in self.cfg and self.cfg["io_cells"]:
            all_parts = cells + [c for c in self.cfg["io_cells"]
                                 if c not in cells]
            if len(set(all_parts)) != len(all_parts):
                raise Fail(f"overlapping part footprints: {sorted(all_parts)}")
        for m in self.arms:
            if self.occupant(self.arms[m][0]):
                raise Fail(f"arm {m} base on an atom")
        self.check_atoms()

    def check_atoms(self):
        seen = {}
        for n, (_, pos) in self.atoms.items():
            if not self.on_board(pos):
                raise Fail(f"atom {n} off board at {pos}")
            if pos in seen:
                raise Fail(f"atoms {seen[pos]} and {n} collide at {pos}")
            seen[pos] = n
            for m, a in self.arms.items():
                if pos == a[0]:
                    raise Fail(f"atom {n} on arm base of {m}")

    # ---------- world rules (asp/core2.lp parity) ----------
    def post(self):
        if (self.spawn and self.nspawned < self.spawn["pool"]
                and self.occupant(self.spawn["cell"]) is None):
            self.nspawned += 1
            self.atoms[self.nspawned] = [self.spawn["elem"],
                                         self.spawn["cell"]]
        for n, a in self.atoms.items():
            if a[1] in self.calc and a[0] in ELEMENTAL:
                a[0] = "salt"
        for c1, c2 in self.bonders:
            x, y = self.occupant(c1), self.occupant(c2)
            if x is not None and y is not None and x != y:
                self.bonds.add(frozenset((x, y)))

    # ---------- actions ----------
    def step(self, act):
        kind = act[0]
        if kind.startswith("place_"):
            if not self.pending or self.pending[0] != kind[len("place_"):]:
                raise Fail(f"unexpected placement {act}; pending={self.pending}")
            self.pending.pop(0)
            io = self.cfg.get("io_cells", [])
            taken = ([a[0] for a in self.arms.values()] + self.calc
                     + [c for p in self.bonders for c in p] + io)
            if kind == "place_arm":
                _, m, q, r, ln, d = act
                self.arms[m] = [(int(q), int(r)), int(ln), int(d), None]
                if (int(q), int(r)) in taken:
                    raise Fail(f"arm base on another part: {act}")
                self.check_layout_static()
            elif kind == "place_calc":
                c = (int(act[1]), int(act[2]))
                if c in taken:
                    raise Fail(f"calc on another part: {act}")
                self.calc.append(c)
                self.check_layout_static()
            elif kind == "place_bonder":
                c1 = (int(act[1]), int(act[2]))
                c2 = (int(act[3]), int(act[4]))
                for c in (c1, c2):
                    if c in taken:
                        raise Fail(f"bonder on another part: {act}")
                self.bonders.append((c1, c2))
                self.check_layout_static()
            self.post()
            return
        if self.pending:
            raise Fail(f"arm action {act} before setup finished "
                       f"(pending={self.pending})")
        m, a = act
        if m not in self.arms:
            raise Fail(f"unknown arm {m}")
        base, ln, d, held = self.arms[m]
        if a in ("rot_cw", "rot_ccw"):
            delta = 1 if a == "rot_cw" else 5
            d1 = (d + delta) % 6
            self.arms[m][2] = d1
            if not self.on_board(self.gripper(m)):
                raise Fail(f"gripper off board after {act}")
            if held is not None:
                comp = self.component(held)
                for n in comp:
                    hb = self.held_by(n)
                    if hb and hb != [m]:
                        raise Fail(f"{act} tears {n} from arm(s) {hb}")
                for n in comp:
                    q, r = self.atoms[n][1]
                    bq, br = base
                    if delta == 1:
                        npos = (bq - (r - br), br + (q - bq) + (r - br))
                    else:
                        npos = (bq + (q - bq) + (r - br), br - (q - bq))
                    self.atoms[n][1] = npos
                self.check_atoms()
                if self.atoms[held][1] != self.gripper(m):
                    raise Fail("held atom not on gripper after rotation")
        elif a == "grab":
            if held is not None:
                raise Fail(f"{m} grabs with full hand")
            x = self.occupant(self.gripper(m))
            if x is None:
                raise Fail(f"{m} grabs empty hex {self.gripper(m)}")
            if self.held_by(x):
                raise Fail(f"{m} grabs {x}, already held by {self.held_by(x)}")
            self.arms[m][3] = x
        elif a == "drop":
            if held is None:
                raise Fail(f"{m} drops with empty hand")
            self.arms[m][3] = None
        else:
            raise Fail(f"unknown action {act}")
        self.post()


def parse_plan(path):
    plan = []
    for line in open(path):
        mt = re.match(r"^PLAN \{(.*)\}\s*$", line)
        if mt:
            plan.append(tuple(t.strip() for t in mt.group(1).split(",")))
            continue
        mt = re.match(r"^\s*\d+\.\s+(\w+)\s*$", line)  # phase-1 format
        if mt:
            plan.append(("m1", mt.group(1)))
    return plan


def main():
    case, path = sys.argv[1], sys.argv[2]
    cfg = CASES[case]
    plan = parse_plan(path)
    if not plan:
        print(f"{case}: FAIL (no plan found in {path})")
        sys.exit(1)
    try:
        st = State(cfg)
        for act in plan:
            st.step(act)
        if st.pending:
            raise Fail(f"setup never finished: pending={st.pending}")
        if not cfg["goal"](st):
            raise Fail(f"goal not reached; final atoms={st.atoms} "
                       f"bonds={st.bonds}")
    except Fail as e:
        print(f"{case}: FAIL ({e})")
        sys.exit(1)
    npl = sum(1 for a in plan if a[0].startswith("place_"))
    print(f"{case}: PASS ({len(plan)} plan steps = {npl} placements + "
          f"{len(plan) - npl} instructions)")


if __name__ == "__main__":
    main()
