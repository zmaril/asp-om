#!/usr/bin/env python3
"""Independent validator for clingo-produced Opus Magnum plans.

Runs clingo on the given ASP files (core + instance, exactly like run.py),
takes the best answer set, and then REPLAYS the plan step by step in pure
Python: grip/rotate/drop semantics, rigid bond-component motion, collision
checks, calcification + bonding glyph effects, reagent spawn rules, and the
instance goal. The replay shares no code with the ASP encoding (it is a
cleaned-up descendant of the phase-2 BFS reference simulator), so a PASS
means two independent implementations of the semantics agree on the plan.

Checks performed:
  1. every action in the answer set is legal in the replayed state
     (grab needs a free hand and an atom under the gripper not held by
     another arm; drop needs a held atom; rotations may not tear a
     molecule held by two arms, swing atoms off the board / onto arm
     bases / into other atoms, or push the gripper off the board);
  2. the replayed world state (atom positions, types, bonds, held flags)
     matches the answer set's at/4, type/3, bond/3, holding/{2,3} atoms
     at every timestep -- catching encoding<->validator divergence even
     when the plan happens to be legal;
  3. the instance goal holds (delivery for the v1 core; exact-molecule
     product match for the v2 instances).

Usage:
    python3 validate.py asp/core.lp asp/trivial_instance.lp
    python3 validate.py asp/core2.lp asp/rigid_instance.lp
    python3 validate.py asp/core2.lp asp/stabilized_water.lp --tmax 10
    python3 validate.py asp/core2.lp asp/layout.lp asp/stabilized_water_free.lp \
        --tmax 10 --time-limit 30
    python3 validate.py asp/core2.lp asp/sw_bent.lp --tmax 25 --goal swsw_bent

Exit status 0 = PASS, 1 = FAIL / no model.
"""
import argparse
import sys
import time as _time

import clingo

DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]  # clockwise
ELEMENTAL = {"air", "earth", "fire", "water"}


def rot_cw(q, r):
    return (-r, q + r)


def rot_ccw(q, r):
    return (q + r, -q)


def hexes(radius):
    return {(q, r) for q in range(-radius, radius + 1)
            for r in range(-radius, radius + 1) if abs(q + r) <= radius}


# ---------------------------------------------------------------------------
# Solving (same call pattern as run.py) and fact extraction
# ---------------------------------------------------------------------------
def solve(files, tmax, time_limit, consts):
    args = []
    if tmax is not None:
        args += ["-c", f"t_max={tmax}"]
    for c in consts:
        args += ["-c", c]
    ctl = clingo.Control(args)
    for f in files:
        ctl.load(f)
    ctl.ground([("base", [])])
    best = {"symbols": None, "cost": None}

    def on_model(model):
        best["symbols"] = model.symbols(atoms=True)
        best["cost"] = list(model.cost)

    with ctl.solve(on_model=on_model, async_=True) as handle:
        if not handle.wait(time_limit if time_limit else None):
            handle.cancel()
        result = handle.get()
    consts_out = {}
    for name in ("t_max", "radius"):
        sym = ctl.get_const(name)
        consts_out[name] = sym.number if sym is not None else None
    return result, best, consts_out


