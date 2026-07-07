# Z3 arm — final report

Z3 (Python API, z3-solver 4.16.0) bounded-model-checking arm of the
multi-solver Opus Magnum comparison. Mirrors the clingo arm
(`asp/core.lp`, `asp/core2.lp` + the three instances) exactly, adds a
Stabilized Water (omsim P007) instance, an independent plan validator,
and ground-truth verification against omsim. All timings measured on
this box; the clingo numbers were measured the same day with the same
`run.py` harness (clingo 5.8.0).

**TL;DR — does Z3 work for solving Opus Magnum problems?** Yes: it
solves every instance to a *proven* optimum, its free-layout mode
co-designs machine layout and program (finding the classic
glyphs-under-the-inputs trick for Stabilized Water, cost 3 vs 10 for
the hand layout), and its plans replay cleanly in an independent
simulator and — for Stabilized Water — in omsim itself against the real
puzzle file. But clingo solves the same models 1–2 orders of magnitude
faster at every size we tried, and Z3's gap widens with scale. For this
problem family (finite hex board, pure combinatorics, no arithmetic
theories), a grounder + CDCL ASP system is simply the right tool; Z3
only becomes competitive when the model is written like a grounder
would write it (the boolean one-hot encoding) — at which point you have
re-implemented half of clingo's front end by hand.

## Files

- `om_solver.py` — primary **Int encoding** (coordinates/orientation/
  action as Z3 Ints, held/bond flags as Bools). Implements both clingo
  semantics: **v1** (`core.lp`: one arm, exactly one instruction per
  step, held atom rides the gripper) and **v2** (`core2.lp`: serialized
  multi-arm, rigid rotation of the held bond-component, base blocking,
  calcification, element types). Both **fixed** and **free** layout.
- `om_bool.py` — **pure-boolean one-hot encoding** (single-arm, fixed
  layout, v1 + v2). Hex geometry is ground at encode time (rotation
  about the fixed base = a precomputed hex permutation), so the solver
  sees near-pure SAT.
- `bench.py` — timing matrix → `results.md` (+ `results.json` cache),
  optimal-plan dumps → `solutions/*.json`.
- `frontier.py` — Stabilized Water radius/horizon scaling study →
  `results-frontier.md`.
- `validate.py` — independent plan replayer (no Z3; see Validation).
- `emit_omsim.py` — emits a real `.solution` v7 file from the Stabilized
  Water plan; `solutions/water-z3.solution` is the omsim-verified result.
- `stabilized_water.lp` — the identical instance for clingo
  (`asp/core2.lp`), used for the apples-to-apples reference timing.

## Encoding design summary

Bounded model checking over states `t = 0..T`, steps `0..T-1`, exactly
the clingo world model: axial hex board `|q|,|r|,|q+r| <= radius`
(default 2), clockwise dir table 0..5, one serialized action per step,
bonds form whenever both bonder hexes are occupied (at every state,
even while held) and persist, calcification turns an elemental atom on
the glyph to salt at the next state, arm bases block hexes (v2). Cost =
number of non-wait steps over the whole horizon, identical to clingo's
`#minimize`.

Two encodings:

- **Int**: `q/r/orient/act` are Ints, transitions are `x[t+1] == If(...)`
  equalities, invariants asserted per state. Cheap to build (~0.1 s)
  but every coordinate comparison is a linear-arithmetic theory atom.
- **Bool one-hot**: `at[atom][hex][t]`, `orient[d][t]`, `act[a][t]`
  Bools with pairwise exactly-one; geometry (gripper hexes, rigid-
  rotation permutations, glyph hexes) precomputed in Python. Build time
  ~0.6–0.7 s but the solve is nearly pure SAT.

Layout modes: **fixed** pins base/orientation/glyph hexes to the
instance values (what the clingo instances do — the comparable
numbers); **free** (Int encoding only) lets the solver choose arm base,
initial orientation, and glyph hexes, with reagent spawn hexes and
product hexes fixed (they define the puzzle). Glyphs may overlap spawn
and product hexes — just like the real game.

