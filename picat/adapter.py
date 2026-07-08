#!/usr/bin/env python3
"""Picat adapter for the multi-solver Opus Magnum harness.

Harness contract (harness/README.md, harness/SPEC.md):

    python3 picat/adapter.py <puzzle.json> [--out FILE] [--time-limit S]
        [--picat PATH] [--noprune] [--keep-program FILE]

Reads the common puzzle JSON, generates a self-contained Picat planner
program (the v2 engine from picat/stabilized_water_free.pi -- state term,
mk_next spawn/calcify/bond post-state rules, rigid rotation, free layout
as a setup phase of cost-1 placement actions -- generalized from the
hard-coded instances to generated instance facts), solves it with the
planner module's best_plan (iterative deepening: the returned cost is a
PROVEN optimum over all layouts within the horizon), and writes the
common plan JSON to stdout (or --out).  Exit 0 = solved, 1 = no plan
found (no solution within the horizon, or the time limit expired),
2 = malformed/unsupported puzzle.  All logs go to stderr.

Environment:
    HARNESS_PICAT_TIME_LIMIT  time limit in seconds (default 300); the
                              picat process is killed when it expires
                              (best_plan does not stream incumbents, so
                              a timeout returns NO plan -- exit 1).
    PICAT                     path to the picat binary (default: `picat`
                              on PATH; see picat/NOTES.md for install).

Harness conformance notes (vs harness/validate.py, the canonical spec):

  * Placements: the engine models free layout as cost-1 setup actions
    (picat/NOTES.md, phase 3).  The adapter strips them into the plan's
    declarative `placements` section, so plan length = engine cost minus
    the constant placement count, exactly the harness metric.  Setup
    ordering cannot diverge from the harness's "everything placed at
    t=0": during setup atoms exist only on input hexes (spawned copy 1),
    and footprint disjointness keeps glyphs off input hexes, so no glyph
    can fire and no atom can move before the first instruction.
  * Glyph timing shim: the engine keeps the merged Picat model's timing
    (calcify/spawn/bond applied in mk_next at the atoms' post-action
    positions), while the harness reads calcifier positions at time t
    and retypes at t+1 (SPEC.md reconciliation decision 2).  The two
    timings agree on every observation OFF the calcifier hex: an atom
    that lands on the glyph at state s is salt from state s under the
    engine and from state s+1 under the harness, and it can only be
    observed elsewhere (output hexes are disjoint from the calcifier by
    the footprint rule) from state s+1 onward, by which point both say
    salt.  Grab/rotate/spawn/bond are element-blind, so the same
    instruction sequences are valid under both timings and the optima
    coincide.  Every emitted plan is still checked with
    harness/validate.py -- do not trust this argument, run the validator.
  * No `wait`: emitted plans have none; under the engine's semantics a
    wait never changes the state, and plan length counts non-waits only.
  * Goal: exact harness completion (element per output hex, atoms
    unheld, product bonds present, exact total bond degree), checked in
    the planner's final state.  Products complete simultaneously there;
    the harness's per-product latching is only weaker, so found plans
    remain valid (with several products this could in principle cost
    optimality; the shared instances have one product each).

Search reductions (all exact / instance-gated, --noprune disables the
distance prunes; the rotational symmetry quotient is always exact):

  * Rotational symmetry: when the puzzle pins nothing, the first arm's
    base is restricted to one representative per orbit of the 6-fold
    board rotation about the origin (orientation fixed to 0 when the
    base is the origin).  Rotating a whole layout+plan about the origin
    is a validity-preserving bijection, so this is lossless.
  * Sound distance prunes, applied only when (a) all reagents are
    single-atom and (b) the total spawnable pool equals the total
    product atom count (then every atom is a product atom, every part
    is load-bearing, and bond-connected components never exceed the
    largest product).  Under those conditions, in any valid plan:
      - an atom's first motion is a direct grab at its spawn hex, so
        every input hex lies at distance exactly L from some arm base;
      - atoms only ever occupy input hexes or hexes within
        L + (max product size - 1) of some base, bounding calcifier,
        bonder and output hexes;
      - a product molecule must move onto its output after its last
        bond fires on the (disjoint) bonder, with a product atom in the
        gripper, so some output hex is at distance exactly L from some
        base;
      - additionally when no product atom has bond degree > 1, every
        bond ever formed in a valid plan joins two singleton atoms,
        which rest only on input hexes or gripper rings, so both bonder
        hexes lie at distance exactly L from some base.
  * Identical reagents (same molecule, same pool) are interchangeable:
    their chosen input hexes are forced into lexicographic order.

Limitations (like the clingo reference adapter): single-atom reagents
only; elements air/earth/fire/water/salt.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]


def log(*a):
    print("adapter:", *a, file=sys.stderr, flush=True)


def die(msg, code=2):
    log("error:", msg)
    sys.exit(code)


def rot_k(q, r, k):
    for _ in range(k % 6):
        q, r = -r, q + r
    return (q, r)


def on_board(q, r, radius):
    return abs(q) <= radius and abs(r) <= radius and abs(q + r) <= radius


def board_hexes(radius):
    return [(q, r) for q in range(-radius, radius + 1)
            for r in range(-radius, radius + 1) if on_board(q, r, radius)]


def molecule(m):
    atoms = [(a["element"], tuple(a["pos"])) for a in m["atoms"]]
    bonds = {frozenset(b) for b in m.get("bonds", [])}
    return atoms, bonds


def canonical_rotations(atoms, bonds):
    """Rotation indices giving geometrically distinct placements (dedupes
    symmetric molecules; same logic as the clingo reference adapter)."""
    keep, seen = [], set()
    for d in range(6):
        cells = [rot_k(q, r, d) for _, (q, r) in atoms]
        anchor = min(cells)
        norm = frozenset(((c[0] - anchor[0], c[1] - anchor[1]), el)
                         for (el, _), c in zip(atoms, cells))
        nbonds = frozenset(
            frozenset(((cells[i][0] - anchor[0], cells[i][1] - anchor[1]),
                       (cells[j][0] - anchor[0], cells[j][1] - anchor[1])))
            for i, j in (sorted(b) for b in bonds))
        key = (norm, nbonds)
        if key not in seen:
            seen.add(key)
            keep.append(d)
    return keep


# ---------------------------------------------------------------------------
# Instance fact generation
# ---------------------------------------------------------------------------
def puzzle_pins_anything(puzzle):
    return any("position" in spec
               for spec in (puzzle["reagents"] + puzzle["products"]
                            + puzzle["parts"]))


def arm_candidates(puzzle, arm, first_and_free):
    """(base_q, base_r, dir, length) candidates for one arm."""
    radius, length = puzzle["board_radius"], arm["length"]
    if "position" in arm:
        bases = [tuple(arm["position"])]
        canonical = False
    elif first_and_free:
        # one representative hex per orbit of rotation about the origin
        bases = sorted({min(rot_k(q, r, k) for k in range(6))
                        for q, r in board_hexes(radius)})
        canonical = True
    else:
        bases = board_hexes(radius)
        canonical = False
    out = []
    for bq, br in bases:
        if "rotation" in arm:
            dirs = [arm["rotation"] % 6]
        elif canonical and (bq, br) == (0, 0):
            dirs = [0]  # origin is fixed by the rotation group
        else:
            dirs = range(6)
        for d in dirs:
            gq, gr = bq + length * DIRS[d][0], br + length * DIRS[d][1]
            if on_board(gq, gr, radius):
                out.append((bq, br, d, length))
    return out


def input_candidates(puzzle, reagent):
    """Spawn-hex candidates for a single-atom reagent; returns
    (candidate hexes, offset, pinned_rotation)."""
    radius = puzzle["board_radius"]
    atoms, _ = molecule(reagent)
    (_, off), = atoms
    if "position" in reagent:
        rot = reagent.get("rotation", 0) % 6
        oq, orr = rot_k(*off, rot)
        return ([(reagent["position"][0] + oq,
                  reagent["position"][1] + orr)], off, rot)
    return ([(q + off[0], r + off[1]) for q, r in board_hexes(radius)
             if on_board(q + off[0], r + off[1], radius)], off, 0)


def bonder_candidates(puzzle, part):
    radius = puzzle["board_radius"]
    if "position" in part:
        q, r = part["position"]
        d = part.get("rotation", 0) % 6
        pair = sorted([(q, r), (q + DIRS[d][0], r + DIRS[d][1])])
        return [tuple(pair)]
    out = []
    for q, r in board_hexes(radius):
        for d in range(3):  # unordered pair: 3 directions suffice
            q2, r2 = q + DIRS[d][0], r + DIRS[d][1]
            if on_board(q2, r2, radius):
                out.append(tuple(sorted([(q, r), (q2, r2)])))
    return sorted(set(out))


def calc_candidates(puzzle, part):
    if "position" in part:
        return [tuple(part["position"])]
    return board_hexes(puzzle["board_radius"])


def output_candidates(puzzle, product):
    """(pos_q, pos_r, rot, cells [(q, r, elem, degree)], bond hex pairs)."""
    radius = puzzle["board_radius"]
    atoms, bonds = molecule(product)
    deg = {i: 0 for i in range(len(atoms))}
    for b in bonds:
        i, j = sorted(b)
        deg[i] += 1
        deg[j] += 1
    if "position" in product:
        positions = [tuple(product["position"])]
        rots = [product.get("rotation", 0) % 6]
    else:
        positions = board_hexes(radius)
        rots = canonical_rotations(atoms, bonds)
    out = []
    for rot in rots:
        offs = [rot_k(q, r, rot) for _, (q, r) in atoms]
        for pq, pr in positions:
            cells = [(pq + oq, pr + orr) for oq, orr in offs]
            if not all(on_board(q, r, radius) for q, r in cells):
                continue
            cell_facts = [(c[0], c[1], atoms[i][0], deg[i])
                          for i, c in enumerate(cells)]
            bond_pairs = [(cells[i], cells[j])
                          for i, j in (sorted(b) for b in bonds)]
            out.append((pq, pr, rot, cell_facts, bond_pairs))
    return out


def picat_list(items):
    return "[" + ",".join(items) + "]"


def generate_program(puzzle, prune):
    radius, t_max = puzzle["board_radius"], puzzle["t_max"]
    arms = [p for p in puzzle["parts"] if p["type"] == "arm"]
    calcs = [p for p in puzzle["parts"] if p["type"] == "calcifier"]
    bonders = [p for p in puzzle["parts"] if p["type"] == "bonder"]
    reagents, products = puzzle["reagents"], puzzle["products"]

    for m in reagents:
        atoms, bonds = molecule(m)
        if len(atoms) != 1 or bonds:
            die(f"reagent {m['id']}: this adapter supports single-atom "
                f"reagents only (like the clingo reference adapter)")

    # --- prune applicability (soundness conditions in the docstring) --------
    total_pool = sum(m["pool"] for m in reagents)
    product_atoms = sum(len(m["atoms"]) for m in products)
    max_prod_size = max(len(m["atoms"]) for m in products)
    max_prod_degree = 0
    for m in products:
        _, bonds = molecule(m)
        for b in bonds:
            for i in b:
                d = sum(1 for bb in bonds if i in bb)
                max_prod_degree = max(max_prod_degree, d)
    prunes_on = prune and total_pool == product_atoms
    part_max_extra = (max_prod_size - 1) if prunes_on else -1
    bonder_ring = prunes_on and max_prod_degree <= 1
    if prune and not prunes_on:
        log("distance prunes disabled: pool total != product atom total")

    pins = puzzle_pins_anything(puzzle)
    facts = [f"radius() = {radius}.", f"tmax() = {t_max}."]

    # --- arms ----------------------------------------------------------------
    arm_ids = {}
    for i, arm in enumerate(arms, start=1):
        arm_ids[i] = arm["id"]
        cands = arm_candidates(puzzle, arm, first_and_free=(i == 1 and
                                                            not pins))
        if not cands:
            die(f"arm {arm['id']}: no legal base/orientation")
        for bq, br, d, l in cands:
            facts.append(f"arm_cand({i},{bq},{br},{d},{l}).")

    # --- inputs ----------------------------------------------------------------
    reagent_ids, input_off, input_rot = {}, {}, {}
    sig_prev = {}
    cand_f, pool_f, type_f, prev_f = [], [], [], []
    for i, m in enumerate(reagents, start=1):
        reagent_ids[i] = m["id"]
        cands, off, rot = input_candidates(puzzle, m)
        input_off[i], input_rot[i] = off, rot
        for q, r in cands:
            cand_f.append(f"input_cand({i},{q},{r}).")
        pool_f.append(f"input_pool({i}) = {m['pool']}.")
        type_f.append(f"input_type({i}) = {m['atoms'][0]['element']}.")
        # identical single-atom reagents are interchangeable: force their
        # chosen hexes into lexicographic order (symmetry breaking)
        sig = (m["atoms"][0]["element"], tuple(m["atoms"][0]["pos"]),
               m["pool"])
        prev = sig_prev.get(sig) if "position" not in m else None
        prev_f.append(f"input_prev({i}) = {prev if prev else 'none'}.")
        sig_prev[sig] = i
    facts += cand_f + pool_f + type_f + prev_f

    # --- glyphs ------------------------------------------------------------------
    calc_ids, bonder_ids = {}, {}
    calc_cands_all = set()
    for i, p in enumerate(calcs, start=1):
        calc_ids[i] = p["id"]
        calc_cands_all.update(calc_candidates(puzzle, p))
    if calc_cands_all:
        for q, r in sorted(calc_cands_all):
            facts.append(f"calc_cand({q},{r}).")
    else:
        facts.append("calc_cand(_, _) => fail.")
    bonder_cands_all = set()
    for i, p in enumerate(bonders, start=1):
        bonder_ids[i] = p["id"]
        bonder_cands_all.update(bonder_candidates(puzzle, p))
    if bonder_cands_all:
        for (q1, r1), (q2, r2) in sorted(bonder_cands_all):
            facts.append(f"bonder_cand({q1},{r1},{q2},{r2}).")
    else:
        facts.append("bonder_cand(_, _, _, _) => fail.")
    # note: with several calcifiers/bonders the per-part candidate sets are
    # unioned (pins still enforced by the harness validator's _pinned check
    # would NOT be -- so refuse the unsupported corner instead):
    if len(calcs) > 1 and any("position" in p for p in calcs):
        die("multiple calcifiers with pins: unsupported")
    if len(bonders) > 1 and any("position" in p for p in bonders):
        die("multiple bonders with pins: unsupported")

    # --- outputs ----------------------------------------------------------------
    product_ids = {}
    out_place_facts, out_cells_facts, out_bonds_facts = [], [], []
    for k, m in enumerate(products, start=1):
        product_ids[k] = m["id"]
        cands = output_candidates(puzzle, m)
        if not cands:
            die(f"product {m['id']}: no on-board output placement")
        for pq, pr, rot, cells, bond_pairs in cands:
            out_place_facts.append(f"out_place({k},{pq},{pr},{rot}).")
            cl = picat_list([f"{{{q},{r},{el},{dg}}}"
                             for q, r, el, dg in cells])
            out_cells_facts.append(f"out_cells({k},{pq},{pr},{rot}) = {cl}.")
            bl = picat_list([f"{{{{{a[0]},{a[1]}}},{{{b[0]},{b[1]}}}}}"
                             for a, b in bond_pairs])
            out_bonds_facts.append(f"out_bonds({k},{pq},{pr},{rot}) = {bl}.")
    facts += out_place_facts + out_cells_facts + out_bonds_facts

    # --- pending list + prune flags ----------------------------------------------
    pending = ([f"$place_arm({i})" for i in arm_ids]
               + [f"$place_input({i})" for i in reagent_ids]
               + [f"$place_bonder({i})" for i in bonder_ids]
               + [f"$place_calc({i})" for i in calc_ids]
               + [f"$place_out({k})" for k in product_ids])
    facts.append(f"pending_parts() = {picat_list(pending)}.")
    facts.append(f"nplace() = {len(pending)}.")
    facts.append(f"prune_input_ring() = {str(prunes_on).lower()}.")
    facts.append(f"prune_bonder_ring() = {str(bonder_ring).lower()}.")
    facts.append(f"prune_out_ring() = {str(prunes_on).lower()}.")
    facts.append(f"prune_part_max() = {part_max_extra}.")

    program = ("% Generated by picat/adapter.py -- do not edit.\n"
               "import planner.\n\n"
               + "\n".join(facts) + "\n\n" + ENGINE)
    maps = (arm_ids, reagent_ids, input_off, input_rot, calc_ids,
            bonder_ids, product_ids)
    return program, maps


# ---------------------------------------------------------------------------
# The engine (descendant of picat/stabilized_water_free.pi, generalized)
# ---------------------------------------------------------------------------
ENGINE = r"""
main =>
    S0 = {[], [], [], [], [], [], [], pending_parts()},
    Limit = nplace() + tmax(),
    (best_plan(S0, Limit, Plan, Cost) ->
        println(plan_found),
        foreach (A in Plan) print_action(A) end,
        printf("NPLACE %d%n", nplace()),
        printf("COST %d%n", Cost)
    ;
        println(no_plan)
    ).

