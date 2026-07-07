# asp-om — Solving Opus Magnum puzzles with Answer Set Programming

Can [clingo](https://potassco.org/clingo/) solve (a discretized fragment of)
[Opus Magnum](https://www.zachtronics.com/opus-magnum/) puzzles? This repo
encodes machine layout + arm instruction tapes over bounded time as ASP
programs and asks clingo for a plan.

## Current status (phase 1: trivial model)

Minimal world model:

- Bounded hex grid, axial coordinates `(Q,R)`, radius 2.
- One arm: fixed base at the origin, length 1, orientation `0..5`.
- One instruction per timestep: `rot_cw`, `rot_ccw`, `grab`, `drop`, `wait`.
- Atoms sit on hexes; a held atom rides on the gripper hex; free atoms are
  inert. No two atoms may share a hex.
- Goal: each `product(X,Q,R)` atom delivered (unheld) to its hex by `t_max`.
- `#minimize` on the number of non-wait instructions.

Files:

- `asp/core.lp` — domain encoding (grid, arm, actions, frame axioms, goal).
- `asp/trivial_instance.lp` — move one atom from `(1,0)` to `(-1,0)`.
- `asp/bond_instance.lp` — two atoms + a glyph of bonding; bond them and
  leave them on the glyph/product hexes.
- `run.py` — solves with the clingo Python API and prints a
  timestep-by-timestep trace of the plan.

## Running

```sh
pip install clingo   # provides the python module; CLI via `python3 -m clingo`

python3 run.py asp/core.lp asp/trivial_instance.lp
python3 run.py asp/core.lp asp/bond_instance.lp --tmax 16
```

Both instances solve to optimality in well under a second
(5 and 12 instructions respectively).

## Known simplifications (to lift in later phases)

- No multi-atom molecule movement (rotating a held, bonded atom is forbidden),
  no extend/retract/piston, no tracks, no multiple arms.
- Reagents are pre-placed atoms rather than respawning spawn hexes; products
  are fixed target hexes rather than consumed molecule patterns.
- One period of the tape is the whole plan (no looping tapes).
- No calcification/duplication/purification/projection glyphs, no element
  distinctions yet.
