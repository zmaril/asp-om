#!/usr/bin/env python3
"""Harness adapter: canonical puzzle JSON -> MiniZinc -> canonical plan JSON.

Implements the adapter contract of harness/README.md / harness/SPEC.md:

    python3 minizinc/adapter.py [options] <puzzle.json>

writes a plan JSON to stdout and exits 0 on solve; nonzero otherwise.
All logging goes to stderr.

The adapter translates the puzzle into a .dzn instance for minizinc/om.mzn
with the harness-freedom flags on (free input/output placement, free initial
arm orientation, full part-footprint disjointness), runs MiniZinc, and
decodes the last incumbent into the canonical plan format.

Options:
    --solver NAME    chuffed | cp-sat | gecode | highs | coin-bc | auto
                     (default auto: chuffed first; if it does not PROVE
                     optimality within its slice, cp-sat -p<procs> gets the
                     rest of the budget and the best incumbent wins)
    --time-limit S   total budget in seconds (default 300)
    --procs N        threads for cp-sat/gecode (default min(4, cpus))
    --keep-dzn PATH  also write the generated .dzn here (debugging)

Supported puzzle subset (same fragment the whole repo models): parts arm /
calcifier / bonder; single-atom reagents (any pool size); products of any
shape. Multi-atom reagents exit 2 with a clear message.

Exit codes: 0 solved, 1 no plan found (unsat within horizon / timeout),
2 unsupported or malformed puzzle.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "om.mzn")

ELEM = {"salt": 1, "air": 2, "earth": 3, "fire": 4, "water": 5}
DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]


def log(*a):
    print("[adapter]", *a, file=sys.stderr, flush=True)


def die(code, msg):
    log("ERROR:", msg)
    sys.exit(code)


def rot_k(q, r, k):
    for _ in range(k % 6):
        q, r = -r, q + r
    return q, r


# ---------------------------------------------------------------------------
# Puzzle -> dzn (+ pin constraints)
# ---------------------------------------------------------------------------
def build_instance(puz):
    """Return (dzn_text, pins_mzn_text, meta) for om.mzn."""
    try:
        radius = puz["board_radius"]
        t_max = puz["t_max"]
        reagents = puz["reagents"]
        products = puz["products"]
        parts = puz["parts"]
    except KeyError as e:
        die(2, f"puzzle is missing required key {e}")

    arms = [p for p in parts if p["type"] == "arm"]
    calcs = [p for p in parts if p["type"] == "calcifier"]
    bonders = [p for p in parts if p["type"] == "bonder"]
    other = [p for p in parts if p["type"] not in ("arm", "calcifier", "bonder")]
    if other:
        die(2, f"unsupported part types: {[p['type'] for p in other]}")
    if not arms:
        die(2, "no arm in the puzzle")

    pins = []  # extra .mzn constraint strings for pinned placements

    # ---- reagents -> spawn inputs + atom pool -------------------------------
    atoms = []  # (spawn_idx, rank, type_code)
    spawn_types = []
    for s, rg in enumerate(reagents, start=1):
        if len(rg["atoms"]) != 1:
            die(
                2,
                f"reagent {rg['id']!r} has {len(rg['atoms'])} atoms; "
                "this adapter only supports single-atom reagents",
            )
        el = rg["atoms"][0]["element"]
        if el not in ELEM:
            die(2, f"reagent {rg['id']!r}: unknown element {el!r}")
        spawn_types.append(ELEM[el])
        for k in range(1, rg["pool"] + 1):
            atoms.append((s, k, ELEM[el]))
        if "position" in rg:
            off = rg["atoms"][0]["pos"]
            rot = rg.get("rotation", 0)
            oq, orr = rot_k(off[0], off[1], rot)
            hq, hr = rg["position"][0] + oq, rg["position"][1] + orr
            pins.append(f"constraint sq[{s}] = {hq} /\\ sr[{s}] = {hr};")
    nA, nSpawn = len(atoms), len(reagents)

    # ---- products -> output parts + slots -----------------------------------
    prod_out: list[int] = []
    prod_off: list[tuple[int, int]] = []
    prod_type: list[int] = []
    prod_bond: list[tuple[int, int]] = []
    slot_base = {}
    for o, pd in enumerate(products, start=1):
        slot_base[pd["id"]] = len(prod_off)
        for a in pd["atoms"]:
            el = a["element"]
            if el not in ELEM:
                die(2, f"product {pd['id']!r}: unknown element {el!r}")
            prod_out.append(o)
            prod_off.append(tuple(a["pos"]))
            prod_type.append(ELEM[el])
        for i, j in pd.get("bonds", []):
            prod_bond.append((slot_base[pd["id"]] + i + 1, slot_base[pd["id"]] + j + 1))
        if "position" in pd:
            pins.append(
                f"constraint out_q[{o}] = {pd['position'][0]} /\\ out_r[{o}] = {pd['position'][1]};"
            )
            if "rotation" in pd:
                pins.append(f"constraint out_rot[{o}] = {pd['rotation'] % 6};")
    nProd, nOut = len(prod_off), len(products)

    # ---- arms / glyphs ------------------------------------------------------
    for m, p in enumerate(arms, start=1):
        if "position" in p:
            pins.append(
                f"constraint base_q[{m}] = {p['position'][0]} /\\ base_r[{m}] = {p['position'][1]};"
            )
        if "rotation" in p:
            pins.append(f"constraint ori[0,{m}] = {p['rotation'] % 6};")
    for g, p in enumerate(calcs, start=1):
        if "position" in p:
            pins.append(
                f"constraint calc_q[{g}] = {p['position'][0]} /\\ calc_r[{g}] = {p['position'][1]};"
            )
    for g, p in enumerate(bonders, start=1):
        if "position" in p:
            rot = p.get("rotation", 0) % 6
            aq, ar = p["position"]
            bq, br = aq + DIRS[rot][0], ar + DIRS[rot][1]
            pins.append(
                f"constraint (bonder_q1[{g}] = {aq} /\\ bonder_r1[{g}] = {ar}"
                f" /\\ bonder_q2[{g}] = {bq} /\\ bonder_r2[{g}] = {br}) \\/ "
                f"(bonder_q1[{g}] = {bq} /\\ bonder_r1[{g}] = {br} /\\ "
                f"bonder_q2[{g}] = {aq} /\\ bonder_r2[{g}] = {ar});"
            )

    # ---- dzn text -----------------------------------------------------------
    def a1(vals):
        return "[" + ", ".join(str(v) for v in vals) + "]"

    def a2(vals, ncols):
        flat = [str(x) for row in vals for x in row]
        return f"array2d(1..{len(vals)}, 1..{ncols}, [" + ", ".join(flat) + "])"

    nM = len(arms)
    L = []
    L.append(f"T = {t_max};")
    L.append(f"radius = {radius};")
    L.append(f"nA = {nA};")
    L.append(f"nM = {nM};")
    L.append(f"arm_len = {a1(p['length'] for p in arms)};")
    L.append(f"init_ori = {a1([0] * nM)};        % unused (free_init_ori)")
    L.append(f"given_base_q = {a1([0] * nM)};    % unused (free layout)")
    L.append(f"given_base_r = {a1([0] * nM)};")
    L.append(f"init_q = {a1([0] * nA)};          % unused (free_in_layout)")
    L.append(f"init_r = {a1([0] * nA)};")
    L.append(f"init_type = {a1(a[2] for a in atoms)};")
    L.append("nInitBond = 0;")
    L.append("init_bond = array2d(1..0, 1..2, []);")
    L.append(f"nBonder = {len(bonders)};")
    L.append(f"given_bonder = {a2([[0, 0, 0, 0]] * len(bonders), 4)};")
    L.append(f"nCalc = {len(calcs)};")
    L.append(f"given_calc = {a2([[0, 0]] * len(calcs), 2)};")
    L.append(f"nSpawn = {nSpawn};")
    L.append(f"spawn_q = {a1([0] * nSpawn)};     % unused (free_in_layout)")
    L.append(f"spawn_r = {a1([0] * nSpawn)};")
    L.append(f"spawn_type = {a1(spawn_types)};")
    L.append(f"atom_spawn = {a1(a[0] for a in atoms)};")
    L.append(f"atom_rank = {a1(a[1] for a in atoms)};")
    L.append(f"nProd = {nProd};")
    L.append(f"prod_atom = {a1([1] * nProd)};    % unused (free_prod_atoms)")
    L.append(f"prod_q = {a1([0] * nProd)};       % unused (free_out_layout)")
    L.append(f"prod_r = {a1([0] * nProd)};")
    L.append(f"prod_type = {a1(prod_type)};")
    L.append("require_any_bond = false;")
    L.append(f"nProdBond = {len(prod_bond)};")
    L.append(f"prod_bond = {a2(prod_bond, 2)};")
    L.append("exact_molecule = true;")
    L.append("free_prod_atoms = true;")
    L.append("free_in_layout = true;")
    L.append("free_out_layout = true;")
    L.append("free_init_ori = true;")
    L.append("parts_disjoint_full = true;")
    L.append(f"nOut = {nOut};")
    L.append(f"prod_out = {a1(prod_out)};")
    L.append(f"prod_off = {a2(prod_off, 2)};")
    dzn = (
        "% generated by minizinc/adapter.py from puzzle "
        f"{puz.get('name')!r}\n" + "\n".join(L) + "\n"
    )
    pins_mzn = (
        ("% pinned placements from the puzzle file\n" + "\n".join(pins) + "\n") if pins else None
    )

    meta = {
        "arm_ids": [p["id"] for p in arms],
        "calc_ids": [p["id"] for p in calcs],
        "bonder_ids": [p["id"] for p in bonders],
        "reagent_ids": [r["id"] for r in reagents],
        "reagent_off": [tuple(r["atoms"][0]["pos"]) for r in reagents],
        "product_ids": [p["id"] for p in products],
        "t_max": t_max,
    }
    return dzn, pins_mzn, meta


# ---------------------------------------------------------------------------
# MiniZinc invocation + JSON stream parsing
# ---------------------------------------------------------------------------
def run_minizinc(solver, files, limit_s, procs):
    """Run one engine; return (solution_dict_or_None, proven_optimal, wall)."""
    cmd = [
        "minizinc",
        "--solver",
        solver,
        "--output-mode",
        "json",
        "--output-objective",
        "--time-limit",
        str(int(limit_s * 1000)),
    ]
    if solver in ("cp-sat", "gecode") and procs > 1:
        cmd += ["-p", str(procs)]
    cmd += files
    log("run:", " ".join(cmd))
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=limit_s + 120)
    except subprocess.TimeoutExpired:
        log(f"{solver}: hard-killed at {limit_s + 120:.0f}s (ignored --time-limit)")
        return None, False, time.time() - t0
    wall = time.time() - t0
    for line in (proc.stderr or "").strip().splitlines():
        log(f"{solver} stderr: {line}")
    text = proc.stdout or ""
    proven = "==========" in text
    sol = None
    for chunk in text.split("----------"):
        lines = [
            line
            for line in chunk.splitlines()
            if not line.strip().startswith("%") and "=====" not in line
        ]
        blob = "\n".join(lines).strip()
        if not blob:
            continue
        try:
            sol = json.loads(blob)
        except json.JSONDecodeError:
            continue
    if "=====UNSATISFIABLE=====" in text:
        log(f"{solver}: UNSATISFIABLE within the horizon ({wall:.1f}s)")
        return None, True, wall
    status = (
        "optimal"
        if proven and sol is not None
        else "incumbent"
        if sol is not None
        else "no solution"
    )
    obj = sol.get("total_actions") if sol else None
    log(f"{solver}: {status}, objective={obj}, wall={wall:.1f}s")
    return sol, proven and sol is not None, wall


def solve(files, solver, limit_s, procs):
    if solver != "auto":
        sol, proven, _ = run_minizinc(solver, files, limit_s, procs)
        return sol, proven, solver
    # auto: chuffed first (fast on easy instances), cp-sat -pN as fallback
    slice1 = min(60.0, limit_s * 0.4)
    t0 = time.time()
    sol1, proven1, _ = run_minizinc("chuffed", files, slice1, 1)
    if proven1:
        return sol1, True, "chuffed"
    remaining = max(10.0, limit_s - (time.time() - t0))
    sol2, proven2, _ = run_minizinc("cp-sat", files, remaining, procs)
    best, engine, proven = None, None, False
    for s, p, name in ((sol1, False, "chuffed"), (sol2, proven2, "cp-sat")):
        if s is None:
            continue
        if (
            best is None
            or s["total_actions"] < best["total_actions"]
            or (s["total_actions"] == best["total_actions"] and p)
        ):
            best, engine, proven = s, name, p
    return best, proven, engine


# ---------------------------------------------------------------------------
# Solution -> plan JSON
# ---------------------------------------------------------------------------
def decode(puz, sol, meta, engine, proven):
    T = meta["t_max"]
    placements = []
    ori0 = sol["ori"][0]
    for m, aid in enumerate(meta["arm_ids"]):
        placements.append(
            {
                "type": "arm",
                "id": aid,
                "position": [sol["base_q"][m], sol["base_r"][m]],
                "rotation": ori0[m],
            }
        )
    for s, rid in enumerate(meta["reagent_ids"]):
        oq, orr = meta["reagent_off"][s]
        placements.append(
            {
                "type": "input",
                "id": rid,
                "position": [sol["sq"][s] - oq, sol["sr"][s] - orr],
                "rotation": 0,
            }
        )
    for o, pid in enumerate(meta["product_ids"]):
        placements.append(
            {
                "type": "output",
                "id": pid,
                "position": [sol["out_q"][o], sol["out_r"][o]],
                "rotation": sol["out_rot"][o],
            }
        )
    for g, cid in enumerate(meta["calc_ids"]):
        placements.append(
            {"type": "calcifier", "id": cid, "position": [sol["calc_q"][g], sol["calc_r"][g]]}
        )
    for g, bid in enumerate(meta["bonder_ids"]):
        d = (sol["bonder_q2"][g] - sol["bonder_q1"][g], sol["bonder_r2"][g] - sol["bonder_r1"][g])
        placements.append(
            {
                "type": "bonder",
                "id": bid,
                "position": [sol["bonder_q1"][g], sol["bonder_r1"][g]],
                "rotation": DIRS.index(d),
            }
        )
    instructions = []
    acts = [
        ("grab", sol["doGrab"]),
        ("drop", sol["doDrop"]),
        ("rot_cw", sol["doCW"]),
        ("rot_ccw", sol["doCCW"]),
    ]
    for t in range(T):
        for m, aid in enumerate(meta["arm_ids"]):
            for name, arr in acts:
                if arr[t][m]:
                    instructions.append({"t": t, "arm": aid, "action": name})
    return {
        "puzzle": puz["name"],
        "solver": f"minizinc/{engine} via minizinc/adapter.py "
        f"({'proved optimal' if proven else 'best incumbent'}, "
        f"objective {sol['total_actions']})",
        "placements": placements,
        "instructions": instructions,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("puzzle")
    ap.add_argument(
        "--solver",
        default="auto",
        choices=["auto", "chuffed", "cp-sat", "gecode", "highs", "coin-bc"],
    )
    ap.add_argument("--time-limit", type=float, default=300.0)
    ap.add_argument("--procs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--keep-dzn")
    args = ap.parse_args()

    try:
        with open(args.puzzle) as f:
            puz = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        die(2, f"cannot read puzzle: {e}")

    dzn, pins, meta = build_instance(puz)
    tmp = tempfile.mkdtemp(prefix="om-adapter-")
    try:
        dzn_path = os.path.join(tmp, "instance.dzn")
        with open(dzn_path, "w") as f:
            f.write(dzn)
        if args.keep_dzn:
            with open(args.keep_dzn, "w") as f:
                f.write(dzn)
        files = [MODEL, dzn_path]
        if pins:
            pins_path = os.path.join(tmp, "pins.mzn")
            with open(pins_path, "w") as f:
                f.write(pins)
            files.append(pins_path)
        sol, proven, engine = solve(files, args.solver, args.time_limit, args.procs)
        if sol is None:
            die(1, "no plan found within the budget")
        plan = decode(puz, sol, meta, engine, proven)
        log(
            f"plan: {sol['total_actions']} actions, engine={engine}, "
            f"optimal={'yes' if proven else 'not proved'}"
        )
        json.dump(plan, sys.stdout, indent=2)
        print()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
