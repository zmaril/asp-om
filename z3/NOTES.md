# Z3 arm — notes in progress

Z3 (Python API, z3-solver 4.16.0) bounded-model-checking arm of the
multi-solver Opus Magnum comparison. Mirrors the clingo arm
(`asp/core.lp`, `asp/core2.lp` + the three instances) exactly, so the
numbers are apples-to-apples.

## Files

- `om_solver.py` — primary **Int encoding** (coordinates/orientation/action
  as Z3 Ints, held/bond flags as Bools). Implements both clingo semantics:
  - **v1** (`core.lp`): one arm, exactly one instruction per step from
    {rot_cw, rot_ccw, grab, drop, wait}; held atom rides the gripper; the
    bond instance's phase-1 rule "no rotating while holding a bonded atom".
  - **v2** (`core2.lp`): serialized multi-arm (≤1 non-wait action per step
    globally — Int action code 0=wait, 1+4m+a=arm m action a), rigid
    rotation of the held atom's bond-connected component about the arm base,
    arm bases block hexes, calcification glyph (element enum Int per atom,
    only materialized when a calc glyph is present).
  Instances are Python dicts mirroring the .lp instance files verbatim
  (same bases, orientations, atom positions, glyph hexes, goals, horizons
  10/16/10).
- `om_bool.py` — **pure-boolean one-hot variant** (v1 only, fixed layout):
  Bool per (atom, hex, t), one-hot orientation and action rows,
  pairwise-encoded exactly-one. Built for the requested int-vs-bool
  comparison on tests 1 and 2.
- `bench.py` — timing matrix; writes `results.md`, dumps optimal plans to
  `solutions/*.json` (layout + per-step actions + atom trajectories +
  held/bond timelines) for the later validation phase.
- `om_solver.py` CLI doubles as the plan printer:
  `python3 z3/om_solver.py bond --strategy descend-cost --json out.json`.

## Encoding design (Int variant)

Per state t=0..T: `orient[m][t]` (Int 0..5), gripper position as *defined*
aux Ints `gq/gr[m][t] = base + L*dir(orient)` (dir table via nested If —
exactly the clingo clockwise table; rot_cw maps dir d to d+1, verified),
atom coords `q/r[i][t]`, `held[m][i][t]` Bool, bond Bool per unordered atom
pair (only when the instance can bond), v2 rigid component `comp[m][i][t]`
Bool defined by an (n_atoms−1)-step unrolled closure of bonds from the held
atom. Per step t: one Int `act[t]` in 0..4·n_arms.

Transitions are equalities (`x[t+1] == If(...)`), invariants (board bounds,
one-atom-per-hex, gripper-on-board, v2 base-blocking) asserted at every
state — the same legality conditions as the clingo cores, including bond
formation firing at *every* state (even while atoms are held) and bonds
persisting forever.

`cost == Sum(If(act[t] != 0, 1, 0))` over the FULL horizon — identical to
clingo's `#minimize { 1,T : do(A,T), A != wait }` (core2's minimize counts
all actions, which is the same thing since wait is not an action there).

### Layout modes

- **fixed**: base/init_orient/glyph hexes pinned to the instance values.
  This matches the clingo instances (they fix layout entirely via facts),
  so fixed-mode numbers are the comparable ones.
- **free** (Z3 extra): base hex, initial orientation, glyph hexes are
  solver-chosen. Sanity constraints: base on board (and pairwise-distinct
  bases), glyph_bond hexes on board and adjacent to each other. Reagent
  (initial atom) positions and product/goal hexes stay fixed — they define
  the puzzle. v1 free mode keeps core.lp's "base does not block" semantics;
  v2 keeps core2's base-blocking (which in free mode also stops the solver
  from putting a base on a reagent hex). Glyphs may overlap product hexes
  (they do in test 2 by design).

### Optimality strategies

- `optimize` — z3.Optimize, minimize(cost). Matches clingo's semantics
  directly.
- `ramp-cost` — incremental Solver, assumption-guarded `cost<=k` for
  k=0,1,…; first SAT k is a proven optimum (all smaller k UNSAT).
- `descend-cost` — plain SAT first, then monotonically add
  `cost <= best-1` until UNSAT. Also a proven optimum but with only ONE
  hard UNSAT proof (at opt−1) instead of opt-many. **Fastest optimality
  strategy here** (bond, Int, fixed: 6.3s vs 16.0s Optimize vs 54.6s
  ramp-cost).
- `oneshot` — single SAT check at t_max, no optimality (baseline for the
  incremental comparison).
- `ramp-horizon` — ONE unrolled encoding to t_max, goal asserted at state h
  via assumption literals, h=1..T, stop at first SAT. Truly incremental
  (learned clauses shared across horizons).

**"Optimal" here** = minimum number of non-wait instructions over the fixed
t_max horizon, exactly clingo's objective. Note min-horizon-first (as in
`ramp-horizon`) is not in general min-instructions — we report its cost
unminimized. (In this particular fragment waits are pure no-ops — free
atoms are inert, bond formation is state-based and persistent — so min
feasible horizon equals min instruction count and `ramp-horizon`
incidentally returned the optimum on all three tests; but that's a domain
accident, not a guarantee, and would break e.g. with core2's respawn
timing.)

