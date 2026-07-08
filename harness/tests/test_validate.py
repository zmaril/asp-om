#!/usr/bin/env python3
"""Tests for the canonical harness validator.

Positive tests: the three hand-written reference plans in tests/plans/
PASS on the shipped puzzle instances.
Negative tests: systematically broken plans (bad grab, collision, wrong
product, missing bond, out-of-bounds, overlapping parts, ...) must FAIL
with the expected error.

Run either way:
    python3 harness/tests/test_validate.py     # plain script
    python3 -m pytest harness/tests/           # pytest
"""

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from validate import Invalid, Malformed, validate  # noqa: E402

PUZZLES = os.path.join(os.path.dirname(HERE), "puzzles")
PLANS = os.path.join(HERE, "plans")


def load(kind, name):
    d = PUZZLES if kind == "puzzle" else PLANS
    with open(os.path.join(d, name + ".json")) as f:
        return json.load(f)


def case(name):
    return load("puzzle", name), load("plan", name + "_good")


def expect_fail(puzzle, plan, needle, exc=Invalid):
    try:
        validate(puzzle, plan)
    except exc as e:
        assert needle in str(e), f"expected failure containing {needle!r}, got: {e}"
        return
    raise AssertionError(f"plan was accepted but should have failed with {needle!r}")


# ---------------------------------------------------------------------------
# Positive: the three reference plans pass
# ---------------------------------------------------------------------------
def test_good_single_transport():
    puzzle, plan = case("single_transport")
    assert validate(puzzle, plan) == {"salt_out": 5}


def test_good_two_atom_bond():
    puzzle, plan = case("two_atom_bond")
    assert validate(puzzle, plan) == {"salt_dimer": 12}


def test_good_stabilized_water():
    puzzle, plan = case("stabilized_water")
    assert validate(puzzle, plan) == {"stabilized_water": 13}


def test_explicit_waits_are_legal_and_free():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    for ins in plan["instructions"]:
        ins["t"] += 1  # shift plan right ...
    plan["instructions"].insert(0, {"t": 0, "arm": "m1", "action": "wait"})
    assert validate(puzzle, plan) == {"salt_out": 6}


def test_bonder_flip_equivalence():
    # (p, k) and (p + dir[k], k+3) denote the same bonder
    puzzle, plan = case("two_atom_bond")
    plan = copy.deepcopy(plan)
    b = next(p for p in plan["placements"] if p["type"] == "bonder")
    assert (b["position"], b["rotation"]) == ([-1, 0], 1)
    b["position"], b["rotation"] = [-1, 1], 4
    validate(puzzle, plan)


# ---------------------------------------------------------------------------
# Negative: illegal actions
# ---------------------------------------------------------------------------
def test_grab_over_empty_hex():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    # rotate away first: the gripper then hovers over an empty hex
    plan["instructions"][0]["action"] = "rot_cw"
    plan["instructions"][1]["action"] = "grab"
    expect_fail(puzzle, plan, "grabs over empty hex")


def test_grab_with_full_hand():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    plan["instructions"][1] = {"t": 1, "arm": "m1", "action": "grab"}
    expect_fail(puzzle, plan, "grabs with a full hand")


def test_drop_with_empty_hand():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    plan["instructions"][0]["action"] = "drop"
    expect_fail(puzzle, plan, "drops with an empty hand")


def test_collision():
    # swinging salt_a clockwise from (1,0) lands it on salt_b at (0,1)
    puzzle, plan = case("two_atom_bond")
    plan = copy.deepcopy(plan)
    plan["instructions"][1]["action"] = "rot_cw"
    expect_fail(puzzle, plan, "collide")


def test_two_instructions_same_timestep():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    plan["instructions"].append({"t": 0, "arm": "m1", "action": "rot_cw"})
    expect_fail(puzzle, plan, "two instructions at t=0")


def test_instruction_beyond_horizon():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    plan["instructions"].append({"t": 99, "arm": "m1", "action": "grab"})
    expect_fail(puzzle, plan, "outside the horizon")


def test_unknown_action():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    plan["instructions"][0]["action"] = "pivot"
    expect_fail(puzzle, plan, "unknown action")


def test_unknown_arm():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    plan["instructions"][0]["arm"] = "m9"
    expect_fail(puzzle, plan, "unknown arm")


