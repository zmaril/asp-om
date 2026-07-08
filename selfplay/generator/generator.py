#!/usr/bin/env python3
"""Forward-generation engine: manufacture guaranteed-solvable, self-labeled
(puzzle, solution) pairs from the game rules alone.

Instead of solving puzzles backward, this runs a random machine FORWARD:
sample random reagent inputs on the bounded hex board, place a random LEGAL
machine (arms / calcification + bonding glyphs, within the simplified model
of asp/core2.lp), build a random legal instruction tape step by step, and
simulate it with the repo's exact replay semantics (validate.replay_v2,
imported verbatim). Whatever molecule the machine ends up producing IS the
puzzle's product -- so by construction every emitted puzzle is solvable and
ships with the exact machine + tape that solves it as a reference solution.

Output is in the COMMON HARNESS FORMATS (harness/SPEC.md): one puzzle JSON
and one plan JSON per pair, and every emitted pair is validated through
the canonical harness/validate.py before it is written.

No external solution data is used anywhere: the only inputs are the game
rules (the simulator) and a random seed.

Usage (see --help for all knobs):
    python3 selfplay/generator/generator.py --count 100 --seed 7 \
        --out selfplay/generator/sample_batch
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from model import (
    ATOM_TYPES,
    Arm,
    Input,
    Machine,
    canonical_molecule,
    component_to_molecule,
    components,
    emit_plan,
    emit_puzzle,
    find_output_placement,
    load_harness_validator,
)

import validate as omval  # repo root, put on sys.path by model

# ---------------------------------------------------------------------------
# Layout sampling: place each part on a still-free hex (constructive, so
# the OM non-overlap rule holds by construction; footprint_ok re-checks).
#
# An arm's gripper can only ever visit the 6 hexes base + L*dir(d) -- arms
# do not translate in this model -- so a machine is only *productive* if
# reagents / glyphs lie on those gripper hexes.  Placement therefore draws
# each part from the union of the arms' gripper hexes with high probability
# (REACH_BIAS) and uniformly from the whole board otherwise, keeping the
# occasional unreachable decoy part for diversity.
# ---------------------------------------------------------------------------
REACH_BIAS = 0.85


def sample_layout(rng: random.Random, p) -> Machine | None:
    """Sample a random machine layout; None if placement runs out of room
    or the final legality check fails (caller retries)."""
    board = omval.hexes(p.radius)
    free = sorted(board)
    rng.shuffle(free)

    arms = []
    for i in range(rng.randint(*p.arms)):
        if not free:
            return None
        base = free.pop()
        length = rng.randint(1, p.arm_len)
        dirs = [
            d
            for d in range(6)
            if (base[0] + length * omval.DIRS[d][0], base[1] + length * omval.DIRS[d][1]) in board
        ]
        if not dirs:
            return None
        arms.append(Arm(name=f"m{i + 1}", base=base, length=length, orient=rng.choice(dirs)))

    grip_hexes = {
        (a.base[0] + a.length * omval.DIRS[d][0], a.base[1] + a.length * omval.DIRS[d][1])
        for a in arms
        for d in range(6)
    } & board

    def take_hex() -> tuple[int, int] | None:
        reach = [h for h in free if h in grip_hexes]
        pool = reach if reach and rng.random() < REACH_BIAS else free
        if not pool:
            return None
        h = rng.choice(pool)
        free.remove(h)
        return h

    bonders = []
    for _ in range(rng.randint(*p.bonders)):
        # strongly prefer an adjacent pair with BOTH hexes on gripper
        # hexes (a bond needs both hexes covered at once, and an arm can
        # only deliver an atom to its 6 gripper hexes)
        pairs = [
            (h1, (h1[0] + dq, h1[1] + dr))
            for h1 in free
            for dq, dr in omval.DIRS
            if (h1[0] + dq, h1[1] + dr) in board and (h1[0] + dq, h1[1] + dr) in free
        ]
        both = [pr for pr in pairs if pr[0] in grip_hexes and pr[1] in grip_hexes]
        pool = both if both and rng.random() < REACH_BIAS else pairs
        if not pool:
            return None
        h1, h2 = rng.choice(pool)
        free.remove(h1)
        free.remove(h2)
        bonders.append((h1, h2))

    calcs = []
    for _ in range(rng.randint(*p.calcifiers)):
        h = take_hex()
        if h is None:
            return None
        calcs.append(h)

    inputs = []
    for i in range(rng.randint(*p.inputs)):
        h = take_hex()
        if h is None:
            return None
        inputs.append(
            Input(index=i + 1, hex=h, type=rng.choice(p.atom_types), pool=rng.randint(1, p.pool))
        )

    m = Machine(
        radius=p.radius, arms=arms, inputs=inputs, calcs=calcs, bonders=bonders, tape={}, tmax=0
    )
    if not m.footprint_ok():
        return None
    # cheap viability screen: a machine can only ever produce something if
    # its arms can actually deliver atoms to a bonder (both hexes) or to a
    # calcifier. Layouts that cannot are rejected before the (much more
    # expensive) tape sampling. This is a heuristic bias, not a semantics
    # change: multi-arm relay chains it cannot see are astronomically
    # unlikely to assemble by random walk anyway.
    reachable_pool = sum(i.pool for i in inputs if i.hex in grip_hexes)
    bondable = reachable_pool >= 2 and any(
        h1 in grip_hexes and h2 in grip_hexes for h1, h2 in bonders
    )
    calcable = any(h in grip_hexes for h in calcs) and any(
        i.pool >= 1 and i.hex in grip_hexes and i.type in omval.ELEMENTAL for i in inputs
    )
    if not bondable and not calcable:
        return None
    return m


# ---------------------------------------------------------------------------
# Tape sampling: build a legal plan step by step.
# Legality of each candidate action is decided by replaying the prefix with
# validate.replay_v2 -- the physics is never reimplemented here.  Among the
# LEGAL candidates, selection is randomly weighted by a potential function
# read off the replayed state (bonds formed, atoms parked on bonder hexes,
# held atoms near bonders) so that random walks actually assemble molecules
# instead of stirring the board; the guidance only biases sampling and can
# never make an illegal plan.
# ---------------------------------------------------------------------------
GREED = 3.0  # softmax sharpness over the state potential
MOMENTUM = 3.0  # prior boost for continuing the previous rotation


def try_step(machine: Machine, plan: dict, t: int, cand: tuple[str, str] | None):
    """Replay plan[0..t-1] + cand; return the state list or None if the
    candidate action is illegal."""
    trial = dict(plan)
    if cand is not None:
        trial[t] = cand
    m2 = Machine(
        machine.radius, machine.arms, machine.inputs, machine.calcs, machine.bonders, trial, t + 1
    )
    states, err = m2.replay()
    return None if err is not None else states


def hexdist(a: tuple[int, int], b: tuple[int, int]) -> int:
    dq, dr = a[0] - b[0], a[1] - b[1]
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


def score_state(machine: Machine, st, grippers) -> float:
    """Potential of a replay snapshot: reward assembled bonds, unbonded
    atoms STAGED (dropped, unheld) on bonder hexes and elementals on
    calcifiers; shape every unbonded atom toward the bonders (held or
    not, so that grabbing a far reagent is score-neutral and un-staging
    a parked atom costs); pull empty grippers toward grabbable atoms; and
    push finished (bonded) atoms OFF part hexes, because the harness
    output part must be placed on part-free hexes for the product to be
    deliverable.

    grippers: {arm_name: (gripper_hex, holding: bool)} for this snapshot.
    """
    bonded = {x for b in st["bonds"] for x in b}
    bonder_hexes = [h for pair in machine.bonders for h in pair]
    feet = machine.part_footprint()
    s = 6.0 * len(st["bonds"])
    s += 2.0 * sum(
        1
        for x, h in st["pos"].items()
        if h in bonder_hexes and x not in bonded and x not in st["held"]
    )
    s += 0.8 * sum(
        1 for x, h in st["pos"].items() if h in machine.calcs and st["typ"][x] in omval.ELEMENTAL
    )
    s -= 0.7 * sum(1 for x, h in st["pos"].items() if x in bonded and h in feet)
    if bonder_hexes:
        for x, h in st["pos"].items():
            if x not in bonded:
                s -= 0.25 * min(hexdist(h, b) for b in bonder_hexes)
    # holding an unbonded atom is mild progress (breaks grab/drop dither)
    s += 0.3 * sum(1 for x in st["held"] if x not in bonded)
    # empty hands drift toward the nearest loose (unheld) atom
    loose = [h for x, h in st["pos"].items() if x not in st["held"]]
    if loose:
        for g, holding in grippers.values():
            if not holding:
                s -= 0.15 * min(hexdist(g, h) for h in loose)
    return s


def holding_after(machine: Machine, plan: dict, t: int) -> set[str]:
    """Arms whose hand is full after plan[0..t-1]. The plan prefix is legal
    by construction (every step passed try_step), so a legal grab always
    fills the hand and a legal drop always empties it -- no replay needed."""
    holds: dict[str, bool] = {a.name: False for a in machine.arms}
    for tt in sorted(k for k in plan if k < t):
        arm, act = plan[tt]
        if act == "grab":
            holds[arm] = True
        elif act == "drop":
            holds[arm] = False
    return {a for a, h in holds.items() if h}


def sample_tape(rng: random.Random, machine: Machine, tape_len: int) -> bool:
    """Fill machine.tape/tmax with a random legal plan. Returns False if the
    initial layout state is itself illegal (shouldn't happen after
    footprint_ok, but replay is the ground truth)."""
    plan: dict[int, tuple[str, str]] = {}
    if try_step(machine, plan, -1, None) is None:  # t=0 static state check
        return False
    orient = {a.name: a.orient for a in machine.arms}
    lengths = {a.name: (a.base, a.length) for a in machine.arms}
    last_choice: tuple[str, str] | None = None

    def grippers_for(cand, full):
        """{arm: (gripper hex, holding)} in the state after cand."""
        out = {}
        for name, (base, ln) in lengths.items():
            d = orient[name]
            holding = name in full
            if cand is not None and cand[0] == name:
                if cand[1] == "rot_cw":
                    d = (d + 1) % 6
                elif cand[1] == "rot_ccw":
                    d = (d + 5) % 6
                elif cand[1] == "grab":
                    holding = True
                elif cand[1] == "drop":
                    holding = False
            g = (base[0] + ln * omval.DIRS[d][0], base[1] + ln * omval.DIRS[d][1])
            out[name] = (g, holding)
        return out

    for t in range(tape_len):
        full = holding_after(machine, plan, t)
        cands: list[tuple[tuple[str, str] | None, float]] = [(None, 0.25)]
        for a in machine.arms:
            if a.name in full:
                prior = {"rot_cw": 2.0, "rot_ccw": 2.0, "drop": 1.0}
                if t >= tape_len - 2 * len(machine.arms):
                    prior["drop"] = 10.0  # end of tape: put things down
            else:
                prior = {"grab": 4.0, "rot_cw": 1.0, "rot_ccw": 1.0}
            for act, w in prior.items():
                # momentum: keeping a rotation going makes multi-step
                # detours (e.g. around an occupied bonder hex) likely
                if (a.name, act) == last_choice and act.startswith("rot"):
                    w *= MOMENTUM
                cands.append(((a.name, act), w))
        legal = []
        for c, w in cands:
            states = try_step(machine, plan, t, c)
            if states is not None:
                legal.append((c, w, score_state(machine, states[-1], grippers_for(c, full))))
        best = max(s for _, _, s in legal)
        weights = [w * math.exp(GREED * min(s - best, 0.0)) for _, w, s in legal]
        choice = rng.choices([c for c, _, _ in legal], weights=weights)[0]
        if choice is not None:
            plan[t] = choice
            last_choice = choice
            if choice[1] == "rot_cw":
                orient[choice[0]] = (orient[choice[0]] + 1) % 6
            elif choice[1] == "rot_ccw":
                orient[choice[0]] = (orient[choice[0]] + 5) % 6
    # trim trailing waits; effects of the action at t land at t+1
    last = max(plan) if plan else -1
    machine.tape = {t: a for t, a in plan.items() if t <= last}
    machine.tmax = last + 1 if last >= 0 else 0
    return True


# ---------------------------------------------------------------------------
# Product extraction + rejection rules
# ---------------------------------------------------------------------------
def pick_product(machine: Machine, states) -> tuple | None:
    """Choose the product molecule from the replay trajectory.

    The harness goal is 'complete at SOME t <= t_max' and completion does
    not consume the atoms (harness/SPEC.md section 5.4), so every state is
    scanned: any moment a molecule rests unheld on part-free hexes is a
    valid delivery, even if the machine disturbs it afterwards.

    Rejections (degenerate outputs):
      * component held by an arm at that time;
      * single atom of a type that is directly available as a reagent
        input (product identical to a reagent / no-op machine);
      * component resting on any part footprint hex -- the harness output
        part must be placeable exactly where the product rests, and part
        footprints must be pairwise disjoint (harness/SPEC.md section 4);
      * nothing left after the above (empty product).
    Reagents are single unbonded atoms in this model, so any component of
    size >= 2 required real work (inputs never overlap bonder hexes).
    Among survivors, prefer the largest molecule, then the earliest
    completion time (the tape is trimmed to it).

    Returns (canon_atoms, canon_bonds, hash, rest_hexes, t_star) where
    rest_hexes maps the product's actual resting hexes to elements and
    t_star is the completion time.
    """
    reagent_types = {i.type for i in machine.inputs}
    feet = machine.part_footprint()
    best = None
    for t, st in enumerate(states):
        for comp in components(st):
            if comp["held"]:
                continue
            if any(h in feet for h in comp["atoms"].values()):
                continue
            atoms, bonds = component_to_molecule(comp)
            if len(atoms) == 1 and atoms[0][2] in reagent_types:
                continue
            c_atoms, c_bonds, h = canonical_molecule(atoms, bonds)
            rest = {hx: comp["types"][x] for x, hx in comp["atoms"].items()}
            key = (len(atoms), -t, h)
            if best is None or key > best[0]:
                best = (key, c_atoms, c_bonds, h, rest, t)
    if best is None:
        return None
    _, c_atoms, c_bonds, h, rest, t_star = best
    return c_atoms, c_bonds, h, rest, t_star


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------
def generate_one(rng: random.Random, p):
    machine = sample_layout(rng, p)
    if machine is None:
        return None, "layout"
    tape_len = rng.randint(*p.tape)
    if not sample_tape(rng, machine, tape_len):
        return None, "layout"
    if machine.instruction_count() == 0:
        return None, "empty_tape"
    states, err = machine.replay()
    assert err is None, f"generator produced an illegal plan: {err}"
    product = pick_product(machine, states)
    if product is None:
        return None, "no_product"
    c_atoms, c_bonds, phash, rest, t_star = product
    # trim the tape to the completion time: instructions after t_star do
    # not contribute to the (earliest) delivery; the prefix trajectory is
    # unchanged, so the product still rests at rest_hexes at t_star
    machine.tape = {t: a for t, a in machine.tape.items() if t < t_star}
    machine.tmax = t_star
    if machine.instruction_count() == 0:
        return None, "empty_tape"
    return (machine, (c_atoms, c_bonds, phash, rest)), None


def diversity_report(pairs: list[tuple[dict, dict]], rejects: Counter, attempts: int) -> dict:
    puzzles = [pz for pz, _ in pairs]
    plans = [pl for _, pl in pairs]
    prod_sizes = Counter(len(pz["products"][0]["atoms"]) for pz in puzzles)
    bond_counts = Counter(len(pz["products"][0]["bonds"]) for pz in puzzles)
    atom_mix = Counter(a["element"] for pz in puzzles for a in pz["products"][0]["atoms"])
    arm_counts = Counter(sum(1 for p in pz["parts"] if p["type"] == "arm") for pz in puzzles)
    tape_lens = Counter(sum(1 for i in pl["instructions"] if i["action"] != "wait") for pl in plans)
    glyphs: Counter[str] = Counter()
    for pz in puzzles:
        for p in pz["parts"]:
            if p["type"] != "arm":
                glyphs[p["type"]] += 1
    reagent_counts = Counter(len(pz["reagents"]) for pz in puzzles)
    reagent_mix = Counter(
        a["element"] for pz in puzzles for r in pz["reagents"] for a in r["atoms"]
    )
    uniq = len({json.dumps(pz["products"][0], sort_keys=True) for pz in puzzles})
    return {
        "pairs": len(pairs),
        "attempts": attempts,
        "yield": round(len(pairs) / attempts, 4) if attempts else None,
        "rejections": dict(rejects),
        "unique_products": uniq,
        "product_size_distribution": dict(sorted(prod_sizes.items())),
        "product_bond_count_distribution": dict(sorted(bond_counts.items())),
        "product_atom_type_mix": dict(atom_mix.most_common()),
        "reagent_atom_type_mix": dict(reagent_mix.most_common()),
        "machine_arm_count_distribution": dict(sorted(arm_counts.items())),
        "plan_length_distribution": dict(sorted(tape_lens.items())),
        "glyph_totals": dict(glyphs),
        "reagent_count_distribution": dict(sorted(reagent_counts.items())),
    }


def summarize(rep: dict) -> str:
    lines = [
        f"pairs: {rep['pairs']}  (attempts: {rep['attempts']}, yield: {rep['yield']})",
        f"rejections: {rep['rejections']}",
        f"unique products (canonical up to rotation+translation): {rep['unique_products']}",
        f"product size dist:  {rep['product_size_distribution']}",
        f"product bond dist:  {rep['product_bond_count_distribution']}",
        f"product atom mix:   {rep['product_atom_type_mix']}",
        f"reagent atom mix:   {rep['reagent_atom_type_mix']}",
        f"arm count dist:     {rep['machine_arm_count_distribution']}",
        f"plan length dist:   {rep['plan_length_distribution']}",
        f"glyph totals:       {rep['glyph_totals']}",
        f"reagent count dist: {rep['reagent_count_distribution']}",
    ]
    return "\n".join(lines)


def parse_range(s: str) -> tuple[int, int]:
    if ":" in s:
        a, b = s.split(":", 1)
        return (int(a), int(b))
    return (int(s), int(s))


def main() -> int:
    ap = argparse.ArgumentParser(description="Forward-generate solvable (puzzle, solution) pairs.")
    ap.add_argument("--count", type=int, default=100, help="pairs to generate (after dedup)")
    ap.add_argument("--seed", type=int, default=0, help="RNG seed (full run is deterministic)")
    ap.add_argument(
        "--out", type=Path, default=Path(__file__).parent / "batch", help="output directory"
    )
    # difficulty knobs -------------------------------------------------------
    ap.add_argument("--radius", type=int, default=2, help="board radius")
    ap.add_argument(
        "--arms", type=parse_range, default=(1, 2), metavar="A[:B]", help="number of arms"
    )
    ap.add_argument("--arm-len", type=int, default=2, help="max arm length")
    ap.add_argument(
        "--tape",
        type=parse_range,
        default=(12, 26),
        metavar="A[:B]",
        help="tape length (timesteps)",
    )
    ap.add_argument(
        "--inputs",
        type=parse_range,
        default=(1, 3),
        metavar="A[:B]",
        help="number of reagent inputs",
    )
    ap.add_argument(
        "--calcifiers",
        type=parse_range,
        default=(0, 1),
        metavar="A[:B]",
        help="number of calcification glyphs",
    )
    ap.add_argument(
        "--bonders",
        type=parse_range,
        default=(1, 2),
        metavar="A[:B]",
        help="number of bonding glyphs",
    )
    ap.add_argument("--pool", type=int, default=2, help="max atoms per reagent input")
    ap.add_argument(
        "--atom-types",
        default="air,earth,fire,water,salt",
        help="comma-separated reagent atom types",
    )
    ap.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="give up after this many attempts (default: 200 * count)",
    )
    args = ap.parse_args()
    args.atom_types = tuple(t.strip() for t in args.atom_types.split(","))
    for t in args.atom_types:
        if t not in ATOM_TYPES:
            ap.error(f"unknown atom type {t!r} (choose from {ATOM_TYPES})")
    max_attempts = args.max_attempts or 200 * args.count

    rng = random.Random(args.seed)
    puzzles_dir = args.out / "puzzles"
    plans_dir = args.out / "plans"
    puzzles_dir.mkdir(parents=True, exist_ok=True)
    plans_dir.mkdir(parents=True, exist_ok=True)
    hval = load_harness_validator()

    seen: set[tuple] = set()
    pairs: list[tuple[dict, dict]] = []
    rejects: Counter = Counter()
    attempts = 0
    while len(pairs) < args.count and attempts < max_attempts:
        attempts += 1
        result, why = generate_one(rng, args)
        if result is None:
            rejects[why] += 1
            continue
        machine, (c_atoms, c_bonds, phash, rest) = result
        key = (machine.radius, tuple(sorted(i.type for i in machine.inputs)), phash)
        if key in seen:
            rejects["duplicate"] += 1
            continue
        seen.add(key)
        name = f"fg_s{args.seed}_{len(pairs) + 1:04d}"
        out_pos, out_rot = find_output_placement(c_atoms, rest)
        puzzle = emit_puzzle(name, machine, c_atoms, c_bonds, phash)
        plan = emit_plan(name, machine, out_pos, out_rot)
        # every pair must pass the canonical harness validator, by
        # construction -- a failure here is a generator (or model) bug
        hval.validate(puzzle, plan)
        pairs.append((puzzle, plan))
        (puzzles_dir / f"{name}.json").write_text(json.dumps(puzzle, indent=1) + "\n")
        (plans_dir / f"{name}.json").write_text(json.dumps(plan, indent=1) + "\n")

    rep = diversity_report(pairs, rejects, attempts)
    (args.out / "diversity_report.json").write_text(json.dumps(rep, indent=2) + "\n")
    summary = summarize(rep)
    (args.out / "diversity_summary.txt").write_text(summary + "\n")
    print(summary)
    if len(pairs) < args.count:
        print(
            f"WARNING: only {len(pairs)}/{args.count} pairs after {attempts} attempts",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
