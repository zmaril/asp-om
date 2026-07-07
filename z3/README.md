# Z3 arm

Z3 (SMT, via bounded model checking) arm of the multi-solver Opus Magnum
comparison.  Mirrors the clingo arm's world model and instances exactly
(see `../asp/`), adds the Stabilized Water puzzle (omsim P007), a
solver-independent plan validator, and a ground-truth check against
[omsim](https://github.com/ianh/omsim).  Full report: `NOTES.md`;
result tables: `results.md`, `results-frontier.md`.

## Setup

```sh
pip install z3-solver         # tested with 4.16.0
pip install clingo            # only for the clingo reference timings
```

## Run

```sh
# solve one instance (trivial | bond | rigid | water)
python3 z3/om_solver.py water --strategy descend-cost          # Int encoding
python3 z3/om_solver.py water --free --strategy descend-cost   # free layout
python3 z3/om_bool.py water --strategy descend-cost            # bool one-hot

# full benchmark matrix -> results.md, solution JSONs -> solutions/
python3 z3/bench.py                    # everything (several minutes)
python3 z3/bench.py --instances water  # just Stabilized Water

# independent plan validation (plain-Python replay, no Z3)
python3 z3/validate.py

# Stabilized Water scaling study -> results-frontier.md
python3 z3/frontier.py --budget 120

# clingo reference for Stabilized Water (same simplified semantics)
python3 run.py asp/core2.lp z3/stabilized_water.lp --tmax 12

# ground truth: emit a real .solution file and verify with omsim
python3 z3/emit_omsim.py
omsim -p <path>/P007.puzzle z3/solutions/water-z3.solution
```

## Files

| file | what |
|---|---|
| `om_solver.py` | Int-based BMC encoding, v1+v2 semantics, fixed & free layout, 5 solve strategies |
| `om_bool.py` | pure-boolean one-hot encoding (single-arm, fixed layout; the fast one) |
| `bench.py` | timing matrix -> `results.md` / `results.json`, plan dumps -> `solutions/*.json` |
| `frontier.py` | Stabilized Water radius/horizon scaling -> `results-frontier.md` |
| `validate.py` | independent plan replayer (no Z3); re-implements asp/core.lp & core2.lp semantics |
| `emit_omsim.py` | converts the Stabilized Water plan into a real OM `.solution` (v7) for omsim |
| `stabilized_water.lp` | the same Stabilized Water instance for clingo (`asp/core2.lp`), for apples-to-apples timing |
| `solutions/` | optimal plans (JSON) + `water-z3.solution` (omsim-verified) |
