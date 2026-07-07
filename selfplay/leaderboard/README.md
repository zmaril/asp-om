# selfplay/leaderboard — Loop 3: self-competition on metrics

A private self-leaderboard: for every (puzzle, metric) pair the system
keeps its OWN best verified solution as the incumbent, and progress is
measured by beating those incumbents.

## THE INVARIANT

> **External puzzles are fine; external solutions are read-only
> comparison data ONLY.** External solutions are never a training
> target and never an incumbent. The incumbent leaderboard is populated
> exclusively by the system's own self-generated solutions, each
> verified by the canonical validator (`harness/validate.py`) at
> submission time. External leaderboard numbers may appear only in the
> clearly-labeled read-only comparison column of the rendered table
> (`driver.py --external`), which is display-only: nothing reads it
> back, and it never feeds the store or any training loop.

## Layout

```
harness/metrics.py            # reusable metric computation (importable
                              #   by every loop, hence under harness/)
harness/tests/test_metrics.py # unit tests incl. a hand-worked example
selfplay/leaderboard/
  store.py                    # incumbent store, keyed (puzzle, metric)
  driver.py                   # self-competition driver + markdown board
  tests/test_store.py         # store unit tests
  incumbents.json             # persisted store (demo run state)
  LEADERBOARD.md              # rendered board from the demo run
```

## Metrics: real vs stubbed

Computed by `harness/metrics.py` from the **canonical replay** (it
calls `validate()` with a state observer — it never re-implements the
world semantics). Definitions follow `docs/metrics-survey.md` (branch
`metrics-survey`); model-forced deviations are documented per metric in
the module docstring.

| status | metrics |
|---|---|
| **real** (leaderboard dimensions) | `instructions`, `makespan` (the sequential-arm stand-in for cycles — deliberately not named "cycles"), `area` (omsim-style used hexes, run-to-victory), `cost` (omsim price table: arm 20, bonder 10, calcifier 10; parameterizable), composites `sum` (G+C+A), `sum4` (G+C+A+I), `product_gca` (G·C·A), `product_gc`, `product_ga`, `product_ca` |
| **real but vacuous** (reported, not competed) | `trackless` (always True — track not modeled), `overlap` (always False — the validator forbids part overlap) |
| **stubbed** (`None`, not on the board) | `rate`, `area_at_infinity`, `looping` — all three need steady-state detection (detect the machine returning to an identical past state, then measure the loop, omsim-style). The current model also lacks the prerequisites that make them meaningful (tape loops, multi-copy consuming outputs). See the TODO in `harness/metrics.py`. |

Two honesty notes on the real metrics: `cost` cannot currently differ
between plans for the same puzzle (the harness requires every puzzle
part to be placed), and `area` omits rotation-sweep hexes of length-2+
arms (the shared instances only have length-1 arms, where omsim adds no
sweep hexes either).

## The `submit()` interface (what Loops 1 and 2 consume)

```python
from store import IncumbentStore

store = IncumbentStore("selfplay/leaderboard/incumbents.json")
result = store.submit(puzzle_json, plan_json, source="loop1-iter42")

result["accepted"]   # False iff the canonical validator rejected the
                     # plan (reason in result["reason"]); rejected
                     # plans change nothing.
result["metrics"]    # full metric vector of the plan
result["improved"]   # [{"metric", "old", "new", "delta"}, ...]
```

`result["improved"]` — the records this plan set or beat — **is the
self-competition reward signal**:

* Loop 1 (expert iteration, `selfplay/expert_iteration/`): use the
  improvement deltas as the reward/selection signal for which
  self-generated solutions become training data — a plan that beats an
  incumbent taught the system something; `delta = old - new > 0`
  quantifies how much. `old is None` marks a first-ever record on a
  (puzzle, metric) key (a solved-for-the-first-time event).
* Loop 2 (curriculum): puzzles whose incumbents keep improving are at
  the frontier of learnability; puzzles with long-stale incumbents are
  either mastered or too hard — both readable straight off the store
  (`store.records[puzzle][metric]["submission"]` vs
  `store.submissions`).

Ties do **not** replace an incumbent (first solution to reach a score
keeps the record). The store persists to a single JSON file after every
improving submission (atomic rename).

## How the demo candidates were seeded (full honesty)

The committed `LEADERBOARD.md` / `incumbents.json` come from one driver
run over the 3 shared harness instances:

```sh
python3 selfplay/leaderboard/driver.py \
    --adapter clingo="python3 harness/adapters/clingo/adapter.py" \
    --store selfplay/leaderboard/incumbents.json \
    --out selfplay/leaderboard/LEADERBOARD.md --fresh
```

Candidate sources, all self-generated and all validator-checked:

1. **The clingo solver adapter** (`harness/adapters/clingo/adapter.py`)
   solved all 3 instances live during the run.
2. **The hand-written reference plans** from `harness/tests/plans/`
   (part of this repo's own harness — not external leaderboard
   solutions).
3. **Deliberately wasteful perturbations** of 1–2 (wait-shifts, which
   worsen makespan, and post-completion junk rotations, which worsen
   instructions). These exist so a short demo run visibly shows
   incumbents being beaten when the better originals arrive; any
   perturbation that failed the canonical validator was discarded at
   generation time (0 discards in the committed run — all 16 submitted
   candidates passed).
4. Submission order is **worst-first** (sorted by descending
   instructions + makespan), again so the demo shows improvement
   events. The store itself is order-independent.

The committed run: 16 submissions, 16 accepted, 64 incumbent updates,
34 of which beat an existing incumbent (e.g. `single_transport`
instructions 5 → 3 when the clingo plan beat the reference).

## Next steps

* **Steady-state detection** → un-stub `rate` / `area_at_infinity` /
  `looping` (needs tape loops + multi-copy consuming outputs in the
  model; survey section 4.3 items 5–6 is the roadmap).
* **Parallel arms** → replace `makespan` with true `cycles`.
* Optional part placement / more part types → make `cost` a real
  optimization axis; track → make `trackless` non-vacuous.
* Pareto frontiers per manifold (leaderboard-style) instead of
  independent per-metric records, once multiple loops feed the store.
* Wire Loop 1 / Loop 2 candidate streams into `driver.py` (today it
  seeds from solver adapters + perturbations).
* Populate the read-only external comparison column from zlbb data for
  the real campaign puzzle (`stabilized_water` = P007) — comparison
  only, per the invariant.