print_action({place_arm, I, BQ, BR, L, D}) =>
    printf("PLACE arm %w %w %w %w %w%n", I, BQ, BR, L, D).
print_action({place_input, I, Q, R}) =>
    printf("PLACE input %w %w %w%n", I, Q, R).
print_action({place_calc, I, Q, R}) =>
    printf("PLACE calc %w %w %w%n", I, Q, R).
print_action({place_bonder, I, Q1, R1, Q2, R2}) =>
    printf("PLACE bonder %w %w %w %w %w%n", I, Q1, R1, Q2, R2).
print_action({place_out, K, Q, R, Rot}) =>
    printf("PLACE output %w %w %w %w%n", K, Q, R, Rot).
print_action({step, M, Act}) =>
    printf("STEP %w %w%n", M, Act).

% admissible lower bound: every pending part still costs 1 to place
heuristic({_,_,_,_,_,_,_,Pending}) = len(Pending).

% goal: every product complete in the final state (exact molecule,
% unheld, exact bond degree -- harness/SPEC.md section 5.4)
final({Arms, Atoms, Bonds, _Ins, _Calc, _Bd, Outs, Pending}) =>
    Pending == [],
    foreach ({K, Q, R, Rot} in Outs)
        product_done(K, Q, R, Rot, Arms, Atoms, Bonds)
    end.

