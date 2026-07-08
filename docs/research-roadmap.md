# Research roadmap: from the simplified solver model to full Opus Magnum

This document lays out a staged research program that takes the project
from today's deliberately simplified model (`harness/SPEC.md`,
`harness/validate.py`) to a **full model of Opus Magnum** — the game as
defined by its own files and by the community-exact simulator
[omsim](https://github.com/ianh/omsim) — with the self-play/ML program
(`docs/self-play-design.md`) scaling alongside every stage.

Ground truth for "what the real game does" throughout this document is
the omsim source tree (cloned and read for this roadmap; file/line
references are to omsim's current master, which matches the commit
`930c5dc` pinned by `docs/metrics-survey.md` in every place we checked).
Claims we could not confirm from a primary source are marked
**UNCERTAIN**.

**The one invariant that never changes across stages:** an *exact*
simulator/validator is the ground truth at every stage
(validator-in-the-loop). Every solver arm, every metric, every self-play
loop scores through it. When the modeled fragment grows, the validator
grows *first*, with differential tests against omsim; encodings and
learned components follow. This is the same discipline that already
made the five-arm bake-off comparable (`docs/solver-comparison.md` §5:
"The harness is what made any of this comparable") and that makes
reward hacking structurally hard in self-play
(`docs/self-play-design.md` §7).

Contents:

1. [Gap analysis: current model vs the full game](#1-gap-analysis)
2. [Staged roadmap](#2-staged-roadmap)
3. [Self-play program scaling](#3-self-play-program-scaling)
4. [Tooling and infrastructure](#4-tooling-and-infrastructure)
5. [Open questions, risks, success criteria](#5-open-questions-risks-and-success-criteria)

---

## 1. Gap analysis

Current model = `harness/SPEC.md` (canonical implementation
`harness/validate.py`; known simplifications listed in SPEC §6). Full
game = omsim semantics. Difficulty is a judgment call for *this*
project's stack (5 declarative solver arms + Python validator +
self-play loops); each estimate gets a one-line justification.

| Feature | Current (simplified) | Full game (omsim) | Difficulty to add |
|---|---|---|---|
| **Time model** | Global discrete timesteps `t = 0..t_max`; **at most one instruction per timestep across ALL arms** (SPEC §4) — arms are sequential | Per-arm instruction tapes executed **in parallel**, one slot per arm per cycle; each cycle runs two half-cycles — grab/drop execute in half-cycle 1, all motion in half-cycle 2 (`sim.c` `run()` and the `(board->half_cycle == 1) != (inst == 'f' \|\| inst == 'r')` gate in `perform_arm_instructions`, ~L1036); tapes have per-arm start cycles and halt indices (`sim.h` `struct solution`) | **High** — parallelism removes the sequential-interleaving symmetry every encoding currently exploits and multiplies the action space per step by the number of arms; the clingo arm already hits a cliff at 2 sequential arms (`docs/solver-comparison.md` §4) |
| **Tape looping** | None; a plan is a finite action list, `t_max` is a hard horizon | Non-halting tapes loop forever with period = longest tape (`decode.c`, tape-period computation; `index %= solution->tape_period` in `sim.c` `perform_arm_instructions`); `repeat` (`'C'`) and `reset` (`'X'`) instructions are expanded to primitives at decode time (`decode.c` ~L1136–1166) | **High** — turns bounded-horizon planning into periodic-schedule synthesis; the cycles/rate metrics are only meaningful with loops (`docs/metrics-survey.md` §4.3 items 2, 5) |
| **Instruction set** | `grab, drop, rot_cw, rot_ccw, wait` (SPEC §4) | Hotkeys `f r a d` plus **pivot** (`q`/`e` — rotate the held molecule about the gripper), **piston extend/retract** (`w`/`s`), **track ±** (`g`/`t`), blank, halt (`sim.c` `perform_arm_instructions` switch; hotkey list also in `docs/metrics-survey.md` §1.5) | **Medium** — each new instruction is a new motion generator in the validator and a new action in every encoding; pivot alone adds a second rotation center per arm |
| **Arms** | Single-gripper arms of fixed length ≥ 1; in practice instances use one length-1 arm | Arm lengths 1–3; **pistons** change length 1↔3 at runtime (`sim.c` caps extend at 3, retract at 1); **multi-gripper arms** (2/3/6-armed) grab in several directions at once (`angular_distance_between_grabbers`, per-direction `GRABBING_LOW_BIT` in `sim.h`/`sim.c`); **Van Berlo's wheel** (6 permanent wheel atoms, never grabs/drops — `ANY_WHEEL` checks in `perform_arm_instructions`); Ravari's wheel exists in omsim (`sim.h` `RAVARI`; **UNCERTAIN** whether it is vanilla or mod-only) | **Medium-High** — mechanically simple in a validator, but multi-gripper + piston length changes explode the per-arm state that tabled/declarative encodings carry (`picat/NOTES.md`: state size is its scaling wall) |
| **Track** | Not modeled | Track hexes with per-hex ± motion vectors, loops or dead ends, hash-table lookup (`sim.h` `track_positions/track_plus_motions/track_minus_motions`); cost 5/hex; trackless is a leaderboard flag | **Medium** — validator side is a table lookup; solver side adds a discrete position dimension per tracked arm |
| **Glyphs** | Bonder (2-hex) and calcifier (1-hex) only (SPEC §3) | Full set (`sim.c` `apply_glyphs`): bonding, **multi-bonding** (center + 3 neighbors), **unbonding**, **triplex bonding** (fire-only, three colored bond components), calcification, **duplication**, **animismus** (2 salt → vitae + mors, two-half-cycle conversion), **projection** (quicksilver + metal → next metal), **purification** (2 same metal → next metal), **dispersion** (quintessence → 4 elementals), **unification** (4 elementals → quintessence), **disposal**, **equilibrium** (no-op glyph), conduits; plus rejection/division/proliferation which omsim supports (**UNCERTAIN**: we believe these three are mod-only, not vanilla) | **High for encodings, Medium for the validator** — conversion glyphs create/destroy atoms (dynamic atom sets break the fixed-atom-universe assumption most arms encode); validator-side each glyph is ~20 lines of replay |
| **Elements** | `air, earth, fire, water, salt` (SPEC §3) | 16 atom types: + quicksilver, 6 metals (lead→gold), vitae, mors, quintessence, repetition placeholder (`sim.h` L17–32) | **Low-Medium** — mostly enum plumbing, but only meaningful together with the conversion glyphs |
| **Bonds** | Normal bonds only; **bonds never break** (SPEC §5.2) | Normal + 3 triplex colors; unbonder removes bonds; disjoint/floating bonds under atom overlap (`sim.h` bond bitfields, `DISJOINT_SAFE`) | **Medium** — unbonding invalidates the monotone-bond-set assumption; triplex is 3 extra bond relations |
| **Collision** | **Endpoint-only**: no two atoms per hex at state boundaries; swept arcs unchecked (SPEC §5.3) | Continuous collision during motion with **circular colliders** — atom radius 29 vs hex size 82 (`collision.c` L65–68), atom–atom, atom–arm-base, atoms-being-produced colliders, checked along swept rotation/track/piston paths (`collision.c`; sweep hexes also feed area via `record_swing_area`, `sim.c` ~L829–864) | **High** — continuous geometry inside a discrete solver is the single hardest gap; exact discretizations exist (precomputed swept-hex tables for legal/illegal move pairs) but must be *proven* conservative against omsim |
| **Board** | Bounded hex disc, radius 2–5 (SPEC §1) | Effectively unbounded plane (hash-grid `atom_grid`, `sim.h`); the leaderboard only rejects parts >16384 from origin (`docs/metrics-survey.md` §1.5) | **Medium** — SAT CNF already grows ~quadratically with radius and its UNSAT proofs die around radius 6 (`sat/NOTES.md` via `docs/solver-comparison.md` §4); unboundedness forces solver-chosen bounding boxes rather than fixed grids |
| **Inputs** | Bounded `pool` per reagent (SPEC §3: "approximates the game's unlimited inputs") | Infinite inputs; a new copy spawns whenever the input hexes are clear (`sim.c` `spawn_inputs`/`flag_blocked_inputs`) | **Low** — the harness spawn rule is already shape-correct; drop the pool cap once loops exist |
| **Outputs / goal** | **One product copy**, non-consuming output, exact molecule match (SPEC §5.4) | Consuming outputs; completion = every output has produced ≥ **6 × output_scale** products (`sim.c` `check_completion` ~L1828–1850); **repeating/infinite polymer outputs** (`sim.h` `REPEATING_OUTPUT`, 6 repetitions); variable outputs for computation puzzles (`sim.h` `VARIABLE_OUTPUT`) | **Medium-High** — consumption + 6× makes plans throughput-shaped; polymer outputs need chain-atom machinery (`sim.h` `struct chain_atom`) |
| **Metrics** | Non-wait instruction count + makespan; `harness/metrics.py` adds cost/area/composites with documented deviations, and stubs rate/looping/area@∞ | Official cost/cycles/area/instructions (`decode.c` price table ~L1298–1349, instruction counting ~L1351–1361; `sim.c` area accumulation) plus rate, area@∞ (3 growth classes), height/width/bounding-hexagon, all via steady-state detection (`steady-state.c`); full catalog in `docs/metrics-survey.md` | **Medium as measurement, High as solver objective** — measuring rate needs steady-state detection; *optimizing* rate is ratio optimization over periodic schedules, a different problem class |
| **Puzzle/solution I/O** | Hand-written JSON formats (SPEC §3–4) | Binary `.puzzle`/`.solution` formats (`parse.c`, `decode.c`); the repo already byte-decoded `P007.puzzle` via omsim's parser (`docs/solver-comparison.md` §1) | **Low** — omsim's parser exists and has been used here once already |
| **Production puzzles** | Not modeled | Cabinets with walls and isolation rules, conduits (with "spooky action at a distance" cloning that even omsim hasn't implemented — omsim `README` L16–21), cabinet/conduit violation flags (`decode.h`) | **High, defer** — rarest requirements, most simulator surgery (`docs/metrics-survey.md` §4.4 item 7 reaches the same verdict) |
| **Overlap exploits** | Forbidden by footprint disjointness (SPEC §4) | omsim models overlapped parts, atom stacking (`MAX_ATOMS_PER_HEX 6`, `OVERLAPS_ATOMS`), overlap counting for the O-flag | **Low priority** — an *exploit* category; model only when leaderboard-parity for O-categories matters |

## 2. Staged roadmap

Each stage adds one coherent capability slice. For every stage:
**adds** / **solver arms** (who survives, who falls off, citing the
measured walls in `docs/solver-comparison.md` §4) / **validation** /
**exit criterion**. Stages are ordered so that each one's validator work
is testable against omsim *before* any solver or ML work depends on it.

A standing rule from Stage 1 on: **every stage lands validator-first.**
The Python validator (or its successor, §4) implements the new
semantics; a differential test suite replays solutions through both our
validator and omsim and diffs verdict + metrics; only then do encodings
and self-play move onto the new fragment.

### Stage 0 — today's model (baseline, done)

- **Is:** sequential arms, {arm, bonder, calcifier}, 5 elements,
  endpoint collision, bounded board/pools, one product copy
  (`harness/SPEC.md` §6).
- **Solver arms:** all five solve the canonical instances; SAT, Picat
  and MiniZinc/CP-SAT prove the optima (12/11/3); clingo and Z3 find
  but don't prove (`docs/solver-comparison.md` §2.1).
- **Exit criterion (met):** every arm's plan passes
  `harness/validate.py`; two arms' plans exported to `.solution` files
  were accepted by omsim against the real `P007.puzzle`
  (`docs/solver-comparison.md` §1).

### Stage 1 — parallel per-arm tapes + looping (the time-model rewrite)

- **Adds:** per-arm instruction tapes executed in parallel; the
  half-cycle order (grab/drop before motion, per `sim.c`); tape looping
  with period = longest tape; `repeat`/`reset` accepted as decode-time
  sugar exactly like `decode.c`; run-until-N-outputs instead of a hard
  `t_max` (initially N=1 to stay comparable). This unlocks the **true
  cycles metric** — today's `makespan` is deliberately not called
  cycles (`harness/metrics.py`, `docs/metrics-survey.md` §4.3 item 2).
- **Solver arms:** this is the stage where the field thins.
  - **clingo**: already ~130 s to a *first* model at 2 sequential
    arms / 36 steps with the optimality proof out of reach at 10 min
    (`docs/solver-comparison.md` §4); parallel tapes make the per-step
    action space the product over arms. Expect needle-finder role only,
    and only with aggressive symmetry breaking.
  - **SAT**: the current encoder is single-arm by construction
    (`docs/solver-comparison.md` §4, "Multi-arm was never attempted");
    needs a re-encode (one action variable block per arm per cycle).
    Best bet for optimality proofs to survive, given it already proves
    10–14× faster than clingo on UNSAT certificates.
  - **Picat**: tabled state must carry every arm's tape position; its
    wall is exactly state-set size (`picat/NOTES.md` via
    `docs/solver-comparison.md` §4), so expect it to hold at 2 arms,
    small boards, and degrade beyond.
  - **MiniZinc**: only multi-core CP-SAT survived horizon growth in
    the bake-off ("the only engine that keeps proving optimality as
    the horizon grows"); keep CP-SAT, drop the rest from the bench.
  - **Z3**: fixed-layout proofs already die at t_max ≈ 20
    (`z3/NOTES.md` frontier); likely the first arm to become
    find-only. Keep as a semantics cross-check, not a competitor.
- **New validation:** differential tester: export plan → `.solution`
  (the SAT arm already has this path), run omsim, assert same
  accept/reject and same cycles/cost/instructions. Negative tests for
  half-cycle ordering (a grab and a rotate interacting in the same
  cycle) and loop boundary conditions.
- **Exit criterion:** for a corpus of ≥100 solutions (own + generated),
  our validator's verdict and its cycles/instructions/cost numbers
  match omsim exactly; at least two solver arms solve a 2-arm looping
  instance end-to-end; the leaderboard's `makespan` column is replaced
  by a true `cycles` column.

### Stage 2 — full arm mechanics: pistons, track, pivot, multi-grippers

- **Adds:** pivot (`q`/`e`), piston extend/retract with the 1–3 length
  clamp, track parts with ± motion and the track-move instructions,
  arm lengths 1–3, 2/3/6-gripper arms, Van Berlo's wheel (validator
  side; whether any solver *searches* over Van Berlo is a later
  question). Cost table entries activate (arm 20, piston 40, track
  5/hex, ... — `decode.c` price table), so **cost becomes a real
  optimization axis** for the first time (`selfplay/leaderboard/README.md`
  notes cost currently cannot differ between plans).
- **Solver arms:** validator-side this is mechanical; solver-side each
  new instruction multiplies branching. Expect: SAT and CP-SAT remain
  usable on short-horizon instances; Picat's state grows again (track
  position + piston length per arm); clingo grounding grows but its
  precomputed-rotation-image trick (`docs/solver-comparison.md` §4)
  generalizes to precomputed piston/track images. Plan for the
  declarative arms to be *fragment specialists* from here on: each
  bench run declares which feature subset an arm supports, and the
  bench table says so explicitly.
- **New validation:** omsim differential tests targeting each
  mechanic (a pivot-only solution, a track loop, a piston reach);
  area numbers now include swing/sweep hexes for length-2/3 arms
  (`sim.c` `record_swing_area`), closing the documented area gap in
  `harness/metrics.py`.
- **Exit criterion:** our validator replays, verdict- and
  metric-identically vs omsim, a hand-built suite that uses every
  instruction letter and every arm type; at least one solver arm
  solves an instance that *requires* a piston or track to be solvable.

### Stage 3 — full glyph set + all 16 elements + real bonds

- **Adds:** unbonding, multi-bonding, triplex bonding, duplication,
  animismus, projection, purification, dispersion, unification,
  disposal, equilibrium, all elements/metals, Van Berlo interaction
  with duplication (semantics from `sim.c` `apply_glyphs`, including
  the two-half-cycle conversion pattern for animismus/purification/
  dispersion/unification). Defer conduits and the
  (**UNCERTAIN**-vanilla) rejection/division/proliferation glyphs.
- **Solver arms:** conversion glyphs break the fixed-atom-universe
  assumption (atoms are created/destroyed mid-run). SAT/CP-SAT can
  model a bounded atom pool with liveness bits; clingo handles dynamic
  objects poorly at grounding time (expect grounding blowup — same
  failure shape as its 2-arm grounding wall before the rotation-image
  fix); Picat's planner state remains viable since it's simulation-
  based. Realistically this stage is where **search shifts from
  declarative-first to proposer/MCTS-first with declarative arms as
  sub-solvers** on subproblems (e.g., tape synthesis for a fixed
  layout), which is exactly the Loop-1 fallback design
  (`docs/self-play-design.md` §3).
- **New validation:** per-glyph unit tests mirroring `apply_glyphs`
  case-by-case; omsim differential runs on campaign puzzles from
  chapters 2–3 (metal/purification chains) using omsim's own
  `test/` solution corpus **as validation inputs only** (they are
  external solutions: never training data — §3 below).
- **Exit criterion:** validator handles every vanilla glyph with
  omsim-identical results on the differential suite; the harness
  puzzle JSON schema covers every vanilla campaign puzzle *except*
  production/polymer ones, verified by round-tripping decoded
  `.puzzle` files.

### Stage 4 — full collision + unbounded board

- **Adds:** omsim's continuous collision model — circular colliders
  (radius 29 on an 82-unit hex, `collision.c`), swept checks during
  rotation/pivot/piston/track motion, produced-atom and arm-base
  colliders — and removal of the bounded-disc board in the validator
  (solvers still pick their own bounding box).
- **Approach:** do **not** reimplement continuous collision in Python
  or in encodings. Two-track plan: (a) the canonical validator
  delegates collision (and ideally the whole replay) to omsim via
  bindings (§4); (b) for solvers, precompute a **conservative
  discrete approximation**: a table of (arm length, rotation,
  neighboring-occupancy) → legal/illegal, proven sound by exhaustive
  comparison against omsim on the finite local configuration space.
  Solvers search in the conservative fragment; anything they emit is
  exactly checked anyway (invariant). The gap between conservative
  and exact is measured, not guessed.
- **Solver arms:** encodings keep endpoint semantics *plus* the
  conservative sweep tables — this is the "precomputed swept-arc
  tables" item already anticipated in `docs/metrics-survey.md` §4.3.
  Cost: more clauses/rules per rotation, same asymptotics. Board
  unboundedness hurts SAT most (CNF ~quadratic in radius, proof death
  extrapolated near radius 6 — `docs/solver-comparison.md` §4);
  mitigation is solver-chosen tight bounding boxes with an outer
  omsim check.
- **New validation:** fuzzing — random machines run in both simulators,
  diff collision verdicts and locations; omsim's `llvm-fuzz.c` shows
  the shape.
- **Exit criterion:** **zero false accepts**: on a fuzz corpus of ≥10⁵
  random machines, every plan our stack calls legal is legal per
  omsim (false *rejects* from the conservative tables are allowed but
  measured and reported).

### Stage 5 — throughput: 6× consuming outputs, infinite inputs, asymptotic metrics

- **Adds:** consuming outputs with completion at 6 × output_scale
  (`sim.c` `check_completion`), unbounded input pools, steady-state
  detection (state-repeat at tape-period-aligned cycles, omsim
  `steady-state.c`), and with it the real **cycles**, **rate**,
  **looping** flag, and bounded-case **area@∞** — un-stubbing the
  three `None` metrics in `harness/metrics.py`. Defer chain-atom
  polymer machinery (linear/quadratic area growth, A′/A″) unless a
  concrete need appears (`docs/metrics-survey.md` §4.4 item 7).
- **Solver arms:** optimizing cycles-to-6th-product or rate is
  periodic-schedule optimization; none of the five arms was built for
  it. Tractable declarative queries that remain: "does a period-p tape
  achieve k outputs per period?" for fixed small p (bounded model
  checking over one period + wraparound constraints — SAT-shaped).
  Everything else is search + exact measurement: propose (net/MCTS),
  measure rate exactly via the simulator. This stage is where the
  self-play program stops being a consumer of the solver arms and
  becomes the primary optimizer (§3).
- **New validation:** rate/area@∞ numbers cross-checked against
  omsim's verifier metrics (`per repetition cycles/outputs`, with the
  leaderboard's `ceil(100·x)/100` rate rounding per
  `docs/metrics-survey.md` §1.2).
- **Exit criterion:** for looping solutions in the corpus, our
  reported cycles, rate, and looping flag match omsim's verifier
  outputs exactly; the self-leaderboard grows @V and @∞ columns whose
  numbers are leaderboard-comparable (same definitions, same
  rounding).

### Stage 6 — full campaign compatibility

- **Adds:** whatever remains for "any vanilla puzzle, any legal
  solution": polymer/repeating outputs (6 repetitions,
  `sim.h` `REPEATING_OUTPUT_REPETITIONS`), production puzzles with
  cabinets and conduits, computation-puzzle variable outputs, native
  `.puzzle`/`.solution` round-trip as first-class harness I/O, and the
  leaderboard legality floor (duplicate-part limits, track-gap checks,
  coordinate bounds — `docs/metrics-survey.md` §2.6).
- **Solver arms:** at this point the declarative arms are specialist
  sub-solvers invoked by the search/ML stack on the fragments they
  handle; the bench keeps scoring them honestly on those fragments.
- **New validation:** run the full omsim `test/` puzzle corpus through
  the harness I/O layer; every decoded puzzle re-encodes
  byte-compatibly (or with documented canonicalization).
- **Exit criterion:** see the success criteria in §5 — this stage *is*
  "a full model".

**Sequencing rationale.** Tapes/looping come first because every
metric that matters (cycles, rate) and every later mechanic is defined
in tape-time — building pistons on sequential time would be rework.
Collision comes after glyphs/arms because its omsim-delegation strategy
(§4) wants the bindings that Stages 1–3's differential testing already
builds, and because until arms are length-2+ the collision gap is
provably zero for rotations of length-1 arms carrying single atoms
(sweep hexes only appear at length ≥ 2, `sim.c` `record_swing_area` —
multi-atom molecules can sweep even at length 1, so Stage 1–2 fuzzing
must confirm where the endpoint model is actually exact,
**UNCERTAIN** until measured). Throughput lands after collision so that
rate records are real-game-legal from day one.

## 3. Self-play program scaling

The three loops of `docs/self-play-design.md` evolve per stage. The
standing **data invariant restated**: *external puzzles are allowed;
external solutions are* ***never*** *training data* — they are
read-only comparison rows only, enforced structurally by the incumbent
store's schema (`docs/self-play-design.md` §5,
`selfplay/leaderboard/README.md`). omsim's `test/` solution corpus and
community records used for differential *validation* in Stages 1–6 fall
under exactly this rule: they may check our simulator, they may never
teach our proposer.

**Loop 2 — forward-generation curriculum** (`selfplay/generator/`):
scales most naturally, because it only needs the *executor*. At every
stage, the generator gains the new mechanics as sampling knobs
(pistons/track at Stage 2, glyph subsets at Stage 3, tape period and
loop structure at Stages 1/5) and keeps its guarantee: whatever a
random legal machine produces is a solvable puzzle with a
self-generated reference solution. The feature grid for
distribution-collapse control (`docs/self-play-design.md` §4) grows
axes in lockstep (arm types used, glyph set, tape period, rate class).
Each stage's generator batch also doubles as the fuzz corpus for that
stage's differential validation — one artifact, two uses.

**Loop 3 — self-competition leaderboard** (`selfplay/leaderboard/`):
grows a column per newly-real metric, following
`docs/metrics-survey.md` §4.4's order: true cycles (Stage 1), real
cost variety + trackless flag (Stage 2), rate/looping/area@∞
(Stage 5), @∞ geometry (Stage 6, if polymers land). Old incumbents are
rescored by replay whenever the validator's semantics version bumps —
cheap, and it converts every semantics fix into a leaderboard-wide
audit. External comparison columns become genuinely comparable to
zlbb.faendir.com numbers from Stage 5 on (same definitions, same
rounding), which raises the display-only stakes: the schema-level
no-read-path rule stays mandatory.

**Loop 1 — expert iteration** (`selfplay/expert_iteration/`): the
teacher composition shifts with the solver-arm attrition documented per
stage above. Stages 0–2: declarative teachers (clingo for finding, SAT
for proving) behind the existing `teacher.py` interface. Stage 3+: the
improver hierarchy inverts — proposer/MCTS drafts full machines,
declarative arms are called on *decompositions* (fixed-layout tape
synthesis, single-arm subroutines, period-p feasibility) where they
still prove things. Stage 5+: reward comes from throughput metrics
measured by the (by then omsim-backed) validator; expert iteration's
"expert" is increasingly "search + exact measurement" rather than
"complete solver", which is the AlphaDev configuration the design doc
already anticipated (`docs/self-play-design.md` §1, §7 "solver
competence ceiling"). Model-gap reward hacking shrinks at each stage
by construction — the fragment converges to the game — but the
transition windows (validator ahead of encodings) are exactly when
incumbents must be re-verified against omsim before being trusted as
training targets.

## 4. Tooling and infrastructure

**A native/fast simulator is the critical path.** Today's
`harness/validate.py` is pure Python and validates a plan in
milliseconds at radius 2 — fine for 5 solver arms, not for self-play at
scale (millions of forward-generation rollouts and MCTS node
expansions; `docs/self-play-design.md` §6 already demands "one
execution core" shared by generator/MCTS/validator). Options, not
mutually exclusive:

1. **Adopt omsim as the reference validator** via its bot-facing
   shared-library API: `make libverify.so`, documented in omsim's
   `verifier.h` ("an API designed for bots to use", per omsim
   `README`). Write thin Python bindings (ctypes/cffi). From Stage 1
   this powers the differential suite; from Stage 4 it *is* the
   canonical collision/replay authority. Requires the JSON↔`.puzzle`/
   `.solution` converters (partially existing: the SAT arm's `.solution`
   exporter, omsim's parser already used for P007).
2. **Keep a readable Python model** of whatever fragment the solvers
   encode (the SPEC's role today: executable documentation +
   negative-test host, `harness/tests/test_validate.py`). It defines
   the *solver fragment*; omsim defines the *game*. The SPEC's
   "validator wins" rule gets a second clause: where the Python model
   and omsim disagree on shared semantics, omsim wins and the Python
   model has a bug.
3. **A native step-function core** (Rust/C with Python bindings) only
   if profiling shows the omsim bindings can't serve MCTS's
   incremental state needs (omsim's API is solution-replay-shaped, not
   single-step-shaped — **UNCERTAIN** how much surgery incremental use
   needs until tried).

**Known omsim caveats** (even ground truth has bugs): conduit "spooky
action at a distance" cloning unimplemented; track-reset differs from
the game in some overlapping-track cases (omsim `README` L16–21). Both
sit in deferred-stage features; document them as accepted deviations.

**Metric computation:** `harness/metrics.py` stays the single metric
module (it already computes from the canonical replay via a state
observer, never re-implementing semantics —
`selfplay/leaderboard/README.md`), growing per
`docs/metrics-survey.md` §4.4 and cross-checked against omsim's
verifier metrics in the differential suite from Stage 1 on.

**Compute:** the dominant cost is solver CPU, not GPU
(`docs/self-play-design.md` §7: ~130 s per hard clingo call burns
core-years under naive expert iteration; mitigations listed there —
feasibility-at-fixed-T, warm starts, caching — remain the plan).
Budget shape per stage: Stages 1–3 are bench-scale (a few dedicated
multicore boxes; CP-SAT wants ≥4 cores — its `-p4` vs `-p1` gap was
decisive, `docs/solver-comparison.md` §3); Stage 4's fuzzing and
Stage 5's self-play want a small cluster of cheap CPU nodes driving
the native simulator, plus one GPU node for the proposer (the model
stays small; the state space is tiny relative to modern ML).

**Bench discipline:** `harness/bench.py` gains a *fragment manifest*
per adapter (which stages/features an arm supports) so cross-arm
tables stay honest as arms specialize; every result row records the
validator semantics version.

## 5. Open research questions, risks, and success criteria

### Open questions

1. **Periodic-schedule synthesis.** Is there a declarative encoding of
   "period-p tape achieving k outputs/period" that stays tractable for
   p ≤ ~40, 2–4 arms? (Bounded model checking over one period with
   wraparound state constraints — SAT-shaped, unproven here.) If yes,
   rate optimization keeps an exact improver; if no, Stage 5 is
   search-only.
2. **Conservative collision tables.** How large is the legal-move gap
   between endpoint semantics + conservative sweep tables and omsim's
   continuous model, measured on real machines? (Determines whether
   solver arms lose competitive machines at Stage 4.)
3. **Where exactly is the endpoint model exact?** Claimed zero-gap for
   length-1 single-atom rotations; multi-atom molecules at length 1
   are **UNCERTAIN** — settle by Stage 1–2 fuzzing before trusting any
   "no-collision-gap" shortcut.
4. **Does net-guided warm-starting move the multi-arm cliff?** Flagged
   in `docs/self-play-design.md` §7; becomes urgent at Stage 1 when
   the 2-arm wall is on the critical path.
5. **Decomposition interfaces.** What is the right
   layout-vs-tape / arm-vs-arm decomposition so declarative arms stay
   useful past Stage 3? (The Picat fixed-layout result — 0.05 s vs
   62.6 s free-layout, `docs/solver-comparison.md` §4 — says
   decomposition is worth orders of magnitude.)
6. **Vanilla-vs-mod boundary.** Confirm which omsim parts are vanilla
   (rejection/division/proliferation glyphs, Ravari's wheel —
   **UNCERTAIN** above); the full-model target is *vanilla* OM, with
   modded parts optional.

### Risks

- **The time-model rewrite (Stage 1) invalidates all five encodings at
  once.** Mitigation: validator + differential suite first; keep the
  Stage-0 bench running until ≥2 arms are ported, so there is never a
  window with zero exact solvers.
- **Declarative attrition outpaces ML readiness.** If Stages 3–5 arrive
  before the proposer/MCTS stack produces signal, the project has a
  full validator and no strong optimizer. Mitigation: the self-play
  build order (`docs/self-play-design.md` §8) front-loads
  forward-generation and proposer-v0, which only need the executor.
- **Simulator divergence.** Two implementations (Python fragment model,
  omsim) invite silent drift. Mitigation: the differential suite is a
  merge gate from Stage 1; semantics versioning + incumbent rescoring
  make drift detectable after the fact.
- **Scope creep into omsim reimplementation.** The point is to *use*
  omsim as ground truth, not to rewrite it. The Python model only ever
  implements the solver fragment.
- **omsim's own gaps** (conduits, track reset) put a ceiling on
  "exactness" for Stage 6 features; accepted and documented.

### Success criteria for "a full model" (concrete, testable)

1. **Campaign verification:** solutions produced by this project's
   stack, exported to native `.solution` files, are accepted by omsim
   against the game's own `.puzzle` files for every non-production
   vanilla campaign puzzle attempted, and for at least one production
   and one polymer puzzle (Stage 6).
2. **Full mechanics:** the stack searches over and validates multi-arm
   solutions with looping tapes using every vanilla instruction
   (grab/drop, rotate, pivot, extend/retract, track ±, repeat/reset),
   arm lengths 1–3, multi-gripper arms, Van Berlo's wheel, and every
   vanilla glyph.
3. **Metric parity:** for every solution in the differential corpus,
   our computed cost/cycles/area/instructions equal omsim's, and
   rate/area@∞/height/width/bounding-hexagon match omsim's verifier
   outputs (with the leaderboard's documented rounding).
4. **Collision exactness:** zero false accepts vs omsim on the
   standing fuzz corpus (§2 Stage 4), continuously enforced in CI.
5. **Self-play at full semantics:** all three loops run against the
   full model — generated curricula exercise the full part set, the
   self-leaderboard's @V and @∞ columns are populated by self-generated
   verified records, and the data invariant (external solutions
   read-only) has held at every stage, auditable from incumbent
   lineage.
