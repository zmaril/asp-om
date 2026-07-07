"""Solver backends: pysat's Cadical195 / Glucose42 (in-process, support
assumptions natively) and kissat 4.0.4 (external binary, DIMACS on disk;
assumptions become appended unit clauses)."""

import os
import subprocess
import tempfile
import time

from pysat.solvers import Cadical195, Glucose42

KISSAT_DEFAULT = ("/tmp/claude-0/-workspace-asp-om/"
                  "231137e8-aa53-5099-b493-86deb373db42/scratchpad/"
                  "kissat/build/kissat")
KISSAT = os.environ.get("KISSAT", KISSAT_DEFAULT)

PYSAT_BACKENDS = {"cadical195": Cadical195, "glucose42": Glucose42}


def solve(backend, cnf, assumptions=()):
    """Solve `cnf` (pysat CNF) under unit `assumptions`.

    Returns (sat: bool, model: list[int] or None, solve_time_s: float).
    """
    if backend in PYSAT_BACKENDS:
        with PYSAT_BACKENDS[backend](bootstrap_with=cnf.clauses) as s:
            t0 = time.perf_counter()
            sat = s.solve(assumptions=list(assumptions))
            dt = time.perf_counter() - t0
            return sat, (s.get_model() if sat else None), dt
    if backend == "kissat":
        return solve_kissat(cnf, assumptions)
    raise ValueError(f"unknown backend {backend!r}")


def solve_kissat(cnf, assumptions=()):
    """Dump DIMACS (assumptions appended as unit clauses) and run kissat.

    solve_time is the subprocess wall clock (includes kissat's own parsing);
    DIMACS write time is excluded.
    """
    nv = cnf.nv
    with tempfile.NamedTemporaryFile(
            "w", suffix=".cnf", delete=False) as f:
        path = f.name
        clauses = list(cnf.clauses) + [[l] for l in assumptions]
        f.write(f"p cnf {nv} {len(clauses)}\n")
        for c in clauses:
            f.write(" ".join(map(str, c)) + " 0\n")
    try:
        t0 = time.perf_counter()
        res = subprocess.run([KISSAT, "-q", path],
                             capture_output=True, text=True)
        dt = time.perf_counter() - t0
        if res.returncode == 10:
            model = []
            for line in res.stdout.splitlines():
                if line.startswith("v "):
                    model.extend(int(x) for x in line[2:].split())
            model = [l for l in model if l != 0]
            return True, model, dt
        if res.returncode == 20:
            return False, None, dt
        raise RuntimeError(
            f"kissat exited {res.returncode}: {res.stderr[:500]}")
    finally:
        os.unlink(path)
