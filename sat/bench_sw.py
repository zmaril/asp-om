"""Benchmark harness for the SAT arm, phase 2 (Stabilized Water).

Runs, with a per-solve wall-clock timeout (default 300 s):

1. Horizon iteration for instance x layout-mode x backend: T = 1 upward
   until SAT, recording CNF size, encode time and solve time for every
   run (UNSAT and TIMEOUT rows included; a series is abandoned after two
   consecutive timeouts or at the horizon cap).  Every SAT model is
   decoded and checked by the independent validator (sat/validate2.py);
   a validation failure aborts the benchmark.
2. Instruction-count minimization (clingo `#minimize` parity): at fixed
   t_max, minimize the number of non-wait steps by downward linear search
   over CardEnc.atmost bounds, including slack horizons t_max=16/20 where
   the clingo arm needed a symmetry breaker to finish.
3. Free-layout board-radius scaling probes (radius 3/4/5) to find where
   tractability ends.

Writes sat/results-stabilized-water.md.

Usage: python3 sat/bench_sw.py [--timeout 300] [--skip-scaling]
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pysat.card import CardEnc, EncType
from pysat.formula import CNF

from instances import SW_CASES, sw_scaled
from encode2 import Encoder2
from solvers import solve
from decode2 import decode_model2, format_plan2
from validate2 import validate_plan2

BACKENDS = ["cadical195", "glucose42", "kissat"]
MODES = ["fixed", "free"]
CAPS = {"sw": 14, "sw-omsim": 16}


def res_str(sat):
    return "TIMEOUT" if sat is None else ("SAT" if sat else "UNSAT")


def horizon_iteration(inst, mode, backend, timeout, cap, log, start=1):
    rows = []
    consecutive_timeouts = 0
    for T in range(start, cap + 1):
        enc = Encoder2(inst, T)
        assumptions = enc.layout_assumptions() if mode == "fixed" else []
        sat, model, solve_t = solve(backend, enc.cnf, assumptions,
                                    timeout=timeout)
        rows.append(dict(case=inst.name, mode=mode, backend=backend, T=T,
                         nvars=enc.nvars, nclauses=enc.nclauses,
                         encode_t=enc.encode_time, solve_t=solve_t,
                         result=res_str(sat)))
        log(f"  {inst.name}/{mode}/{backend} T={T}: "
            f"{enc.nvars}v {enc.nclauses}c enc {enc.encode_time:.3f}s "
            f"solve {solve_t:.3f}s {res_str(sat)}")
        if sat:
            plan = decode_model2(enc, model)
            errs = validate_plan2(inst, plan)
            if errs:
                for e in errs:
                    log(f"    VALIDATION ERROR: {e}")
                raise SystemExit("validator rejected a SAT model; aborting")
            log(f"    validator: OK (min makespan {T})")
            return rows, T, plan
        if sat is None:
            consecutive_timeouts += 1
            if consecutive_timeouts >= 2:
                log(f"    abandoning series after {consecutive_timeouts} "
                    f"consecutive timeouts")
                return rows, None, None
        else:
            consecutive_timeouts = 0
    return rows, None, None


def minimize_instructions(inst, mode, backend, t_max, timeout, log):
    """Minimize non-wait instruction count at fixed t_max (downward linear
    search with cardinality constraints).  Returns a result dict; honest
    about timeouts: `proved` is False if any solve timed out before the
    UNSAT bound was established."""
    t_total0 = time.perf_counter()
    enc = Encoder2(inst, t_max)
    assumptions = enc.layout_assumptions() if mode == "fixed" else []
    lits = enc.non_wait_literals()

    sat, model, st = solve(backend, enc.cnf, assumptions, timeout=timeout)
    if sat is None:
        total_t = time.perf_counter() - t_total0
        log(f"  {inst.name}/{mode} opt@T={t_max} [{backend}]: first solve "
            f"TIMEOUT after {st:.1f}s")
        return dict(case=inst.name, mode=mode, t_max=t_max, optimum=None,
                    proved=False, total_t=total_t, plan=None,
                    note="first solve timeout")
    if not sat:
        raise SystemExit(f"{inst.name}/{mode} UNSAT at t_max={t_max}?!")
    true = set(l for l in model if l > 0)

    def cost_of(m):
        tr = set(l for l in m if l > 0)
        return sum(1 for l in lits
                   if (l > 0 and l in tr) or (l < 0 and -l not in tr))

    best_model, best_cost = model, cost_of(model)
    proved, note = True, ""
    k = best_cost - 1
    while k >= 0:
        bounded = CNF()
        bounded.extend(enc.cnf.clauses)
        card = CardEnc.atmost(lits=lits, bound=k, top_id=enc.pool.top,
                              encoding=EncType.seqcounter)
        bounded.extend(card.clauses)
        sat, model, st = solve(backend, bounded, assumptions,
                               timeout=timeout)
        if sat is None:
            proved = False
            note = f"timeout at bound {k} after {st:.1f}s"
            break
        if not sat:
            break
        best_cost = cost_of(model)
        best_model = model
        k = best_cost - 1
    total_t = time.perf_counter() - t_total0

    plan = decode_model2(enc, best_model)
    errs = validate_plan2(inst, plan)
    if errs:
        for e in errs:
            log(f"    VALIDATION ERROR: {e}")
        raise SystemExit("validator rejected an optimized model; aborting")
    log(f"  {inst.name}/{mode} opt@T={t_max} [{backend}]: "
        f"{'optimum' if proved else 'best found'} {best_cost} non-wait, "
        f"{'proved ' if proved else ''}in {total_t:.3f}s "
        f"{note} validator OK")
    return dict(case=inst.name, mode=mode, t_max=t_max, optimum=best_cost,
                proved=proved, total_t=total_t, plan=plan, note=note)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--skip-scaling", action="store_true")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    log_lines = []

    def log(msg):
        print(msg, flush=True)
        log_lines.append(msg)

    all_rows, makespans, plans = [], {}, {}

    # ---- 1. horizon iteration ----
    for name, inst in SW_CASES.items():
        for mode in MODES:
            for backend in BACKENDS:
                rows, satT, plan = horizon_iteration(
                    inst, mode, backend, args.timeout, CAPS[name], log)
                all_rows.extend(rows)
                key = (name, mode)
                if satT is not None:
                    prev = makespans.get(key)
                    if prev is not None and prev != satT:
                        raise SystemExit(
                            f"backend disagreement on min makespan {key}: "
                            f"{prev} vs {satT}")
                    makespans[key] = satT
                    if backend == "cadical195":
                        plans[key] = plan

    # ---- 2. instruction-count minimization ----
    opt_results = []
    sw = SW_CASES["sw"]
    for mode in MODES:
        opt_results.append(minimize_instructions(
            sw, mode, "cadical195", 10, args.timeout, log))
    # slack horizons (clingo's wait-padding cliff: fixed T=20 was >300s
    # for clingo without its nowait symmetry breaker)
    for t_max in (16, 20):
        opt_results.append(minimize_instructions(
            sw, "fixed", "cadical195", t_max, args.timeout, log))
    opt_results.append(minimize_instructions(
        sw, "free", "cadical195", 16, args.timeout, log))

    # ---- 3. free-layout radius scaling ----
    scaling_rows = []
    if not args.skip_scaling:
        for radius in (3, 4, 5):
            inst = sw_scaled(radius)
            for backend in ("cadical195", "kissat"):
                rows, satT, plan = horizon_iteration(
                    inst, "free", backend, args.timeout, 12, log)
                scaling_rows.extend(rows)
                if satT is not None and backend == "cadical195":
                    plans[(inst.name, "free")] = plan
                    makespans[(inst.name, "free")] = satT

    md = render_markdown(all_rows, makespans, plans, opt_results,
                         scaling_rows, args.timeout)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "results-stabilized-water.md")
    with open(out, "w") as f:
        f.write(md)
    print(f"\nwrote {out}")
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(dict(rows=all_rows, scaling=scaling_rows,
                           makespans={f"{k[0]}/{k[1]}": v
                                      for k, v in makespans.items()},
                           opt=[{kk: vv for kk, vv in o.items()
                                 if kk != "plan"} for o in opt_results]),
                      f, indent=1)
        print(f"wrote {args.json_out}")


def render_markdown(rows, makespans, plans, opt_results, scaling_rows,
                    timeout):
    lines = []
    lines.append("# SAT arm — Stabilized Water (Opus Magnum campaign "
                 "puzzle P007)\n")
    lines.append(
        "Generated by `python3 sat/bench_sw.py`. Machine: this repo's dev "
        "container; python-sat 1.9.dev5 (Cadical195, Glucose42), kissat "
        "4.0.4 (external binary; its solve time is subprocess wall clock "
        f"incl. DIMACS parsing). Per-solve timeout {timeout:.0f} s.\n")
    lines.append(
        "Instances (phase-2 mechanics = the clingo arm's asp/core2.lp: "
        "rigid molecule motion, calcification + bonding glyphs, "
        "respawning bounded-pool inputs, exact salt–water dimer goal):\n\n"
        "* **sw** — the clingo arm's exact Stabilized Water instance "
        "(asp/stabilized_water.lp): radius-2 board, arm(0,0) len 1 D0, "
        "water inputs (1,0) and (0,1) pool 2 each, calcifier (1,-1), "
        "bonder (-1,0)/(-1,1); goal: exact unheld salt–water dimer "
        "anywhere.\n"
        "* **sw-omsim** — same puzzle on the reference solution's machine "
        "layout (radius-3 board, arm(2,-1) D4, one input (2,-2), "
        "calcifier (1,-1), bonder (3,-2)/(3,-1)); goal additionally fixes "
        "the product cells salt@(1,0), water@(2,0) (a real output part), "
        "so plans export to game-format .solution files for omsim.\n\n"
        "Modes: **fixed** pins the layout via unit assumptions; **free** "
        "lets the solver place arm, inputs, calcifier and bonder anywhere "
        "on the board under OM's part-non-overlap rule (same CNF). "
        "Horizon T iterated upward from 1 until SAT => first SAT is the "
        "minimum makespan. Every SAT model passed the independent "
        "forward-simulation validator (sat/validate2.py).\n")

    lines.append("## Horizon iteration (instance × mode × backend × T)\n")
    lines.append("| instance | mode | backend | T | vars | clauses | "
                 "encode s | solve s | result |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['case']} | {r['mode']} | {r['backend']} | {r['T']} "
            f"| {r['nvars']} | {r['nclauses']} | {r['encode_t']:.3f} "
            f"| {r['solve_t']:.3f} | {r['result']} |")
    lines.append("")

    lines.append("## Minimum makespan (first SAT horizon)\n")
    lines.append("| instance | mode | min makespan T | clingo arm |")
    lines.append("|---|---|---|---|")
    clingo_ms = {("sw", "fixed"): "10 (optimum 10 instr, 0.07 s)",
                 ("sw", "free"): "9 (SAT T=9 1.3 s; UNSAT T=8 114 s)"}
    for k, T in sorted(makespans.items()):
        lines.append(f"| {k[0]} | {k[1]} | {T} "
                     f"| {clingo_ms.get(k, '—')} |")
    lines.append("")

    lines.append("## Instruction-count minimization "
                 "(clingo `#minimize` parity)\n")
    lines.append(
        "Number of non-wait instructions at fixed t_max, minimized by "
        "downward linear search over `CardEnc.atmost` bounds with "
        "Cadical195; time is total wall clock of the whole search "
        "(encode + all solves). clingo reference: fixed t_max=10 optimum "
        "10 in 0.07 s; free t_max=10 found 9 in 12.4 s, optimality NOT "
        "proved in 300 s; fixed slack t_max=16/20 both >300 s without "
        "its opt-in `nowait.lp` symmetry breaker (1.9 s with it).\n")
    lines.append("| instance | mode | t_max | best (non-wait) | proved "
                 "optimal | total s | note |")
    lines.append("|---|---|---|---|---|---|---|")
    for o in opt_results:
        lines.append(
            f"| {o['case']} | {o['mode']} | {o['t_max']} "
            f"| {o['optimum'] if o['optimum'] is not None else '—'} "
            f"| {'yes' if o['proved'] else 'NO'} | {o['total_t']:.3f} "
            f"| {o['note'] or ''} |")
    lines.append("")

    if scaling_rows:
        lines.append("## Free-layout board-radius scaling "
                     "(tractability probe)\n")
        lines.append(
            "The same sw puzzle with the free-layout search space blown "
            "up to radius-3/4/5 boards (37/61/91 hexes; the CNF grows "
            "roughly quadratically in board size because rigid-rotation "
            "clauses range over base × hex).\n")
        lines.append("| instance | backend | T | vars | clauses | "
                     "encode s | solve s | result |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in scaling_rows:
            lines.append(
                f"| {r['case']} | {r['backend']} | {r['T']} | {r['nvars']} "
                f"| {r['nclauses']} | {r['encode_t']:.3f} "
                f"| {r['solve_t']:.3f} | {r['result']} |")
        lines.append("")

    lines.append("## Decoded minimum-makespan plans (Cadical195 models, "
                 "validator-approved)\n")
    for k in sorted(plans):
        name, mode = k if isinstance(k, tuple) else (k, "free")
        inst = (SW_CASES.get(name)
                or sw_scaled(int(name.split("-r")[1])))
        lines.append(f"### {name}, {mode} layout (T={makespans[k]})\n")
        lines.append("```")
        lines.append(format_plan2(plans[k], inst))
        lines.append("```\n")

    lines.append("## Validation\n")
    lines.append(
        "Every SAT model above was decoded (sat/decode2.py) and "
        "re-simulated by the independent validator (sat/validate2.py), "
        "which shares no logic with the encoder: layout sanity + part "
        "non-overlap, gripper on-board, legal grabs/drops, rigid "
        "component motion, collision/base-blocking checks, calcification "
        "timing, bounded-pool respawn timing, bond formation, and the "
        "exact-dimer (+ product-hex) goal, plus a per-timestep diff "
        "against the decoded trajectories. All passed. The sw-omsim plan "
        "was additionally exported to a game-format .solution file and "
        "accepted by omsim (see sat/NOTES.md).\n")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
