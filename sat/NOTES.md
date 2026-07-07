# Does a raw SAT solver work for solving Opus Magnum puzzles? — SAT arm findings

## TL;DR

**Yes — and it is the strongest arm so far on the shared fragment.** A
plain CNF encoding (PySAT + Cadical195/Glucose42/kissat, no theories, no
ASP grounder) solves the real chapter-1 campaign puzzle *Stabilized
Water* end to end: with the hand layout it re-derives the 10-instruction
optimum in well under a second, and with a **free layout it both finds
the 9-step machine and proves no 8-step machine exists in 8.3 s** — the
same proof took the clingo arm 113.6 s. The slack-horizon optimality
proofs that made clingo fall off a cliff (>300 s at t_max=20 without a
bespoke symmetry breaker) cost the SAT arm 8 s flat with off-the-shelf
cardinality constraints. One SAT plan was exported to a game-format
`.solution` file and **accepted by omsim, the cycle-accurate community
simulator, against the game's own P007.puzzle file — with exactly the
same metrics (40 cost / 82 cycles / 7 area / 14 instructions) as the
human reference solution**. All three shared-harness instances solve
with proved-optimal plan lengths (3 / 11 / 12) and pass the canonical
harness validator; the SAT plan for `stabilized_water` beats the
hand-written 13-instruction reference plan. Tractability ends where all
bounded-horizon methods end: UNSAT proofs just below the minimum
makespan blow up as the free-placement space grows (kissat already
times out at 300 s on the radius-5 board), and the encoding still
covers only the agreed simplified fragment of the game (single
sequential arms, endpoint-only collisions, no pistons/track/tape
loops).

## What was built

Three layers, all under `sat/`:

1. **`encode.py`** (phase 1) — the trivial fragment: one length-1..2
   arm, inert atoms, optional bonding glyph, per-atom delivery goals.
   Results in `results-trivial.md`.
2. **`encode2.py` + `instances.py` + `decode2.py` + `validate2.py` +
   `bench_sw.py` + `export_omsim.py`** (phase 2) — the Stabilized Water
   fragment, mirroring the clingo arm's `asp/core2.lp` semantics
   exactly: rigid bond-component rotation about the arm base, element
   types + glyph of calcification, glyph of bonding (persistent bonds),
   respawning bounded-pool reagent inputs with clingo's spawn timing,
   arm-base blocking, exact salt–water-dimer goals. Results in
   `results-stabilized-water.md`.
3. **`encode3.py` + `adapter.py`** — the cross-solver **harness**
   adapter (harness/ on the default branch): reads the shared puzzle JSON
   (instance-driven parts, placeable *output part* participating in the
   part-non-overlap rule, optional pinned placements), emits the shared
   plan JSON. Every reported harness result was validated by the
   canonical `harness/validate.py`.

### Encoding design