## Results (see results.md for the full matrix; medians of 5 where fast)

All three tests SAT at the expected optima in BOTH layout modes:
**trivial=5, bond=12, rigid=4** — matching clingo. Plans print sensibly
(test 1: grab, 3×rot, drop; test 2: park one atom on a glyph hex, fetch
the other; test 3: grab + 2×rot_cw swinging a2 through the distance-2 arc
+ drop).

Headline timings, fixed layout, to PROVEN optimum:

| test | clingo | z3 int descend-cost | z3 int Optimize | z3 bool descend-cost | z3 bool Optimize |
|---|---|---|---|---|---|
| trivial | 0.009s | 0.52s | 0.64s | 0.075s | 0.040s |
| bond    | 0.148s | 6.3s  | 16.0s | 0.57s  | 0.83s |
| rigid   | 0.004s | 0.29s | 0.41s | (v2, not in bool variant) | |

**clingo wins by 1–2 orders of magnitude on every test.** Z3's pain point
is the UNSAT/optimality-proof side; plain satisfiability at t_max is fast
(bond int oneshot 0.28s, bool 0.08s), and incremental horizon ramp-up is
fast too (trivial 0.019s, bond 0.75s, rigid 0.022s — within ~5× of clingo
without proving cost optimality).

### Int vs Bool verdict (so far)

The one-hot boolean encoding is **~10× faster than the Int encoding** at
solve time on the v1 tests — bond to proven optimum: 0.57s bool vs 6.3s
int (descend-cost); 0.83s vs 16.0s (Optimize); trivial 0.04–0.08s vs
0.5–0.6s. The Int encoding drags in linear arithmetic (every coordinate
comparison is a theory atom); the bool variant is nearly pure SAT and
grounds the hex geometry at encode time, much like clingo's grounder —
which also explains why clingo is fast here. Bool Python-side build time
is higher (~0.7s for bond vs ~0.08s int) but total time still favors bool
decisively. Lesson for the next phase: prefer the grounded/boolean style
(or a Bool-heavy hybrid) for Stabilized Water.

### Incremental vs one-shot verdict (so far)

- For pure satisfiability at t_max, one-shot is cheap (0.03–0.6s
  everywhere) but returns sloppy plans (cost 8–14 vs optima 4–12).
- Incremental horizon ramp-up (goal-at-h assumptions over one unrolled
  encoding) beats one-shot-at-t_max *and* returned optimal-cost plans on
  all three tests at a fraction of the optimality-proof cost (bond: 0.75s
  vs 6.3s). In this fragment that's guaranteed-lucky: waits are pure
  no-ops (free atoms inert, bonds persistent), so min feasible horizon =
  min instruction count. That equivalence breaks under core2's respawn
  timing, so it stays a heuristic.
- For proven optimality, incremental descend-cost (one hard UNSAT proof)
  < Optimize < ramp-cost (opt-many UNSAT proofs): bond int 6.3s / 16.0s /
  54.6s.

### Free layout findings

Free layout never beats fixed on these instances (5/12/4 again): the
geometry pins the base — e.g. in test 1, (0,0) is the *only* hex adjacent
to both the reagent (1,0) and product (−1,0) hexes, and orientation
distance 3 is unavoidable; same story in tests 2 and 3. Free-mode solve
times are ~2–4× slower than fixed for the same strategy (bond descend-cost
21.8s vs 6.3s; ramp-cost 155s vs 55s) — the extra layout freedom widens
the search without adding better solutions here.

## Gotchas discovered (semantics traps)

- clingo's `holding(X,T+1) :- do(grab,T), at(X,Q,R,T), gripper(Q,R,T)` means
  the held flag becomes true at T+1 but the atom does not move on the grab
  step; position update keys off `holding(·,T+1)` and `gripper(·,T+1)`.
  Getting the t vs t+1 indexing of held/gripper wrong silently costs an
  extra instruction (caught against the expected optima).
- Bond formation must fire at every STATE including t=0 and t_max (clingo's
  rule is over `at/4`, not gated on steps), and even while atoms are held.
- rot_ccw about base: `(q,r) -> (BQ+(q-BQ)+(r-BR), BR-(q-BQ))` — easy to
  fat-finger; verified via dir-table round trips (cw maps dir d to d+1).
- core.lp v1 does NOT make the arm base block its hex; core2 v2 does. The
  two must not be mixed or test costs shift.
- v2's objective counts all actions but has no wait action, so both cores'
  objectives are "count non-wait steps" — one shared cost definition works.

## Left for the Stabilized Water phase

- Real puzzle needs: TWO water inputs (respawning input hexes — core2's
  `spawn/nreagent` bounded-pool trick is the template, not yet in the Z3
  encoding), calcification (already implemented: element Int per atom +
  glyph_calc list + `product_types` goal hook — smoke-tested: a scratch
  v2 instance "grab water, rotate onto the calc glyph, drop" solves at
  cost 3 with the atom's final type = salt),
  bonder glyph (done), multi-arm (encoded, untested beyond n=1),
  6-products victory / looping tapes if we go full-fidelity, and emitting a
  real .solution file for omsim validation (see scout notes).
- Boolean-variant support for v2 (rigid rotation) if performance demands.
- Solution JSONs in `solutions/` are ready for the replay/validation phase.
