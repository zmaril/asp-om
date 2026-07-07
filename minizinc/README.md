# MiniZinc encoding of Opus Magnum bounded-horizon puzzle solving

A constraint-programming counterpart to the clingo encoding in `asp/`,
using the same conventions so results are directly comparable:
axial (Q,R) hex grid with `|Q|,|R|,|Q+R| <= radius`, clockwise directions
0..5 with dir 0 = (1,0), cw rotation `(Q,R) -> (-R, Q+R)`, actions
{rot_cw, rot_ccw, grab, drop, wait}, rigid molecule rotation, bonding and
calcification glyphs (the `asp/core2.lp` semantics), and the same
objective: minimize the number of actions within the horizon.

## Files

- `om.mzn` — core model. Machine LAYOUT IS PART OF THE DECISION: arm base
  hexes and glyph hexes are solver-chosen anywhere on the board.
- `om_fixed.mzn` — includes `om.mzn` and pins the layout to the `given_*`
  parameters; this variant matches the clingo instances exactly.
- `instances/*.dzn` — puzzle instances (t1–t3 mirror `asp/*.lp`; t4 adds a
  calcification test cross-checked against `asp/core2.lp`).
- `trace.py` — decodes `--output-mode json` solutions into a per-timestep
  trace (run.py style) and, with `--check`, independently re-simulates the
  plan and verifies legality and (with `--dzn`) the goal.
- `bench.py` — benchmark driver; `results/benchmarks.csv` + `.md` hold the
  phase-3 engine matrix, `results/frontier.csv` the tractability probes.

## Usage

```sh
minizinc --solver gecode  minizinc/om_fixed.mzn minizinc/instances/t1_transport.dzn
minizinc --solver chuffed minizinc/om.mzn       minizinc/instances/t2_bond.dzn

# decode + verify a plan:
minizinc --solver cp-sat --output-mode json \
    minizinc/om_fixed.mzn minizinc/instances/t2_bond.dzn \
  | python3 minizinc/trace.py --check --dzn minizinc/instances/t2_bond.dzn
```

## Verified optima (all of gecode / chuffed / cp-sat agree)

| instance | fixed layout (= clingo) | free layout |
|---|---|---|
| t1_transport (T=10) | 5 | 5 |
| t2_bond (T=16)      | 12 | 5 |
| t3_rigid (T=10)     | 4 | 4 |
| t4_calc (T=10)      | 5 | 5 |
| stabilized_water (T=12) | 9 | 9 |
| sw_1input (T=12)    | 11 | 11 |

`stabilized_water` is the real campaign puzzle P007 (one product copy):
2 respawning water inputs (pool 2 each), calcifier + bonder, product =
bonded salt–water pair. `sw_1input` is the single-input variant that
`asp/core2.lp` can also express; clingo agrees on its optimum (11), which
cross-validates the respawn semantics. Reagent respawning follows core2:
the next pool atom appears as soon as the input hex clears.

Known deviations from `asp/core.lp` (v1) and other notes are documented in
the phase-2/phase-3 handoff notes (scratchpad) and in comments in `om.mzn`.