Bounded-horizon planning-as-SAT. States `t = 0..T`, one instruction per
step from {rot_cw, rot_ccw, grab, drop, wait} (exactly-one per step,
matching clingo's `{do} 1` with idle=wait). Variable families mirror
the ASP predicates roughly 1:1:

* layout: `base(h)`, `spawn(i,h)`, `cpos(h)` (calcifier), `gpos(h)` +
  `gdir(d<3)` (bonder), output `opos(h)` + `orot(k)` (harness encoder)
  — each exactly-one over the hex ball; **the same CNF serves both
  modes**: free layout lets the solver assign them (under the OM
  part-non-overlap rule, pairwise-disjoint footprints), fixed layout
  pins them with unit *assumptions*;
* arm state: `orient(d,t)`, derived `grip(h,t)`;
* atom state: `ex(x,t)` (spawn pools), `at(x,h,t)`, `hold(x,t)`,
  `salt(x,t)` (the only dynamic element change is elemental→salt);
* `bond(p,t)` per unordered atom pair, plus Tseitin witnesses (`bf`,
  `cw`, `exw`) so that every effect has a *completion* direction — the
  solver can neither invent bonds/calcifications/spawns nor skip them;
* rigid motion: the held bond-connected component is computed exactly
  by a **level-based closure** `comp(k,x,t)` (k ≤ #atoms−1 suffices;
  arbitrary fixpoints are excluded because every level is defined with
  both implication directions), and rotation effect clauses range over
  (base b × hex h) pairs with the axial rotation maps
  `(q,r) → (−r, q+r)` / `(q+r, −q)` translated to b; off-board images
  are forbidden on the pre-state;
* frame axioms: positional persistence unless `mv(x,t)` (turn ∧ in
  component); `salt`/`bond`/`ex` persist monotonically with completion
  clauses; hold persists unless dropped.

Exactly-one/at-most-one are naive pairwise (board sizes keep this
acceptable). Instruction-count optimization = downward linear search
over `pysat.card.CardEnc.atmost` (sequential counter) bounds on the
"non-wait" literals — deliberately the same objective as clingo's
`#minimize { 1,M,A,T : do(M,A,T) }`.

CNF sizes (encode times in parentheses, this container):

| instance | board | atoms | T | vars | clauses |
|---|---|---|---|---|---|
| sw fixed/free | r=2 (19 hexes) | 4 | 10 | 9,243 | 84,697 (0.12 s) |
| sw-omsim | r=3 (37 hexes) | 2 | 12 | 6,457 | 125,410 (0.15 s) |
| sw-r4 free | r=4 (61 hexes) | 4 | 9 | 27,784 | 508,097 (0.77 s) |
| sw-r5 free | r=5 (91 hexes) | 4 | 9 | 41,944 | 1,032,674 (1.6 s) |

## Results (all numbers real, measured here; 300 s per-solve timeout)

### Phase 1 (trivial cases, `results-trivial.md`)

Min makespan by horizon iteration: case (a) fixed 5 / free 3, case (b)
12 / 12; instruction optima at clingo's t_max match clingo exactly (5
and 12), total optimization wall time 0.03–0.34 s vs clingo's
0.007–0.120 s — at this scale both are instant.

### Stabilized Water — the real puzzle (`results-stabilized-water.md`)

The `sw` instance is byte-identical in layout and semantics to the
clingo arm's `asp/stabilized_water.lp` (radius-2 board, two water
inputs pool 2, calcifier, bonder, exact-dimer goal). Horizon iteration
T = 1, 2, … per backend:

| question | SAT arm | clingo arm (branch stabilized-water) |
|---|---|---|
| fixed layout: min makespan | **10** (SAT@10 in 0.05 s, UNSAT@9 in 0.04 s, cadical) | optimum 10 instr in 0.07 s |
| fixed layout: 10-instr optimum @ t_max=10 | proved in **0.45 s** | proved in 0.07 s |
| free layout: min makespan | **9** (SAT@9 in 2.0 s; **UNSAT@8 in 8.3 s**) | 9 (SAT@9 1.3 s; UNSAT@8 **113.6 s**) |
| free layout: 9-instr optimum @ t_max=10 | **proved in 34.8 s** | found 9 in 12.4 s, **not proved in 300 s** |
| slack horizon t_max=16, fixed | optimum 10 proved in **3.2 s** | >300 s without opt-in `nowait.lp` breaker (1.9 s with) |
| slack horizon t_max=20, fixed | optimum 10 proved in **8.0 s** | >300 s without breaker |
| slack horizon t_max=16, free | optimum 9 proved in 302.6 s (last UNSAT solve just under the limit) | not attempted |

All three backends (Cadical195, Glucose42, kissat) agree on every
SAT/UNSAT answer; cadical and glucose are consistently fastest, kissat
pays a constant factor on the UNSAT side (it re-parses DIMACS and gets
no incremental reuse). Every SAT model was decoded and re-simulated by
the independent validator.

The `sw-omsim` instance (reference-solution machine layout, single
input, output cells pinned) has min makespan **12**, fixed and free,
solved in well under a second per horizon.

### Free-layout board-radius scaling — where tractability ends

Same puzzle, free layout, board radius scaled up (the machine placement
space and the rigid-motion clause space grow quadratically). Minimum
makespan stays 9 at every radius; the cost concentrates in the **UNSAT
proof at T=8**, exactly the "no shorter machine exists" certificate:

