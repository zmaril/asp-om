# harness — common infrastructure for the multi-solver Opus Magnum experiment

Every solver arm (clingo, picat, minizinc, z3, sat, ...) plugs into the
same three things:

1. **Shared puzzle instances** (`harness/puzzles/*.json`) in a common
   puzzle JSON format;
2. **A common plan JSON format** that your solver's output gets converted
   into by a thin adapter;
3. **One canonical validator** (`harness/validate.py`) and **one
   benchmark runner** (`harness/bench.py`) that score every arm the same
   way.

The formats and the world semantics (coordinates, rotation convention,
action semantics, glyph/spawn timing, goal) are specified **precisely**
in [`SPEC.md`](SPEC.md) — including every reconciliation decision made
where the existing clingo and picat arms disagreed. The validator is the
executable form of that spec.

## Layout

```
harness/
  SPEC.md               # normative formats + semantics
  puzzles/              # shared test instances (puzzle JSON)
    single_transport.json    # (a) move one salt atom input -> output
    two_atom_bond.json       # (b) bond two salts, deliver the dimer
    stabilized_water.json    # (c) the real campaign puzzle P007
  validate.py           # canonical validator (pure Python, no deps)
  bench.py              # benchmark runner (markdown table)
  adapters/
    clingo/adapter.py   # reference adapter wrapping asp/core2.lp+layout.lp
  tests/
    test_validate.py    # positive + negative validator tests
    plans/*.json        # hand-written reference plans (format examples)
```

## The adapter contract

An adapter is any command that turns a puzzle JSON into a plan JSON:

```
<adapter-cmd> <puzzle.json>
```

* **stdout**: the plan JSON (and nothing else). An optional `--out FILE`
  flag is nice to have but the runner only reads stdout.
* **exit code**: `0` = solved (stdout has a plan), nonzero = no solution
  produced (UNSAT, timeout, unsupported feature, crash).
* **stderr**: yours — logs/diagnostics; the runner passes it through.
* **wall time** is measured by the runner around the whole invocation;
  manage your own internal time limits (the reference adapter reads
  `HARNESS_CLINGO_TIME_LIMIT`, default 30 s, and returns the best plan
  found so far when it expires).
* The plan must conform to `SPEC.md` section 4: a `placements` list
  (layout is part of the solution — arms, inputs, outputs, glyphs) and an
  `instructions` list (`{"t": .., "arm": .., "action":
  grab|drop|rot_cw|rot_ccw|wait}`, at most one instruction per timestep,
  missing timesteps are implicit waits).
* **Plan length** (the benchmark metric) = number of non-`wait`
  instructions. Placements are free.

Puzzle JSON shape (see `SPEC.md` section 3 for the normative version):
`name`, `board_radius`, `t_max` (horizon), `reagents` (molecules:
`atoms` = element + relative hex, `bonds` = index pairs, `pool`),
`products` (molecules), `parts` (available machine parts: `arm` with
`length`, `calcifier`, `bonder`). Any reagent/product/part may carry an
optional pinned `position`/`rotation`; otherwise placement is the
solver's job.

## Commands

```sh
# validate one plan against one puzzle (PASS/FAIL, exit 0/1)
python3 harness/validate.py harness/puzzles/stabilized_water.json my_plan.json
python3 harness/validate.py <puzzle> <plan> --verbose   # step-by-step replay

# run the validator test suite (positive + negative)
python3 harness/tests/test_validate.py        # or: python3 -m pytest harness/tests/

# run the full benchmark: all instances x all adapters, canonical
# validation of every plan, markdown comparison table
python3 harness/bench.py \
    --adapter clingo="python3 harness/adapters/clingo/adapter.py" \
    --out bench.md

# add your arm to the same table
python3 harness/bench.py \
    --adapter clingo="python3 harness/adapters/clingo/adapter.py" \
    --adapter picat="python3 harness/adapters/picat/adapter.py" \
    --keep-plans /tmp/plans
```

Dependencies: the validator, tests and bench runner are **pure Python 3**
(stdlib only). Only the clingo reference adapter needs `pip install
clingo`.

## The shared instances

| instance | reagents | product | parts | t_max |
|---|---|---|---|---|
| `single_transport` | 1 salt (pool 1) | 1 salt atom | arm | 6 |
| `two_atom_bond` | 2 x salt (pool 1) | salt–salt dimer | arm, bonder | 13 |
| `stabilized_water` | water (pool 2) | salt–water dimer | arm, calcifier, bonder | 14 |

`stabilized_water` is the real chapter-1 campaign puzzle: its
reagent/product molecules were byte-decoded from the game's own
`P007.puzzle` file via [omsim](https://github.com/ianh/omsim)'s parser by
the clingo/picat arms (provenance in the top-level `NOTES.md` and
`picat/NOTES.md`); the modeling simplifications are listed in `SPEC.md`
sections 5–6 and in the instance's `description` field.

All three ship with **free layout**: the solver chooses where the arm,
inputs, output and glyphs go, then programs the arm. Hand-written
reference plans for all three live in `harness/tests/plans/` and double
as format examples.

## The reference adapter (clingo)

`harness/adapters/clingo/adapter.py` wraps the existing, unmodified
encodings on master (`asp/core2.lp` + `asp/layout.lp`): it generates the
instance facts and exact-molecule goal rules from the puzzle JSON (adding
a placeable *output part*, which the original clingo instances lacked),
solves under core2's instruction-count `#minimize` with a time limit, and
converts the best answer set's layout atoms + `do/3` tape into plan JSON.
It is both the proof that the harness works end to end and the template
for writing your arm's adapter.
