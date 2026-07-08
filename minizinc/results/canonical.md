# Canonical harness validation (harness/puzzles/*.json)

Adapter: `minizinc/adapter.py` (harness adapter contract; see
`harness/SPEC.md` on the default branch). Every plan below was checked with
the canonical validator `harness/validate.py` — a plan only counts if it
PASSES. Machine: 4-core container, MiniZinc 2.9.7, 300 s budget per run,
wall time includes flattening (~0.2–0.4 s). Under harness conventions
EVERYTHING is free: arm base + initial orientation, glyph hexes, input
placement, output placement + rotation, with all part footprints pairwise
disjoint.

| puzzle | t_max | engine | status | objective | wall (s) | validate.py |
|---|---|---|---|---|---|---|
| single_transport | 6 | chuffed | proved optimal | **3** | 0.2 | PASS |
| single_transport | 6 | cp-sat -p4 | proved optimal | **3** | 0.3 | PASS |
| single_transport | 6 | gecode -p4 | proved optimal | **3** | 0.3 | PASS |
| two_atom_bond | 13 | chuffed | timeout, NO solution | — | 300 | — |
| two_atom_bond | 13 | cp-sat -p4 | proved optimal | **11** | 21.1 | PASS |
| two_atom_bond | 13 | gecode -p4 | timeout, NO solution | — | 300 | — |
| stabilized_water | 14 | chuffed | timeout, NO solution | — | 300 | — |
| stabilized_water | 14 | cp-sat -p4 | proved optimal | **12** | 124.4 | PASS |
| stabilized_water | 14 | gecode -p4 | timeout, NO solution | — | 300 | — |

- 3/3 canonical puzzles solved and validated; all three optima **proved**
  (by 4-thread CP-SAT). single_transport 3, two_atom_bond 11,
  stabilized_water 12 — the latter two beat the hand-written reference
  plans (12 and 13) and match the clingo adapter's incumbents from PR #3,
  which were not proven optimal there.
- Only CP-SAT solves all three: Chuffed and Gecode return NOTHING on the
  fully-free two_atom_bond / stabilized_water within 300 s (their default
  searches collapse when input/output placement joins the decision space —
  note Chuffed solved the *phase-3* free-layout variants of comparable size
  easily; the harness conventions, not the size, are what broke it).
- The adapter's default `--solver auto` is therefore a portfolio: Chuffed
  gets a short first slice (wins easy instances at ~0.2 s), then
  `cp-sat -p4` gets the rest of the budget.
- Validated plans: `results/plans/*.plan.json`. Reproduce any row with
  `python3 minizinc/adapter.py --solver <engine> harness/puzzles/<p>.json`
  and `python3 harness/validate.py harness/puzzles/<p>.json <plan>`.

`harness/bench.py --adapter minizinc="python3 minizinc/adapter.py"`
(adapter in auto mode) output:

| puzzle | solver | solved | valid plan | wall time (s) | plan length |
|---|---|---|---|---|---|
| single_transport | minizinc | yes | yes | 0.32 | 3 |
| stabilized_water | minizinc | yes | yes | 181.09 | 12 |
| two_atom_bond | minizinc | yes | yes | 80.02 | 11 |

(auto-mode walls include the wasted 60 s Chuffed slice on the two hard
puzzles; `--solver cp-sat` directly is faster, see the table above.)
