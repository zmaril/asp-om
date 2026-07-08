# Loop 1: Expert iteration (solver-as-teacher)

Minimal viable expert-iteration loop (AlphaZero/AlphaDev style) for the
Opus Magnum harness: a cheap **proposer** suggests machine layouts, an
exact **solver-teacher** (the clingo adapter) completes them into valid
plans or proves them infeasible, the **canonical validator** is the
reward oracle, and the proposer **learns** from the loop's own verified
records.

## THE INVARIANT: no external solutions, ever

> External **puzzles** are fine as inputs. The system may **never**
> train on or imitate external **solutions**. All training signal comes
> from the system's OWN self-generated solutions plus the exact
> simulator's (validator's) reward. External solutions are read-only
> comparison only.

Concretely, in this loop: every record in `runs/*/records.jsonl` is a
plan produced by *this loop's* proposer + solver-teacher and verified by
`harness/validate.py` before being recorded (`loop.py` re-checks this
with a direct `validate()` call, on top of the leaderboard store's own
validation). The learned proposer's two update signals are (a) REINFORCE
on the validator-derived reward of its own proposals and (b) imitation
of the *teacher's* layouts — and the teacher is our own solver, so both
signals are self-generated.

## Architecture

```
                 puzzle JSON (harness/puzzles/*.json)
                          |
                          v
   +------------------ proposer.py -------------------+
   | RandomProposer  | LearnedProposer (tabular       |
   | (baseline)      |  softmax policy, REINFORCE +   |
   |                 |  imitation, hand-rolled)       |
   +---------------------------------------------------+
                          |  proposal = partial plan:
                          |  full placements, EMPTY tape
                          v
   +------------------- teacher.py --------------------+
   | pin proposal's placements into a puzzle copy      |
   |   -> clingo adapter (harness/adapters/clingo)     |
   |      solves ONLY the instruction tape  [timeboxed]|
   | UNSAT/timeout -> relax: cached from-scratch solve |
   +---------------------------------------------------+
                          |  complete plan (or nothing)
                          v
        harness/validate.py  (canonical reward oracle)
                          |
                          v
        selfplay/leaderboard/store.py  IncumbentStore.submit()
          -> metrics (harness/metrics.py) + improvement deltas
                          |
                          v
        records.jsonl  (verified self-generated dataset)
                          |
                          v
        LearnedProposer.update() / .imitate()   (close the loop)
```

## Teacher coupling: what is real

The seeding is **real, not a scaffold**: the proposal's placements are
written into a copy of the puzzle as `position`/`rotation` **pins**
(SPEC.md section 3), which the clingo adapter turns into layout facts.
The solver's layout choice rules collapse to the proposed layout, so the
teacher genuinely *completes the proposal* — any returned plan uses
exactly the proposed machine, and an UNSAT verdict is a proof that the
proposed layout admits no valid program within `t_max`.

Relaxation: on UNSAT/timeout the teacher falls back to one cached
from-scratch (free-layout) solve of the original puzzle. That plan is
the *reference* — the proposal scored 0, and the reference layout is
what the learned proposer imitates.

## What is real vs stubbed

Real:
- Layout proposing over the full legal candidate space (footprint
  disjointness and board bounds enforced by construction).
- Teacher seeding via pins (above); all solver calls subprocess-timeboxed.
- Canonical validation of every recorded plan; metrics + improvement
  rewards via the Loop 3 leaderboard interface (see below).
- The learning: tabular softmax policy, exact `adv * grad log pi`
  updates (REINFORCE with a per-puzzle running-mean baseline) plus
  cross-entropy imitation of teacher layouts. No torch (not installed
  here), no fake learning — weights, gradients and the replayable
  masking context are all in `proposer.py`.

Stubbed / deferred (documented, honest):
- **Proposals carry an empty instruction tape.** "Partial tape" in the
  Loop 1 design means the proposer should eventually also suggest a
  tape prefix; the pin mechanism cannot seed instructions, so tape
  seeding needs adapter support for `do/3` seed facts (next steps).
