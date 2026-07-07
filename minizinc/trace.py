#!/usr/bin/env python3
"""Decode (and legality-check) a MiniZinc JSON solution of om.mzn/om_fixed.mzn.

Reads the output of `minizinc --output-mode json` (which may contain several
incumbent solutions separated by `----------`), takes the LAST solution, and
prints a per-timestep trace in the same style as the clingo run.py printer.

With --check, it additionally re-simulates the plan with an independent
implementation of the transition rules (grab/drop legality, rigid rotation,
inertia, collisions, base blocking, bond formation/persistence,
calcification, board bounds) and fails loudly on any violation. With
--dzn FILE it also checks the goal (product positions/types, any-bond).

Usage:
  minizinc --solver chuffed --output-mode json minizinc/om_fixed.mzn \
      minizinc/instances/t2_bond.dzn | python3 minizinc/trace.py --check \
      --dzn minizinc/instances/t2_bond.dzn
  python3 minizinc/trace.py [--check] [--dzn FILE] solution.json
"""
import argparse
import json
import re
import sys

# clockwise directions, dir 0 = (1,0)  (matches asp/core.lp, om.mzn)
DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]
ACTS = ["rot_cw", "rot_ccw", "grab", "drop"]
TYPE_NAME = {1: "salt", 2: "air", 3: "earth", 4: "fire", 5: "water"}


def rot_cw(q, r, bq, br):
    return (bq + br - r, q + r - bq)


def rot_ccw(q, r, bq, br):
    return (q + r - br, bq + br - q)


def load_solution(text):
    """Return the last JSON solution object in a minizinc JSON output stream."""
    chunks = [c for c in text.split("----------") if c.strip()]
    for chunk in reversed(chunks):
        lines = [
            l for l in chunk.splitlines()
            if not l.strip().startswith("%") and "=====" not in l
        ]
        txt = "\n".join(lines).strip()
        if not txt:
            continue
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            continue
    sys.exit("error: no JSON solution found in input (was the model UNSAT?)")


def parse_dzn(path):
    """Tiny .dzn reader: only the literal forms used by the instances here."""
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
        elif val.startswith("[|"):
            rows = val[2:-2].strip()
            out[name] = [
                [int(x) for x in row.split(",") if x.strip()]
                for row in rows.split("|") if row.strip()
            ] if rows else []
        elif val.startswith("array2d"):
            inner = re.search(r"\[(.*)\]", val, re.S).group(1)
            out[name] = [int(x) for x in inner.split(",") if x.strip()]
        elif val.startswith("["):
            out[name] = [int(x) for x in val[1:-1].split(",") if x.strip()]
    return out


def actions_of(sol, t, n_arms):
    """List of (arm, action-name) taken at step t (0 or 1 entries)."""
    acts = []
    for m in range(n_arms):
        for name, key in (("rot_cw", "doCW"), ("rot_ccw", "doCCW"),
                          ("grab", "doGrab"), ("drop", "doDrop")):
            if sol[key][t][m]:
                acts.append((m, name))
    return acts


def bonded_pairs(sol, t, n_atoms):
    return sorted(
        (a, b)
        for a in range(n_atoms) for b in range(n_atoms)
        if a < b and sol["bonded"][t][a][b]
    )


