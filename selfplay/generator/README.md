# selfplay/generator — forward-generation of solvable (puzzle, plan) pairs

The bootstrap data engine for the self-play project: it **manufactures
guaranteed-solvable, self-labeled (puzzle, solution) pairs from the game
rules alone**, with zero external solution data.

## The idea

Instead of taking a puzzle and solving it *backward*, run a random machine
*forward*:

1. sample random reagent inputs on the bounded hex board;
2. place a random **legal** machine around them — arms, glyph of
   calcification, glyph(s) of bonding, subject to the part non-overlap
   rule (the same simplified model as `asp/core2.lp` / `harness/SPEC.md`);
3. build a random **legal** instruction tape step by step, where the
   legality of every candidate action is decided by replaying the prefix
   with the repo's proven simulator;
4. whatever molecule the machine ends up producing **is** the puzzle's
   product.

By construction, every emitted puzzle is solvable — and it ships with the
exact machine + tape that produced it, as a known reference solution.

### The no-external-solutions guarantee

The hard project rule is: external *puzzles* are fine, but we never train
on or imitate external *solutions*. This generator honors that trivially —
its only inputs are the game rules (the simulator) and a random seed.
Every puzzle, every product molecule and every reference plan is
self-generated; no game solutions, community solves, or omsim replays are
read anywhere.

## Formats: the common harness formats

Pairs are emitted in the **common harness formats** (`harness/SPEC.md`):

* `BATCH/puzzles/NAME.json` — puzzle JSON (`name`, `board_radius`,
  `t_max`, `reagents`, `products`, `parts`). Nothing is pinned: layout is
  the solver's job (the reference plan proves a layout exists).
* `BATCH/plans/NAME.json` — plan JSON (`placements` incl. the output
  part, `instructions`), the generating machine itself as the reference
  solution.

Every pair is validated through the **canonical validator**
(`harness/validate.py`) before it is written, and a batch can be
re-validated from disk at any time:

```sh
python3 selfplay/generator/validate_batch.py selfplay/generator/sample_batch
# -> 100/100 pairs PASS (canonical harness validator)
```

A validation failure is never skipped: pairs are valid *by construction*,
so any failure is a real bug in the generator or the model and the run
aborts.

## Usage

```sh
# the shipped sample batch (100 pairs, deterministic):
python3 selfplay/generator/generator.py --count 100 --seed 7 \
    --arms 1:3 --bonders 1:3 --inputs 1:4 --tape 12:30 --pool 3 \
    --out selfplay/generator/sample_batch

# small & easy:
python3 selfplay/generator/generator.py --count 20 --seed 1 \
    --arms 1 --arm-len 1 --bonders 1 --inputs 1:2 --tape 10:16 --out /tmp/easy
```

Range-valued knobs accept `A` or `A:B` (sampled uniformly per machine).

| knob | default | meaning |
|---|---|---|
| `--count` | 100 | pairs to emit (after rejection + dedup) |
| `--seed` | 0 | RNG seed; the whole run is deterministic |
| `--out` | `batch/` | output directory (`puzzles/`, `plans/`, reports) |
| `--radius` | 2 | board radius (difficulty: board size) |
| `--arms` | 1:2 | number of arms |
| `--arm-len` | 2 | max arm length |
| `--tape` | 12:26 | sampled tape length (timesteps) |
| `--inputs` | 1:3 | number of reagent inputs |
| `--calcifiers` | 0:1 | number of calcification glyphs |
| `--bonders` | 1:2 | number of bonding glyphs |
| `--pool` | 2 | max atoms per reagent input |
| `--atom-types` | all five | reagent element pool (`air,earth,fire,water,salt`) |
| `--max-attempts` | 200×count | give up threshold |

Small radius + 1 short arm + short tape + 1 bonder ⇒ easy puzzles; more
arms/glyphs/inputs + longer tapes ⇒ larger products and longer reference
plans. `t_max` of each emitted puzzle is trimmed to its reference plan's
completion time, so horizons are tight.

## How it works (and what it reuses)

* **Forward engine** — `validate.py`'s `replay_v2` (the repo's proven
  pure-Python replay of the core2 semantics), imported verbatim from the
  repo root; the physics is never reimplemented. `harness/SPEC.md`
  reconciliation decision 2 adopted exactly this timing, and with the
  single-atom reagents generated here the two simulators agree —
  guaranteed per-pair by the harness validation step.