def extract(symbols):
    """Pull plan + layout facts + claimed trajectory out of the answer set."""
    F = {
        "arm": [], "base": {}, "armlen": {}, "init_orient": {},
        "init_at": {}, "init_type": {}, "init_bond": set(),
        "spawn": {}, "spawn_type": {}, "pool": {},
        "glyph_calc": set(), "glyph_bond": set(),
        "product": {}, "plan": {},          # plan: t -> (arm, action)
        "v1_base": None, "v1_orient": None,
        # claimed trajectory, for the state cross-check:
        "claim_at": {}, "claim_type": {}, "claim_bond": {}, "claim_held": {},
    }
    dup = None
    for s in symbols:
        a = s.arguments
        n = s.name
        if n == "do":
            if len(a) == 2:                     # v1: do(action, t)
                t = a[1].number
                if t in F["plan"]:
                    dup = t
                F["plan"][t] = ("arm0", a[0].name)
            else:                               # v2: do(arm, action, t)
                t = a[2].number
                if t in F["plan"]:
                    dup = t
                F["plan"][t] = (str(a[0]), a[1].name)
        elif n == "arm":
            F["arm"].append(str(a[0]))
        elif n == "base":
            if len(a) == 3:
                F["base"][str(a[0])] = (a[1].number, a[2].number)
            else:
                F["v1_base"] = (a[0].number, a[1].number)
        elif n == "armlen":
            F["armlen"][str(a[0])] = a[1].number
        elif n == "init_orient":
            if len(a) == 2:
                F["init_orient"][str(a[0])] = a[1].number
            else:
                F["v1_orient"] = a[0].number
        elif n == "init_at":
            F["init_at"][str(a[0])] = (a[1].number, a[2].number)
        elif n == "init_type":
            F["init_type"][str(a[0])] = a[1].name
        elif n == "init_bond":
            F["init_bond"].add((str(a[0]), str(a[1])))
        elif n == "spawn":
            F["spawn"][a[0].number] = (a[1].number, a[2].number)
        elif n == "spawn_type":
            F["spawn_type"][a[0].number] = a[1].name
        elif n == "pool":
            F["pool"][a[0].number] = a[1].number
        elif n == "glyph_calc":
            F["glyph_calc"].add((a[0].number, a[1].number))
        elif n == "glyph_bond":
            F["glyph_bond"].add(((a[0].number, a[1].number),
                                 (a[2].number, a[3].number)))
        elif n == "product":
            F["product"][str(a[0])] = (a[1].number, a[2].number)
        elif n == "at":
            F["claim_at"].setdefault(a[3].number, {})[str(a[0])] = \
                (a[1].number, a[2].number)
        elif n == "type" and len(a) == 3:
            F["claim_type"].setdefault(a[2].number, {})[str(a[0])] = a[1].name
        elif n == "bond":
            x, y = str(a[0]), str(a[1])
            F["claim_bond"].setdefault(a[2].number, set()).add(
                (min(x, y), max(x, y)))
        elif n == "holding":
            t = a[-1].number
            F["claim_held"].setdefault(t, set()).add(str(a[-2]))
    return F, dup


# ---------------------------------------------------------------------------
# Goal checkers (mirror the goal_met rules of the supported instances)
# ---------------------------------------------------------------------------
def _deg(bonds):
    d = {}
    for x, y in bonds:
        d[x] = d.get(x, 0) + 1
        d[y] = d.get(y, 0) + 1
    return d


def goal_product(F, states):
    """v1 core: every product(X,Q,R) atom rests on its hex at t_max."""
    pos, held = states[-1]["pos"], states[-1]["held"]
    return all(pos.get(x) == h and x not in held
               for x, h in F["product"].items())


def goal_rigid(F, states):
    """asp/rigid_instance.lp: a1@(-1,1), a2@(-2,2), unheld, at t_max."""
    pos, held = states[-1]["pos"], states[-1]["held"]
    return (pos.get("a1") == (-1, 1) and pos.get("a2") == (-2, 2)
            and "a1" not in held and "a2" not in held)


def _dimer_at(st):
    """Exact salt--water dimer, both deg 1, bonded, unheld."""
    deg = _deg(st["bonds"])
    occ = {h: x for x, h in st["pos"].items()}
    for w, (q, r) in st["pos"].items():
        if st["typ"][w] != "water" or w in st["held"] or deg.get(w, 0) != 1:
            continue
        for dq, dr in DIRS:
            s = occ.get((q + dq, r + dr))
            if (s is not None and st["typ"][s] == "salt"
                    and s not in st["held"] and deg.get(s, 0) == 1
                    and (min(w, s), max(w, s)) in st["bonds"]):
                return True
    return False