def print_trace(sol):
    T = len(sol["aq"]) - 1
    nA = len(sol["aq"][0])
    nM = len(sol["ori"][0])
    print(f"total_actions = {sol['total_actions']}")
    if "prod_who" in sol:
        print(f"product slots filled by atoms: {sol['prod_who']}")
    for m in range(nM):
        print(f"arm{m+1}: base=({sol['base_q'][m]},{sol['base_r'][m]})")
    for g in range(len(sol.get("bonder_q1", []))):
        print(f"bonder{g+1}: ({sol['bonder_q1'][g]},{sol['bonder_r1'][g]})"
              f"-({sol['bonder_q2'][g]},{sol['bonder_r2'][g]})")
    for g in range(len(sol.get("calc_q", []))):
        print(f"calc{g+1}: ({sol['calc_q'][g]},{sol['calc_r'][g]})")
    for t in range(T + 1):
        arms = "  ".join(
            f"arm{m+1} dir={sol['ori'][t][m]} "
            f"gripper=({sol['gq'][t][m]},{sol['gr'][t][m]})"
            for m in range(nM))
        atoms = "  ".join(
            f"a{a+1}@({sol['aq'][t][a]},{sol['ar'][t][a]})"
            + (f"[held:{sol['held'][t][a]}]" if sol["held"][t][a] else "")
            + (f"[{TYPE_NAME[sol['typ'][t][a]]}]" if sol["typ"][t][a] != 1 else "")
            + ("[ghost]" if "ex" in sol and not sol["ex"][t][a] else "")
            for a in range(nA))
        bonds = "".join(f"  bond(a{a+1},a{b+1})"
                        for a, b in bonded_pairs(sol, t, nA))
        print(f"t={t:>2}  {arms}  {atoms}{bonds}")
        if t < T:
            for m, name in actions_of(sol, t, nM):
                print(f"      action: arm{m+1} {name}")