product_done(K, Q, R, Rot, Arms, Atoms, Bonds) =>
    foreach ({CQ, CR, E, Deg} in out_cells(K, Q, R, Rot))
        member({X, E, CQ, CR}, Atoms),
        not is_held(Arms, X),
        degree(Bonds, X) == Deg
    end,
    foreach ({{QA,RA},{QB,RB}} in out_bonds(K, Q, R, Rot))
        member({X1, _, QA, RA}, Atoms),
        member({X2, _, QB, RB}, Atoms),
        membchk(norm_pair(X1, X2), Bonds)
    end.

is_held(Arms, X) => member({_,_,_,_,_,H}, Arms), H == X.

degree(Bonds, X) = sum([1 : {A,B} in Bonds, pair_has(A, B, X)]).
pair_has(A, B, X) => (A == X ; B == X).

% -- geometry -----------------------------------------------------------------
dvec(0) = {1,0}.
dvec(1) = {0,1}.
dvec(2) = {-1,1}.
dvec(3) = {-1,0}.
dvec(4) = {0,-1}.
dvec(5) = {1,-1}.

on_board(Q,R) => abs(Q) =< radius(), abs(R) =< radius(), abs(Q+R) =< radius().

% axial rotation about (BQ,BR); Delta 1 = cw, 5 = ccw
rot_point(1, BQ, BR, Q, R) = {BQ - (R-BR), BR + (Q-BQ) + (R-BR)}.
rot_point(5, BQ, BR, Q, R) = {BQ + (Q-BQ) + (R-BR), BR - (Q-BQ)}.