def _swsw_at(st, dpairs):
    """Exact salt-water-salt trimer (bent or linear), unheld."""
    deg = _deg(st["bonds"])
    occ = {h: x for x, h in st["pos"].items()}
    for w, (q, r) in st["pos"].items():
        if st["typ"][w] != "water" or w in st["held"] or deg.get(w, 0) != 2:
            continue
        for d1, d2 in dpairs:
            s1 = occ.get((q + DIRS[d1][0], r + DIRS[d1][1]))
            s2 = occ.get((q + DIRS[d2][0], r + DIRS[d2][1]))
            if (s1 is not None and s2 is not None
                    and st["typ"][s1] == "salt" and st["typ"][s2] == "salt"
                    and s1 not in st["held"] and s2 not in st["held"]
                    and deg.get(s1, 0) == 1 and deg.get(s2, 0) == 1
                    and (min(w, s1), max(w, s1)) in st["bonds"]
                    and (min(w, s2), max(w, s2)) in st["bonds"]):
                return True
    return False


def goal_sw_dimer(F, states):
    return any(_dimer_at(st) for st in states)          # complete(T), any T


def goal_swsw_bent(F, states):
    return any(_swsw_at(st, [(d, (d + 2) % 6) for d in range(6)])
               for st in states)


def goal_swsw_linear(F, states):
    return any(_swsw_at(st, [(d, (d + 3) % 6) for d in range(3)])
               for st in states)


GOALS = {
    "product": goal_product,
    "rigid": goal_rigid,
    "sw_dimer": goal_sw_dimer,
    "swsw_bent": goal_swsw_bent,
    "swsw_linear": goal_swsw_linear,
}


def detect_goal(files, F):
    names = " ".join(files)
    if F["product"]:
        return "product"
    if "rigid_instance" in names:
        return "rigid"
    if "stabilized_water" in names:
        return "sw_dimer"
    if "sw_bent" in names:
        return "swsw_bent"
    if "sw_linear" in names:
        return "swsw_linear"
    return None


# ---------------------------------------------------------------------------
# Replay -- v1 core (core.lp): single arm, no bonds/types/spawns
# ---------------------------------------------------------------------------
def replay_v1(F, tmax, radius, log):
    board = hexes(radius)
    base, d = F["v1_base"], F["v1_orient"]
    pos = dict(F["init_at"])
    held = None
    states = []
    for t in range(tmax + 1):
        g = (base[0] + DIRS[d][0], base[1] + DIRS[d][1])
        if g not in board:
            return None, f"t={t}: gripper {g} off the board"
        if len(set(pos.values())) != len(pos):
            return None, f"t={t}: atom collision"
        states.append({"pos": dict(pos), "held": {held} - {None},
                       "typ": {}, "bonds": set()})
        if t == tmax:
            break
        act = F["plan"].get(t, ("arm0", "wait"))[1]
        log(f"t={t}: {act}  arm d{d} gripper {g}  atoms {sorted(pos.items())}")
        if act == "grab":
            if held is not None:
                return None, f"t={t}: grab with full hand"
            x = next((x for x, h in pos.items() if h == g), None)
            if x is None:
                return None, f"t={t}: grab over empty hex {g}"
            held = x
        elif act == "drop":
            if held is None:
                return None, f"t={t}: drop with empty hand"
            held = None
        elif act in ("rot_cw", "rot_ccw"):
            d = (d + 1) % 6 if act == "rot_cw" else (d + 5) % 6
            if held is not None:
                pos[held] = (base[0] + DIRS[d][0], base[1] + DIRS[d][1])
                if pos[held] not in board:
                    return None, f"t={t}: held atom swung off the board"
        elif act != "wait":
            return None, f"t={t}: unknown action {act}"
    return states, None


