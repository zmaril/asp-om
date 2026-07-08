"""Export a SAT plan for the sw-omsim instance as a game-format .solution
file and verify it with omsim (ianh's cycle-accurate Opus Magnum
simulator) against the real campaign puzzle file P007.puzzle.

Mapping (design brief section 6):
  * parts: input (reagent) at the spawn hex; glyph-calcification at the
    calcifier hex; bonder at the bonder cells (rotation = cell direction);
    out-std at the product salt hex with rotation = direction from the
    salt cell to the water cell; arm1 at the arm base, size 1, rotation =
    initial orientation.
  * instruction letters: clingo/SAT rot_cw -> 'r' (the game calls this
    counterclockwise -- naming caveat in the brief), rot_ccw -> 'R',
    grab -> 'G', drop -> 'g', wait -> no instruction at that cycle.
  * a trailing 'X' (reset: one cycle, returns the arm to its initial
    rotation and releases the grip) closes the loop so omsim can run the
    tape periodically until the game's required 6 products are delivered.

The modeled fragment ignores output consumption and unbounded inputs, so
the instance used here (sw-omsim) was built for faithful export: parts
laid out exactly like the known-good reference solution (no overlaps,
output cells distinct from all parts) and the goal requires the dimer to
rest exactly on the output cells.

Usage: python3 sat/export_omsim.py [--horizon N] [--out FILE]
                                   [--omsim BIN --puzzle FILE]
"""

import argparse
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from instances import SW_CASES, DIRS
from encode2 import Encoder2
from solvers import solve
from decode2 import decode_model2, format_plan2
from validate2 import validate_plan2

SCRATCH = ("/tmp/claude-0/-workspace-asp-om/"
           "231137e8-aa53-5099-b493-86deb373db42/scratchpad")
DEFAULT_OMSIM = os.path.join(SCRATCH, "omsim", "omsim")
DEFAULT_PUZZLE = os.path.join(SCRATCH, "omsim", "test", "puzzle",
                              "campaign", "ch1-and-prologue",
                              "P007.puzzle")

LETTERS = {"rot_cw": b"r", "rot_ccw": b"R", "grab": b"G", "drop": b"g"}


def _string(s):
    b = s.encode()
    assert len(b) < 128
    return bytes([len(b)]) + b


def _part(name, pos, size, rotation, io, instrs, arm_number):
    out = _string(name)
    out += bytes([1])
    out += struct.pack("<iiIi", pos[0], pos[1], size, rotation)
    out += struct.pack("<I", io)
    out += struct.pack("<I", len(instrs))
    for idx, letter in instrs:
        out += struct.pack("<i", idx) + letter
    out += struct.pack("<I", arm_number)
    return out


def solution_bytes(inst, plan, solution_name="SAT-ARM"):
    """Build the .solution byte string from a validated sw-omsim plan."""
    T = len(plan["instructions"])
    salt_hex = inst.products["salt"]
    water_hex = inst.products["water"]
    out_dir = DIRS.index((water_hex[0] - salt_hex[0],
                          water_hex[1] - salt_hex[1]))
    tape = [(t, LETTERS[a]) for t, a in enumerate(plan["instructions"])
            if a != "wait"]
    tape.append((T, b"X"))  # reset: close the loop for repeated products

    out = struct.pack("<I", 7)          # magic
    out += _string("P007")              # puzzle name
    out += _string(solution_name)
    out += struct.pack("<I", 0)         # unsolved header
    parts = []
    for i, spawn in enumerate(plan["spawns"]):
        parts.append(_part("input", spawn, 1, 0, i, [], 0))
    parts.append(_part("out-std", salt_hex, 1, out_dir, 0, [], 0))
    parts.append(_part("glyph-calcification", plan["calc"], 1, 0, 0, [], 0))
    gp = plan["glyph"][0]
    gd = DIRS.index((plan["glyph"][1][0] - gp[0],
                     plan["glyph"][1][1] - gp[1]))
    parts.append(_part("bonder", gp, 1, gd, 0, [], 0))
    parts.append(_part("arm1", plan["base"], 1, plan["orient0"], 0,
                       tape, 0))
    out += struct.pack("<I", len(parts)) + b"".join(parts)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=None,
                    help="use this horizon (default: iterate to first SAT)")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "p007-sat.solution"))
    ap.add_argument("--omsim", default=DEFAULT_OMSIM)
    ap.add_argument("--puzzle", default=DEFAULT_PUZZLE)
    ap.add_argument("--backend", default="cadical195")
    args = ap.parse_args()

    inst = SW_CASES["sw-omsim"]
    horizons = ([args.horizon] if args.horizon
                else range(1, inst.t_max_default + 1))
    plan = None
    for T in horizons:
        enc = Encoder2(inst, T)
        sat, model, st = solve(args.backend, enc.cnf,
                               enc.layout_assumptions(), timeout=300)
        print(f"T={T}: {'SAT' if sat else 'UNSAT' if sat is False else 'TIMEOUT'}"
              f" in {st:.3f}s")
        if sat:
            plan = decode_model2(enc, model)
            break
    if plan is None:
        sys.exit("no plan found")

    errs = validate_plan2(inst, plan)
    if errs:
        for e in errs:
            print("VALIDATION ERROR:", e)
        sys.exit(1)
    print(format_plan2(plan, inst))
    print("validator: plan is valid")

    data = solution_bytes(inst, plan)
    with open(args.out, "wb") as f:
        f.write(data)
    print(f"wrote {args.out} ({len(data)} bytes)")

    if os.path.exists(args.omsim) and os.path.exists(args.puzzle):
        res = subprocess.run([args.omsim, "-p", args.puzzle, args.out],
                             capture_output=True, text=True, timeout=120)
        print("omsim stdout:", res.stdout.strip())
        if res.stderr.strip():
            print("omsim stderr:", res.stderr.strip())
        sys.exit(0 if res.returncode == 0 and res.stdout.strip() else 2)
    else:
        print("omsim binary or puzzle file not found; skipped verification")


if __name__ == "__main__":
    main()