hex_dist(Q1,R1,Q2,R2) = (abs(Q1-Q2) + abs(R1-R2) + abs(Q1+R1-Q2-R2)) div 2.

% -- helpers ------------------------------------------------------------------
norm_pair(X,Y) = cond(X @< Y, {X,Y}, {Y,X}).

elemental(E) => membchk(E, [air, earth, fire, water]).

cell_free(Atoms, Q, R) => not member({_,_,Q,R}, Atoms).

% hexes covered by already-placed part footprints
part_feet(Arms, Ins, Calc, Bd, Outs) = Feet =>
    Feet = [{BQ,BR} : {_,BQ,BR,_,_,_} in Arms]
        ++ [{Q,R} : {_I,Q,R,_N} in Ins]
        ++ [{Q,R} : {Q,R} in Calc]
        ++ [C : {C1,C2} in Bd, C in [C1,C2]]
        ++ [{Q,R} : {K,OQ,OR,Rot} in Outs,
                    {Q,R,_,_} in out_cells(K,OQ,OR,Rot)].

% distance prunes (relative to some arm base; see adapter docstring)
on_ring(Arms, Q, R) => member({_,BQ,BR,L,_,_}, Arms),
                       hex_dist(Q,R,BQ,BR) == L.
within_parts(Arms, Q, R) => member({_,BQ,BR,L,_,_}, Arms),
                            hex_dist(Q,R,BQ,BR) =< L + prune_part_max().