* **Legal-by-construction tapes** — at each timestep every candidate
  `(arm, action)` is checked by replaying the plan prefix; illegal
  candidates are discarded. Among legal ones, selection is a weighted
  draw: priors (grab-happy, rotation momentum so multi-step detours
  happen) × a softmax over a *potential* read off the replayed state
  (bonds formed, atoms staged on bonder hexes, elementals on calcifiers,
  held atoms pulled toward bonders, empty grippers pulled toward loose
  atoms, finished molecules pushed off part hexes so the output part is
  placeable). The guidance only biases sampling — it can never produce an
  illegal plan, and correctness never depends on it.
* **Product extraction** — the whole trajectory is scanned (the harness
  goal is "complete at some `t <= t_max`"; completion does not consume
  atoms): any moment a molecule rests unheld on part-free hexes is a
  valid delivery. The largest such molecule wins, ties to the earliest
  time, and the tape is trimmed to that completion time.
* **Rejection rules** (degenerate outputs): empty products; molecules
  still held or resting on part footprints (no legal output placement);
  single atoms whose element is directly available as a reagent (product
  identical to a reagent — also covers no-op machines); empty tapes.
  Duplicates are deduped on (radius, reagent multiset, product canonical
  form), where canonicalization is up to hex rotation + translation (no
  reflection — arms cannot mirror a molecule).

Files:

* `generator.py` — sampling, guidance, rejection, dedup, emission, stats;
* `model.py` — machine/molecule data model, canonicalization, harness
  JSON emission, `replay_v2` bridge;
* `validate_batch.py` — canonical re-validation of a saved batch;
* `sample_batch/` — the shipped verified batch + diversity report.

## The shipped sample batch

`sample_batch/` holds 100 pairs (seed 7, knobs in the command above),
**all 100 validated by `harness/validate.py`**. From
`sample_batch/diversity_report.json`:

* attempts 7,430 → yield 1.35% (rejections: 2,497 layout, 4,775
  no-product, 58 duplicate);
* product sizes: 27× 1 atom, 72× 2 atoms, 1× 3 atoms (17 unique products
  up to rotation+translation);
* product atoms: salt 62, fire 32, air 32, earth 26, water 22; reagent
  atoms: air 62, fire 61, earth 60, water 58, salt 38;
* machines: 15× 1-arm, 41× 2-arm, 44× 3-arm; 143 bonders + 47 calcifiers
  across the batch;
* reference plan lengths 6–28 non-wait instructions.

The report exists precisely to make **distribution collapse visible**:
at these settings the generator is dimer-heavy and salt-heavy (bonding
staging plus calcification both funnel there). Knobs to push it: more
bonders + longer tapes for larger molecules, `--calcifiers 0` for
elemental-only products, `--atom-types` to control the element mix.

## How this feeds the self-play loops

* **Loop 1 (solve)**: the emitted puzzles are ordinary harness puzzles —
  point any solver arm at them, e.g.
  `python3 harness/adapters/clingo/adapter.py sample_batch/puzzles/fg_s7_0001.json`,
  or benchmark whole arms against a generated batch with
  `harness/bench.py`. Every instance is guaranteed SAT within its
  `t_max`, so solver failures are solver findings, not data noise.
* **Loop 2 (this generator)**: mints unlimited fresh, labeled,
  difficulty-controlled training/eval instances from nothing but the
  rules + a seed.
* **Loop 3 (learn)**: each pair is a supervised (puzzle → plan) example
  whose label is self-generated, so imitation/policy bootstrapping on
  them never touches external solutions. Reference plans are random-walk
  artifacts, not optima — they upper-bound plan length, and a learner or
  solver beating them is genuine improvement signal. Curriculum =
  sweeping the difficulty knobs.

## Known limitations (v0)

* Single-atom reagents only (the harness format allows molecule reagents;
  the wrapped `replay_v2` spawn model does not — same limitation as the
  clingo adapter).
* Products beyond 3 atoms are rare: the myopic guided walk seldom chains
  bonds. Fixes worth trying: multi-step lookahead, subgoal scripts
  (deliver→stage→bond→carry), or MCTS-style tape search — all safe,
  since legality and validation never depend on the guidance.
* One product per puzzle; `pool` is small; all model simplifications of
  `harness/SPEC.md` sections 5–6 are inherited.