# ---------------------------------------------------------------------------
# Replay -- v2 core (core2.lp): the full phase-2 semantics
# ---------------------------------------------------------------------------
def replay_v2(F, tmax, radius, log):
    board = hexes(radius)
    arms = sorted(F["arm"])
    bases = {F["base"][m] for m in arms}
    orient = {m: F["init_orient"][m] for m in arms}
    holds = {m: None for m in arms}

    pos, typ = {}, {}
    bonds = set()
    for x, h in F["init_at"].items():
        pos[x], typ[x] = h, F["init_type"].get(x)
    for x, y in F["init_bond"]:
        bonds.add((min(x, y), max(x, y)))
    spawned = {}
    for i, h in F["spawn"].items():
        if F["pool"].get(i, 0) > 0:
            x = f"r({i},1)"
            pos[x], typ[x] = h, F["spawn_type"][i]
            spawned[i] = 1
        else:
            spawned[i] = 0

    def gripper(m):
        b, ln, d = F["base"][m], F["armlen"][m], orient[m]
        return (b[0] + ln * DIRS[d][0], b[1] + ln * DIRS[d][1])

    def component(x):
        seen, stack = {x}, [x]
        while stack:
            c = stack.pop()
            for a, b in bonds:
                for u, v in ((a, b), (b, a)):
                    if u == c and v not in seen:
                        seen.add(v)
                        stack.append(v)
        return seen

    def apply_bonders():
        occ = {h: x for x, h in pos.items()}
        for h1, h2 in F["glyph_bond"]:
            if h1 in occ and h2 in occ:
                x, y = occ[h1], occ[h2]
                bonds.add((min(x, y), max(x, y)))

    def snapshot():
        return {"pos": dict(pos), "typ": dict(typ), "bonds": set(bonds),
                "held": {x for x in holds.values() if x is not None}}

    def static_checks(t):
        for m in arms:
            if gripper(m) not in board:
                return f"t={t}: gripper of {m} off the board"
        if len(set(pos.values())) != len(pos):
            return f"t={t}: atom collision"
        if any(h not in board for h in pos.values()):
            return f"t={t}: atom off the board"
        if any(h in bases for h in pos.values()):
            return f"t={t}: atom on an arm base"
        return None

    apply_bonders()                                  # bond/3 holds at t=0 too
    states = []
    for t in range(tmax + 1):
        err = static_checks(t)
        if err:
            return None, err
        states.append(snapshot())
        if t == tmax:
            break
        m, act = F["plan"].get(t, (None, "wait"))
        log(f"t={t}: {m or '-'} {act}  " +
            " ".join(f"{a}:d{orient[a]}" for a in arms) + "  " +
            " ".join(f"{x}/{typ[x]}@{h}" for x, h in sorted(pos.items())))
        oldpos = dict(pos)                           # calcify reads t, not t+1
        if act == "grab":
            if holds[m] is not None:
                return None, f"t={t}: {m} grabs with full hand"
            g = gripper(m)
            x = next((x for x, h in pos.items() if h == g), None)
            if x is None:
                return None, f"t={t}: {m} grabs over empty hex {g}"
            if x in {h for a, h in holds.items() if a != m and h is not None}:
                return None, f"t={t}: {m} grabs atom held by another arm"
            holds[m] = x
        elif act == "drop":
            if holds[m] is None:
                return None, f"t={t}: {m} drops with empty hand"
            holds[m] = None
        elif act in ("rot_cw", "rot_ccw"):
            rot = rot_cw if act == "rot_cw" else rot_ccw
            b = F["base"][m]
            orient[m] = (orient[m] + (1 if act == "rot_cw" else 5)) % 6
            if gripper(m) not in board:
                return None, f"t={t}: {m} rotates its gripper off the board"
            if holds[m] is not None:
                comp = component(holds[m])
                if any(holds[a] in comp for a in arms
                       if a != m and holds[a] is not None):
                    return None, (f"t={t}: {m} would tear a molecule held "
                                  f"by another arm")
                for x in comp:
                    dq, dr = rot(pos[x][0] - b[0], pos[x][1] - b[1])
                    pos[x] = (b[0] + dq, b[1] + dr)
                    if pos[x] not in board:
                        return None, f"t={t}: {m} swings {x} off the board"
        elif act != "wait":
            return None, f"t={t}: unknown action {act}"
        # glyph of calcification: reads positions at t, retypes at t+1
        for x, h in oldpos.items():
            if h in F["glyph_calc"] and typ[x] in ELEMENTAL:
                typ[x] = "salt"
        # reagent respawn: next atom appears once the input hex is clear
        # of every atom that existed at t (at its t+1 position)
        for i, h in F["spawn"].items():
            if spawned[i] < F["pool"].get(i, 0) and h not in pos.values():
                x = f"r({i},{spawned[i] + 1})"
                pos[x], typ[x] = h, F["spawn_type"][i]
                spawned[i] += 1
        apply_bonders()                              # bonds at t+1, new pos
    return states, None


