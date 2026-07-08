#!/usr/bin/env python3
"""Emit a real Opus Magnum .solution (v7) file for P007 (Stabilized Water)
from the Z3 fixed-layout plan, for ground-truth validation with omsim.

Coordinate/rotation mapping (verified against a decoded reference solution
for P007, see NOTES.md):
  * omsim part positions are axial (u,v) pairs == our (q,r);
  * omsim rotation integers index the same clockwise dir table
    dir0=(1,0) dir1=(0,1) ... dir5=(1,-1);
  * the .solution instruction letter 'r' rotates dir d -> d+1 (== our
    rot_cw) and 'R' rotates d -> d-1 (== our rot_ccw).  (omsim labels 'r'
    "ccw" -- same operation, opposite visual naming convention.)

The simplified semantics are serialized and single-arm here, so the plan's
step indices map 1:1 onto omsim cycles (wait = blank tape cell).  omsim
tapes loop, and victory needs 6 products, so the tape must be a fixed
point: we append the rotations that return the arm to its initial
orientation.  Inputs respawn whenever their hex clears (the plan never
re-enters a vacated input hex, checked below).

Usage: python3 z3/emit_omsim.py [--plan z3/solutions/water-fixed.json]
                                [--out z3/solutions/water-z3.solution]
Then:  omsim -p P007.puzzle z3/solutions/water-z3.solution
"""

import argparse
import json
import os
import struct

DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]
LETTER = {"grab": b"G", "drop": b"g", "rot_cw": b"r", "rot_ccw": b"R"}

HERE = os.path.dirname(os.path.abspath(__file__))


def string(s):
    b = s.encode()
    assert len(b) < 128
    return bytes([len(b)]) + b


def part(name, pos, rot, which=0, size=1, instrs=(), arm_number=0):
    out = string(name)
    out += bytes([1])  # magic
    out += struct.pack("<ii", pos[0], pos[1])
    out += struct.pack("<I", size)
    out += struct.pack("<i", rot)
    out += struct.pack("<I", which)
    out += struct.pack("<I", len(instrs))
    for cycle, letter in instrs:
        out += struct.pack("<i", cycle) + letter
    out += struct.pack("<I", arm_number)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=os.path.join(HERE, "solutions", "water-fixed.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "solutions", "water-z3.solution"))
    args = ap.parse_args()

    with open(args.plan) as f:
        sol = json.load(f)
    lay = sol["layout"]
    assert len(lay["arms"]) == 1, "emitter maps single-arm plans only"
    arm = lay["arms"][0]
    base = tuple(arm["base"])
    assert arm["length"] == 1

    # sanity: the plan must not move an atom back onto a vacated input hex
    # (omsim inputs respawn as soon as the hex clears)
    inputs = [tuple(tr[0]) for tr in sol["atom_trajectories"].values()]
    for name, tr in sol["atom_trajectories"].items():
        start = tuple(tr[0])
        away = False
        for p in map(tuple, tr):
            if p != start:
                away = True
                if p in inputs:
                    raise SystemExit(
                        f"{name} enters input hex {p}; tape would collide with a respawned input"
                    )
            elif away:  # returned to its own (respawned) input hex
                raise SystemExit(f"{name} re-enters its input hex {start}")

    # arm tape: plan actions at their step indices, then close the loop by
    # rotating back to the initial orientation
    instrs = []
    for a in sol["actions"]:
        if a["action"] == "wait":
            continue
        instrs.append((a["t"], LETTER[a["action"]]))
    final_o = sol["orientations"][arm["name"]][sol["horizon"]]
    delta = (arm["init_orient"] - final_o) % 6
    cyc = sol["horizon"]
    letters = [b"r"] * delta if delta <= 3 else [b"R"] * (6 - delta)
    for m in letters:
        instrs.append((cyc, m))
        cyc += 1

    parts = []
    for k, p in enumerate(inputs):
        parts.append(part("input", p, 0, which=k))
    parts.append(part("arm1", base, arm["init_orient"], size=1, instrs=instrs, arm_number=0))
    for g in lay["glyph_calcs"]:
        parts.append(part("glyph-calcification", (g[0], g[1]), 0))
    for g in lay["glyph_bonds"]:
        (q1, r1, q2, r2) = g
        rot = DIRS.index((q2 - q1, r2 - r1))
        parts.append(part("bonder", (q1, r1), rot))
    # output: product = salt local (0,0) bonded to water local (1,0);
    # the Z3 product slots are salt@(-1,0), water@(0,-1) -> position at the
    # salt slot, rotated so local (1,0) lands on the water slot
    salt_slot, water_slot = (-1, 0), (0, -1)
    rot = DIRS.index((water_slot[0] - salt_slot[0], water_slot[1] - salt_slot[1]))
    parts.append(part("out-std", salt_slot, rot, which=0))

    blob = struct.pack("<I", 7)  # version
    blob += string("P007")  # puzzle name
    blob += string("Z3")  # solution name
    blob += struct.pack("<I", 0)  # unsolved (omsim computes metrics)
    blob += struct.pack("<I", len(parts))
    blob += b"".join(parts)

    with open(args.out, "wb") as f:
        f.write(blob)
    print(f"wrote {args.out} ({len(blob)} bytes, {len(instrs)} arm instructions)")


if __name__ == "__main__":
    main()