# ---------------------------------------------------------------------------
# Negative: layout problems
# ---------------------------------------------------------------------------
def test_gripper_off_board():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    arm = next(p for p in plan["placements"] if p["type"] == "arm")
    arm["position"] = [2, 0]  # gripper at (3,0): off a radius-2 board
    expect_fail(puzzle, plan, "off the board")


def test_part_footprint_off_board():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    out = next(p for p in plan["placements"] if p["type"] == "output")
    out["position"] = [3, 0]
    expect_fail(puzzle, plan, "off the board")


def test_overlapping_parts():
    puzzle, plan = case("two_atom_bond")
    plan = copy.deepcopy(plan)
    b = next(p for p in plan["placements"] if p["type"] == "bonder")
    b["position"], b["rotation"] = [1, 0], 1  # on top of input salt_a
    expect_fail(puzzle, plan, "footprints overlap")


def test_missing_placement():
    puzzle, plan = case("two_atom_bond")
    plan = copy.deepcopy(plan)
    plan["placements"] = [p for p in plan["placements"] if p["type"] != "output"]
    expect_fail(puzzle, plan, "never places an output")


def test_pinned_placement_violated():
    puzzle, plan = case("single_transport")
    puzzle = copy.deepcopy(puzzle)
    puzzle["parts"][0]["position"] = [0, 1]  # pin the arm elsewhere
    expect_fail(puzzle, plan, "pins position")


def test_arm_length_must_match_puzzle():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    arm = next(p for p in plan["placements"] if p["type"] == "arm")
    arm["length"] = 2
    expect_fail(puzzle, plan, "length")


# ---------------------------------------------------------------------------
# Negative: goal problems
# ---------------------------------------------------------------------------
def test_wrong_delivery_location():
    # product ends up on (0,-1)/(1,-1); the output part sits elsewhere
    puzzle, plan = case("two_atom_bond")
    plan = copy.deepcopy(plan)
    out = next(p for p in plan["placements"] if p["type"] == "output")
    out["position"] = [0, -2]
    expect_fail(puzzle, plan, "goal not reached")


def test_incomplete_bond():
    # park both atoms on the output hexes without ever visiting the bonder
    puzzle, plan = case("two_atom_bond")
    plan = copy.deepcopy(plan)
    plan["instructions"] = [
        {"t": 0, "arm": "m1", "action": "grab"},  # salt_a @ (1,0)
        {"t": 1, "arm": "m1", "action": "rot_ccw"},  # -> (1,-1)
        {"t": 2, "arm": "m1", "action": "rot_ccw"},  # -> (0,-1)
        {"t": 3, "arm": "m1", "action": "drop"},
        {"t": 4, "arm": "m1", "action": "rot_cw"},  # d5
        {"t": 5, "arm": "m1", "action": "rot_cw"},  # d0
        {"t": 6, "arm": "m1", "action": "rot_cw"},  # d1: over salt_b @ (0,1)
        {"t": 7, "arm": "m1", "action": "grab"},
        {"t": 8, "arm": "m1", "action": "rot_ccw"},  # salt_b -> (1,0)
        {"t": 9, "arm": "m1", "action": "rot_ccw"},  # salt_b -> (1,-1)
        {"t": 10, "arm": "m1", "action": "drop"},
    ]
    expect_fail(puzzle, plan, "goal not reached")


def test_wrong_product_type():
    # move the calcifier away: the first water never becomes salt, so the
    # delivered molecule is water-water, not salt-water
    puzzle, plan = case("stabilized_water")
    plan = copy.deepcopy(plan)
    calc = next(p for p in plan["placements"] if p["type"] == "calcifier")
    calc["position"] = [0, 2]
    expect_fail(puzzle, plan, "goal not reached")


def test_held_product_does_not_count():
    # same plan minus the final drop: the molecule rests on the output
    # hexes but is still held
    puzzle, plan = case("stabilized_water")
    plan = copy.deepcopy(plan)
    plan["instructions"] = plan["instructions"][:-1]
    expect_fail(puzzle, plan, "goal not reached")