- The learned policy is per-puzzle tabular — no features, no
  generalization across puzzles.
- `rate`/`area_at_infinity`/`looping` metrics are stubbed upstream in
  `harness/metrics.py` (see its docstring).

## Loop 3 integration

This branch **merged `selfplay-leaderboard`** (rather than copying
files): `harness/metrics.py` computes the metric vector from the
canonical replay, and `selfplay/leaderboard/store.py`'s
`IncumbentStore.submit()` provides validation + metrics + improvement
deltas. Each run uses its **own fresh store**
(`runs/<name>/incumbents.json`); the shared leaderboard in
`selfplay/leaderboard/` is not touched by this loop. Improvement deltas
feed the reward as a `0.1 * #metrics-improved` bonus on top of the
validator-derived term.

## Reward

- Infeasible proposal (teacher UNSAT/timeout on the pinned puzzle): `0`.
- Feasible: `1 + (ref_len - plan_len)/ref_len + 0.1 * #improved`,
  where `ref_len` is the from-scratch reference plan's non-wait
  instruction count and `plan_len` the seeded completion's. Shorter-
  than-reference layouts earn extra reward; longer ones earn less.

## Teacher competence ceiling (observed on this machine)

- `single_transport` (1 arm, t_max=6): free-layout solve **~0.1s**.
- `two_atom_bond` (1 arm + 1 bonder, t_max=13): free-layout solve needs
  the **full 60s budget** to find (not prove optimal) an 11-instruction
  plan. This is the wall the project has seen before (~2 arms / ~36
  steps is hopeless for free-layout clingo).
- **Pinned-layout (seeded) solves stay ~0.1–0.3s on both puzzles, UNSAT
  included.** Seeding is what makes this loop fast, and is also the
  strategic point of Loop 1: a good proposer moves work from the
  solver's exponential layout search into a learned policy.

Keep loop puzzles trivial; the driver skips any puzzle the teacher
cannot solve from scratch within `--relaxed-limit`.

## How to run

Requires the `clingo` Python module (`pip install clingo`). From the
repo root:

```sh
python3 selfplay/expert_iteration/loop.py \
    --puzzles harness/puzzles/single_transport.json \
              harness/puzzles/two_atom_bond.json \
    --iterations 80 --proposer learned --seed 0 --run-name demo
```

Artifacts land in `selfplay/expert_iteration/runs/<run-name>/`:
`records.jsonl` (verified dataset), `curve.csv` (learning curve),
`run.log`, `incumbents.json`, `weights.json`. Use `--proposer random`
for the no-learning control.

## Committed demo results

Both runs committed under `runs/` (80 iterations/puzzle, seed 0;
matplotlib absent, so the curve is CSV + log):

| run | puzzle | proposal validity, 1st half → 2nd half | mean reward |
|---|---|---|---|
| `demo` (learned) | single_transport | **0.70 → 0.93** | 0.72 → 0.93 |
| `demo` (learned) | two_atom_bond    | **0.50 → 0.93** | 0.52 → 0.93 |
| `random-control` | single_transport | 0.05 → 0.08 | 0.00 → 0.05 |
| `random-control` | two_atom_bond    | 0.00 → 0.00 | 0.00 → 0.00 |

All 162+162 recorded solutions in the two runs re-pass
`harness/validate.py` (checked independently after the runs).

## Next steps

1. Tape-prefix proposals: teach the adapter to accept `do/3` seed facts
   so proposals can constrain the program, not just the layout.
2. Feature-based policy (offsets relative to the arm, part adjacency)
   for cross-puzzle generalization; torch optional.
3. Feed Loop 2 (curriculum/generator) puzzles into this loop instead of
   the two fixed trivial instances.
4. Use the Z3 arm (branch `z3-encoding`) as a second teacher and keep
   whichever completion is better.
5. Batch updates from `records.jsonl` (currently online, one record at
   a time) and hold-out evaluation of the policy.