def cross_check(F, states):
    """Replayed trajectory must equal the answer set's claimed trajectory."""
    for t, st in enumerate(states):
        if F["claim_at"].get(t, {}) != st["pos"]:
            return (f"t={t}: positions diverge: clingo {F['claim_at'].get(t)}"
                    f" vs replay {st['pos']}")
        ct = F["claim_type"].get(t, {})
        if ct and ct != st["typ"]:
            return f"t={t}: types diverge: clingo {ct} vs replay {st['typ']}"
        if F["claim_bond"].get(t, set()) != st["bonds"]:
            return (f"t={t}: bonds diverge: clingo {F['claim_bond'].get(t)}"
                    f" vs replay {st['bonds']}")
        if F["claim_held"].get(t, set()) != st["held"]:
            return (f"t={t}: held atoms diverge: clingo "
                    f"{F['claim_held'].get(t)} vs replay {st['held']}")
    return None


def main():
    ap = argparse.ArgumentParser(
        description="Validate a clingo plan by independent replay.")
    ap.add_argument("files", nargs="+", help="ASP files (core + instance)")
    ap.add_argument("--tmax", type=int, default=None)
    ap.add_argument("--time-limit", type=float, default=None)
    ap.add_argument("-c", dest="consts", action="append", default=[])
    ap.add_argument("--goal", choices=sorted(GOALS),
                    help="goal checker (default: inferred from file names)")
    ap.add_argument("--verbose", action="store_true",
                    help="print the replay step by step")
    args = ap.parse_args()
    log = print if args.verbose else (lambda *a: None)
    name = " + ".join(args.files)

    t0 = _time.time()
    result, best, consts = solve(args.files, args.tmax, args.time_limit,
                                 args.consts)
    if best["symbols"] is None:
        print(f"FAIL  {name}: no model ({result})")
        return 1
    F, dup = extract(best["symbols"])
    if dup is not None:
        print(f"FAIL  {name}: two actions at t={dup}")
        return 1
    tmax = args.tmax if args.tmax is not None else consts["t_max"]
    radius = consts["radius"]

    goal_name = args.goal or detect_goal(args.files, F)
    if goal_name is None:
        print(f"FAIL  {name}: cannot infer goal; pass --goal")
        return 1

    v2 = bool(F["arm"])
    states, err = (replay_v2 if v2 else replay_v1)(F, tmax, radius, log)
    if err is None and states is not None and v2:
        err = cross_check(F, states)
    if err is None and not GOALS[goal_name](F, states):
        err = f"goal '{goal_name}' not reached"
    plan = [f"{m}:{a}" if v2 else a for t, (m, a) in sorted(F["plan"].items())]
    if err:
        print(f"FAIL  {name}: {err}")
        print(f"      plan ({len(plan)} instructions): {' '.join(plan)}")
        return 1
    print(f"PASS  {name}")
    print(f"      cost={best['cost']} t_max={tmax} radius={radius} "
          f"goal={goal_name} wall={_time.time() - t0:.2f}s")
    print(f"      plan ({len(plan)} instructions): {' '.join(plan)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
