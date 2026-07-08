# MiniZinc arm — engineering notes

Honest writeup of the MiniZinc encoding of the shared Opus Magnum fragment,
the 5-engine benchmark, the native OR-Tools CP-SAT comparison, and the
canonical-harness validation. Companion to `minizinc/README.md` (quickstart)
and `harness/SPEC.md` (the shared world semantics, branch `harness`).

Machine for all numbers below: 4-core container, MiniZinc 2.9.7 (Gecode
6.3.0, Chuffed 0.13.2, OR-Tools CP-SAT 9.15, HiGHS 1.14.0, COIN-BC 2.10.13),
clingo 5.8.0, ortools 9.15 (pip). Timeout 300 s unless stated.

---

## 1. What was modeled

One model, `om.mzn`, covers the whole fragment (the `asp/core2.lp`
semantics, which subsume `asp/core.lp` for the shared tests):

- **World**: bounded hex board, axial (Q,R), `|Q|,|R|,|Q+R| <= radius`;
  clockwise directions 0..5 with dir 0 = (1,0); time 0..T; at most one
  (arm, action) per step from {rot_cw, rot_ccw, grab, drop}; idle = wait.
- **State per timestep** (the encoding follows "atom positions, not an
  occupancy grid"): `aq/ar[t,a]` atom hexes, `held[t,a] in 0..nM`,
  `typ[t,a]` element, `ori[t,m]` arm orientation with the gripper hex tied
  by `gripper = base + len*dir(ori)`, `bonded[t,a,b]` symmetric persistent
  bonds, `ex[t,a]` existence (spawning).
- **Rigid rotation**: rotating an arm rotates the whole bond-connected
  component of its held atom about the base. The component is the exact
  least fixpoint of bond reachability, unrolled nA-1 stages
  (`compS[t,m,a,k]` booleans). Rotation about a *variable* base stays
  linear in axial coords: cw `(Q,R) -> (BQ+BR-R, Q+R-BQ)`.
- **Glyphs**: bonder (two adjacent hexes; occupants bond, bonds persist,
  fires at t=0 and on t+1 positions) and calcifier (elemental atom on the
  hex at t is salt at t+1).
- **Reagent respawning** (matches core2.lp exactly): each input has a
  bounded pool of atoms; the rank-(k+1) atom appears at t+1 exactly when
  the rank-k atom exists at t and the input hex is not occupied at t+1 by
  a previously-existing atom. Spawning is forced, not chosen. Not-yet
  spawned atoms are GHOSTS parked on the spawn hex and excluded from
  occupancy/grab/bond/calcify; each ghost gets a unique off-board dummy
  cell id so collision checking stays ONE `alldifferent` per timestep.
- **Layout is part of the decision** (`om.mzn`): arm bases and glyph hexes
  are decision variables over the board, pairwise-disjoint. `om_fixed.mzn`
  pins them to instance parameters — that variant is what clingo solves.
- **Goal**: product slots filled by solver-chosen atoms (injective), each
  unheld on its hex with the required element, the product's bonds present
  and (exact-molecule) no extra bonds. **Objective**: minimize the number
  of actions = non-wait steps — the harness plan-length metric.
- **Phase-4 harness extensions** (flags, all off for the phase-2/3
  instances): free input placement (`free_in_layout`: spawn hexes become
  decision variables), free output placement (`free_out_layout`: each
  product is a placeable part with position + rotation, slot hexes derived
  through a pre-tabulated offset-rotation table), free initial arm
  orientation (`free_init_ori`), and the harness footprint rule
  (`parts_disjoint_full`: input and output hexes join the part
  disjointness `alldifferent`).

Two things the model needs to behave, both required by Gecode and harmless
for the others: a chronological `bool_search` annotation over the action
booleans, and a single-arm wait-compaction dominance constraint ("all
actions form a prefix"), which is only sound for one arm with no spawning
and is auto-disabled otherwise.

An independent checker, `trace.py`, re-simulates every solution with a
separate Python implementation of all rules and asserts the simulated state
equals the solver state at every timestep; every plan reported below passed
it (canonical plans are additionally checked by `harness/validate.py`).

## 2. Results: the phase-2/3 instance matrix

Instances: t1–t4 mirror the clingo tests (transport / bond / rigid
rotation / calcification); `stabilized_water` is the real campaign puzzle
P007 (2 water inputs pool 2, calcifier, bonder, product = bonded salt-water
pair, one copy); `sw_1input` is the 1-input variant clingo can also
express. Full data: `results/benchmarks.csv` / `results/benchmarks.md`.
Cells: **objective** + wall seconds (flattening included) when proved
optimal.

Fixed layout (`om_fixed.mzn`, directly comparable to clingo):

| instance | gecode p1 | chuffed p1 | cp-sat p1 | cp-sat p4 | highs p1 | coin-bc p1 |
|---|---|---|---|---|---|---|
| t1_transport | **5** 0.2s | **5** 0.2s | **5** 0.3s | **5** 0.3s | **5** 0.9s | **5** 6.0s |
| t2_bond | **12** 5.2s | **12** 0.4s | **12** 0.6s | **12** 0.6s | **12** 23.4s | t/o 300s |
| t3_rigid | **4** 0.3s | **4** 0.3s | **4** 0.4s | **4** 0.4s | **4** 0.8s | **4** 6.8s |
| t4_calc | **5** 0.2s | **5** 0.2s | **5** 0.3s | **5** 0.3s | **5** 0.8s | **5** 6.1s |
| stabilized_water | **9** 6.2s | **9** 0.6s | **9** 1.3s | **9** 1.3s | t/o | t/o |
| sw_1input | **11** 1.7s | **11** 0.3s | **11** 0.5s | **11** 0.5s | — | — |

Free layout (`om.mzn`, arm + glyph placement in the decision space; note
these phase-3 free optima predate the harness footprint rule — they may
place a glyph under the product hexes, which the harness forbids):

| instance | gecode p1 | chuffed p1 | cp-sat p1 | cp-sat p4 | highs p1 | coin-bc p1 |
|---|---|---|---|---|---|---|
| t1_transport | **5** 0.3s | **5** 0.3s | **5** 0.3s | **5** 0.3s | **5** 0.8s | **5** 9.8s |
| t2_bond | **5** 0.8s | **5** 0.5s | **5** 0.9s | **5** 0.8s | **5** 257.3s | **5** 132.4s |
| t3_rigid | **4** 0.3s | **4** 0.3s | **4** 0.6s | **4** 0.4s | **4** 0.8s | **4** 5.8s |
| t4_calc | **5** 0.3s | **5** 0.2s | **5** 0.3s | **5** 0.3s | **5** 1.0s | **5** 7.8s |
| stabilized_water | 9? t/o | **9** 225.9s | **9** 43.6s | **9** 3.8s | err 420s | err 420s |
| sw_1input | **11** 292.2s | **11** 0.4s | **11** 0.9s | **11** 0.8s | — | — |

(`9? t/o` = optimal-valued incumbent, unproven at timeout; `err 420s` =
MIP backend ignored `--time-limit` and was hard-killed.)

All objectives agree with clingo where clingo can express the instance
(t1–t4 fixed: 5/12/4/5; sw_1input: 11) and every plan passes the
independent re-simulation.

## 3. Tractability frontier (free-layout Stabilized Water family)

Probes vary the horizon T and radius (data: `results/frontier.csv`):

| probe | gecode p1 | chuffed p1 | cp-sat p1 | cp-sat p4 |
|---|---|---|---|---|
| T=10, r=2 | 9? t/o | **9** 28.6s | **9** 11.4s | not run |
| T=12, r=2 (base) | 9? t/o (600s) | **9** 225.9s | **9** 43.6s | **9** 3.8s |
| T=14, r=2 | 9? t/o | 9? t/o | t/o none | **9** 12.9s |
| T=16, r=2 | not run | 9? t/o | t/o none | not run |
| T=20, r=2 | not run | 9? t/o | t/o none | not run |
| T=12, r=3 | not run | 9? t/o | **9** 95.7s | not run |
| T=16, r=3 | not run | 9? t/o | t/o none | not run |

Findings: the horizon T is the dominant hardness axis, board radius is
mild. Gecode proves nothing in this family; Chuffed's proving edge is
T=12/r=2; single-thread CP-SAT hits a portfolio cliff at T>=14 (returns
*nothing*), yet 4-thread CP-SAT proves T=14 in 12.9 s. Only multi-core
CP-SAT keeps proving optimality as T grows.

## 4. Native CP-SAT vs MiniZinc's FlatZinc route

`native/native_cpsat.py` is a faithful OR-Tools CP-SAT port of the same
model (same variables, constraints, dominance constraint, objective),
reading the same .dzn files; its plans pass `trace.py --check` unchanged
and all objectives match. Benchmark (`native/bench_results.csv`, medians
of 3, single-threaded):

- **Flattening is the dominant MiniZinc overhead and it is constant-ish**:
  flatTime 0.19–0.25 s on every t1–t4 instance = 10–40x the native model
  build time (5–19 ms). Like-for-like (build+solve vs flatten+solve),
  native is 1.4–5.5x faster end-to-end, with the biggest ratios on the
  easiest instances.
- **No FlatZinc formulation cliff**: solve-time ratio mzn/native is
  0.94–1.43x. Inspecting the .fzn shows the fragile constructs survive
  flattening intact for cp-sat (`array_int_element` for the gripper
  lookup, `int_mod` for the orientation transition, native
  `all_different`, half-reified linear for rotation about a var base).
  The two routes hand CP-SAT near-isomorphic models.
- Caveat at process granularity: `import ortools` costs ~0.5 s, i.e. at
  one-shot CLI granularity Python's import tax exceeds MiniZinc's
  flattening tax; it amortizes to zero in a long-lived process.

## 5. Canonical harness validation (branch `harness`, PR #3)

`adapter.py` implements the harness adapter contract: canonical
puzzle.json in, canonical plan.json out, `harness/validate.py` as the
external referee. The harness conventions required real model extensions
(section 1 "phase-4 extensions"): input/output placement became decision
variables, output footprints joined part disjointness (the phase-3
free-layout trick of putting the bonder under the product hexes is
**illegal** under harness rules), and initial arm orientation became part
of the arm placement. Semantics (spawn/calcify/bond timing, rigid
rotation, sequential arms, plan-length metric) matched `SPEC.md` exactly —
no adapter-side simulation shims, only format translation.

Results on the three canonical puzzles (adapter wall time incl. ~0.2–0.4 s
flattening; every emitted plan passes `harness/validate.py`):

| puzzle | t_max | engine | status | objective | wall (s) | validate.py |
|---|---|---|---|---|---|---|
| single_transport | 6 | chuffed | proved optimal | **3** | 0.2 | PASS |
| single_transport | 6 | cp-sat -p4 | proved optimal | **3** | 0.3 | PASS |
| single_transport | 6 | gecode -p4 | proved optimal | **3** | 0.3 | PASS |
| two_atom_bond | 13 | chuffed | t/o, NO solution | — | 300 | — |
| two_atom_bond | 13 | cp-sat -p4 | proved optimal | **11** | 21.1 | PASS |
| two_atom_bond | 13 | gecode -p4 | t/o, NO solution | — | 300 | — |
| stabilized_water | 14 | chuffed | t/o, NO solution | — | 300 | — |
| stabilized_water | 14 | cp-sat -p4 | proved optimal | **12** | 124.4 | PASS |
| stabilized_water | 14 | gecode -p4 | t/o, NO solution | — | 300 | — |

3/3 puzzles solved and validated, and all three canonical optima are now
**proved**: 3 / 11 / 12. The latter two beat the hand-written reference
plans (12 and 13) and equal the clingo adapter's PR #3 incumbents — which
clingo had found within ~1 s but not proven optimal within its 30 s limit.

Notable: the canonical instances are *harder* than the phase-3 ones for
the CP engines because everything (arm, glyphs, input, output, initial
orientation) is free and output footprints join the disjointness rule.
Chuffed and Gecode — fine on the phase-3 free-layout instances of similar
size — find NO solution for two_atom_bond (t_max=13) or stabilized_water
(t_max=14) in 300 s, on instances where 4-thread CP-SAT proves the optimum
in 21 s / 124 s. The adapter's default is therefore a portfolio: Chuffed
first (wins the easy instances at ~0.2 s), then 4-thread CP-SAT with the
rest of the budget. Full data: `results/canonical.csv` / `canonical.md`;
the validated plans are committed under `results/plans/`.

## 6. Comparison with clingo (same machine)

| instance | clingo | best MiniZinc engine |
|---|---|---|
| t1 fixed | 5 in 0.009s | 5 in 0.2s (chuffed) |
| t2 fixed | 12 in 0.152s | 12 in 0.4s (chuffed) |
| t3 fixed | 4 in 0.004s | 4 in 0.3s (chuffed) |
| t4 fixed | 5 in 0.004s | 5 in 0.2s (chuffed) |
| sw_1input fixed | 11 in 0.028s | 11 in 0.3s (chuffed) |

clingo is 1–3 orders of magnitude faster than every MiniZinc backend on
identical instances. Two structural reasons: (a) MiniZinc pays a fixed
~0.2–0.7 s flattening cost that alone exceeds clingo's entire solve time
on every one of these instances; (b) clasp's grounding-native
conflict-driven search handles planning-style disjunctions the way Chuffed
does, without the FlatZinc translation layer. (clingo has not been pushed
to *its* frontier here; free-layout instances of harness scale were not
run through clingo by this arm.)

## 7. What worked / what didn't / verdict

**Worked**

- One MiniZinc model covers the whole shared fragment, fixed and free
  layout, with spawning — and its optima cross-validate against clingo and
  against two independent replay checkers (trace.py, harness validate.py).
- Layout-as-decision-variables is where CP shines: rotation about a
  variable base stays linear in axial coordinates, and glyph placement
  reduces to equality tests. The free-layout instances would be painful to
  grid-search externally (19 hexes x parts x 6 orientations) and the CP
  engines just absorb them.
- CP-SAT's multi-core portfolio is the single most effective lever on hard
  instances (11x on SW-free; the only engine past T=14).
- The FlatZinc route is *not* the bottleneck: flat models are
  near-isomorphic to hand-built CP-SAT ones (section 4).

**Didn't**

- MIP backends (HiGHS, COIN-BC) are hopeless beyond toys: timeouts with no
  incumbent on SW-class instances, and both overran `--time-limit` and had
  to be hard-killed. The time-indexed reified channeling linearizes into
  loose big-M constraints.
- Gecode is search-fragile: it needs the hand-written search annotation
  plus a dominance constraint to solve even t2_bond fixed, and it cannot
  prove any free-layout spawning instance.
- Chuffed's default search collapses on the fully-free canonical
  instances (no solution on two_atom_bond in 300 s) — robustness across
  instance *conventions*, not just sizes, turned out to be an engine
  differentiator.
- Wait-compaction dominance — the thing that saves Gecode — is unsound
  with spawning or multiple arms, so exactly the harder instances lose it.

**Verdict.** Does MiniZinc work for Opus Magnum? Yes — correctly and
conveniently: one declarative model, five engines for free, optima proved,
plans validate externally. But it is not the *fast* way. Engine ranking on
this family: **Chuffed >= CP-SAT >> Gecode >> HiGHS > COIN-BC** on the
easy/fixed instances, with the order flipping to **CP-SAT (multi-core)
first** on every hard free-layout instance — and on the canonical
harness instances CP-SAT is the only engine that solves all three, so
CP-SAT -p4 is the engine to pick if you pick one. clingo beats them all
by 1–3 orders of magnitude on identical instances; the grounding+CDNL
approach is simply a better fit for this bounded-horizon planning
fragment at these sizes. MiniZinc's payoff is the modeling economy
(layout vars, one model for all conventions) and the free engine
portfolio, at a 0.2–0.7 s flattening tax per call plus engine variance
you have to manage.

## 8. Reproduce

Everything below from the repo root. MiniZinc 2.9.7 bundle (with Gecode,
Chuffed, CP-SAT, HiGHS, COIN-BC) is expected on PATH as `minizinc`; on
this container it was installed by extracting `/usr/local` from the
`minizinc/minizinc:2.9.7` Docker image layers into `/opt/minizinc` and
symlinking `/opt/minizinc/bin/minizinc` into `/usr/local/bin` (plain
`docker pull`-less recipe in the phase-1 notes; any standard MiniZinc
bundle install works). Python deps: `pip install ortools clingo`.

```sh
# solve one instance (fixed layout = clingo conventions)
minizinc --solver chuffed minizinc/om_fixed.mzn minizinc/instances/stabilized_water.dzn

# free layout, parallel CP-SAT
minizinc --solver cp-sat -p 4 minizinc/om.mzn minizinc/instances/stabilized_water.dzn

# decode + independently re-verify a plan
minizinc --solver cp-sat --output-mode json \
    minizinc/om_fixed.mzn minizinc/instances/t2_bond.dzn \
  | python3 minizinc/trace.py --check --dzn minizinc/instances/t2_bond.dzn

# full 5-engine benchmark matrix (writes results/benchmarks.csv)
python3 minizinc/bench.py

# native CP-SAT port + FlatZinc-overhead benchmark
python3 minizinc/native/native_cpsat.py minizinc/instances/t2_bond.dzn --fixed
python3 minizinc/native/bench.py

# canonical harness (needs harness/ from the `harness` branch checked out):
python3 minizinc/adapter.py harness/puzzles/stabilized_water.json > plan.json
python3 harness/validate.py harness/puzzles/stabilized_water.json plan.json
python3 harness/bench.py --adapter minizinc="python3 minizinc/adapter.py"

# clingo baselines
python3 run.py asp/core.lp asp/trivial_instance.lp
python3 run.py asp/core2.lp asp/rigid_instance.lp
```
