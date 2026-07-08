#!/usr/bin/env bash
# Type-check the repo one top-level unit at a time. Whole-repo `mypy .` cannot
# work here because several directories reuse module basenames (bench.py,
# validate.py, adapter.py).
set -euo pipefail

cd "$(dirname "$0")/.."

mypy harness/
# selfplay/expert_iteration and selfplay/leaderboard put <repo>/harness on
# sys.path at runtime, so `validate`/`metrics` mean the harness modules;
# selfplay/generator puts the repo root on sys.path instead, so `validate`
# means the root module. MYPYPATH makes mypy resolve each the same way.
MYPYPATH=harness mypy selfplay/expert_iteration/ selfplay/leaderboard/
MYPYPATH=. mypy selfplay/generator/
mypy sat/ --explicit-package-bases
# z3/ is checked from inside the directory: from the repo root the z3/
# source directory would shadow the z3 solver package that the code imports.
(cd z3 && mypy .)
mypy picat/
# minizinc/ needs explicit package bases: minizinc/bench.py and
# minizinc/native/bench.py share a basename.
mypy minizinc/ --explicit-package-bases
mypy run.py validate.py experiments.py

echo "typecheck: all units passed"