% bond-connected component containing atom X
component(X, Bonds) = fixcomp([X], Bonds).
fixcomp(Comp, Bonds) = Comp1 =>
    New = sort_remove_dups(
            [B : {A,B} in Bonds, membchk(A,Comp), not membchk(B,Comp)] ++
            [A : {A,B} in Bonds, membchk(B,Comp), not membchk(A,Comp)]),
    (New == [] -> Comp1 = Comp ; Comp1 = fixcomp(sort(Comp ++ New), Bonds)).

rotated({N,E,Q,R}, Comp, BQ, BR, Delta) = A1 =>
    (membchk(N, Comp) ->
        {Q1,R1} = rot_point(Delta, BQ, BR, Q, R),
        A1 = {N,E,Q1,R1}
    ;
        A1 = {N,E,Q,R}
    ).

% every atom on the board, not on an arm base, no two atoms on one hex
state_ok(Arms, Atoms) =>
    foreach ({_,_,Q,R} in Atoms)
        on_board(Q,R),
        foreach ({_,BQ,BR,_,_,_} in Arms) {Q,R} != {BQ,BR} end
    end,
    Cells = sort([{Q,R} : {_,_,Q,R} in Atoms]),
    Cells == sort_remove_dups(Cells).

% -- post-state rules: spawn, calcification, bonding --------------------------
mk_next(Arms, Atoms, Bonds, Ins, Calc, Bd, Outs, Pending, S1) =>
    spawn_all(Ins, Atoms, AtomsA, Ins1),
    AtomsB = apply_calc(sort(AtomsA), Calc),
    Bonds1 = apply_bonds(AtomsB, Bonds, Bd),
    S1 = {Arms, AtomsB, Bonds1, Ins1, Calc, Bd, Outs, Pending}.