def test_excess_bonds_rejected():
    # a salt trimer contains a salt dimer, but exact-degree matching must
    # reject it: give salt_b pool 2, bond a third atom onto the dimer, and
    # rest the chain so two of its atoms cover the output hexes exactly
    puzzle, plan = case("two_atom_bond")
    puzzle = copy.deepcopy(puzzle)
    puzzle["reagents"][1]["pool"] = 2
    puzzle["t_max"] = 20
    plan = copy.deepcopy(plan)
    plan["instructions"] += [
        # after t=11 the bonded dimer rests on (0,-1)/(1,-1) [the output];
        # fetch the respawned salt_b and bond it on: dimer completes at
        # t=12, but keep going and build a trimer overlapping the output
        {"t": 12, "arm": "m1", "action": "rot_ccw"},  # d3
        {"t": 13, "arm": "m1", "action": "rot_ccw"},  # d2
        {"t": 14, "arm": "m1", "action": "rot_ccw"},  # d1: over salt_b#2
        {"t": 15, "arm": "m1", "action": "grab"},
        {"t": 16, "arm": "m1", "action": "rot_cw"},  # -> (-1,1) bonder A
        {"t": 17, "arm": "m1", "action": "rot_cw"},  # -> (-1,0) bonder B
        {"t": 18, "arm": "m1", "action": "drop"},
    ]
    # the dimer legitimately completed at t=12, before the third atom
    # arrived -- that is fine and must PASS ...
    assert validate(puzzle, plan) == {"salt_dimer": 12}
    # ... but if the output only ever sees the trimer, exact matching must
    # reject it. Rebuild: bond all three atoms FIRST, then deliver.
    plan2 = copy.deepcopy(plan)
    plan2["instructions"] = [
        {"t": 0, "arm": "m1", "action": "grab"},  # salt_a @ (1,0)
        {"t": 1, "arm": "m1", "action": "rot_ccw"},
        {"t": 2, "arm": "m1", "action": "rot_ccw"},
        {"t": 3, "arm": "m1", "action": "rot_ccw"},  # salt_a -> (-1,0) = bonder B
        {"t": 4, "arm": "m1", "action": "drop"},
        {"t": 5, "arm": "m1", "action": "rot_ccw"},  # d2
        {"t": 6, "arm": "m1", "action": "rot_ccw"},  # d1: over salt_b#1
        {"t": 7, "arm": "m1", "action": "grab"},
        {"t": 8, "arm": "m1", "action": "rot_cw"},  # b#1 -> (-1,1) = bonder A; bond a-b1
        {"t": 9, "arm": "m1", "action": "rot_cw"},  # dimer swings: b#1 -> (-1,0), a -> (0,-1)
        {"t": 10, "arm": "m1", "action": "drop"},
        {"t": 11, "arm": "m1", "action": "rot_ccw"},  # d2
        {"t": 12, "arm": "m1", "action": "rot_ccw"},  # d1: over respawned salt_b#2
        {"t": 13, "arm": "m1", "action": "grab"},
        {
            "t": 14,
            "arm": "m1",
            "action": "rot_cw",
        },  # b#2 -> (-1,1) A; B holds b#1 => bond b1-b2 (trimer a-b1-b2)
        {
            "t": 15,
            "arm": "m1",
            "action": "rot_cw",
        },  # trimer swings: b#2->(-1,0), b#1->(0,-1), a->(1,-1)
        {"t": 16, "arm": "m1", "action": "drop"},
    ]
    # now atoms b#1@(0,-1) and a@(1,-1) cover the output hexes, both salt,
    # bonded to each other -- but b#1 also bonds to b#2: degree 2 != 1
    expect_fail(puzzle, plan2, "goal not reached")


# ---------------------------------------------------------------------------
# Negative: malformed inputs
# ---------------------------------------------------------------------------
def test_malformed_missing_instructions():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    del plan["instructions"]
    expect_fail(puzzle, plan, "instructions", exc=Malformed)


def test_malformed_bad_element():
    puzzle, plan = case("single_transport")
    puzzle = copy.deepcopy(puzzle)
    puzzle["reagents"][0]["atoms"][0]["element"] = "quicksilver"
    expect_fail(puzzle, plan, "unknown element", exc=Malformed)


def test_plan_for_wrong_puzzle():
    puzzle, _ = case("single_transport")
    _, plan = case("two_atom_bond")
    expect_fail(puzzle, plan, "plan is for puzzle")


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