| board | clauses @T=9 | UNSAT@8 (cadical) | UNSAT@8 (kissat) | SAT@9 (cadical) |
|---|---|---|---|---|
| r=2 (19 hexes) | 77 k | 8.3 s | 9.5 s | 2.0 s |
| r=3 (37 hexes) | 218 k | 33.0 s | 60.8 s | 4.4 s |
| r=4 (61 hexes) | 508 k | 76.5 s | 210.3 s | 7.7 s |
| r=5 (91 hexes) | 1.03 M | 171.8 s | **TIMEOUT (300 s)** | 72.6 s |

(The r=5 series was re-run in isolation to rule out CPU contention;
numbers above are the clean run.) Extrapolating the ~2.3× per-radius
growth, cadical's UNSAT proof passes 300 s around radius 6. Finding
plans (the SAT side) stays cheap much longer. This mirrors the clingo
arm's finding — layout freedom is cheap for *finding* machines,
expensive for *proving* anything about them — but the SAT wall is an
order of magnitude further out. Multi-arm puzzles (clingo's real cliff:
~130 s for a first 2-arm plan, optimality unreachable) were not
attempted: the phase-2 encoder is deliberately single-arm, so that
boundary is untested here.

### Harness conformance (harness/ on the default branch, merged from PR #3)

`sat/adapter.py` implements the adapter contract; all three shared
instances solve and **PASS the canonical `harness/validate.py`**, with
the plan length proved optimal by the SAT search itself in every case:

| puzzle | plan length (SAT) | proved optimal | wall time | clingo reference adapter |
|---|---|---|---|---|
| single_transport | 3 | yes | 0.15 s | 3 (0.08 s) |
| two_atom_bond | 11 | yes | 9.3 s | 11 (30.2 s, time-limit capped, no proof) |
| stabilized_water | 12 | yes | 9.6 s | 12 (30.2 s, time-limit capped, no proof) |

(`harness/bench.py` from the default branch run with both adapters in
isolation; wall time is the runner's measurement around the whole
adapter invocation, which for the SAT arm includes proving the plan
length optimal. clingo's reference adapter returns its best model at
its internal 30 s limit. The harness's own validator test suite passes
27/27 here. No `harness/metrics.py` exists on the default branch at
the time of writing, so there was nothing further to hook into.)
The 12-instruction `stabilized_water` plan beats the hand-written
13-instruction reference plan shipped with the harness. Note the
harness instance models the puzzle with ONE pool-2 input (reconciliation
decision 5) and a placeable output part, so its optimum (12) differs
legitimately from the clingo-parity instance's 9/10 (goal "dimer
anywhere", two inputs).

### omsim cross-check (the game-accurate arbiter)

`sat/export_omsim.py` exports the `sw-omsim` fixed-layout plan (12
steps, found by horizon iteration, validated by `validate2.py`) to a
binary game-format `.solution` file: parts mapped 1:1 (input, out-std,
glyph-calcification, bonder, arm1), instruction letters `G/g/r/R`, one
trailing `X` (reset) so the 13-entry tape loops. Verified against the
game's own `P007.puzzle`:

```
$ omsim -p P007.puzzle sat/p007-sat.solution
40g/14i@0 82c/7a@V
```

omsim simulates the tape to the campaign's full 6-product completion:
**40 cost / 82 cycles / 7 area / 14 instructions — identical on every
metric to the decoded human reference solution** from the community
archive. This is the strongest validation in the project so far: the
modeled fragment's plan survives the real game's parallel-cycle
semantics, swept-arc collision detection, infinite inputs and consuming
outputs. (That is a property of this instance's design — single arm,
loop-clean tape, parts laid out exactly like the reference solution —
not a general guarantee; see limitations.)

## Validation methodology

Four independent layers, none sharing logic with the encoders:

1. `sat/validate.py` / `sat/validate2.py`: forward re-simulation of the
   decoded layout + instruction list (layout sanity, non-overlap,
   gripper on-board, grab/drop legality, exact rigid-component motion,
   collisions, calcification/spawn/bond timing, goal), plus a
   per-timestep diff against the decoded trajectories. **Every SAT
   model in every table passed**; the benchmark aborts on any failure.
