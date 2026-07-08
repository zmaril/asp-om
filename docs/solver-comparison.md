# Solver bake-off: can computers solve Opus Magnum puzzles?

Five independent solver arms — **clingo** (ASP), **Picat** (tabled
planner), **Z3** (SMT/bounded model checking), **raw SAT**
(PySAT/CaDiCaL/Glucose/kissat), and **MiniZinc** (CP/MIP, five engines) —
each encoded the same deliberately simplified Opus Magnum fragment and
solved the same instances, including the real chapter-1 campaign puzzle
*Stabilized Water* (byte-decoded from the game's own `P007.puzzle` file
via [omsim](https://github.com/ianh/omsim)'s parser). A common harness
(merged PR #3) defines the canonical puzzle/plan JSON formats, the world
semantics (`harness/SPEC.md`), one validator (`harness/validate.py`),
and an adapter contract, so the harness-canonical numbers below are the
apples-to-apples comparison.

Source of every number: the arms' own notes and result files —
`NOTES.md` (clingo, default branch), `picat/NOTES.md` (default branch)
plus `picat/results/canonical.md` (branch `picat-harness-adapter`,
PR #13), `z3/NOTES.md` (branch `z3-encoding`, PR #4), `sat/NOTES.md`
(branch `sat-encoding`, PR #10), `minizinc/NOTES.md` +
`minizinc/results/benchmarks.md` + `minizinc/results/canonical.md`
(branch `minizinc`, PR #11). Machines differ slightly per arm (all
4-core containers); treat cross-arm wall times as order-of-magnitude
comparisons, except where an arm explicitly benchmarked another solver
on the same box (Z3, SAT and MiniZinc each ran the clingo reference
adapter locally).

## 1. Headline verdict

**Yes — computers solve real Opus Magnum puzzles with these solvers.**
All five arms solve *Stabilized Water* end to end within the shared
simplified model, every reported plan passes an independent replay
validator, and two arms went further and verified their plans against
the **actual game**, using omsim (the cycle-accurate community
simulator) and the game's own puzzle file:

- **SAT** exported its 12-step plan to a game-format `.solution` file;
  omsim accepted it against `P007.puzzle` with
  `40g/14i@0 82c/7a@V` — "identical on every metric to the decoded
  human reference solution" (`sat/NOTES.md`, "omsim cross-check").
- **Z3** did the same with its fixed-layout plan:
  `40g/12i@0 75c/7a@V (exit 0)` — "a legal, complete solution of the
  actual game puzzle derived from the Z3 plan, verified on the first
  attempt" (`z3/NOTES.md`, "Validation").

The interesting differences between the arms are not *whether* they
solve the shared instances but **how fast they prove optimality** and
**where each falls off a tractability cliff** (sections 4–5).

## 2. Main comparison: the three shared instances

### 2.1 Harness-canonical results (free layout — the apples-to-apples table)

The three canonical instances (`harness/puzzles/*.json`) all ship with
**free layout**: the solver places the arm, the input(s), the output
and the glyphs, then programs the arm; all part footprints must be
pairwise disjoint (`harness/SPEC.md` §4). Plan length = non-wait
instructions; placements are free. Every plan below passed the
canonical `harness/validate.py`.

Cell = **plan length** (wall time; optimality proof status). Canonical
optima: **single_transport 3, two_atom_bond 11, stabilized_water 12** —
proved independently by the SAT arm, by MiniZinc/CP-SAT, and by Picat's
planner.

| puzzle | clingo (reference adapter) | Picat | MiniZinc (best engine) | Z3 | SAT |
|---|---|---|---|---|---|
| `single_transport` | **3** (0.08–0.11 s; proved) | **3** (0.06 s; proved) | **3** (0.2 s, Chuffed; proved) | **3** (0.16 s; proved) | **3** (0.15 s; proved) |
| `two_atom_bond` | **11** (returned at its 30 s cap; found in ~1 s, **not proved**) | **11** (2.8 s; **proved**) | **11** (21.1 s, CP-SAT `-p4`; proved) | **11** (returned at its 120 s cap; **not proved**) | **11** (9.3 s; **proved**) |
| `stabilized_water` | **12** (returned at its 30 s cap; found in ~1 s, **not proved**) | **12** (62.6 s; **proved**) | **12** (124.4 s, CP-SAT `-p4`; proved) | **12** (found ~15–20 s, returned at its 120 s cap; **not proved**) | **12** (9.6 s; **proved**) |

Sources: SAT rows and the clingo-reference columns from `sat/NOTES.md`
("Harness conformance"); Z3 rows and a second clingo measurement from
`z3/NOTES.md` ("Canonical validation results"); MiniZinc rows from
`minizinc/results/canonical.md`; Picat rows from
`picat/results/canonical.md` (PR #13). Notes on reading it:

- **clingo's 30.2 s walls are its adapter's internal time-limit cap,
  not solve time**: it finds the optimal-length plans "within ~1 s"
  (`minizinc/NOTES.md` §5) but never proves them optimal — raising the
  budget to 300 s changes nothing (`z3/NOTES.md`). Same story for Z3's
  120.2–120.3 s walls.
- **SAT, MiniZinc's CP-SAT and Picat prove the canonical optima**, and
  SAT is the fastest at it (9.3 s / 9.6 s vs Picat's 2.8 s / 62.6 s and
  CP-SAT's 21.1 s / 124.4 s — Picat is actually quickest on
  `two_atom_bond` but 6.5× slower than SAT on `stabilized_water`).
- **Picat's adapter landed later than the other arms'.** Its arm
  (PR #1) merged before the harness (PR #3); the harness adapter
  (`picat/adapter.py`) and canonical results arrived in PR #13
  (`picat/results/canonical.md`, branch `picat-harness-adapter`).
  Because it solves with the planner module's `best_plan` (iterative
  deepening), every Picat optimum above is proved, not an incumbent —
  a timeout returns no plan at all. One caveat: the adapter keeps the
  merged Picat model's glyph timing (calcify/spawn/bond applied at
  post-action positions) rather than the harness's read-at-t/
  retype-at-t+1 calcifier rule, but every emitted plan was replayed by
  the canonical `harness/validate.py` and PASSED — the numbers are
  validator-checked facts, not model claims.
- MiniZinc's wall times above are with the engine chosen directly; its
  adapter's default portfolio (Chuffed slice, then CP-SAT) reports
  0.32 / 80.02 / 181.09 s through `harness/bench.py`
  (`minizinc/results/canonical.md`).

### 2.2 Why canonical Stabilized Water is 12, not 9 (or 3)

Pre-harness, several arms found *shorter* free-layout Stabilized Water
machines — clingo, SAT and MiniZinc found **9**, and Z3 found **3** —
because their conventions allowed **stacking glyphs under the reagent
and/or product hexes** (Z3's notes call the cost-3 machine "the classic
OM speedrun trick": bonder and calcifier under the input hexes, so the
bond and calcification happen at t=0). The harness's **footprint
disjointness rule** (`harness/SPEC.md` §4: arm bases, input hexes,
output hexes, calcifier and bonder hexes pairwise disjoint) outlaws
that stacking, and it additionally makes the **output a placeable part**
and collapses the two reagent sites into **one respawning pool-2
input** (SPEC "Reconciliation decisions" 1 and 5). Under those shared
rules the proven optimum is **12** (SAT, CP-SAT). The 9s and the 3 are
not wrong — they answer a laxer question that the arms happened to pose
differently, which is exactly why the harness exists.

### 2.3 Pre-harness fixed-layout results (per-arm hand layouts — read with care)

Before the harness, each arm also solved *fixed-layout* variants where
a human pinned the machine and the solver only synthesized the
instruction tape. **These instances are only cross-comparable where
arms shared them**: clingo, Z3 and SAT used a byte-identical Stabilized
Water instance (`asp/stabilized_water.lp`, mirrored as
`z3/stabilized_water.lp`; SAT's `sw` is "byte-identical in layout and
semantics" per `sat/NOTES.md`), while Picat and MiniZinc pinned
*different* hand layouts and goal conventions.

Cell = **optimum** (time to proven optimum).

| instance (pre-harness analogue) | clingo | Picat | MiniZinc (best engine) | Z3 (bool encoding) | SAT |
|---|---|---|---|---|---|
| transport one atom ("trivial"/t1) | **5** (0.009–0.01 s) | **5** (0.000 s) | **5** (0.2 s, Chuffed) | **5** (0.075 s) | **5** (≤0.34 s) |
| bond two atoms (t2) | **12** (0.148–0.152 s) | **12** (0.001 s) | **12** (0.4 s, Chuffed) | **12** (0.57 s) | **12** (≤0.34 s) |
| Stabilized Water, fixed layout | **10** (0.06–0.07 s) | **13** (0.008 s) † | **9** (0.6 s, Chuffed) † | **10** (0.17 s) | **10** (0.45 s; makespan-10 in 0.05 s) |

† Not the same question: Picat pinned the output hexes *and* enforced
footprint disjointness including input/output hexes (13 is its proven
optimum over that stricter convention, `picat/NOTES.md`) — a convention
that already matched the harness footprint rule: PR #13's adapter,
re-run on the canonical Stabilized Water puzzle with that same hand
layout pinned, reproduces **optimum 13, proved, in 0.05 s**, and the
plan passes `harness/validate.py` (`picat/results/canonical.md`,
"Fixed layout"); MiniZinc's
fixed instance pins a *different*, better hand layout with the bonder
directly on the product hexes (`minizinc/instances/stabilized_water.dzn`
comments; hand plan = 9). Only the clingo/Z3/SAT 10s are the same
instance. Sources: `NOTES.md` results table, `picat/NOTES.md` results
table, `minizinc/results/benchmarks.md`, `z3/NOTES.md` results tables,
`sat/NOTES.md` phase-1/2 results.

### 2.4 Pre-harness free-layout Stabilized Water (layout as a solver decision)

| arm | best machine found | proof status | time | convention caveat |
|---|---|---|---|---|
| clingo | **9** instructions | found in 12.4 s; instruction-optimality **unproved in 300 s**; makespan-9 proved minimal via UNSAT at T=8 in **113.6 s** | first plan 0.7 s | glyphs may overlap spawn/product hexes |
| Picat | **13** (+3 placements) | **proved optimal over all legal layouts** | 2.29 s (7.39 s unpruned) | stricter: pinned outputs, full footprint disjointness — closest to harness rules |
| MiniZinc | **9** | proved (Chuffed 225.9 s; CP-SAT `-p4` **3.8 s**) | — | "may place a glyph under the product hexes, which the harness forbids" (`minizinc/NOTES.md` §2) |
| Z3 | **3** | proved (int ramp-cost 0.56 s) | — | glyphs allowed under input/product hexes ("just like the real game", `z3/NOTES.md`) |
| SAT | **9** | 9-instruction optimum **proved in 34.8 s**; UNSAT at T=8 ("no 8-step machine") in **8.3 s** | SAT@9 in 2.0 s | same convention as clingo (mirrors `asp/` semantics) |

The spread (3 / 9 / 13 for the *same puzzle*) is entirely a
layout-convention spread — see §2.2. Under the harness's single
convention everyone lands on 12.

## 3. MiniZinc per-engine breakdown

One MiniZinc model (`minizinc/om.mzn` / `om_fixed.mzn`) ran on five
engines, plus a hand-written native OR-Tools CP-SAT port of the same
model. Cell = **objective** + wall seconds (flattening included) when
the optimum was proved; `9? t/o` = optimal-valued incumbent, unproven
at 300 s; `err` = MIP backend overran `--time-limit` and was killed.
Source: `minizinc/results/benchmarks.md`.

Fixed layout (`om_fixed.mzn`):

| instance | Gecode | Chuffed | CP-SAT `-p1` | CP-SAT `-p4` | HiGHS | COIN-BC |
|---|---|---|---|---|---|---|
| t1_transport | **5** 0.2s | **5** 0.2s | **5** 0.3s | **5** 0.3s | **5** 0.9s | **5** 6.0s |
| t2_bond | **12** 5.2s | **12** 0.4s | **12** 0.6s | **12** 0.6s | **12** 23.4s | t/o 300s |
| stabilized_water | **9** 6.2s | **9** 0.6s | **9** 1.3s | **9** 1.3s | t/o | t/o |

Free layout (`om.mzn`, pre-harness conventions):

| instance | Gecode | Chuffed | CP-SAT `-p1` | CP-SAT `-p4` | HiGHS | COIN-BC |
|---|---|---|---|---|---|---|
| t2_bond | **5** 0.8s | **5** 0.5s | **5** 0.9s | **5** 0.8s | **5** 257.3s | **5** 132.4s |
| stabilized_water | 9? t/o | **9** 225.9s | **9** 43.6s | **9** 3.8s | err 420s | err 420s |

Canonical harness instances (fully free layout + footprint rule,
`minizinc/results/canonical.md`):

| puzzle | Chuffed | CP-SAT `-p4` | Gecode `-p4` |
|---|---|---|---|
| single_transport | **3** 0.2s (proved) | **3** 0.3s (proved) | **3** 0.3s (proved) |
| two_atom_bond | **timeout, NO solution (300 s)** | **11** 21.1s (proved) | **timeout, NO solution (300 s)** |
| stabilized_water | **timeout, NO solution (300 s)** | **12** 124.4s (proved) | **timeout, NO solution (300 s)** |

Findings (`minizinc/NOTES.md` §3–5, §7):

- **Gecode times out (>300 s, no solution at all) on the two harder
  canonical instances that CP-SAT proves optimal in 21 s / 124 s**;
  Chuffed — fine on phase-3 free-layout instances of similar size —
  also collapses once input/output placement joins the decision space.
  Engine robustness to instance *conventions*, not just size, was a
  differentiator.
- **Multi-core CP-SAT is the only engine that keeps proving optimality
  as the horizon grows** (free-layout SW: T=14 proved in 12.9 s at
  `-p4` while single-thread CP-SAT returns nothing; Gecode "proves
  nothing in this family").
- **MIP backends (HiGHS, COIN-BC) are hopeless beyond toys** —
  timeouts with no incumbent on SW-class instances, both overran the
  time limit and were hard-killed.
- **FlatZinc-translation overhead is real but constant-ish and is not
  a formulation cliff**: flattening costs 0.19–0.25 s per instance
  (10–40× the native model build of 5–19 ms); like-for-like, the
  native CP-SAT Python port is **1.4–5.5× faster end-to-end**, but
  pure solve-time ratios are only 0.94–1.43× — the two routes hand
  CP-SAT near-isomorphic models (`minizinc/NOTES.md` §4,
  `minizinc/native/bench_results.csv`). Caveat: `import ortools`
  itself costs ~0.5 s at one-shot CLI granularity.
- Engine ranking per the arm's own verdict: "Chuffed ≥ CP-SAT ≫
  Gecode ≫ HiGHS > COIN-BC" on easy/fixed instances, flipping to
  **CP-SAT (multi-core) first on every hard free-layout instance** —
  and CP-SAT is the only engine that solves all three canonical
  puzzles.

## 4. Optimality proofs — the real differentiator

Finding a plan is cheap for everyone. **Proving no shorter plan exists
is where the arms separate**, and it is exactly the question that
matters for optimization play.

Head-to-head on the same box, same instances (`sat/NOTES.md`,
"Stabilized Water" table):

| question | SAT | clingo |
|---|---|---|
| free layout: no 8-step machine exists (UNSAT @ T=8) | **8.3 s** | **113.6 s** |
| free layout: 9-instruction optimum @ t_max=10 | **proved in 34.8 s** | found 9 in 12.4 s, **not proved in 300 s** |
| fixed layout, slack horizon t_max=16 | optimum 10 proved in **3.2 s** | >300 s (1.9 s only with the opt-in, unsound-in-general `nowait.lp` breaker) |
| fixed layout, slack horizon t_max=20 | optimum 10 proved in **8.0 s** | >300 s without the breaker |

And on the canonical instances (§2.1): SAT proves all three optima in
≤9.6 s; Picat's `best_plan` proves all three in ≤62.6 s (proof is the
only mode it has — iterative deepening exhausts every shorter cost
bound before returning); MiniZinc/CP-SAT proves all three in ≤124.4 s;
clingo and Z3 find the same plan lengths but prove only
`single_transport`, even at 300 s budgets.

Within Z3, encoding style dominates: the **pure-boolean one-hot
encoding is ~10× faster to solve than the Int encoding** everywhere it
applies (bond: 0.57 s vs 6.3 s; water: 0.17 s vs 2.3 s) and survives
one horizon step further before the proof wall (`z3/NOTES.md`, "Int vs
Bool verdict"). The arm's own conclusion: "on finite combinatorial
boards, encode like a grounder, or use one."

### Where each arm falls off a cliff

- **clingo** (`NOTES.md`, "Where it breaks down"): (1) horizon slack
  under `#minimize` — the trivial 1-atom instance goes 0.01 s → 0.57 s
  → 15 s → >300 s at T=10/20/40/80, almost entirely in the optimality
  proof; (2) **arm count** — 1 arm/2-atom 0.07 s → 1 arm/3-atom 53 s →
  **2 arms / 36 steps: ~130 s to a first model, optimality proof out
  of reach at 10 min**. (The raw grounding blowup at 2 arms — the
  naive encoding "never left the grounder in 12+ minutes" — was fixed
  by precomputed on-board rotation images, bringing grounding to
  1.6 s / 76 k rules; the residual cliff is the solve.) (3) layout
  freedom makes proofs, not finding, infeasible. Board radius is
  nearly free.
- **SAT** (`sat/NOTES.md`, radius-scaling table): CNF grows roughly
  quadratically with board radius (77 k clauses at r=2 → 1.03 M at
  r=5); the UNSAT@8 certificate goes 8.3 s (r=2) → 33.0 s (r=3) →
  76.5 s (r=4) → 171.8 s (r=5, kissat already TIMEOUT at 300 s);
  "extrapolating the ~2.3× per-radius growth, cadical's UNSAT proof
  passes 300 s around radius 6." Finding plans stays cheap much
  longer. Multi-arm was never attempted (encoder is single-arm).
- **Z3** (`z3/NOTES.md`, frontier): fixed-layout optimality proofs die
  at t_max ≈ 20 for both encodings at a 120 s budget, while plans keep
  arriving in seconds well past that; the Int encoding hits the wall
  one horizon step before bool.
- **MiniZinc** (`minizinc/NOTES.md` §3): the horizon T is the dominant
  hardness axis (radius is mild); Gecode proves nothing on free-layout
  SW; single-thread CP-SAT returns *nothing* at T≥14; only `-p4`
  CP-SAT keeps proving as T grows; Chuffed/Gecode return no solution
  at all on the fully-free canonical instances.
- **Picat** (`picat/NOTES.md`, "Where it will break down"): free
  layout is multiplicative — ~40× (bond) to ~900× (SW, unpruned) over
  the fixed-layout solve on a 19-hex board; the tabled state carries
  every atom/bond/arm plus the chosen layout, so bigger products and
  boards grow the reachable state set sharply, and iterative deepening
  re-expands each layout's subtree at every depth bound. The canonical
  runs (PR #13) confirm it: the adapter needs symmetry reduction plus
  sound distance prunes to prove 11/12 in 2.8 s / 62.6 s — with
  `--noprune`, `two_atom_bond` alone blows the 300 s budget — and the
  pinned-layout SW variant that free-layout search takes 62.6 s on is
  proved in 0.05 s (`picat/results/canonical.md`).

## 5. Takeaways

- **Finding a solution fast**: clingo. On identical instances it is
  1–2 orders of magnitude faster than Z3 (`z3/NOTES.md`) and 1–3
  orders faster than every MiniZinc backend (`minizinc/NOTES.md` §6);
  it found the canonical 11/12-length plans in ~1 s. Picat's planner
  is similarly instant at this scale (milliseconds fixed-layout) and
  has the most natural model to write.
- **Proving optimality**: the **SAT arm** is the clear winner —
  off-the-shelf cardinality constraints + incremental CDCL prove
  every canonical optimum in ≤10 s and deliver UNSAT certificates
  10–14× faster than clingo on the same questions. **Picat** is the
  runner-up: `best_plan`'s iterative deepening proves all three
  canonical optima in ≤62.6 s (PR #13) — proof is structural, not
  optional, since it has no incumbent-at-timeout mode. MiniZinc with
  **multi-core OR-Tools CP-SAT** proves all three too, in ≤124.4 s
  (and is the only MiniZinc engine that survives the canonical
  instances); clingo and Z3 find the optimal plans but prove only the
  easiest one.
- **Joint layout + program design**: all arms can do it; SAT, Picat
  and CP-SAT are the ones that also *prove* the co-designed machine
  optimal under the harness rules. Z3's free-layout mode deserves
  credit for *discovering* the glyphs-under-inputs speedrun trick
  (cost 3) rather than being told it — the one qualitative win for
  SMT in the study.
- **The harness is what made any of this comparable.** Before it, the
  five arms reported optima of 3, 9, 9, 10 and 13 for the *same
  puzzle* because layout legality, goal placement and reagent modeling
  differed; the shared formats, footprint-disjointness rule and single
  validator (`harness/SPEC.md`, `harness/validate.py`) turned that
  into one number (12) everyone can be scored against.
- **Honest caveats.** Everything above is the agreed *simplified*
  fragment: global sequential timesteps (one instruction per step
  across all arms — no parallel tapes, no loops, no cycle-count
  metric), endpoint-only collision checks, bounded boards (radius 2–5)
  and bounded input pools, one product copy with a non-consuming
  output, and a small part set (fixed-length arms, bonder, calcifier
  only). The omsim verifications show the fragment *can* emit fully
  game-legal solutions, but SAT's notes are explicit that this worked
  because those instances were designed for it (single arm, loop-clean
  tape); plans relying on modeled-but-unreal behavior would fail the
  real game. Per-arm timings were also measured on similar but not
  identical containers, and clingo was never pushed to *its* frontier
  on the canonical free-layout instances by the other arms.

## Appendix: claims deliberately marked unverified

- **Picat's canonical numbers rest on the validator, not the model**:
  its adapter (PR #13) keeps the merged model's glyph timing rather
  than the harness's calcifier rule (`picat/results/canonical.md`,
  "Methodology / caveats"). Every emitted plan passed
  `harness/validate.py`, so the plan lengths and PASS verdicts are
  verified; the "proved optimal" claims additionally rely on the
  adapter's soundness argument for its timing shim and search prunes
  (cross-checked against the SAT/CP-SAT-proved optima, which match
  exactly).
- clingo's canonical-instance behavior is reported via the other arms'
  runs of the reference adapter (`sat/NOTES.md`, `z3/NOTES.md`,
  `minizinc/NOTES.md`) — the clingo arm itself predates the canonical
  bench and published no canonical table of its own.
- SAT's "dies around radius 6" is the arm's own extrapolation from
  measured r=2..5 data, not a measured r=6 timeout.
