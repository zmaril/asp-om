#!/usr/bin/env python3
"""Solver-as-teacher for Loop 1 (expert iteration).

The teacher takes a proposal (a machine layout in the harness plan
format, empty instruction tape) and asks an EXACT solver -- the clingo
adapter, harness/adapters/clingo/adapter.py -- to complete it into a
valid plan or prove that no completion exists.

Coupling (the real one, not a scaffold): the proposal's placements are
written into a copy of the puzzle JSON as PINS (the "position"/
"rotation" fields of SPEC.md section 3). The adapter turns pins into
facts (base/init_orient/spawn/out_at/calc_at/bond_at), so the solver's
layout choice rules collapse to the proposed layout and the solver
only searches for the instruction tape. This makes "the teacher
completes the proposal" literally true: any plan returned uses exactly
the proposed machine.

Relaxation: if the seeded solve returns UNSAT or times out, the
proposal is dynamically infeasible (or too hard to complete within the
timebox); the teacher then falls back to solving the ORIGINAL,
unpinned puzzle from scratch. That from-scratch solution is cached per
puzzle (it is the expensive call -- free layout is the hard part) and
serves as the reference the proposal is scored against.

All solver calls run in a subprocess with a hard timeout on top of the
adapter's own --time-limit; clingo can hang on anything nontrivial.

Competence ceiling observed on this machine (see README.md): free-
layout solves are ~0.1s for single_transport (1 arm, t_max=6) but
already need the full 60s budget to find (not prove) an 11-instruction
plan for two_atom_bond (1 arm + 1 bonder, t_max=13). Pinned-layout
(seeded) solves stay ~0.2s on both, UNSAT included -- seeding is what
keeps this loop fast.
"""

import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ADAPTER = os.path.join(REPO, "harness", "adapters", "clingo", "adapter.py")


def pin_puzzle(puzzle, proposal):
    """Copy the puzzle with every proposed placement written as a pin."""
    p = copy.deepcopy(puzzle)
    by_id = {}
    for pl in proposal["placements"]:
        by_id[(pl["type"], pl["id"])] = pl
    for part in p["parts"]:
        pl = by_id.get((part["type"], part["id"]))
        if pl:
            part["position"] = list(pl["position"])
            if part["type"] != "calcifier":
                part["rotation"] = pl.get("rotation", 0)
    for kind, ptype in (("reagents", "input"), ("products", "output")):
        for m in p[kind]:
            pl = by_id.get((ptype, m["id"]))
            if pl:
                m["position"] = list(pl["position"])
                m["rotation"] = pl.get("rotation", 0)
    return p


class ClingoTeacher:
    """Expert teacher wrapping the clingo adapter CLI."""

    def __init__(self, scratch_dir, seeded_limit=15.0, relaxed_limit=60.0):
        self.scratch_dir = scratch_dir
        self.seeded_limit = seeded_limit
        self.relaxed_limit = relaxed_limit
        self._relaxed_cache = {}  # puzzle name -> plan dict or None
        os.makedirs(scratch_dir, exist_ok=True)

    def _run_adapter(self, puzzle, time_limit, tag):
        """One timeboxed adapter call. Returns (plan_or_None, note)."""
        pz = os.path.join(self.scratch_dir, f"{tag}.puzzle.json")
        out = os.path.join(self.scratch_dir, f"{tag}.plan.json")
        with open(pz, "w") as f:
            json.dump(puzzle, f)
        try:
            r = subprocess.run(
                [sys.executable, ADAPTER, pz, "--time-limit", str(time_limit), "--out", out],
                capture_output=True,
                text=True,
                timeout=time_limit + 15,
            )  # hard stop over clingo's own limit
        except subprocess.TimeoutExpired:
            return None, "subprocess timeout"
        if r.returncode != 0:
            return None, r.stderr.strip().splitlines()[-1] if r.stderr else f"exit {r.returncode}"
        with open(out) as f:
            return json.load(f), r.stderr.strip()

    def relaxed_solve(self, puzzle):
        """From-scratch (free layout) reference solution, cached."""
        name = puzzle["name"]
        if name not in self._relaxed_cache:
            plan, _note = self._run_adapter(puzzle, self.relaxed_limit, f"{name}.relaxed")
            self._relaxed_cache[name] = plan
        return self._relaxed_cache[name]

    def teach(self, puzzle, proposal):
        """Complete the proposal into a valid plan, or relax.

        Returns {"mode": "seeded"|"relaxed"|"none",
                 "seeded_ok": bool,   # the proposed layout admits a plan
                 "plan": plan dict or None,
                 "note": adapter diagnostics}
        """
        pinned = pin_puzzle(puzzle, proposal)
        plan, note = self._run_adapter(pinned, self.seeded_limit, f"{puzzle['name']}.seeded")
        if plan is not None:
            return {"mode": "seeded", "seeded_ok": True, "plan": plan, "note": note}
        relaxed = self.relaxed_solve(puzzle)
        if relaxed is not None:
            return {"mode": "relaxed", "seeded_ok": False, "plan": relaxed, "note": note}
        return {"mode": "none", "seeded_ok": False, "plan": None, "note": note}