2. The canonical harness validator for all adapter results.
3. omsim for the exportable instance (above).
4. Cross-solver agreement: three SAT backends agree on every answer,
   and every headline number that clingo also computed (fixed optimum
   10, free makespan 9, UNSAT@8, phase-1 optima 5/12) matches.

## What worked, what didn't

Worked:

* **Feasibility-per-horizon instead of one big `#minimize`.** Iterating
  T upward gives makespan optimality for free and sidesteps the
  wait-padding symmetry entirely on the feasibility side.
* **Cardinality constraints for the instruction objective.** The
  slack-horizon optimality proofs that clingo needed a bespoke, unsound-
  in-general symmetry breaker for are simply not hard for CDCL +
  sequential counters (t_max=20: 8.0 s).
* **Layout as assumptions.** One CNF generator for fixed and free modes;
  fixed layout costs nothing extra and reuses all clauses.
* **Completion witnesses everywhere.** The first encoding bug class in
  planning-as-SAT is "solver helps itself to an effect"; Tseitin
  witnesses for bond/calcify/spawn made the independent validator pass
  on the first SAT model and stay green through every change.
* **Level-based component closure.** Exact transitive closure in CNF is
  awkward; with ≤4 atoms, #atoms−1 levels with biconditional definitions
  are exact and tiny.

Didn't / rough edges:

* **Python encode time and memory.** The encoder re-grounds from
  scratch at every horizon (no incremental extension); at radius 5 each
  horizon costs ~1.6 s and 1M clauses, and the naive pairwise AMO and
  per-(base,hex) rigid-motion clauses are the quadratic bulk. An
  incremental encoder (extend T, add assumptions) or a compiled
  grounder would push the boundary out noticeably.
* **pysat's CaDiCaL has no interrupt()** in this build; per-solve
  timeouts for cadical run in a forked child process (documented in
  `solvers.py`).
* **Free-layout instruction-optimality at big slack** (free, t_max=16:
  302 s) shows the proof cost creeping back once placement freedom and
  horizon slack compound — CDCL is better here than ASP defaults, but
  not immune.
* kissat as an external binary loses to the incremental in-process
  solvers on this workload (DIMACS re-parse per call, no reuse), and
  is first to time out on the big UNSAT proofs.

## Limitations of the modeled fragment (shared across arms)

Same simplified game as the clingo/picat arms and the harness SPEC:
sequential arms (no parallel tapes; the encoders here additionally
handle only ONE arm — multi-arm is future work), endpoint-only
collision checks (no swept arcs), bounded board and bounded input
pools, one product copy with a non-consuming output, no
piston/track/pivot/tape-loop/repeat, no unbonder or other glyphs, no
metals/quicksilver. Goals are encoded at the horizon; harness
"complete at any t" is equivalent there because a completed unheld
product persists under trailing waits. The omsim export shows the
fragment can produce fully game-legal solutions, but only because the
sw-omsim instance was designed for it (loop-clean single-arm tape,
reference part layout); plans that rely on modeled-but-unreal behavior
(e.g. resting atoms on hexes a swept arc would cross) would fail omsim.

## Bottom line

A raw SAT solver is not just adequate for the Opus Magnum fragment this
project agreed on — it is currently the best tool in the house for it.
It matches the clingo arm on every optimum, is 10–100× faster on
exactly the queries that matter for optimization (UNSAT certificates:
"no 8-step machine exists" in 8.3 s vs 113.6 s; slack-horizon optima in
seconds vs timeouts), designs the machine and the program in one shot,
and produced the project's first solution verified by the game-accurate
simulator with metrics identical to a human expert's solution. The
honest caveats: the encoding covers a deliberately small fragment of
the real game (one arm, no parallelism, no swept collisions, small
boards), CNF size grows quadratically with board radius, and the
minimality proofs — the thing SAT is best at here — still die around
radius 6 boards at a 300 s budget. Within the fragment: solved. Scaling
to the full game would need incremental encoding, symmetry breaking,
and multi-arm support before raw CDCL runs out of steam.
