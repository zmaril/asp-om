"""Solver backends: pysat's Cadical195 / Glucose42 (in-process, support
assumptions natively) and kissat 4.0.4 (external binary, DIMACS on disk;
assumptions become appended unit clauses).

All backends accept an optional wall-clock `timeout` (seconds); a timed-out
solve returns sat=None (pysat: threading.Timer + solver.interrupt() around
solve_limited; kissat: subprocess timeout)."""

import os
import subprocess
import tempfile
import threading
import time

from pysat.solvers import Cadical195, Glucose42

KISSAT_DEFAULT = ("/tmp/claude-0/-workspace-asp-om/"
                  "231137e8-aa53-5099-b493-86deb373db42/scratchpad/"
                  "kissat/build/kissat")
KISSAT = os.environ.get("KISSAT", KISSAT_DEFAULT)

PYSAT_BACKENDS = {"cadical195": Cadical195, "glucose42": Glucose42}


def solve(backend, cnf, assumptions=(), timeout=None):
    """Solve `cnf` (pysat CNF) under unit `assumptions`.

    Returns (sat: bool or None, model: list[int] or None, solve_time_s: float).
    sat=None means the wall-clock `timeout` was hit before an answer.
    """
    if backend in PYSAT_BACKENDS:
        if timeout is not None and backend == "cadical195":
            # this pysat build's CaDiCaL has no interrupt(); enforce the
            # timeout by solving in a forked child process instead
            return _solve_pysat_forked(backend, cnf, assumptions, timeout)
        with PYSAT_BACKENDS[backend](bootstrap_with=cnf.clauses) as s:
            t0 = time.perf_counter()
            if timeout is None:
                sat = s.solve(assumptions=list(assumptions))
            else:
                timer = threading.Timer(timeout, s.interrupt)
                timer.start()
                try:
                    sat = s.solve_limited(assumptions=list(assumptions),
                                          expect_interrupt=True)
                finally:
                    timer.cancel()
            dt = time.perf_counter() - t0
            return sat, (s.get_model() if sat else None), dt
    if backend == "kissat":
        return solve_kissat(cnf, assumptions, timeout)
    raise ValueError(f"unknown backend {backend!r}")


def _solve_pysat_forked(backend, cnf, assumptions, timeout):
    """Run a pysat solve in a forked child so it can be killed at timeout.

    The reported solve time is measured inside the child around s.solve()
    only (bootstrap excluded, matching the in-process path)."""
    import multiprocessing as mp
    ctx = mp.get_context("fork")
    rx, tx = ctx.Pipe(duplex=False)

    def work(conn):
        with PYSAT_BACKENDS[backend](bootstrap_with=cnf.clauses) as s:
            t0 = time.perf_counter()
            sat = s.solve(assumptions=list(assumptions))
            dt = time.perf_counter() - t0
            conn.send((sat, s.get_model() if sat else None, dt))

    p = ctx.Process(target=work, args=(tx,), daemon=True)
    t0 = time.perf_counter()
    p.start()
    if rx.poll(timeout):
        result = rx.recv()
        p.join()
        return result
    p.terminate()
    p.join()
    return None, None, time.perf_counter() - t0


def solve_kissat(cnf, assumptions=(), timeout=None):
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
        try:
            res = subprocess.run([KISSAT, "-q", path],
                                 capture_output=True, text=True,
                                 timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, None, time.perf_counter() - t0
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
