# Can clingo solve Opus Magnum puzzles? — findings

## TL;DR

**Yes, for real (small) puzzles — end to end.** clingo solves the actual
chapter-1 Opus Magnum puzzle *Stabilized Water* (spec byte-decoded from the
game's own puzzle file) in **0.06 s** with a hand-placed machine, and when
given a free hand it **designs the machine itself** — arm, both inputs,
calcifier, bonder — finding a **9-instruction machine that beats the
10-instruction hand layout** (first plan in 0.7 s), and even *proving* that
9 steps is globally minimal over all layouts (t_max=8 is UNSAT in 114 s).
But tractability falls off a cliff along three axes: horizon slack under
`#minimize` (wait-padding symmetry: the trivial 1-atom instance goes
0.01 s → 0.57 s → 15 s → >300 s at T=10/20/40/80), number of arms (a 2-arm
36-step plan needs ~130 s for a first model; its optimality proof is out of
reach at 10 min), and layout freedom (finding machines stays cheap, proving
them optimal does not). clingo is a **needle-finder, not an optimizer**,
beyond ~25-step single-arm plans — and the encoding is still a simplified
OM (see below). The interesting frontier is symmetry handling and
decomposition, not raw encoding size.

Every plan clingo produced was verified by an **independent pure-Python
replay** (`validate.py`) of the same semantics; all shipped instances PASS.

## What was modeled

Two encodings over a bounded axial-coordinate hex board and discrete time:

- `asp/core.lp` (v1, phase 1): one length-1 arm, actions
  {rot_cw, rot_ccw, grab, drop, wait}, one instruction per step, inert free
  atoms, per-atom delivery goals.
- `asp/core2.lp` (v2, phase 2): the real mechanics —
  - **rigid molecule motion**: rotating an arm holding an atom rotates the
    atom's whole bond-connected component 60° about the arm base
    (`(q,r) → (-r,q+r)` cw, `(q,r) → (q+r,-q)` ccw);
  - multiple arms with per-arm length, ≤1 (arm, action) per timestep,
    no-tearing constraint, collision + arm-base + off-board checks;
  - atom element types, passive **glyph of calcification**
    (elemental → salt) and **glyph of bonding** (persistent normal bonds);
  - **respawning reagent inputs** (the next atom appears the step after
    the input hex clears; bounded pool);
  - instance-defined goals: **exact molecule match** (types + bond
    topology + degrees), anywhere on the board, any rotation, unheld.
- `asp/layout.lp`: optional **free-layout module** — choice rules place the
  arm(s), inputs, calcifier and bonder anywhere on the board, subject to
  OM's part-non-overlap rule, so the solver designs the machine *and*
  programs it in one shot.
- `asp/nowait.lp`: optional prefix symmetry breaker (see below).

### Simplifications vs the real game

- **Sequential arms**: one arm acts per timestep; real OM executes all
  arms' tapes in parallel (a real 2-arm machine could interleave).
- **Endpoint-only collision**: a rotation checks landing hexes, not the
  swept arcs; real OM does continuous collision detection, so some plans
  legal here would collide there.
- **Bounded board** (radius 2 in all experiments) and **bounded input
  pools** stand in for OM's unbounded board and unlimited inputs.
- **One product copy**, "exists assembled + unheld anywhere" — no output
  area that consumes molecules, no 6-copy campaign target.
- **No pistons, no track, no tape loops/repeat, no pivot instruction**,
  no unbonding/triplex/projection/etc. glyphs.
- Instruction cost = non-wait instruction count; makespan bounded by
  `t_max` (feasibility at fixed T is the honest "can it be done in T
  steps" question).

## Results

Machine: 4-core box, 15 GB RAM, clingo 5.8.0 (pip). Numbers below are from
the recorded phase-2 experiment logs (`experiments.py --time-limit 300`);
rows marked `*` ran concurrently with other solvers, so treat those times
as upper bounds. The four headline instances were re-run and re-validated
in phase 3 with matching times.

| instance | t_max | ground rules | best model s | total s | outcome |
|---|---|---|---|---|---|
| trivial (1 atom, v1) | 10 | 908 | 0.00 | 0.01 | OPTIMUM cost=5 |
| trivial | 20 | 1,878 | 0.00 | 0.57 | OPTIMUM cost=5 |
| trivial | 40 | 3,818 | 0.01 | 15.0 | OPTIMUM cost=5 |
| trivial | 80 | 7,698 | – | >300 | TIMEOUT (optimality proof) |
| rigid dimer swing (v2) | 10 | 1,366 | 0.00 | 0.01 | OPTIMUM cost=4 |
| **Stabilized Water (true spec, fixed layout)** | 10 | 4,326 | 0.00 | **0.07** | **OPTIMUM cost=10** |
| **Stabilized Water, free layout** | 10 | 59,608 | 12.4 | >300 | **SAT cost=9** (beats hand layout); optimality unproved |
| free layout, t_max=9 (feasibility) | 9 | ~55 k | 1.15 | 1.3 | SAT |
| free layout, t_max=8 (minimality proof) | 8 | ~50 k | – | 113.6 | **UNSAT ⇒ 9 steps globally minimal** |
| Stabilized Water, slack T=20 | 20 | 10,304 | – | >300 | TIMEOUT* (with `nowait.lp`: OPTIMUM in 1.9 s) |
| Stabilized Water, slack T=40 | 40 | 22,184 | – | >300 | TIMEOUT* (with `nowait.lp`: 2.4 s) |
| SW bent 3-atom, 1 arm | 25 | 14,392 | 37.6 | 53.4 | OPTIMUM cost=25 |
| SW bent, T=24 (< optimum) | 24 | 13,722 | – | 35.3 | UNSAT (proves makespan 25) |
| SW bent, slack T=30 | 30 | 17,742 | – | >300 | TIMEOUT*; with `nowait.lp`: OPTIMUM 25 in 132 s |
| SW linear 3-atom, 2 arms | 36 | 76,033 | ~131 (uncontended) | >600 for opt proof | SAT cost=36 (BFS-provably optimal); optimality proof out of reach |
| SW linear, 1 arm (impossible) | 25 | 12,998 | – | 0.02 | UNSAT — **proved by the grounder alone**, 0 choices |

Fixed vs free layout on the same puzzle, same T=10: 4.3 k → 60 k ground
rules (~14×); 0.06 s optimum-proved → 0.7 s first plan / 12 s to the
9-instruction machine / optimality unprovable in 300 s. **Layout freedom
is cheap for finding machines, expensive for proving optimality.**

Notable side findings:

- **A single arm (any length) + one bonder can never build a straight
  3-atom chain**: a held molecule only ever rotates about the one fixed
  base, and colinear chain extension requires a translation. Verified
  three ways: geometric argument, exhaustive BFS over all 144 single-arm
  ring layouts (0 solvable), and clingo UNSAT — for `sw_linear_1arm.lp`
  the grounder alone empties the goal rule in 0.02 s.
- Two arms fix it: rotations about two adjacent pivots compose into a
  one-hex translation (the second arm must be length 2 here).
- Exact-match goals matter: a "pattern exists as subgraph" goal lets the
  solver cheat by building a larger molecule containing the pattern (both
  clingo and the BFS found the cheat); the shipped goals require exact
  bond degrees.

## What made it work

1. **Keeping the grounder's over-approximation of `at/4` on the board** —
   the phase-2 make-or-break fix. The naive rotation rule
   `at(rot(Q,R),T+1) ← …` lets the grounder derive off-board positions;
   with one pivot the closure stays small, but with two arms the group
   generated by two rotations contains translations and the closure
   explodes — the 2-arm instance never left the grounder in 12+ minutes.
   Precomputing per-arm rotation images restricted to the board
   (`rotimg_cw/ccw`) and forbidding off-board swings via a constraint on
   the *pre*-state brought grounding to 1.6 s / 76 k rules.
2. **The `nowait.lp` prefix symmetry breaker** (actions form a prefix of
   the tape) kills the wait-padding permutation symmetry that makes
   `#minimize` optimality proofs blow up at slack horizons: Stabilized
   Water T=20 goes >300 s → 1.9 s, T=40 → 2.4 s; bent T=30 → 132 s. It is
   opt-in because it is unsound if an optimal plan needs a mid-plan wait
   (e.g. idling for a respawn) — verified safe on these instances against
   BFS optima.
3. **Feasibility-at-fixed-T instead of optimization** (`--opt-mode=ignore`)
   where possible: Stabilized Water T=20 feasibility takes 0.04 s while
   the same instance under `#minimize` times out.
4. **Independent validation**: a pure-Python BFS simulator of the same
   semantics (phase 2, now distilled into `validate.py`) cross-checked
   every optimum (rigid 4, fixed SW 10, bent 25, linear 36) and replayed
   clingo's plans action by action; `validate.py` additionally diffs the
   replayed trajectory against the answer set's `at/type/bond/holding`
   atoms at every timestep.

Things that did **not** help on the hard 2-arm instance:
`--configuration=trendy/jumpy`, `-t 4`, `--opt-strategy=usc`, slack
horizons, and hand-written landmark constraints — none beat plain
defaults (~131 s to first model).

## Where it breaks down

- **Horizon slack under `#minimize`** is the dominant cost, almost
  entirely via the optimality proof, not feasibility (trivial instance:
  >300 s at T=80 for a 5-instruction plan).
- **Arm count**: 1 arm/2-atom product 0.07 s → 1 arm/3-atom 53 s →
  2 arms/3-atom ~130 s first model, optimality unreachable. The
  sequential-arm interleaving multiplies the branching factor and defeats
  the prefix breaker (different symmetry source).
- **Layout freedom** makes proofs (not finding) infeasible: the placement
  choice space defeats both instruction-count optimality (300 s+) and
  most symmetry breaking; only the pure makespan proof (UNSAT at T=8)
  stayed tractable.
- Board radius, by contrast, is nearly free (r=2/3/4 identical times) as
  long as the dynamics keep `at/4` bounded.

## What scaling further would take

- **Multi-shot / incremental solving** (clingo's `#program step(t)` +
  `clingo.Control.solve` loop): ground the horizon lazily, ask "solvable
  at T?" for T = 1, 2, … — removes the slack-horizon problem entirely and
  is the standard ASP-planning idiom this project deliberately skipped.
- **Better symmetry breaking**: arm-identity symmetry for equal arms,
  layout canonicalization (fix the first part's position/orientation and
  quotient by the board's dihedral symmetry — a ~12× reduction the free
  layout currently pays for), and action-commutation breaking for
  independent arms.
- **Decomposition**: solve layout and tape in separate calls (propose
  layouts, check plannability), or portfolio-solve configurations in
  parallel; neither was attempted here.
- **Closing the model gap**: parallel arm execution (real OM semantics)
  is a bigger, denser encoding but removes the sequential-interleaving
  symmetry; swept-arc collision needs per-rotation arc hexes (precomputed
  tables would keep grounding linear); tape loops need a modular-time
  encoding; multiple product copies need consuming outputs.

## Provenance of the puzzle spec

The Stabilized Water spec was **byte-decoded from the game's actual
puzzle file** (campaign `P007.puzzle`) with a Python port of
[omsim](https://github.com/ianh/omsim)'s parser: two inputs, each one
unbonded water atom; product = salt normal-bonded to water; allowed parts
include arms/piston/track, bonder, unbonder, multi-bonder, calcification.
Glyph semantics (passive calcification/bonding, exact-match outputs) were
taken from omsim's `sim.c`.

## Reproducing

```sh
pip install clingo

# headline results
python3 run.py asp/core2.lp asp/stabilized_water.lp --tmax 10
python3 run.py asp/core2.lp asp/layout.lp asp/stabilized_water_free.lp --tmax 10 --time-limit 30

# independent validation (PASS/FAIL)
python3 validate.py asp/core.lp asp/trivial_instance.lp
python3 validate.py asp/core2.lp asp/rigid_instance.lp
python3 validate.py asp/core2.lp asp/stabilized_water.lp --tmax 10
python3 validate.py asp/core2.lp asp/layout.lp asp/stabilized_water_free.lp --tmax 10 --time-limit 30

# stress instances (slow: ~1 min and ~2+ min)
python3 run.py asp/core2.lp asp/sw_bent.lp   --tmax 25 --time-limit 600
python3 run.py asp/core2.lp asp/sw_linear.lp --tmax 36 --time-limit 600

# full scaling table
python3 experiments.py --time-limit 300
```
