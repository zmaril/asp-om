# Harness spec: puzzle format, plan format, world semantics

This document defines the **common formats and semantics** shared by all
solver arms (clingo, picat, minizinc, z3, sat, ...). The canonical
implementation of these semantics is `harness/validate.py`; if this
document and the validator ever disagree, the validator wins and this
document has a bug.

The semantics are a reconciliation of the two existing arms
(`asp/core2.lp` + `validate.py` on the clingo side, `picat/*.pi` +
`picat/validate.py` on the picat side). Every place where the two arms
differed, the choice made here is called out explicitly in
[Reconciliation decisions](#reconciliation-decisions) at the bottom.

---

## 1. Coordinate system

* **Axial hex coordinates** `(q, r)`, integer.
* The board is the bounded hex-disc of radius `R` (`board_radius` in the
  puzzle file): all `(q, r)` with `|q| <= R`, `|r| <= R`, `|q + r| <= R`.
  Radius 2 = 19 hexes. (The real game board is effectively unbounded;
  the bounded board is a deliberate, shared simplification.)
* The **six direction vectors**, indexed `0..5`:

  | index | vector |
  |---|---|
  | 0 | `( 1,  0)` |
  | 1 | `( 0,  1)` |
  | 2 | `(-1,  1)` |
  | 3 | `(-1,  0)` |
  | 4 | `( 0, -1)` |
  | 5 | `( 1, -1)` |

  Incrementing the index is what this project calls **clockwise** (`cw`).
  (Whether that renders visually clockwise depends on how you draw the
  axes; the formulas below are the normative definition.)

## 2. Rotation convention

* A **rotation step** is 60 degrees. `rot_cw` = direction index `+1 mod 6`,
  `rot_ccw` = direction index `-1 mod 6` (= `+5 mod 6`).
* Rotating a point about the origin:
  * cw: `(q, r) -> (-r, q + r)`
  * ccw: `(q, r) -> (q + r, -q)`
* Rotating about an arbitrary center `(bq, br)`: translate, rotate, translate
  back. cw: `(q, r) -> (bq - (r - br), br + (q - bq) + (r - br))`.
* Verified identity: `rot_cw(dir[d]) = dir[(d+1) mod 6]`.
* A **rotation field** on a placed part (`"rotation": k`, `k` in `0..5`)
  means: transform every relative hex `o` of the part to
  `position + rot_cw^k(o)`.

## 3. Puzzle JSON

```jsonc
{
  "name": "stabilized_water",
  "board_radius": 2,          // required, int >= 1
  "t_max": 14,                // required: the horizon. States t=0..t_max,
                              // instructions at t=0..t_max-1.
  "reagents": [               // required, non-empty
    {
      "id": "water",          // unique string
      "pool": 2,              // how many copies may spawn (>=1).
                              // Approximates the game's unlimited inputs.
      "atoms": [ {"element": "water", "pos": [0, 0]} ],  // relative hexes
      "bonds": []             // pairs of atom indices, e.g. [[0,1]]
      // optional: "position": [q,r], "rotation": d  -- pins the input part
    }
  ],
  "products": [               // required, non-empty
    {
      "id": "stabilized_water",
      "atoms": [ {"element": "salt",  "pos": [0, 0]},
                 {"element": "water", "pos": [1, 0]} ],
      "bonds": [[0, 1]]
      // optional: "position", "rotation" -- pins the output part
    }
  ],
  "parts": [                  // required: the machine parts available
    {"type": "arm",       "id": "m1", "length": 1},
    {"type": "calcifier", "id": "c1"},
    {"type": "bonder",    "id": "b1"}
    // optional per part: "position": [q,r], "rotation": d -- pins it
  ]
}
```

* `atoms[i].pos` are **relative** hexes (the molecule's own frame); the
  plan's placement maps them onto the board.
* Element names: `air`, `earth`, `fire`, `water`, `salt` (the modeled
  subset). `air/earth/fire/water` are **elemental** (calcifiable).
* Bonds are unordered pairs of atom indices; all bonds are normal bonds.
* Every reagent implies exactly one **input part**, every product exactly
  one **output part**; the plan must place them (see below).
* Supported part types: `arm` (needs `length >= 1`), `calcifier`
  (glyph of calcification, 1 hex), `bonder` (glyph of bonding, 2 adjacent
  hexes). Pistons, track, multi-arms, other glyphs: not modeled (yet).
* If a reagent/product/part carries `"position"` (and, where meaningful,
  `"rotation"`), a plan MUST place it exactly there; otherwise placement
  is the solver's decision. **Layout is part of the solution.**

## 4. Plan (solution) JSON

```jsonc
{
  "puzzle": "stabilized_water",     // must equal puzzle.name
  "placements": [
    // exactly one entry per arm/glyph part, per reagent (type "input")
    // and per product (type "output"):
    {"type": "arm",       "id": "m1",               "position": [0, 0],  "rotation": 0},
    {"type": "input",     "id": "water",            "position": [1, 0],  "rotation": 0},
    {"type": "output",    "id": "stabilized_water", "position": [0, -1], "rotation": 0},
    {"type": "calcifier", "id": "c1",               "position": [0, 1]},
    {"type": "bonder",    "id": "b1",               "position": [-1, 0], "rotation": 1}
  ],
  "instructions": [
    {"t": 0, "arm": "m1", "action": "grab"},
    {"t": 1, "arm": "m1", "action": "rot_cw"}
    // ...
  ]
}
```

* **Placements**
  * `arm`: `position` = base hex; `rotation` = initial direction index of
    the gripper (`0..5`). The gripper hex is
    `base + length * dir[rotation]` and must be on the board.
  * `input` / `output`: `id` names the reagent/product; `position` +
    `rotation` transform the molecule's relative hexes onto the board
    (section 2). Single-atom molecules: use `rotation: 0`.
  * `calcifier`: `position` only (1 hex).
  * `bonder`: footprint = `position` and `position + dir[rotation]`.
    `(p, k)` and `(p + dir[k], k+3 mod 6)` denote the same bonder; both
    are accepted.
  * **Footprint disjointness**: the footprints of all placed parts (arm
    bases, input hexes, output hexes, calcifier hexes, bonder hexes) must
    be pairwise disjoint and entirely on the board. This is the game's
    part-overlap rule; note that *atoms* may freely travel over and rest
    on any part hex — the rule constrains parts only.
* **Instructions**
  * Each entry: integer `t` with `0 <= t < t_max`, an `arm` id, and an
    `action` in `{grab, drop, rot_cw, rot_ccw, wait}`.
  * **At most one instruction per timestep across ALL arms** (sequential
    arms — the shared simplification; real OM runs arm tapes in
    parallel). A timestep with no entry is an implicit `wait`.
  * `wait` entries are legal but pointless; **plan length** (the
    benchmark metric) = number of non-`wait` instructions.

## 5. World semantics (the replay)

The state at time `t` (`t = 0..t_max`) consists of: each arm's direction
index and held atom (or none), each atom's hex, element, and the set of
bonds (unordered atom pairs, persistent). Arm bases, lengths and all part
positions are static.

### 5.1 Initial state (t = 0)

1. For every input with `pool >= 1`, **copy 1 of its reagent spawns**:
   atoms appear on the input's (transformed) hexes with the reagent's
   elements and internal bonds.
2. **Bonders fire** on the initial state (see 5.3 step 4).
3. No arm holds anything.

### 5.2 One step (state t -> state t+1, instruction at t)

Let the instruction be `(m, act)` (default `(_, wait)`). Order of effects:

1. **Arm action**:
   * `grab`: requires the acting arm's hand empty, an atom on its gripper
     hex at time t, and that atom not held by another arm. The arm holds
     that atom from `t+1` on.
   * `drop`: requires a held atom; the arm's hand is empty from `t+1` on.
     The atom stays where it is.
   * `rot_cw` / `rot_ccw`: the arm's direction index changes by +1/-1
     (mod 6). The new gripper hex must be on the board. If the arm holds
     an atom, the atom's whole **bond-connected component** rotates
     rigidly by 60 degrees about the arm's base (formulas in section 2).
     Illegal if: any component atom would land off the board; or the
     component contains an atom held by *another* arm (no tearing; a
     rotation that would move another arm's held atom is illegal even in
     the same direction).
   * `wait`: no effect.
2. **Calcification**: every atom whose hex **at time t** (i.e. before
   this step's motion) is a calcifier hex and whose element is elemental
   (`air/earth/fire/water`) has element `salt` at `t+1`. (An atom swung
   onto a calcifier at step t is calcified by step t+1, i.e. is salt from
   t+2; an atom swung *off* the calcifier at step t is still calcified,
   because it was on the glyph at time t.)
3. **Spawning**: for each input, if fewer than `pool` copies have spawned
   and **all** of the input's hexes are free of atoms at their new
   (t+1) positions, the next copy spawns: its atoms and internal bonds
   exist at `t+1`. (Single-atom reagents reduce to: the input hex was
   vacated.)
4. **Bonding**: for every bonder, if both its hexes are occupied at
   `t+1` (after motion and spawning), the two occupants become bonded
   (idempotent; bonds never break — no unbonder modeled).

### 5.3 Invariants checked at every state

* Every atom on the board.
* No two atoms on the same hex (**endpoint-only collision**: only the
  landing positions of a rotation are checked, not swept arcs — shared
  simplification vs the game's continuous collision).
* No atom on any arm's base hex.
* Every arm's gripper hex on the board.

### 5.4 Goal

* A product is **complete at time t** if its output part's hexes are
  covered by atoms such that: each output hex holds an atom of exactly
  the product's element for that hex, **none** of these atoms is held by
  any arm, every product bond is present between the corresponding atoms,
  and each atom's **total** bond degree equals its degree inside the
  product (i.e. the molecule is exact — no extra bonds to anything else;
  together with per-hex element equality this forces an exact molecule
  match in the placed orientation).
* **The plan is valid iff every product is complete at some time
  `t <= t_max`** (products may complete at different times). One copy per
  product suffices (the campaign's 6 copies and the consuming output area
  are not modeled); completion does not consume the atoms.

## 6. Known shared simplifications vs the real game

Inherited from both arms, kept deliberately:

* sequential arms (one instruction per timestep, no parallel tapes, no
  tape loops/repeat, cycle-count metric not modeled);
* endpoint-only collision checking;
* bounded board, bounded input pools;
* one product copy, non-consuming output;
* part subset: arms (fixed length), calcifier, bonder only — no
  piston/track/unbonder/multi-bonder/triplex/etc.;
* no pivot instruction (atoms cannot be rotated about the gripper).

## Reconciliation decisions

Where the clingo and picat arms disagreed, the harness picks one
convention. Solvers must conform to these (thin adapter layers are fine):

1. **Output part instead of "anywhere" / hard-coded hexes.** clingo's
   instances accepted the product molecule anywhere on the board (any
   rotation); picat hard-coded goal hexes per instance. The harness makes
   the output a **placeable part**: the plan chooses (or the puzzle pins)
   its position/rotation, the molecule must rest exactly there, and the
   output footprint participates in part-overlap. This is closer to the
   real game and subsumes both old behaviors (free placement ~= clingo's
   "anywhere"; pinning ~= picat's fixed hexes).
2. **Glyph/spawn timing = clingo's.** picat applied
   spawn/calcify/bond immediately after each action *at the atom's new
   position*; clingo evaluates calcification on positions **at time t**
   (pre-motion) with the type change visible at t+1, spawns at t+1 when
   the input hex is clear, and fires bonders on t+1 positions (and on the
   initial state). The harness adopts the clingo timing exactly (it is
   what master's proven validator implements). Observable difference:
   rotating an atom onto a calcifier at step t makes it salt at t+2
   under this rule (t+1 under picat's).
3. **`wait` exists.** picat plans had no `wait` (pure action sequences);
   clingo tapes had implicit waits. Harness: missing timesteps are
   implicit waits, explicit `wait` entries allowed, plan length counts
   non-wait instructions. This matters: with respawning inputs, an
   optimal plan can need a mid-plan wait.
4. **Placements are declarative, not actions.** picat modeled free layout
   as cost-1 `place_*` actions in a setup phase; clingo as choice rules
   over layout facts. The harness plan format lists placements
   **declaratively** (a `placements` section), timeless. Plan length
   therefore never counts placements (picat's `+N placements` bookkeeping
   disappears).
5. **Stabilized Water reagent modeling = picat's.** The true P007 spec
   has two single-water reagent sites. clingo's instance used two input
   sites (pool 2 each); picat collapsed them to **one respawning input
   site with pool 2**. The harness instance uses one site, pool 2: with a
   single length-1 arm, 2 input sites + calcifier + bonder + a 2-hex
   output cannot all fit on the 6 ring-1 hexes, so the two-site variant
   would be unsolvable under the (new, stricter) output-part rule.
   The decoded product/reagent molecules themselves are unchanged
   (reagent = 1 water; product = salt@(0,0) bonded to water@(1,0)).
6. **Rotation naming/indexing**: both arms already agreed (`rot_cw` =
   +1 on the direction index, same `dir` table, same axial formulas);
   the harness keeps those names and conventions verbatim.
7. **Bonder representation**: clingo used an unordered hex pair
   (`glyph_bond(q1,r1,q2,r2)`), picat a cell-pair list. The harness uses
   `position + rotation` like every other part, with the flip-equivalence
   `(p, k) == (p + dir[k], (k+3) mod 6)` accepted.
