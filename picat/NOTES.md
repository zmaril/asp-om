# Picat experiment notes (phase 1)

Parallel experiment to the clingo/ASP encoding in `asp/`: can Picat's
`planner` module solve the same trivial Opus Magnum fragments?

## Setup

- Picat 3.9#10, Linux x86_64 binary from
  <https://picat-lang.org/download/picat39_10_linux64.tar.gz>
  (see <https://picat-lang.org/download.html> for the current version).
- No installation step: untar and run the `Picat/picat` binary.
- Run a program: `picat picat/case1_transport.pi`

## World model (mirrors `asp/core.lp`)

- Axial hex grid `(Q,R)`, radius 2; one arm, base at origin, length 1,
  orientation 0..5 with the same clockwise direction indexing as the
  clingo `dir/3` facts.
- Actions `rot_cw`, `rot_ccw`, `grab`, `drop`. No `wait`: clingo fills a
  fixed `t_max`-step tape and minimizes non-wait instructions; the planner
  just returns an action sequence, so plan length == clingo's optimization
  cost.
- State is a ground term `{Dir, Held, Atoms}` (case 2 adds a `Bonds` list),
  kept in canonical (sorted) form so the planner's tabling detects
  revisited states.
- `best_plan(S0, Limit, Plan, Cost)` gives length-optimal plans; `Limit`
  plays the role of clingo's `t_max`.

## Status / results

Both trivial cases solve instantly and match the clingo optima:

| case | file | plan length | clingo optimum | Picat CPU time | wall time |
|------|------|-------------|----------------|----------------|-----------|
| 1: transport one salt atom (1,0) -> (-1,0) | `case1_transport.pi` | 5 | 5 | 0.000 s | ~0.02 s |
| 2: bond two atoms on glyph (-1,0)/(0,-1)   | `case2_bond.pi`      | 12 | 12 | 0.001 s | ~0.02 s |

Case 1 plan: `grab, rot_cw x3, drop`.
Case 2 plan: `grab, rot_ccw x3, drop, rot_ccw x2, grab, rot_ccw x3, drop`
(routes a2 counterclockwise past (1,-1) because the clockwise path through
(-1,0) is blocked by the already-delivered a1).

## Picat gotchas learned

- Pattern-matching rule heads (`=>`/`?=>`) never bind variables of the
  *call*: `action(S, S1, grab, 1) => ...` silently never matches when the
  planner calls it with unbound Action/Cost. Assign them in the body.
- Structured states must stay canonical (sort atom/bond lists) or tabling
  treats permutations as distinct states.

## Later phases (parity with `asp/core2.lp`)

- Rigid molecule rotation (axial rotation about the base:
  cw `(Q,R) -> (-R,Q+R)`), multiple arms, calcification, respawning
  reagents — the clingo v2 encoding (`asp/core2.lp`, `asp/rigid_instance.lp`)
  is the reference.
- A CP/SAT formulation (`import cp` / `import sat`) over a fixed horizon
  with decision array `Do[1..TMax]` would be the direct analogue of the
  clingo encoding; try it if planner search degrades on bigger instances.