spawn_all([], Atoms, AtomsOut, InsOut) => AtomsOut = Atoms, InsOut = [].
spawn_all([{I,Q,R,N}|T], Atoms0, AtomsOut, InsOut) =>
    (N < input_pool(I), cell_free(Atoms0, Q, R) ->
        N1 = N + 1,
        Atoms1 = [{{I,N1}, input_type(I), Q, R}|Atoms0]
    ;
        N1 = N, Atoms1 = Atoms0
    ),
    spawn_all(T, Atoms1, AtomsOut, InsT),
    InsOut = [{I,Q,R,N1}|InsT].

apply_calc(Atoms, Calc) = sort([calc1(A, Calc) : A in Atoms]).
calc1({N,E,Q,R}, Calc) = A1 =>
    (membchk({Q,R}, Calc), elemental(E) -> A1 = {N,salt,Q,R}
     ; A1 = {N,E,Q,R}).

apply_bonds(Atoms, Bonds, Bd) = Bonds1 =>
    New = findall(P, (member({{QA,RA},{QB,RB}}, Bd),
                      member({X,_,QA,RA}, Atoms),
                      member({Y,_,QB,RB}, Atoms),
                      X != Y, P = norm_pair(X,Y))),
    Bonds1 = sort_remove_dups(Bonds ++ New).

% -- actions ------------------------------------------------------------------
% setup phase: cost-1 placements, in the fixed pending_parts() order
action({Arms, Atoms, Bonds, Ins, Calc, Bd, Outs, [place_arm(I)|P]},
       S1, Action, Cost) ?=>
    arm_cand(I, BQ, BR, D, L),
    not membchk({BQ,BR}, part_feet(Arms, Ins, Calc, Bd, Outs)),
    {DQ,DR} = dvec(D),
    on_board(BQ + L*DQ, BR + L*DR),
    Arms1 = sort([{I,BQ,BR,L,D,none}|Arms]),
    mk_next(Arms1, Atoms, Bonds, Ins, Calc, Bd, Outs, P, S1),
    Action = {place_arm, I, BQ, BR, L, D},
    Cost = 1.

action({Arms, Atoms, Bonds, Ins, Calc, Bd, Outs, [place_input(I)|P]},
       S1, Action, Cost) ?=>
    input_cand(I, Q, R),
    not membchk({Q,R}, part_feet(Arms, Ins, Calc, Bd, Outs)),
    (prune_input_ring() == true -> on_ring(Arms, Q, R) ; true),
    IP = input_prev(I),
    (IP == none -> true ; member({IP,QP,RP,_}, Ins), {QP,RP} @< {Q,R}),
    Ins1 = sort([{I,Q,R,0}|Ins]),
    mk_next(Arms, Atoms, Bonds, Ins1, Calc, Bd, Outs, P, S1),
    Action = {place_input, I, Q, R},
    Cost = 1.

action({Arms, Atoms, Bonds, Ins, Calc, Bd, Outs, [place_bonder(I)|P]},
       S1, Action, Cost) ?=>
    bonder_cand(Q1, R1, Q2, R2),
    Feet = part_feet(Arms, Ins, Calc, Bd, Outs),
    not membchk({Q1,R1}, Feet),
    not membchk({Q2,R2}, Feet),
    (prune_bonder_ring() == true ->
        on_ring(Arms, Q1, R1), on_ring(Arms, Q2, R2)
    ; prune_part_max() >= 0 ->
        within_parts(Arms, Q1, R1), within_parts(Arms, Q2, R2)
    ; true),
    Bd1 = sort([{{Q1,R1},{Q2,R2}}|Bd]),
    mk_next(Arms, Atoms, Bonds, Ins, Calc, Bd1, Outs, P, S1),
    Action = {place_bonder, I, Q1, R1, Q2, R2},
    Cost = 1.

action({Arms, Atoms, Bonds, Ins, Calc, Bd, Outs, [place_calc(I)|P]},
       S1, Action, Cost) ?=>
    calc_cand(Q, R),
    not membchk({Q,R}, part_feet(Arms, Ins, Calc, Bd, Outs)),
    (prune_part_max() >= 0 -> within_parts(Arms, Q, R) ; true),
    Calc1 = sort([{Q,R}|Calc]),
    mk_next(Arms, Atoms, Bonds, Ins, Calc1, Bd, Outs, P, S1),
    Action = {place_calc, I, Q, R},
    Cost = 1.