Optimality strategies: `optimize` (z3.Optimize), `ramp-cost`
(cost ≤ k for k = 0,1,…), `descend-cost` (SAT then tighten until UNSAT;
one hard UNSAT proof), `oneshot` (SAT at T, no optimality),
`ramp-horizon` (goal-at-h assumption literals over one unrolled
encoding, h = 1..T; truly incremental, no cost-optimality guarantee).

## Results (full matrices in `results.md` and `results-frontier.md`)

All four instances solve to proven optima; the three shared tests match
clingo (trivial = 5, bond = 12, rigid = 4) and Stabilized Water's
fixed-layout optimum 10 is cross-checked by running clingo on the
identical instance (`z3/stabilized_water.lp` + `asp/core2.lp`: cost 10,
0.060 s).

Seconds to a PROVEN optimum, fixed layout (Z3 numbers are the best
strategy, descend-cost; medians of 5 where < 2 s):

| instance | clingo | Z3 bool (solve) | Z3 int (solve) | best-Z3 / clingo |
|---|---|---|---|---|
| trivial (v1) | 0.009 | 0.075 | 0.52 | 8× slower |
| bond (v1) | 0.148 | 0.57 | 6.3 | 4× slower |
| rigid (v2) | 0.004 | — (int only) | 0.29 | 72× slower |
| water (v2) | 0.060 | 0.17 | 2.3 | 3× slower |

(Bool adds ~0.6–0.7 s Python build time on top of solve; clingo's
numbers include grounding. Counting build+solve, bool-Z3 is within
4–15× of clingo on these sizes, and the gap grows with scale — see the
frontier.)

### Stabilized Water (omsim P007)

Modelling choices (no clingo instance existed, so this arm defined the
instance and mirrored it into `stabilized_water.lp`):

- Real puzzle (decoded from `P007.puzzle`): two 1-atom WATER reagent
  inputs; product = SALT(0,0) bonded to WATER(1,0); parts available
  include arms, glyph of calcification, glyph of bonding.
- Simplified-semantics instance (v2/core2): board radius 2, horizon 12,
  one arm (base (0,0), length 1, orient 0), water atoms at (1,0) and
  (1,-1), calcifier at (-1,1), bonder on ((-1,0),(0,-1)) = the product
  hexes. Product goal: *anonymous slots* — some unheld salt atom on
  (-1,0) bonded to some unheld water atom on (0,-1) (an OM product is a
  molecule pattern, not named atoms; the goal is a disjunction over
  atom-to-slot assignments).
- Reagent pools: core2's `spawn/nreagent` respawn machinery with a
  1-atom pool per spawn hex degenerates to a pre-placed atom (`r(1)` at
  t=0; no respawn can trigger since each input is consumed exactly once
  at output_scale 1), so the two inputs are two `init_at` water atoms.
  No respawn encoding was needed.

Results (solve seconds, proven optimum unless noted):

| variant | cost | bool descend | int descend | int optimize | int ramp-cost | int ramp-horizon* |
|---|---|---|---|---|---|---|
| fixed layout | **10** | 0.17 | 2.3 | 7.8 | 7.7 | 0.38 (cost 10 @ h=10) |
| free layout | **3** | n/a | 4.4 | 2.5 | 0.56 | 0.11 (cost 3 @ h=3) |

\* heuristic, no optimality proof. clingo, fixed layout, same instance:
**0.060 s**.

- **Fixed layout, optimum 10**: grab water₁, three cw rotations carrying
  it across the calcifier (calcified in passing) onto the salt slot,
  drop; two rotations back, grab water₂, one ccw rotation onto the
  water slot, drop — the bond forms on the bonder under the product
  hexes.
