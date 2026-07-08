# asp-om — Solving Opus Magnum puzzles with Answer Set Programming

Can [clingo](https://potassco.org/clingo/) solve
[Opus Magnum](https://www.zachtronics.com/opus-magnum/) puzzles? This repo
encodes machine layout + arm instruction tapes over bounded time as ASP
programs and asks clingo for a plan.

**Short answer: yes, for real small puzzles.** clingo solves the actual
chapter-1 puzzle *Stabilized Water* (spec byte-decoded from the game's
puzzle file) in 0.06 s with a fixed layout, and with `asp/layout.lp` it
also *designs the machine itself* — finding a 9-instruction machine that
beats the 10-instruction hand layout, with 9 steps proved globally
minimal. Tractability drops off sharply with horizon slack, arm count and
layout freedom. **See [NOTES.md](NOTES.md) for the full findings: results
table, what made it work, where it breaks down, and the honest list of
simplifications vs the real game** (sequential arms, endpoint-only
collision, bounded board, one product copy, no pistons/track/tape loops).

## Files

- `asp/core.lp` — phase-1 minimal encoding (1 arm, grab/rotate/drop);
  instances `asp/trivial_instance.lp`, `asp/bond_instance.lp`.
- `asp/core2.lp` — main encoding: rigid molecule rotation, multiple arms,
  atom types, calcification + bonding glyphs, respawning inputs,
  exact-molecule goals.
- `asp/layout.lp` — optional free-layout module: the solver places the
  arm(s), inputs and glyphs (with OM's non-overlap rule).
- `asp/nowait.lp` — optional prefix symmetry breaker for optimality
  proofs at slack horizons (see caveat in the file).
- Instances: `asp/stabilized_water.lp` (the real puzzle, fixed layout),
  `asp/stabilized_water_free.lp` (free layout), `asp/rigid_instance.lp`,
  and 3-atom stress variants `asp/sw_bent.lp`, `asp/sw_linear.lp`,
  `asp/sw_linear_1arm.lp` (provably UNSAT).
- `run.py` — clingo runner; prints a per-timestep trace.
- `validate.py` — **independent validator**: replays the answer-set plan
  step by step in pure Python (grip/rotate/drop, rigid motion, collisions,
  glyphs, spawns, goal) and prints PASS/FAIL.
- `experiments.py` — scaling battery; prints a markdown results table.

## Running

```sh
pip install clingo   # python module; CLI available as `python3 -m clingo`

# solve
python3 run.py asp/core2.lp asp/stabilized_water.lp --tmax 10
python3 run.py asp/core2.lp asp/layout.lp asp/stabilized_water_free.lp --tmax 10 --time-limit 30
python3 run.py asp/core2.lp asp/rigid_instance.lp

# validate independently
python3 validate.py asp/core2.lp asp/stabilized_water.lp --tmax 10

# scaling table (slow)
python3 experiments.py --time-limit 300
```

## Development

Linting (ruff), type checking (mypy), tests (pytest) and a
[straitjacket](https://github.com/zmaril/straitjacket) scan run in CI on
every push and pull request against `main`. To run them locally:

```sh
uv tool install ruff mypy pre-commit   # or: pip install ruff mypy pre-commit
curl -fsSL https://raw.githubusercontent.com/zmaril/straitjacket/main/install.sh | sh

pre-commit install     # run all checks on every commit

# or run each check by hand
ruff check .
ruff format .
scripts/typecheck.sh   # mypy, one top-level directory at a time
straitjacket
pytest harness/tests/
```