action({Arms, Atoms, Bonds, Ins, Calc, Bd, Outs, [place_out(K)|P]},
       S1, Action, Cost) ?=>
    out_place(K, Q, R, Rot),
    Cells = out_cells(K, Q, R, Rot),
    Feet = part_feet(Arms, Ins, Calc, Bd, Outs),
    foreach ({CQ,CR,_,_} in Cells) not membchk({CQ,CR}, Feet) end,
    (prune_out_ring() == true ->
        member({RQ,RR,_,_}, Cells), on_ring(Arms, RQ, RR)
    ; true),
    (prune_part_max() >= 0 ->
        foreach ({WQ,WR,_,_} in Cells) within_parts(Arms, WQ, WR) end
    ; true),
    Outs1 = sort([{K,Q,R,Rot}|Outs]),
    mk_next(Arms, Atoms, Bonds, Ins, Calc, Bd, Outs1, P, S1),
    Action = {place_out, K, Q, R, Rot},
    Cost = 1.

% rotate: rigid rotation of the held component about the acting arm's base
action({Arms, Atoms, Bonds, Ins, Calc, Bd, Outs, []}, S1, Action, Cost) ?=>
    member({Act, Delta}, [{rot_cw,1}, {rot_ccw,5}]),
    select({M,BQ,BR,L,D,Held}, Arms, Rest),
    D1 = (D + Delta) mod 6,
    {DQ,DR} = dvec(D1),
    on_board(BQ + L*DQ, BR + L*DR),
    Arms1 = sort([{M,BQ,BR,L,D1,Held}|Rest]),
    (Held == none ->
        Atoms1 = Atoms
    ;
        Comp = component(Held, Bonds),
        foreach ({_,_,_,_,_,H2} in Rest) not membchk(H2, Comp) end,
        Atoms1 = sort([rotated(A, Comp, BQ, BR, Delta) : A in Atoms]),
        state_ok(Arms1, Atoms1)
    ),
    mk_next(Arms1, Atoms1, Bonds, Ins, Calc, Bd, Outs, [], S1),
    Action = {step, M, Act},
    Cost = 1.

% grab: hand empty, an atom (not held by another arm) under the gripper
action({Arms, Atoms, Bonds, Ins, Calc, Bd, Outs, []}, S1, Action, Cost) ?=>
    select({M,BQ,BR,L,D,none}, Arms, Rest),
    {DQ,DR} = dvec(D),
    member({X,_,BQ+L*DQ,BR+L*DR}, Atoms),
    foreach ({_,_,_,_,_,H2} in Rest) H2 != X end,
    Arms1 = sort([{M,BQ,BR,L,D,X}|Rest]),
    mk_next(Arms1, Atoms, Bonds, Ins, Calc, Bd, Outs, [], S1),
    Action = {step, M, grab},
    Cost = 1.

% drop
action({Arms, Atoms, Bonds, Ins, Calc, Bd, Outs, []}, S1, Action, Cost) =>
    select({M,BQ,BR,L,D,Held}, Arms, Rest),
    Held != none,
    Arms1 = sort([{M,BQ,BR,L,D,none}|Rest]),
    mk_next(Arms1, Atoms, Bonds, Ins, Calc, Bd, Outs, [], S1),
    Action = {step, M, drop},
    Cost = 1.
