# Picat: canonical harness validation (harness/puzzles/*.json)

Adapter: `picat/adapter.py` (harness adapter contract; `harness/SPEC.md`
on the default branch).  It generates a self-contained Picat planner
program per puzzle -- the v2 engine from `picat/stabilized_water_free.pi`
(state term, `mk_next` spawn/calcify/bond rules, rigid rotation, free
layout as a setup phase of cost-1 placement actions), generalized from
the hard-coded instances to generated instance facts -- and solves it
with the planner module's `best_plan` (iterative deepening), so every
reported optimum is **proved optimal within the puzzle's horizon**, not
just an incumbent.

Every plan below was checked with the canonical validator
`harness/validate.py` -- a plan only counts if it PASSES.  Machine:
4-core cloud container (15 GB RAM), Picat 3.9#10 (Linux x86_64 binary
from picat-lang.org, per `picat/NOTES.md`), 300 s budget per run; wall
times are approximate (single runs on a shared container; repeat runs
varied by < 5%).  Under harness conventions everything is free layout:
the solver chooses the arm base + initial orientation, the input, glyph
and output placements, with all part footprints pairwise disjoint.

## Canonical instances (free layout -- the apples-to-apples table)

| puzzle | t_max | mode | status | optimum (plan length) | wall (s) | validate.py |
|---|---|---|---|---|---|---|
| single_transport | 6 | free | **proved optimal** | **3** | 0.06 | PASS |
| two_atom_bond | 13 | free | **proved optimal** | **11** | 2.8 | PASS |
| stabilized_water | 14 | free | **proved optimal** | **12** | 62.6 | PASS |

- 3/3 canonical puzzles solved, validated, and **proved optimal** --
  3 / 11 / 12 match the canonical optima proved independently by the SAT
  arm and MiniZinc/CP-SAT (`docs/solver-comparison.md` §2.1).
- "Proved" = `best_plan`'s iterative deepening exhausts every shorter
  cost bound over all (symmetry-reduced, soundly pruned) layouts before
  returning; there is no incumbent-at-timeout mode (a timeout returns
  no plan at all).
- Validated plans: `results/plans/*.plan.json`.  Reproduce any row with
  `python3 picat/adapter.py harness/puzzles/<p>.json` and
  `python3 harness/validate.py harness/puzzles/<p>.json <plan>`, or run
  the whole table via
  `python3 harness/bench.py --adapter picat="python3 picat/adapter.py"`
  (bench walls measured 0.11 / 2.79 / 62.60 s, adapter startup
  included).

## Fixed layout (pinned; non-canonical extra)

The canonical instances ship free-layout only (as run by every other
arm), so there is no canonical "fixed" row.  To exercise the adapter's
pin support, `results/stabilized_water_pinned.puzzle.json` pins the
merged arm's hand layout from `picat/stabilized_water.pi` (arm base
(0,0) dir 0; input (1,0); calcifier (0,1); bonder (-1,1)-(-1,0); output
salt@(0,-1)--water@(1,-1)) on the otherwise-identical canonical puzzle:

| puzzle | t_max | mode | status | optimum (plan length) | wall (s) | validate.py |
|---|---|---|---|---|---|---|
| stabilized_water (pinned) | 14 | fixed | **proved optimal** | **13** | 0.05 | PASS |

That reproduces the merged Picat arm's pre-harness fixed-layout optimum
of 13 exactly (`picat/NOTES.md` results table -- its convention already
matched the harness footprint rule), and the emitted plan also PASSES
validation against the canonical free puzzle
(`results/plans/stabilized_water.pinned.plan.json`).

## Methodology / caveats

- **Glyph-timing shim**: the engine keeps the merged Picat model's
  timing (calcify/spawn/bond applied at post-action positions) rather
  than the harness's read-at-t/retype-at-t+1 calcifier rule
  (`harness/SPEC.md`, reconciliation decision 2).  The two agree on
  every observation off the calcifier hex (see the soundness note in
  `picat/adapter.py`'s docstring), and every emitted plan is replayed by
  the canonical validator anyway -- the numbers above are
  validator-checked facts, not model claims.
- **Search reductions**: an exact 6-fold rotational-symmetry quotient on
  the first arm's base, plus sound distance prunes (input hexes on an
  arm's gripper ring; glyph/output hexes within reach of the held
  component; both bonder hexes on the gripper ring when no product atom
  has bond degree > 1), gated on instance structure and disabled by
  `--noprune`.  Cross-checks: `--noprune` reproduces optimum 3 on
  single_transport (0.2 s); on two_atom_bond the unpruned search exceeds
  the 300 s budget (free layout is multiplicative -- the same cliff
  `picat/NOTES.md` measured pre-harness), while the pruned optima 11/12
  match the SAT/CP-SAT-proved canonical optima exactly.
- Limitations shared with the clingo reference adapter: single-atom
  reagents only; elements air/earth/fire/water/salt.