- **Free layout, optimum 3**: the solver placed the bonder under the two
  reagent hexes and the calcifier under one of them — bond and
  calcification happen at t=0, then grab + one rigid rotation + drop
  delivers the finished molecule. This is the classic OM
  speedrun trick, discovered by the solver, and the one place in this
  study where Z3 produced something qualitatively better than the hand
  design. (On the three original tests free layout never beat fixed —
  their geometry pins the layout — and cost 2–4× solve time.)
- Strategy nuance: with a LOW optimum (3), `ramp-cost` (0.56 s) beats
  `descend-cost` (4.4 s) — ramping up meets the optimum after 4 cheap
  checks, while descending must first find some plan unguided. With a
  HIGH optimum (10 of 12 steps), descend-cost wins (2.3 s vs 7.7 s).

### Tractability frontier (`results-frontier.md`)

Stabilized Water, descend-cost to proven optimum, 120 s budget per
configuration. Headlines (full table in `results-frontier.md`):

- **bool/fixed, radius 2**: proven optimum at t_max = 12 (0.16 s) and
  16 (4.4 s); at t_max = 20, 24, 30 the budget dies in the optimality
  proof — the cost-10 plan is still found, but cost ≤ 9 cannot be
  refuted in 120 s (`timeout(10)`).
- **bool/fixed, radius 3** (37 hexes): 0.20 s at t_max = 12, 4.1 s at
  16, and 105.7 s at 20 — curiously *proving* r3/T20 while r2/T20 timed
  out; the UNSAT search is high-variance near the cliff.
- **int/fixed, radius 2**: 2.6 s at t_max = 12, 118.2 s at 16 (barely),
  `timeout(10)` at 20. The Int encoding hits the wall one horizon step
  before bool.
- **int/free**: everywhere *easier* than fixed — proven cost 3 at
  radius 2 for t_max 12/16/20 (2.7 / 20.4 / 63.8 s) and at radius 3 for
  t_max 12/16 (6.3 / 19.8 s). The free-layout optimum is so low that
  the final UNSAT proof (cost ≤ 2 impossible) is shallow, while the
  fixed layout must refute cost ≤ 9 across the whole horizon.

So the practical frontier at a 120 s budget is the **optimality-proof
(UNSAT) side, not plan finding**: fixed-layout proofs die at
t_max ≈ 20 for both encodings (bool lasts a bit longer and even closed
radius 3 at 105.7 s), while plans themselves keep arriving in seconds
well past that. clingo grounds-and-solves the radius-2 fixed instance
to proven optimality in 0.06 s.

## Int vs Bool verdict

The one-hot boolean encoding is **~10× faster to solve** than the Int
encoding everywhere it applies (bond to optimum 0.57 s vs 6.3 s; water
0.17 s vs 2.3 s) at ~0.6 s extra build time, and it scales further
(frontier: bool handles radius-2 horizons the Int encoding times out
on). The Int encoding drags every hex comparison through linear
arithmetic; the bool variant grounds the geometry at encode time —
doing manually what clingo's grounder does automatically. Clearest
lesson of the study: on finite combinatorial boards, encode like a
grounder, or use one.

## Incremental vs one-shot verdict

- To a proven optimum, incremental `descend-cost` (one UNSAT proof)
  beats `optimize` and `ramp-cost` when the optimum is a large fraction
  of the horizon (bond Int: 6.3 / 16.0 / 54.6 s); `ramp-cost` wins when
  the optimum is small (water free: 0.56 s vs 4.4 s). Optimality
  proving (UNSAT) is Z3's pain point; plain satisfiability is cheap
  everywhere (oneshot 0.03–0.6 s, but sloppy plans: cost 8–14 vs
  optima 3–12).
- `ramp-horizon` (assumption literals over one unrolled encoding,
  learned clauses shared across horizons) found optimal-cost plans on
  all four instances at a fraction of the proof cost (bond 0.75 s,
  water fixed 0.38 s / free 0.11 s) — but only because in this fragment
  waits are pure no-ops, so min feasible horizon = min instruction
  count. That equivalence breaks under core2's respawn timing; it stays
  a heuristic, reported without optimality claims.