"""


# ---------------------------------------------------------------------------
# Run picat + parse
# ---------------------------------------------------------------------------
def run_picat(picat_bin, program, time_limit, keep_program):
    if keep_program:
        path = keep_program
        with open(path, "w") as f:
            f.write(program)
        tmpdir = None
    else:
        tmpdir = tempfile.mkdtemp(prefix="picat_adapter_")
        path = os.path.join(tmpdir, "instance.pi")
        with open(path, "w") as f:
            f.write(program)
    try:
        t0 = time.monotonic()
        proc = subprocess.run([picat_bin, path], capture_output=True,
                              text=True, timeout=time_limit)
        wall = time.monotonic() - t0
    except subprocess.TimeoutExpired:
        log(f"picat killed at the {time_limit}s time limit -- no plan "
            f"(best_plan does not stream incumbents)")
        sys.exit(1)
    except OSError as e:
        die(f"cannot run picat binary {picat_bin!r}: {e} "
            f"(install per picat/NOTES.md, set $PICAT or --picat)")
    finally:
        if tmpdir:
            try:
                os.remove(path)
                os.rmdir(tmpdir)
            except OSError:
                pass
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        die(f"picat exited with {proc.returncode}", 1)
    return proc.stdout, wall


def parse_solution(stdout, puzzle, maps):
    (arm_ids, reagent_ids, input_off, input_rot, calc_ids, bonder_ids,
     product_ids) = maps
    if "plan_found" not in stdout:
        return None
    placements, instructions = [], []
    t = 0
    cost = nplace = None
    for line in stdout.splitlines():
        toks = line.split()
        if not toks:
            continue
        if toks[0] == "PLACE":
            kind = toks[1]
            if kind == "arm":
                i, bq, br, l, d = map(int, toks[2:7])
                placements.append({"type": "arm", "id": arm_ids[i],
                                   "position": [bq, br], "rotation": d,
                                   "length": l})
            elif kind == "input":
                i, q, r = map(int, toks[2:5])
                off = rot_k(*input_off[i], input_rot[i])
                placements.append({"type": "input", "id": reagent_ids[i],
                                   "position": [q - off[0], r - off[1]],
                                   "rotation": input_rot[i]})
            elif kind == "calc":
                i, q, r = map(int, toks[2:5])
                placements.append({"type": "calcifier", "id": calc_ids[i],
                                   "position": [q, r]})
            elif kind == "bonder":
                i, q1, r1, q2, r2 = map(int, toks[2:7])
                d = DIRS.index((q2 - q1, r2 - r1))
                placements.append({"type": "bonder", "id": bonder_ids[i],
                                   "position": [q1, r1], "rotation": d})
            elif kind == "output":
                k, q, r, rot = map(int, toks[2:6])
                placements.append({"type": "output", "id": product_ids[k],
                                   "position": [q, r], "rotation": rot})
        elif toks[0] == "STEP":
            m, act = int(toks[1]), toks[2]
            instructions.append({"t": t, "arm": arm_ids[m], "action": act})
            t += 1
        elif toks[0] == "COST":
            cost = int(toks[1])
        elif toks[0] == "NPLACE":
            nplace = int(toks[1])
    order = {"arm": 0, "input": 1, "output": 2, "calcifier": 3, "bonder": 4}
    placements.sort(key=lambda p: (order[p["type"]], p["id"]))
    return {"puzzle": puzzle["name"],
            "solver": "picat (planner; free-layout setup-phase encoding)",
            "placements": placements,
            "instructions": instructions}, cost, nplace


def main():
    ap = argparse.ArgumentParser(
        description="Picat adapter for the Opus Magnum harness.")
    ap.add_argument("puzzle")
    ap.add_argument("--out", help="write the plan JSON here instead of stdout")
    ap.add_argument("--time-limit", type=float,
                    default=float(os.environ.get("HARNESS_PICAT_TIME_LIMIT",
                                                 300)))
    ap.add_argument("--picat", default=os.environ.get("PICAT", "picat"),
                    help="picat binary (default: $PICAT or `picat` on PATH)")
    ap.add_argument("--noprune", action="store_true",
                    help="disable the sound distance prunes (keeps the "
                         "exact rotational-symmetry quotient)")
    ap.add_argument("--keep-program",
                    help="also write the generated Picat program here")
    args = ap.parse_args()

    if shutil.which(args.picat) is None and not os.path.isfile(args.picat):
        die(f"picat binary {args.picat!r} not found -- install per "
            f"picat/NOTES.md (picat-lang.org), set $PICAT or --picat")
    try:
        with open(args.puzzle) as f:
            puzzle = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        die(str(e))
    for key in ("name", "board_radius", "t_max", "reagents", "products",
                "parts"):
        if key not in puzzle:
            die(f"puzzle: missing key {key!r}")

    program, maps = generate_program(puzzle, prune=not args.noprune)
    log(f"solving {puzzle['name']} (t_max={puzzle['t_max']}, "
        f"prune={'off' if args.noprune else 'on'}, "
        f"time limit {args.time_limit:g}s)")
    stdout, wall = run_picat(args.picat, program, args.time_limit,
                             args.keep_program)
    parsed = parse_solution(stdout, puzzle, maps)
    if parsed is None:
        log(f"no plan within the horizon (t_max={puzzle['t_max']}) -- "
            f"proven by iterative deepening in {wall:.2f}s")
        sys.exit(1)
    plan, cost, nplace = parsed
    n_instr = len(plan["instructions"])
    log(f"solved in {wall:.2f}s wall: cost {cost} = {nplace} placements + "
        f"{n_instr} instructions (instruction count PROVEN optimal within "
        f"the horizon by best_plan's iterative deepening)")
    text = json.dumps(plan, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
    else:
        print(text)
    sys.exit(0)


if __name__ == "__main__":
    main()
