"""Benchmark harness for the SAT arm, phase 1 (trivial cases a and b).

For every (case x layout-mode x backend) it iterates the horizon T upward
from 1 until SAT, recording CNF size, encode time and solve time for every
run (UNSAT horizons included).  Every SAT model is decoded and checked by
the independent validator (sat/validate.py); a validator failure aborts
the benchmark.

It then finds, at the clingo arm's fixed t_max (10 for case a, 16 for
case b), the minimum number of non-wait instructions via cardinality
constraints (pysat CardEnc, downward linear search) for parity with the
clingo arm's `#minimize` objective.

Writes sat/results-trivial.md (and optionally a copy elsewhere via
--copy-to PATH).

Usage: python3 sat/bench.py [--copy-to PATH]
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pysat.card import CardEnc, EncType
from pysat.formula import CNF

from sat.decode import decode_model, format_plan
from sat.encode import Encoder
from sat.instances import CASES
from sat.solvers import solve
from sat.validate import validate_plan

BACKENDS = ["cadical195", "glucose42", "kissat"]
MODES = ["fixed", "free"]
HORIZON_CAP = 20


def horizon_iteration(case_key, mode, backend, log):
    """Iterate T upward until SAT; return (rows, sat_T, plan, enc)."""
    inst = CASES[case_key]
    rows = []
    for T in range(1, HORIZON_CAP + 1):
        enc = Encoder(inst, T)
        assumptions = enc.layout_assumptions() if mode == "fixed" else []
        sat, model, solve_t = solve(backend, enc.cnf, assumptions)
        rows.append(
            {
                "case": case_key,
                "mode": mode,
                "backend": backend,
                "T": T,
                "nvars": enc.nvars,
                "nclauses": enc.nclauses,
                "encode_t": enc.encode_time,
                "solve_t": solve_t,
                "result": "SAT" if sat else "UNSAT",
            }
        )
        log(
            f"  {case_key}/{mode}/{backend} T={T}: "
            f"{enc.nvars}v {enc.nclauses}c "
            f"enc {enc.encode_time:.3f}s solve {solve_t:.3f}s "
            f"{'SAT' if sat else 'UNSAT'}"
        )
        if sat:
            plan = decode_model(enc, model)
            errs = validate_plan(inst, plan)
            if errs:
                log(f"  VALIDATION FAILED for {case_key}/{mode}/{backend} T={T}:")
                for e in errs:
                    log(f"    - {e}")
                raise SystemExit("validator rejected a SAT model; aborting")
            log(f"    validator: OK (min makespan {T})")
            return rows, T, plan, enc
    return rows, None, None, None


def minimize_instructions(case_key, mode, backend, log):
    """At the clingo arm's t_max, minimize the non-wait instruction count."""
    inst = CASES[case_key]
    T = inst.t_max_default
    t_total0 = time.perf_counter()
    enc = Encoder(inst, T)
    assumptions = enc.layout_assumptions() if mode == "fixed" else []
    lits = enc.non_wait_literals()

    sat, model, _ = solve(backend, enc.cnf, assumptions)
    if not sat:
        raise SystemExit(f"{case_key}/{mode} UNSAT at t_max={T}?!")
    true = {lit for lit in model if lit > 0}
    cost = sum(1 for lit in lits if (lit > 0 and lit in true) or (lit < 0 and -lit not in true))
    best_model, best_cost = model, cost
    k = cost - 1
    while k >= 0:
        bounded = CNF()
        bounded.extend(enc.cnf.clauses)
        card = CardEnc.atmost(lits=lits, bound=k, top_id=enc.pool.top, encoding=EncType.seqcounter)
        bounded.extend(card.clauses)
        sat, model, _ = solve(backend, bounded, assumptions)
        if not sat:
            break
        true = {lit for lit in model if lit > 0}
        best_cost = sum(
            1 for lit in lits if (lit > 0 and lit in true) or (lit < 0 and -lit not in true)
        )
        best_model = model
        k = best_cost - 1
    total_t = time.perf_counter() - t_total0

    plan = decode_model(enc, best_model)
    errs = validate_plan(inst, plan)
    if errs:
        for e in errs:
            log(f"    - {e}")
        raise SystemExit("validator rejected an optimized model; aborting")
    log(
        f"  {case_key}/{mode} optimize@t_max={T} [{backend}]: "
        f"optimum {best_cost} non-wait instructions, "
        f"proven in {total_t:.3f}s, validator OK"
    )
    return {
        "case": case_key,
        "mode": mode,
        "backend": backend,
        "t_max": T,
        "optimum": best_cost,
        "total_t": total_t,
        "plan": plan,
        "enc": enc,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy-to", help="also write the results markdown here")
    args = ap.parse_args()

    log_lines = []

    def log(msg):
        print(msg, flush=True)
        log_lines.append(msg)

    all_rows = []
    makespans: dict[tuple[str, str], int] = {}  # (case, mode) -> min T
    plans = {}  # (case, mode) -> (plan, inst) from cadical195

    for case_key in ("a", "b"):
        for mode in MODES:
            for backend in BACKENDS:
                rows, satT, plan, _enc = horizon_iteration(case_key, mode, backend, log)
                all_rows.extend(rows)
                key = (case_key, mode)
                if satT is not None:
                    prev = makespans.get(key)
                    if prev is not None and prev != satT:
                        raise SystemExit(
                            f"backend disagreement on min makespan for {key}: {prev} vs {satT}"
                        )
                    makespans[key] = satT
                    if backend == "cadical195":
                        plans[key] = plan

    opt_results = []
    for case_key in ("a", "b"):
        for mode in MODES:
            opt_results.append(minimize_instructions(case_key, mode, "cadical195", log))

    md = render_markdown(all_rows, makespans, plans, opt_results)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results-trivial.md")
    with open(out, "w") as f:
        f.write(md)
    print(f"\nwrote {out}")
    if args.copy_to:
        with open(args.copy_to, "w") as f:
            f.write(md)
        print(f"wrote {args.copy_to}")


def render_markdown(rows, makespans, plans, opt_results):
    lines = []
    lines.append("# SAT arm — phase 1 results (trivial cases)\n")
    lines.append(
        "Generated by `python3 sat/bench.py`. "
        "Machine: this repo's dev container; "
        "python-sat 1.9.dev5 (Cadical195, Glucose42), "
        "kissat 4.0.4 (external binary, DIMACS dump; its solve "
        "time is subprocess wall clock incl. DIMACS parsing).\n"
    )
    lines.append(
        "Modes: **fixed** pins the layout to the clingo arm's layout via "
        "unit assumptions on the layout variables (same CNF generator); "
        "**free** lets the solver choose arm base/length/initial "
        "orientation and (case b) glyph placement from the radius-2 hex "
        "ball. Horizon T is iterated upward from 1 until SAT, so the first "
        "SAT row per series is the minimum makespan. Every SAT model was "
        "decoded and accepted by the independent forward simulator "
        "(sat/validate.py).\n"
    )

    lines.append("## Horizon iteration (case x mode x backend x T)\n")
    lines.append("| case | mode | backend | T | vars | clauses | encode s | solve s | result |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['case']} | {r['mode']} | {r['backend']} | {r['T']} "
            f"| {r['nvars']} | {r['nclauses']} | {r['encode_t']:.3f} "
            f"| {r['solve_t']:.3f} | {r['result']} |"
        )
    lines.append("")

    lines.append("## Minimum makespan (first SAT horizon)\n")
    lines.append("| case | mode | min makespan T |")
    lines.append("|---|---|---|")
    for (c, m), T in sorted(makespans.items()):
        lines.append(f"| {c} | {m} | {T} |")
    lines.append("")

    lines.append("## Instruction-count optimum at the clingo arm's t_max\n")
    lines.append(
        "Objective identical to clingo's `#minimize`: number of "
        "non-wait instructions at fixed t_max (10 for case a, 16 "
        "for case b), minimized by downward linear search over "
        "`CardEnc.atmost` bounds with Cadical195. Times are total "
        "wall clock over the whole search (all solves + encodes) "
        "to the PROVEN optimum.\n"
    )
    lines.append(
        "| case | mode | t_max | optimum (non-wait instr) | total time s | clingo (fixed layout) |"
    )
    lines.append("|---|---|---|---|---|---|")
    clingo_ref = {"a": "5 in 0.007 s", "b": "12 in 0.120 s"}
    for o in opt_results:
        lines.append(
            f"| {o['case']} | {o['mode']} | {o['t_max']} | {o['optimum']} "
            f"| {o['total_t']:.3f} | {clingo_ref[o['case']]} |"
        )
    lines.append("")

    lines.append("## Decoded minimum-makespan plans (Cadical195 models, validator-approved)\n")
    for (c, m), plan in sorted(plans.items()):
        inst = CASES[c]
        lines.append(f"### case {c}, {m} layout (T={makespans[(c, m)]})\n")
        lines.append("```")
        lines.append(format_plan(plan, inst))
        lines.append("```\n")

    lines.append("## Validation & omsim note\n")
    lines.append(
        "* Every SAT result in the tables above was decoded "
        "(sat/decode.py) and re-simulated by the independent validator "
        "(sat/validate.py), which shares no logic with the encoder; all "
        "passed (goal reached, no hex collisions, legal grabs/drops, "
        "gripper on-board, bond semantics respected).\n"
        "* omsim cross-check: NOT meaningful for cases (a) and (b) — they "
        "are synthetic instances of the shared phase-1 fragment, not real "
        "game puzzles, so no .puzzle file exists for them (the brief notes "
        "omsim is only useful for test case (c), Stabilized Water, which "
        "is out of scope for this phase). Rather than force a bogus "
        ".solution export we state this explicitly here; omsim validation "
        "is deferred to the Stabilized Water phase.\n"
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
