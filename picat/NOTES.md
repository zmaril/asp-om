# Picat experiment notes

Parallel experiment to the clingo/ASP encoding in `asp/`: can Picat's
`planner` module solve the same Opus Magnum fragments — including the real
first campaign puzzle, Stabilized Water, and (phase 3) with the machine
layout itself as a decision variable?

## Setup

- Picat 3.9#10, Linux x86_64 binary from
  <https://picat-lang.org/download/picat39_10_linux64.tar.gz>
  (see <https://picat-lang.org/download.html> for the current version).
- No installation step: untar and run the `Picat/picat` binary.
- Run a program: `picat picat/case3_rigid.pi`
- Validate a solver run: `python3 picat/validate.py case3 picat/runs/case3.txt`
  (plain Python 3, no dependencies). `picat/runs/` holds the recorded
  solver outputs that the results table below refers to.

## World model

Phase 1 (`case1_transport.pi`, `case2_bond.pi`) mirrors `asp/core.lp`;
phase 2+ (`case3_rigid.pi`, `case2_free.pi`, `stabilized_water*.pi`)
mirrors `asp/core2.lp`:

- Axial hex grid `(Q,R)`, radius 2 (19 cells); clockwise direction
  indexing identical to the clingo `dir/3` facts.
- Arms with fixed base and length 1; actions `rot_cw`, `rot_ccw`,
  `grab`, `drop`, at most one action per timestep. No `wait`: clingo
  fills a fixed `t_max`-step tape and minimizes non-wait instructions;
  the planner returns an action sequence, so plan length == clingo's
  optimization cost. (With one arm, waiting also never changes the
  state, because spawn/calcify/bond effects apply immediately.)
- v2 engine adds, with the same semantics as `asp/core2.lp`:
  **rigid motion** (rotating an arm holding an atom swings the atom's
  whole bond-connected component about the arm base, cw
  `(Q,R) -> (BQ-(R-BR), BR+(Q-BQ)+(R-BR))`), multiple arms (state
  carries an arm list; all current instances use one), **glyph of
  calcification** (elemental atom on the glyph turns to salt), **glyph
  of bonding** (bond forms whenever both cells are occupied; bonds
  persist), and a **respawning reagent input** (a fresh reagent appears
  at the spawn hex as soon as it is vacated, bounded pool `nreagent`).
- State is a ground term
  `{Arms, Atoms, Bonds, NSpawned, CalcCells, BonderPairs, Pending}`
  with all lists kept sorted (canonical) so tabling detects revisits.
- `best_plan(S0, Limit, Plan, Cost)` gives length-optimal plans;
  `Limit` plays the role of clingo's `t_max`.

### Free machine layout (phase 3)

In `case2_free.pi` and `stabilized_water_free.pi` the machine layout is
part of the problem: the solver chooses the arm base hex + initial
orientation and the glyph positions. This is modeled as an initial
nondeterministic **setup phase**: the state carries a `Pending` list of
parts still to place, and cost-1 placement actions (`place_arm`,
`place_calc`, `place_bonder`) are the only ones available until it is
empty. Every solution places the same number of parts, so the offset is
constant and `best_plan` remains instruction-optimal. Placement
legality: everything on the board, gripper on the board, and (for
Stabilized Water, matching the game) part footprints pairwise disjoint,
including the puzzle's own input/output hexes.

## The Stabilized Water spec (and its source)

Extracted from the **real game puzzle file** shipped in omsim's test
corpus: <https://github.com/ianh/omsim>,
`test/puzzle/campaign/ch1-and-prologue/P007.puzzle` (embedded name
`STABILIZED WATER`), decoded with the format from omsim's `parse.c`:

- **Reagents:** two inputs, each a single **water** atom.
- **Product:** one molecule: **salt@(0,0) — water@(1,0)**, one normal bond.
- **Parts available:** arms (incl. multi-arms), piston, track, bonder,
  unbonder, multi-bonder, **glyph of calcification** (+ the usual
  instruction set).

Simplifications in our encoding vs the real game (all deliberate):

1. Discrete global timesteps, one arm, one action per timestep — no
   per-arm looping instruction tapes, no parallelism, no cycle-count
   metric.
2. One product molecule delivered instead of six; the output is two goal
   hexes the finished molecule must rest on (unheld), not a consuming
   output part.
3. Parts used: 1 arm (length 1), 1 bonder, 1 calcification glyph. No
   piston/track/unbonder/multi-bonder/multi-arm.
4. The two water reagents become one **respawning input site**
   (`asp/core2.lp` spawn semantics) with pool `nreagent = 2` (the product
   needs exactly 2 atoms; in-game reagents are unlimited).
5. Board radius 2 (19 hexes); the game board is effectively unbounded.
6. No `wait` (see above).

The puzzle is **not** shrunk beyond that: it still requires grabbing a
water, calcifying it to salt, fetching a second water (which only spawns
after the first vacates the input), bonding the two on the bonder glyph,
and delivering the 2-atom molecule to the output hexes by rigid rotation.

## Status / results

All cases solve and validate. Times are Picat-reported CPU seconds on
this container (wall times all < 8 s); "plan len" excludes the free-layout
placement actions (reported as `+N` placements).

| case | file | solved? | plan length | Picat CPU time | validated? | clingo optimum |
|------|------|---------|-------------|----------------|------------|----------------|
| 1: transport one atom | `case1_transport.pi` | yes | 5 | 0.000 s | PASS | 5 |
| 2: bond two atoms (fixed layout) | `case2_bond.pi` | yes | 12 | 0.001 s | PASS | 12 |
| 3: rigid 2-atom rotation (= `asp/rigid_instance.lp`) | `case3_rigid.pi` | yes | 4 | 0.001 s | PASS | 4 |
| 2-free: bond, layout decided, fixed-layout mode | `case2_free.pi fixed` | yes | 12 | 0.004 s | PASS | n/a |
| 2-free: bond, **layout decided by solver** | `case2_free.pi` | yes | 5 (+2 placements) | 0.164 s | PASS | n/a |
| Stabilized Water, fixed layout | `stabilized_water.pi` | yes | 13 | 0.008 s | PASS | n/a |
| Stabilized Water, **free layout** (sound pruning) | `stabilized_water_free.pi` | yes | 13 (+3 placements) | 2.29 s | PASS | n/a |
| Stabilized Water, free layout, **no pruning** | `stabilized_water_free.pi noprune` | yes | 13 (+3 placements) | 7.39 s | PASS | n/a |

Notes on individual rows:

- Case 3 reproduces the clingo optimum for `asp/core2.lp` +
  `asp/rigid_instance.lp` (4 instructions: grab, rot_cw ×2, drop).
  clingo itself is **not installed in this container**, so the "clingo
  optimum" column for cases 1–3 quotes the values recorded during the
  clingo phase of this project (see the instance-file comments in
  `asp/`); clingo runtimes were not (re)measured here. There is no
  clingo encoding at all for free layout or Stabilized Water — the Picat
  experiment is ahead of the clingo one there.
- **Fixed vs free layout** (the explicitly requested comparison):
  - bonding case: 0.004 s fixed vs 0.164 s free (~40× slower), and free
    layout finds a strictly better machine: it puts the bonder directly
    under the two reagent atoms (bond forms at t=0) and rigid-rotates
    the finished molecule onto the goal hexes — 5 instructions vs 12.
  - Stabilized Water: 0.008 s fixed vs 2.29 s free with sound
    reachability pruning of placements (~290×), 7.39 s with raw
    placement enumeration (~900×). The solver independently
    rediscovers a layout equivalent to the hand-designed one, and
    proves 13 instructions optimal over *all* legal layouts.
  - The free-layout searches stay tractable here because the placement
    choices (arm base+orientation, calc hex, bonder pair on 19 cells)
    multiply the root branching by ~10³–10⁵; `best_plan`'s
    tabling+iterative deepening absorbs that on this board, but the
    growth is multiplicative in board size and part count, so this is
    the axis where state explosion will bite first.
- Case 2-free differs from case 2 in one more way than free layout: it
  runs on the v2 engine, where rotating while holding a bonded atom is
  allowed (case 2 carried the phase-1 no-rigid-motion restriction).
  That is what makes the 5-instruction machine legal. The `fixed` mode
  row runs the same v2 engine with the case-2 layout, so the timing
  comparison is engine-to-engine.
- Stabilized Water fixed-layout plan (13): grab water, rot_cw onto the
  calc glyph (→ salt), rot_cw, drop on bonder cell A; rot back, grab the
  respawned water, rot_ccw ×3 onto bonder cell B (bond forms), rigid
  rot_cw ×2, drop on the output hexes.

## Validation

`picat/validate.py` is an independent re-implementation of the world
rules (it does not share code with, or trust state printed by, the Picat
programs beyond the plan itself). It simulates the printed plan forward
and checks: layout legality (on-board, part disjointness, base not on an
atom), one action per step, placements only in the setup phase,
grab/drop legality, rigid rotation (no tearing from other arms, no
collisions, atoms on board and off bases, held atom lands on the
gripper), bonds forming *only* on the bonder, calcification only on the
calc glyph, spawning only at the input when free and the pool remains,
and the goal in the final state. All 8 runs in `picat/runs/` PASS;
mutation tests (corrupting a rotation, dropping with an empty hand,
placing the bonder on the input hex) all FAIL as they should.

## Picat gotchas learned

- Pattern-matching rule heads (`=>`/`?=>`) never bind variables of the
  *call*: `action(S, S1, grab, 1) => ...` silently never matches when the
  planner calls it with unbound Action/Cost. Assign them in the body.
- Structured states must stay canonical (sort atom/bond lists) or tabling
  treats permutations as distinct states.
- All clauses of a predicate must be contiguous — you cannot group
  "placement actions" and "arm actions" in separate sections of the file
  with helpers in between.
- Disjunctions are not allowed inside list-comprehension conditions;
  wrap them in a helper predicate.
- There is no module-level code sharing convenient for this layout
  (each `.pi` here is self-contained, so the ~120-line engine is
  duplicated across the v2 files — fine for an experiment, a real
  project would make the engine an importable module).

## Honest assessment: does Picat work for this?

**Yes, for everything tried so far — and it is currently ahead of the
clingo encoding.** Strengths observed:

- The planner formulation is *much* closer to how one thinks about the
  game than the clingo tape encoding: a state term plus four action
  rules, no grounding over `atoms × hexes × timesteps`. Rigid rotation,
  which needs careful frame-axiom handling in ASP (`moved/2`,
  inertia exceptions), is three lines here: compute the component,
  map the rotation over it, re-sort.
- Optimal plans for the real first-campaign puzzle in milliseconds
  (fixed layout) to seconds (free layout), all independently validated.
- Free layout as "setup actions" was a natural, low-effort extension —
  the same trick would be painful to bolt onto the clingo tape encoding
  (every layout atom would multiply the ground program).

Where it will break down, based on what we can already measure:

- **Free layout is multiplicative**: ~40× (bonding) to ~900× (Stabilized
  Water, unpruned) over the fixed-layout solve on a 19-hex board with 3
  placeable parts. Bigger boards / more parts will need either the
  sound-reachability pruning style used here (which is puzzle-specific
  reasoning) or a move to the `sat`/`cp` modules where placements are
  plain decision variables — planned as the natural next step; not
  needed yet, so no timings for it.
- **State explosion**: the tabled state includes every atom position,
  bond, arm and (for free layout) the whole chosen layout. Later
  campaign puzzles with 4–6-atom products, several reagent sites, and
  6 products to deliver will grow the reachable state set sharply;
  iterative deepening also re-expands each layout's subtree at every
  depth bound.
- **Fidelity gap, not a solver gap**: instruction tapes/looping programs,
  cycle-count optimization, piston/track arms and multi-arm parallelism
  are not modeled at all; those are encoding work, and the tape/loop
  semantics in particular would not fit the planner's "plain action
  sequence" shape without redesign (they are closer to program synthesis
  than to planning).