def check(sol, dzn=None):
    """Independent forward simulation; raises AssertionError on any illegality."""
    T = len(sol["aq"]) - 1
    nA = len(sol["aq"][0])
    nM = len(sol["ori"][0])
    radius = max(max(abs(v) for row in sol["aq"] for v in row), 1)
    if dzn:
        radius = dzn["radius"]
    base = [(sol["base_q"][m], sol["base_r"][m]) for m in range(nM)]
    bonders = [((sol["bonder_q1"][g], sol["bonder_r1"][g]),
                (sol["bonder_q2"][g], sol["bonder_r2"][g]))
               for g in range(len(sol.get("bonder_q1", [])))]
    calcs = [(sol["calc_q"][g], sol["calc_r"][g])
             for g in range(len(sol.get("calc_q", [])))]

    # reagent-input (spawn) pools -- asp/core2.lp semantics
    if dzn is not None:
        n_spawn = dzn.get("nSpawn", 0)
        spawn_hex = list(zip(dzn.get("spawn_q", []), dzn.get("spawn_r", [])))
        spawn_typ = dzn.get("spawn_type", [])
        atom_spawn = dzn.get("atom_spawn", [0] * nA)
        atom_rank = dzn.get("atom_rank", [1] * nA)
    else:
        if "ex" in sol and any(not v for row in sol["ex"] for v in row):
            sys.exit("error: solution uses spawning; pass --dzn to check it")
        n_spawn, spawn_hex, spawn_typ = 0, [], []
        atom_spawn, atom_rank = [0] * nA, [1] * nA
    pred_of = [next((b for b in range(nA)
                     if atom_spawn[b] == atom_spawn[a]
                     and atom_rank[b] == atom_rank[a] - 1), None)
               for a in range(nA)]
    exist = [atom_rank[a] <= 1 for a in range(nA)]

    def on_board(q, r):
        return abs(q) <= radius and abs(r) <= radius and abs(q + r) <= radius

    # infer arm lengths from t=0 gripper (gq = base + len*dir)
    length = []
    for m in range(nM):
        d = DIRS[sol["ori"][0][m]]
        dq, dr = sol["gq"][0][m] - base[m][0], sol["gr"][0][m] - base[m][1]
        ln = dq // d[0] if d[0] else dr // d[1]
        assert (dq, dr) == (ln * d[0], ln * d[1]), f"arm {m}: bad t=0 gripper"
        length.append(ln)

    if dzn is not None:
        pos = list(zip(dzn["init_q"], dzn["init_r"]))
        typ = list(dzn["init_type"])
        ori = list(dzn["init_ori"]) if "init_ori" in dzn else list(sol["ori"][0])
    else:
        pos = [(sol["aq"][0][a], sol["ar"][0][a]) for a in range(nA)]
        typ = list(sol["typ"][0])
        ori = list(sol["ori"][0])
    held = list(sol["held"][0])
    if dzn is not None:
        raw = dzn.get("init_bond", [])
        pairs = raw if raw and isinstance(raw[0], list) else \
            [raw[i:i + 2] for i in range(0, len(raw), 2)]
        bonds = {(min(a, b) - 1, max(a, b) - 1) for a, b in pairs}
    else:
        bonds = set(bonded_pairs(sol, 0, nA))
    assert all(h == 0 for h in held), "atoms must start unheld"

    def formed(positions, existing):
        new = set()
        for (h1, h2) in bonders:
            occ1 = [a for a in range(nA) if existing[a] and positions[a] == h1]
            occ2 = [a for a in range(nA) if existing[a] and positions[a] == h2]
            for a in occ1:
                for b in occ2:
                    if a != b:
                        new.add((min(a, b), max(a, b)))
        return new

    bonds |= formed(pos, exist)  # glyph bonds present already at t=0

    for t in range(T + 1):
        # -- state at t must match the solution and be legal
        grip = []
        for m in range(nM):
            d = DIRS[ori[m]]
            g = (base[m][0] + length[m] * d[0], base[m][1] + length[m] * d[1])
            grip.append(g)
            assert on_board(*g), f"t={t}: gripper {m} off board"
            assert ori[m] == sol["ori"][t][m], f"t={t}: ori mismatch arm {m}"
            assert g == (sol["gq"][t][m], sol["gr"][t][m]), \
                f"t={t}: gripper mismatch arm {m}"
        for a in range(nA):
            assert pos[a] == (sol["aq"][t][a], sol["ar"][t][a]), \
                f"t={t}: position mismatch atom {a}: sim {pos[a]}"
            assert held[a] == sol["held"][t][a], f"t={t}: held mismatch atom {a}"
            assert typ[a] == sol["typ"][t][a], f"t={t}: type mismatch atom {a}"
            if "ex" in sol:
                assert exist[a] == bool(sol["ex"][t][a]), \
                    f"t={t}: existence mismatch atom {a}"
            if not exist[a]:  # ghost: parked on its spawn hex, inert
                s = atom_spawn[a] - 1
                assert pos[a] == spawn_hex[s], f"t={t}: ghost {a} off its spawn"
                assert held[a] == 0, f"t={t}: ghost {a} held"
                assert typ[a] == spawn_typ[s], f"t={t}: ghost {a} type"
                continue
            assert on_board(*pos[a]), f"t={t}: atom {a} off board"
            assert pos[a] not in base, f"t={t}: atom {a} on an arm base"
            if held[a]:
                assert pos[a] == grip[held[a] - 1], \
                    f"t={t}: held atom {a} not on gripper"
        live = [pos[a] for a in range(nA) if exist[a]]
        assert len(set(live)) == len(live), f"t={t}: atom collision"
        assert bonds == set(bonded_pairs(sol, t, nA)), f"t={t}: bond mismatch"

        if t == T:
            break

        # -- apply the (at most one) action of step t
        acts = actions_of(sol, t, nM)
        assert len(acts) <= 1, f"t={t}: more than one action"
        new_pos, new_held, new_typ = list(pos), list(held), list(typ)
        if acts:
            m, name = acts[0]
            if name == "grab":
                assert all(h != m + 1 for h in held), f"t={t}: arm{m+1} hand full"
                tgt = [a for a in range(nA) if exist[a] and pos[a] == grip[m]]
                assert tgt, f"t={t}: grab on empty hex"
                assert held[tgt[0]] == 0, f"t={t}: grabbing a held atom"
                new_held[tgt[0]] = m + 1
            elif name == "drop":
                mine = [a for a in range(nA) if held[a] == m + 1]
                assert mine, f"t={t}: drop with empty hand"
                for a in mine:
                    new_held[a] = 0
            else:
                # rigid rotation of the held component about the base
                comp = {a for a in range(nA) if held[a] == m + 1}
                changed = True
                while changed:
                    changed = False
                    for (a, b) in bonds:
                        if (a in comp) != (b in comp):
                            comp |= {a, b}
                            changed = True
                assert all(held[a] in (0, m + 1) for a in comp), \
                    f"t={t}: rotation tears atom from another arm"
                fn = rot_cw if name == "rot_cw" else rot_ccw
                for a in comp:
                    new_pos[a] = fn(*pos[a], *base[m])
                ori[m] = (ori[m] + (1 if name == "rot_cw" else -1)) % 6
        # calcification uses positions at t (existing atoms only)
        for a in range(nA):
            if exist[a] and typ[a] >= 2 and pos[a] in calcs:
                new_typ[a] = 1
        # spawning: the next pool atom appears at t+1 iff its predecessor
        # exists at t and no atom existing at t sits on the spawn hex at t+1
        occ_spawn = [any(exist[b] and new_pos[b] == spawn_hex[s]
                         for b in range(nA)) for s in range(n_spawn)]
        exist = [exist[a] or (atom_rank[a] > 1 and exist[pred_of[a]]
                              and not occ_spawn[atom_spawn[a] - 1])
                 for a in range(nA)]
        pos, held, typ = new_pos, new_held, new_typ
        bonds |= formed(pos, exist)  # bonds forming at t+1

    if dzn:
        who = [w - 1 for w in sol.get("prod_who", dzn["prod_atom"])]
        if dzn.get("free_prod_atoms"):
            assert len(set(who)) == len(who), "goal: product slots not injective"
        else:
            assert who == [p - 1 for p in dzn["prod_atom"]], \
                "goal: prod_who differs from prod_atom without free_prod_atoms"
        for k in range(dzn["nProd"]):
            a = who[k]
            want = (dzn["prod_q"][k], dzn["prod_r"][k])
            assert exist[a], f"goal: atom {a+1} never spawned"
            assert pos[a] == want, f"goal: atom {a+1} at {pos[a]}, want {want}"
            assert held[a] == 0, f"goal: atom {a+1} still held"
            if dzn["prod_type"][k]:
                assert typ[a] == dzn["prod_type"][k], f"goal: atom {a+1} type"
        if dzn.get("require_any_bond"):
            assert bonds, "goal: no bond at t_max"
        raw = dzn.get("prod_bond", [])
        slot_pairs = raw if not raw or isinstance(raw[0], list) else \
            [raw[i:i + 2] for i in range(0, len(raw), 2)]
        req = set()
        for k1, k2 in slot_pairs:
            a, b = who[k1 - 1], who[k2 - 1]
            req.add((min(a, b), max(a, b)))
            assert (min(a, b), max(a, b)) in bonds, \
                f"goal: required product bond slot{k1}-slot{k2} missing"
        if dzn.get("exact_molecule"):
            prodset = set(who)
            for (a, b) in bonds:
                if a in prodset or b in prodset:
                    assert (a, b) in req, \
                        f"goal: extra bond (a{a+1},a{b+1}) on the product"

    n_acts = sum(len(actions_of(sol, t, nM)) for t in range(T))
    assert n_acts == sol["total_actions"], "objective != number of actions"
    return n_acts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", nargs="?", help="JSON output file (default stdin)")
    ap.add_argument("--check", action="store_true",
                    help="re-simulate and verify the plan is legal")
    ap.add_argument("--dzn", help="instance .dzn (enables goal checking)")
    args = ap.parse_args()

    text = open(args.file).read() if args.file else sys.stdin.read()
    sol = load_solution(text)
    print_trace(sol)
    if args.check:
        dzn = parse_dzn(args.dzn) if args.dzn else None
        n = check(sol, dzn)
        print(f"CHECK OK: legal plan, {n} actions"
              + (", goal satisfied" if dzn else " (no goal check: pass --dzn)"))


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(0)
