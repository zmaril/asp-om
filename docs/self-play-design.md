# Self-play training on Opus Magnum — design

Design document for a self-play training system built on this repo's
solver arms and the common harness. The goal: a learned proposer that
designs and programs Opus Magnum machines, trained entirely from its own
attempts plus exact verification — no imitation of human solutions.

## TL;DR

Opus Magnum is verifier-in-the-loop discrete program synthesis: an exact,
cheap simulator tells you with certainty whether a machine works and what
it scores. That verifier is what makes self-play viable with **zero
external solution data**. We propose three interlocking loops: (1)
**expert iteration** — the repo's exact solvers (clingo/Picat/SAT) improve
a learned proposer's drafts and the improved drafts become training
targets; (2) **forward-generation curriculum** — running random machines
forward manufactures guaranteed-solvable puzzles *with* known reference
solutions from game rules alone, and a generator co-evolves to keep those
puzzles at the edge of current competence; (3) **self-competition** — the
system races its own best-known solution per (puzzle, metric) on a
private leaderboard. Everything scores through the common harness's
canonical validator; everything trains only on self-generated data.

---

## ⚠️ The hard data constraint (read this first)

> **External puzzles: allowed. External solutions: never training data.**
>
> * External **puzzles** are fine — import them, generate variations of
>   them, benchmark on them.
> * External **solutions** (community leaderboard records, human GIFs,
>   omsim test-corpus solutions, anything not produced by this system)
>   may be used **only for read-only comparison and benchmarking**. They
>   are **never** training targets, imitation data, curriculum seeds for
>   solution structure, or reward-shaping references.
> * **All training signal comes from two sources only:** the system's
>   own self-generated solutions, and the exact simulator's verdict and
>   metric scores on them.
>
> This is a first-class invariant, not a preference. Each loop below has
> a "where the constraint bites" note, and the incumbent store
> (section 5) enforces it structurally: external records live in a
> separate read-only comparison column that no training code can read as
> a target.

Why this constraint is *affordable* here (and would not be for, say,
learning from scratch without a simulator): a legal machine is checkable
in milliseconds by pure-Python replay (`validate.py` today,
`harness/validate.py` once the harness lands), so the system can generate
its own supervision at whatever volume it can afford to search.

---

## 1. Framing: verifier-in-the-loop program synthesis

An Opus Magnum solution is a **discrete program**: a machine layout
(placements of arms, inputs, outputs, glyphs on a hex board) plus an
instruction tape per arm. This repo already treats it exactly that way —
the plan JSON in `harness/SPEC.md` is `placements` + `instructions`,
nothing else.

This is **not** structure prediction and **not** protein folding, despite
the alchemical set dressing. There is no noisy experimental ground truth
to regress against and no learned energy function standing in for
reality. The ground truth is a deterministic simulator we hold in our
hands:

* **Legality oracle**: the canonical validator replays a plan step by
  step (grip/rotate/drop, rigid motion, collisions, glyphs, spawns,
  goal) and returns PASS/FAIL with certainty. Today that is the repo's
  `validate.py`; the common harness promotes it to `harness/validate.py`
  as the single validator every solver arm is scored by. The semantics
  are themselves grounded in the real game via
  [omsim](https://github.com/ianh/omsim) (the Stabilized Water spec was
  byte-decoded from the game's own `P007.puzzle`; glyph semantics come
  from omsim's `sim.c`).
* **Reward source**: metrics computed on a verified plan — non-wait
  instruction count today (the harness benchmark metric), cost / cycles /
  area and the exotic metrics once `docs/metrics-survey.md` (in flight)
  defines the objective set.

Consequences of having an exact verifier in the loop:

1. **Self-supervision is free.** Any plan the system produces can be
   labeled (legal? score?) without human input. Search becomes a data
   factory.
2. **Reward hacking is structurally hard** (section 7): the reward is
   computed by the same replay that defines legality, so "fooling the
   reward" requires fooling the rules of the game themselves.
3. **The right ML analogies are the program-synthesis / game-playing
   ones**: expert iteration (Anthony, Tian & Barber 2017, "Thinking Fast
   and Slow with Deep Learning and Tree Search"), AlphaZero (Silver et
   al. 2018), AlphaDev (Mankowitz et al. 2023, sorting-network discovery
   as a single-player game with a correctness verifier), POET (Wang et
   al. 2019) and PAIRED (Dennis et al. 2020) for auto-curriculum.

## 2. What we are building on (repo state)

Grounding for everything below — what exists, and where it stops:

* **Solver arms.** clingo/ASP (`asp/core2.lp` + free-layout module
  `asp/layout.lp` + opt-in `asp/nowait.lp` symmetry breaker), Picat
  planner (`picat/*.pi`), and a SAT arm (`sat/` — PySAT with
  cadical195/glucose42/kissat, horizon-iterated feasibility; on the
  `sat-encoding` branch at time of writing). The harness README names
  minizinc and z3 as anticipated future arms.
* **The common harness (in flight, `harness` branch / PR #3).** Shared
  puzzle JSON (`name`, `board_radius`, `t_max`, `reagents`, `products`,
  `parts`), plan JSON (`placements` + `instructions`), the canonical
  validator `harness/validate.py` (pure Python, PASS/FAIL, `--verbose`
  step replay), the benchmark runner `harness/bench.py`, and an adapter
  contract: *any command that maps puzzle JSON on argv to plan JSON on
  stdout, exit 0 iff solved*. This design assumes those interfaces; if
  the harness changes before merging, the component boundaries here
  survive, the file paths move.
* **The metrics survey (in flight).** `docs/metrics-survey.md` is being
  written in parallel and does not exist on the default branch yet. It
  defines the objective set for Loop 3 (cost/cycles/area plus exotic
  community metrics). Until it lands, Loop 3 runs on the one metric the
  harness already scores: non-wait instruction count.
* **Honest solver ceiling** (from `NOTES.md`, phase-2/3 measurements):
  clingo proves optimality for the real Stabilized Water fixed layout in
  0.07 s, *finds* a 9-instruction free-layout machine in ~12 s, but the
  free-layout optimality proof is out of reach at 300 s. Horizon slack
  under `#minimize` blows up (trivial instance: 0.01 s → 0.57 s → 15 s →
  >300 s at T=10/20/40/80). A 2-arm 36-step plan needs ~130 s to a first
  model and its optimality proof is out of reach at 10 min. `NOTES.md`'s
  verdict: clingo is a **needle-finder, not an optimizer, beyond
  ~25-step single-arm plans**; the cliff sits around 2 arms / ~36 steps.
  Picat solves free-layout Stabilized Water in 2.29 s (with sound
  placement pruning) but has only been run on ≤1-arm instances. The SAT
  arm has phase-1 trivial-case results only (`sat/results-trivial.md`).
* **Modeled-fragment caveat.** All arms model a simplified OM:
  sequential arms, endpoint-only collision, bounded board (radius 2),
  bounded input pools, one product copy, no pistons/track/tape
  loops/pivot, and **no cycle-count metric** (instruction count stands
  in). Self-play inherits whatever fragment the validator defines; plans
  are only as transferable to the real game as the model is (section 7).

## 3. Loop 1 — Solver-as-teacher (expert iteration)

**Pattern**: ExIt / AlphaZero / AlphaDev. A fast learned **proposer**
suggests; an expensive exact **improver** refines; the refined result is
the training target; repeat. The net amortizes search.

**Concretely:**

1. **Propose.** A policy net takes a puzzle (reagent/product molecule
   graphs + available parts + board) and emits a machine: placements,
   then an instruction tape, autoregressively. Architecture is
   deliberately unexotic — the state is small and discrete (19 hexes at
   radius 2; ≤6 orientations; 5 actions/step); a transformer over
   tokenized placements+tape, with the puzzle as a graph- or
   set-encoded prefix, is enough to start.
2. **Improve.** Hand the proposal to exact search, warm-started by it:
   * **clingo**: fix (or softly bias, via heuristics/assumptions) the
     proposed layout and ask `asp/core2.lp` for a better tape at the
     proposed horizon, or for the same tape with instructions shaved
     off. Feasibility-at-fixed-T is the cheap query (`NOTES.md`:
     Stabilized Water T=20 feasibility 0.04 s vs `#minimize` timeout) —
     iterate T downward from the proposal's makespan and take the last
     SAT, exactly the SAT arm's horizon-iteration idiom.
   * **SAT**: unit-assume the proposed layout variables (the `sat/`
     fixed-mode mechanism does precisely this) and re-solve for shorter
     horizons.
   * **MCTS fallback** for instances past the declarative cliff: a
     rollout tree over the validator's step function, guided by the
     proposer's own policy/value heads — this is the AlphaZero
     configuration, and unlike clingo it degrades gracefully instead of
     timing out.
3. **Verify + train.** Every improved plan goes through the canonical
   validator; verified plans (and *verified-illegal* proposals, as
   negative signal for a value head) become the next round's training
   set. Target = improved plan; the proposal itself is never a target
   unless search failed to beat it.

**The solver is the bootstrap expert — with a known ceiling.** Expert
iteration only adds signal where the improver actually improves, so
Loop 1 pays off precisely in the regime the arms still reach: single-arm
plans up to ~25 steps, 2-arm up to ~36 steps with patience, free-layout
*finding* (not proving) on small boards. That is not a small regime — it
covers real chapter-1-scale puzzles — and the net's job is to make the
solver's entry point good enough that the expensive part (optimality
proofs, 2-arm interleavings) is invoked rarely and on a narrow gap.
Past the ceiling, Loop 1 hands off to MCTS-as-improver and to Loop 2's
curriculum, which grows difficulty from inside the tractable region
outward instead of jumping to puzzles no expert can touch.

**Where the data constraint bites:** the "expert" must be *our* search
stack, never a human record. Warm starts come from the proposer or from
our own incumbent store (Loop 3) — never from an external solution, which
would smuggle imitation in through the initialization. Training targets
are exclusively plans that our improver produced and our validator
passed.

## 4. Loop 2 — Self-generated curriculum via forward generation

Exact solvers and RL both need a graded exam, and OM's real campaign has
only ~80 puzzles. The game's own rules manufacture unlimited exams:

**Forward generation.** Sample random reagents, a random legal layout,
and a random (or lightly-guided) instruction tape; **run it forward**
under the validator's step function. Whatever molecule the machine emits
is, *by construction*, producible: declare it the product and you have a
guaranteed-solvable puzzle **with a known reference solution** — the very
machine that generated it — manufactured from game rules alone, at
whatever difficulty knob you set (arm count, tape length, glyph set,
board radius, pool sizes). This inverts the hard direction (synthesis)
into the easy one (execution), the same trick as generating SAT instances
from planted solutions. The generated reference solution is
self-generated by definition, so it is legal training data.

**Co-evolving generator (auto-curriculum).** Random forward generation
alone drifts toward trivial or degenerate products. So a **puzzle
generator** is trained against the current solver population,
POET-style / PAIRED-style:

* Reward the generator for puzzles at the **edge of competence** —
  solved by the current best agent but not by a weaker regret baseline
  (PAIRED's antagonist/protagonist gap), or solved only slowly/with
  slack (solve-rate band targeting, e.g. keep the proposer's success
  rate in [0.2, 0.8]).
* POET-style population: keep an archive of (puzzle, best-own-solution)
  pairs; mutate puzzles (add an atom, swap an element, tighten `t_max`,
  remove a part); admit a mutant only if it is neither trivially solved
  nor hopeless for the current population; periodically attempt
  transfer — replay archived proposers against new puzzles.
* **External puzzles as diversity seed** (allowed): the real campaign
  puzzles — already flowing into the repo via the omsim parser, e.g.
  `P007.puzzle` → `harness/puzzles/stabilized_water.json` — and any
  community puzzle files can be *imported as puzzles* and *mutated
  from*. Their human solutions, if any exist, stay outside the training
  set.

**Distribution-collapse risk — the loop's main failure mode.** A
generator rewarded only for "hard for the current agent" collapses onto
one exploit family (e.g. ever-longer linear chains, which we already
know need ≥2 arms — `NOTES.md` proves a single arm can *never* extend a
colinear chain). Countermeasures are mandatory, not optional:

* **Explicit puzzle-feature space + coverage metric**: featurize puzzles
  (atom count, bond topology class, element multiset, arm count, glyph
  set, `t_max` tightness = `t_max` / reference-solution length, board
  radius) and reward the generator for occupying empty cells of that
  grid (novelty bonus / archive distance, MAP-Elites-style binning).
* **Quota floors** per feature cell so no region of puzzle space starves.
* **Anchor set**: the fixed harness instances (`single_transport`,
  `two_atom_bond`, `stabilized_water`, and campaign imports) are
  evaluated every generation as a non-negotiable regression suite —
  curriculum drift that hurts anchor performance rolls back.

**Where the data constraint bites:** external *puzzles* may seed the
archive; external *solutions* may not seed anything. The known reference
solution attached to each generated puzzle is our own forward-run tape —
that is the only reference solution the trainer ever sees. When we
benchmark on a community puzzle that has famous human records, those
records go in the read-only comparison column (Loop 3), and the puzzle
enters the curriculum with *no* reference solution until our own loops
produce one.

## 5. Loop 3 — Self-competition on metrics

OM's depth is multi-objective: the community optimizes **cost**,
**cycles**, **area** (the in-game trio) plus exotic categories
(instruction count, width, height, rate, "trackless", overlap-free, and
Pareto combinations — the objective set will be pinned down by
`docs/metrics-survey.md`, in flight). Solving is step one; the game is
the leaderboard.

**The incumbent store.** A database keyed by `(puzzle_id, metric)` whose
value is the **system's own best verified plan** for that metric:

```
incumbent(puzzle, metric) -> {plan.json, score, verified_at, lineage}
comparison(puzzle, metric) -> {external_score}   # READ-ONLY, display only
```

* **Reward = beating your own record.** A training episode on
  (puzzle, metric) scores `max(0, incumbent_score - achieved_score)`
  (sign-adjusted per metric), with a smaller shaping term for merely
  matching feasibility on unsolved puzzles. This is self-competition in
  the AlphaZero sense — the opponent is the previous best self — adapted
  to a single-player optimization game, exactly AlphaDev's framing
  (latency-verified sorting programs, reward = measured improvement).
* **Private self-leaderboard**: rendered like the community pareto
  boards, one row per puzzle, one column per metric — but every cell is
  populated only by our own attempts, with full lineage (which loop
  produced it, which solver verified/improved it). `harness/bench.py`
  already emits per-adapter markdown tables; the leaderboard is that
  table made persistent and keyed by metric.
* **External comparison column**: known community records may be shown
  *next to* our cells, clearly marked, so humans can judge progress.
  Nothing in training reads that column: no reward references it, no
  curriculum targets it, no early stopping keys off it. Structurally:
  the trainer's data-access layer simply has no read path to
  `comparison` — the constraint is enforced by schema, not by policy.
* **Metric plumbing**: every metric is a pure function of a verified
  replay, computed by (or immediately downstream of) the canonical
  validator, so a score is only ever attached to a plan that passed. New
  metrics from the survey drop in as new columns; old incumbents get
  rescored by replay, which is cheap.

Multi-metric tension is a feature: cost-optimal and cycles-optimal
machines for the same puzzle are usually different machines, so Loop 3
multiplies every puzzle into several distinct optimization problems and
pushes the proposer to condition on the target metric (a one-hot metric
token in its input).

**Where the data constraint bites:** the incumbent store trains only on
our own records. If a community record proves a better score *exists*,
that fact may be displayed but never used — no distillation from the
external plan, no reward bonus for closing the gap to it, no curriculum
sampling weighted by it. The system must find its own way down.

## 6. Architecture

```
                         ┌────────────────────────────────────────────┐
                         │  common harness (in flight, PR #3)         │
                         │  puzzle JSON · plan JSON · adapter contract│
                         └────────────────────────────────────────────┘
                                            │ formats
        ┌───────────────┐  puzzles  ┌───────┴────────┐
        │ curriculum    │──────────▶│  proposer      │  policy/value net
        │ generator     │           │  (policy net)  │◀──────────────┐
        │ (Loop 2)      │           └───────┬────────┘               │
        └───────▲───────┘                   │ draft plans            │ train on
                │ edge-of-competence        ▼                        │ verified
                │ feedback          ┌────────────────┐               │ improved
        ┌───────┴───────┐          │ exact improver  │               │ plans
        │ forward       │          │ clingo/SAT/     │               │
        │ generator     │          │ Picat/MCTS      │               │
        │ (runs random  │          │ (Loop 1 expert) │               │
        │ machines fwd) │          └───────┬─────────┘               │
        └───────┬───────┘                  │ improved plans          │
                │ generated puzzles        ▼                         │
                │ + own ref solutions ┌──────────────────────────┐   │
                └────────────────────▶│ reward oracle            │───┘
                                      │ = canonical validator    │
                                      │   (harness/validate.py)  │
                                      │ + metric functions       │
                                      │   (docs/metrics-survey)  │
                                      └───────────┬──────────────┘
                                                  │ verified plans + scores
                                                  ▼
                                      ┌──────────────────────────┐
                                      │ incumbent store (Loop 3) │
                                      │ own records ‖ read-only  │
                                      │ external comparison col  │
                                      └──────────────────────────┘
```

Component inventory, with harness integration points:

| component | what it is | plugs into the harness as | build cost |
|---|---|---|---|
| **reward oracle** | canonical validator + metric functions | *is* `harness/validate.py`; metrics = survey objectives computed on its replay | cheap — mostly exists (in flight) |
| **exact-solver teacher** | the existing arms behind one interface, plus warm-start hooks | each arm's harness **adapter** (`adapter-cmd puzzle.json → plan.json`), extended with an optional `--hint plan.json` warm start | cheap for plain adapters (clingo reference adapter exists); moderate for warm-start hooks |
| **forward generator** | samples legal machine + tape, executes forward, emits puzzle JSON + reference plan JSON | pure consumer/producer of the two JSON formats; execution engine = the validator's step function refactored to be callable | cheap — reuses the validator core |
| **curriculum generator** | archive + mutation + edge-of-competence scoring (POET/PAIRED) | produces puzzle JSON; consumes bench results (`harness/bench.py` output) as competence signal | moderate — the ML is simple, the diversity machinery (feature grid, quotas, anchors) is the real work |
| **proposer (policy net)** | net mapping puzzle → placements + tape; also usable as MCTS prior | one more **adapter** on the bench table — the learned arm is scored exactly like clingo/Picat/SAT | expensive — model, tokenization, training infra, GPU time |
| **MCTS improver** | search over validator step function with net priors | consumes/produces plan JSON; shares the forward-execution core | moderate |
| **incumbent store + self-leaderboard** | per-(puzzle, metric) own-best DB + rendered board + read-only external column | persists `bench.py`-style results; rescoring = replay via validator | cheap |

Two deliberate properties:

* **The proposer is just another adapter.** The benchmark runner cannot
  tell the neural arm from the declarative arms; the self-leaderboard
  and the anchor regression suite score all of them identically. Any
  claim "the net beats clingo on X" is a bench table row, not a vibe.
* **One execution core.** Forward generator, MCTS, and validator must
  share a single implementation of the step semantics (the validator's),
  or the loops will train on a world subtly different from the one they
  are scored in. This argues for factoring `harness/validate.py`'s
  replay into an importable `step(state, action) -> state` before
  building anything on top of it.

## 7. Honest risks and open questions

* **Distribution collapse (Loop 2).** Covered in section 4; the
  mitigation (feature-grid coverage + quotas + anchors) is mandatory
  scope, not stretch scope. Open question: the right feature set —
  `t_max` tightness and arm count are clearly load-bearing; molecule
  topology classes need design.
* **Solver competence ceiling (Loop 1).** The declarative arms fall off
  around 2 arms / ~36 steps and free-layout optimality proofs are
  already out of reach (`NOTES.md`). Expert iteration cannot conjure
  signal past the expert. Mitigations: MCTS improver (graceful
  degradation), curriculum that grows outward from the tractable region,
  and the `NOTES.md` scaling agenda (multi-shot solving, better symmetry
  breaking, layout/tape decomposition) which directly raises the ceiling
  and thus the training signal. Open question: whether net-guided warm
  starts move the 2-arm cliff meaningfully — worth an early experiment.
* **Reward-hacking the simulator — largely mitigated, with one real
  gap.** The reward is computed by the exact validator that *defines*
  legality in our world: there is no learned reward model to fool, no
  approximate physics to exploit, and the validator is pure replay of
  declared semantics with a negative test suite
  (`harness/tests/test_validate.py`). A plan that scores well *is* a
  good plan in the modeled world, by construction — this is the
  AlphaDev/verifier advantage over learned-reward RL. The real gap is
  **model-gap hacking**: the modeled fragment differs from the game
  (endpoint-only collision vs swept arcs, sequential arms, no cycle
  metric, one product copy — `NOTES.md` lists all of them), so the
  system will happily optimize into corners that are illegal or
  meaningless in real OM. It found one already: the "pattern exists as
  subgraph" goal let both clingo and BFS cheat by building a larger
  molecule, which is why the shipped goals require exact bond degrees.
  Mitigations: treat validator-semantics bugs as reward bugs (fix +
  regression test + rescore incumbents); spot-check flagship incumbents
  against omsim itself as the fragment grows toward real semantics.
* **Compute cost.** Loop 1 is search-heavy: at ~130 s per hard solver
  call, naive expert iteration burns core-years fast. Mitigations:
  feasibility-at-fixed-T instead of optimization proofs (0.04 s vs
  timeout on Stabilized Water T=20), horizon iteration, warm starts,
  caching by canonicalized puzzle, and spending the expensive solver
  only where the proposer's value head is uncertain. Proposer training
  itself is small by modern standards (the state space at radius 2 is
  tiny); the risk is solver CPU, not GPU.
* **Cheap vs expensive, per component** — see the table in section 6.
  Summary: everything except the proposer and the curriculum
  generator's diversity machinery is glue over things this repo (or the
  in-flight harness) already has.
* **Open: metric semantics before the survey lands.** Cycles cannot be
  scored faithfully until parallel-arm execution and tape loops enter
  the model (the current fragment is explicitly sequential with no
  cycle metric). Loop 3 therefore launches on instruction count and
  area-like metrics computable in the current fragment, and grows
  columns as the model and the survey converge.

## 8. Build order (dependency-aware)

Phase 0 — **can start immediately** (no dependency on in-flight work):

1. Factor the replay semantics into an importable step function +
   forward executor. Do it against the current top-level `validate.py`;
   rebase onto `harness/validate.py` when PR #3 merges (they share
   lineage, so this is low-risk).
2. Forward generator v0: random legal machine → run forward → emit
   (puzzle, reference plan) pairs; validate every pair round-trip.
3. Puzzle featurizer + coverage grid (needed by Loop 2 and useful
   immediately for describing the generated distribution).

Phase 1 — **needs the common harness merged** (formats + validator +
bench):

4. Incumbent store + self-leaderboard over `bench.py` results, with the
   read-only external comparison column and the no-read-path rule from
   day one.
5. Solver adapters for Picat and SAT (clingo's reference adapter ships
   with the harness), plus `--hint` warm-start support per arm.
6. Proposer v0 trained purely on forward-generator reference plans
   (self-generated by definition), registered as a bench adapter.
   This is the first end-to-end test of the data-constraint plumbing.

Phase 2 — **needs Phase 1**; metrics survey merges in parallel:

7. Loop 1 proper: propose → improve (warm-started solver / MCTS) →
   verify → retrain; anchor regression suite gating each generation.
8. Loop 3 on instruction count; add metric columns as
   `docs/metrics-survey.md` lands and as the modeled fragment grows to
   support them (cycles requires parallel arms + tape loops first).

Phase 3 — **needs Phases 1–2 producing signal**:

9. Loop 2 co-evolution: generator trained against the proposer
   population with regret-style scoring, coverage quotas, POET-style
   archive with transfer attempts.
10. Ceiling-raising solver work from the `NOTES.md` agenda (multi-shot
    clingo, symmetry breaking, layout/tape decomposition) — scheduled
    here not because it must wait, but because Phases 1–2 tell us
    *which* ceiling is actually binding on training signal.

## References

* Anthony, Tian, Barber (2017). *Thinking Fast and Slow with Deep
  Learning and Tree Search* (Expert Iteration / ExIt). NeurIPS 2017.
* Silver et al. (2018). *A general reinforcement learning algorithm that
  masters chess, shogi, and Go through self-play* (AlphaZero). Science.
* Mankowitz et al. (2023). *Faster sorting algorithms discovered using
  deep reinforcement learning* (AlphaDev). Nature.
* Wang, Lehman, Clune, Stanley (2019). *POET: Paired Open-Ended
  Trailblazer — Endlessly Generating Increasingly Complex and Diverse
  Learning Environments and Their Solutions*.
* Dennis et al. (2020). *Emergent Complexity and Zero-shot Transfer via
  Unsupervised Environment Design* (PAIRED). NeurIPS 2020.
* [omsim](https://github.com/ianh/omsim) — the community-exact Opus
  Magnum simulator; provenance of this repo's puzzle specs and glyph
  semantics (see `NOTES.md`).
* Repo grounding: `NOTES.md` (clingo findings, results table, scaling
  agenda), `picat/NOTES.md` (Picat arm), `sat/results-trivial.md` (SAT
  arm, `sat-encoding` branch), `harness/SPEC.md` + `harness/README.md`
  (common harness, `harness` branch / PR #3), `docs/metrics-survey.md`
  (objective set, in flight).