## Validation

Two independent levels, both passing:

1. **`validate.py`** — a plain-Python replayer (no Z3, no reuse of the
   encoders' transition code) re-implementing the semantics from
   `asp/core.lp` / `asp/core2.lp`: per-step legality (grab/drop
   preconditions, the bond-instance no-rotate rule, rigid-motion
   tearing), per-state invariants (board bounds, collisions, base
   blocking, gripper on board), glyph effects (bond formation at every
   state, calcification on every step incl. waits), goal satisfaction,
   and a full cross-check of the reported trajectory / orientation /
   held / bond timelines and cost. **8/8 solutions PASS**
   (trivial/bond/rigid/water × fixed/free). Mutation-tested: corrupting
   an action, moving the calcifier, or misreporting cost are all
   caught.
2. **omsim ground truth** — `emit_omsim.py` converts the fixed-layout
   Stabilized Water plan into a real `.solution` v7 file (single arm ⇒
   plan steps map 1:1 onto cycles, waits = blank tape cells; omsim's
   `'r'` letter = our `rot_cw` = dir d→d+1, decoded from a reference
   solution; two rotations appended so the looping tape is a fixed
   point; checked that no atom re-enters a vacated input hex, since
   omsim inputs respawn instantly). omsim verifies it against the real
   campaign `P007.puzzle`:

   ```
   $ omsim -p P007.puzzle z3/solutions/water-z3.solution
   40g/12i@0 75c/7a@V        (exit 0)
   ```

   Cost 40, 12 instructions, victory at cycle 75, area 7 — a legal,
   complete solution of the actual game puzzle derived from the Z3
   plan, verified on the first attempt. (For scale: the community
   record archive has a 6-instruction two-arm solution; ours is
   single-arm and serialized by construction.)

## Gotchas discovered (semantics traps)

- clingo's `holding(X,T+1) :- do(grab,T), ...` means held becomes true
  at T+1 but the atom does not move on the grab step; wrong t vs t+1
  indexing silently costs an extra instruction.
- Bond formation fires at every STATE including 0 and T, even while
  held; calcification fires on every STEP including waits (it keys on
  position, not action) — the validator briefly had exactly this bug.
- rot_ccw about a base: `(q,r) → (BQ+(q-BQ)+(r-BR), BR-(q-BQ))`; verify
  via dir-table round trips (cw maps dir d onto d+1).
- core.lp v1 does NOT block the arm-base hex; core2 v2 does. Don't mix.
- omsim's `.solution` letter `'r'` is *labelled* "rotate ccw" but is the
  same axial map as this repo's clockwise-indexed `rot_cw` (d→d+1) —
  the naming depends on how you draw the axes. Decoded from a reference
  solution before trusting it.
- omsim inputs respawn the moment their hex clears: a looping tape must
  never steer an atom back over a vacated input hex and must return the
  arm to its initial orientation (`emit_omsim.py` checks/handles both).

## Honest bottom line

Z3-as-BMC is a *correct* and reasonably capable Opus Magnum solver at
this scale: proven optima on all four instances, layout synthesis that
found a real speedrun trick rather than being told it, and plans strong
enough to survive an independent replayer and the actual game
simulator. It is not the *right* solver for this fragment: clingo is
1–2 orders of magnitude faster on every instance with a far shorter
model description, and Z3's optimality-proof frontier (fixed layout
beyond horizon ≈ 20) is territory clingo would not notice. The domain is finite and
purely combinatorial, so SMT's theories buy nothing — the winning move
inside Z3 was to hand-ground everything to booleans, i.e. to imitate
clingo. Use ASP here; bring in Z3 when the problem genuinely needs
arithmetic/theory reasoning (unbounded counters, real-valued timing,
parametric geometry), which Opus Magnum at this abstraction level does
not.
