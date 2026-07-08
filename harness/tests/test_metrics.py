#!/usr/bin/env python3
"""Tests for harness/metrics.py.

The core positive test is a fully hand-worked example: the
single_transport reference plan, whose replay is short enough to trace
on paper (the trace is written out below), so every implemented metric
is checked against a number derived by hand, not by the code under test.

Run either way:
    python3 harness/tests/test_metrics.py     # plain script
    python3 -m pytest harness/tests/          # pytest
"""

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from metrics import (  # noqa: E402  (import must follow the sys.path setup above)
    METRICS,
    compute_metrics,
    leaderboard_metrics,
    part_cost,
)

from validate import Invalid  # noqa: E402

PUZZLES = os.path.join(os.path.dirname(HERE), "puzzles")
PLANS = os.path.join(HERE, "plans")


def load(kind, name):
    d = PUZZLES if kind == "puzzle" else PLANS
    with open(os.path.join(d, name + ".json")) as f:
        return json.load(f)


def case(name):
    return load("puzzle", name), load("plan", name + "_good")


# ---------------------------------------------------------------------------
# Hand-worked example: single_transport reference plan.
#
# Layout: arm m1 base (0,0) len 1 dir 0 (gripper (1,0)); input salt at
# (1,0); output at (-1,0).
# Replay (state t: atom hex / arm dir):
#   t=0  atom (1,0)   dir 0   -- grab at t=0
#   t=1  atom (1,0)   dir 0   -- rot_cw
#   t=2  atom (0,1)   dir 1   -- rot_cw
#   t=3  atom (-1,1)  dir 2   -- rot_cw
#   t=4  atom (-1,0)  dir 3   -- drop
#   t=5  atom (-1,0)  dir 3   -- product complete at t=5
# instructions = 5 (no waits), makespan = 5.
# area: footprints {(0,0) arm base, (1,0) input, (-1,0) output}
#   + gripper hexes {(1,0),(0,1),(-1,1),(-1,0)}
#   + atom hexes    {(1,0),(0,1),(-1,1),(-1,0)}
#   union = {(0,0),(1,0),(0,1),(-1,1),(-1,0)}  ->  area = 5.
# cost: one arm = 20 (omsim price table).
# composites: sum = 20+5+5 = 30; sum4 = 35; G*C*A = 500; G*C = 100;
#   G*A = 100; C*A = 25.
# ---------------------------------------------------------------------------
def test_hand_worked_single_transport():
    puzzle, plan = case("single_transport")
    m = compute_metrics(puzzle, plan)
    assert m["instructions"] == 5, m
    assert m["makespan"] == 5, m
    assert m["area"] == 5, m
    assert m["cost"] == 20, m
    assert m["sum"] == 30, m
    assert m["sum4"] == 35, m
    assert m["product_gca"] == 500, m
    assert m["product_gc"] == 100, m
    assert m["product_ga"] == 100, m
    assert m["product_ca"] == 25, m


def test_cost_price_table():
    # two_atom_bond: arm 20 + bonder 10; stabilized_water: + calcifier 10
    puzzle, plan = case("two_atom_bond")
    assert compute_metrics(puzzle, plan)["cost"] == 30
    puzzle, plan = case("stabilized_water")
    assert compute_metrics(puzzle, plan)["cost"] == 40


def test_cost_prices_parameterizable():
    puzzle, plan = case("two_atom_bond")
    assert part_cost(puzzle, plan, prices={"bonder": 25}) == 45


def test_makespan_matches_validator_completion():
    puzzle, plan = case("two_atom_bond")
    m = compute_metrics(puzzle, plan)
    assert m["makespan"] == 12  # salt_dimer completes at t=12
    assert m["instructions"] == 12
    puzzle, plan = case("stabilized_water")
    m = compute_metrics(puzzle, plan)
    assert m["makespan"] == 13
    assert m["instructions"] == 13


def test_wait_shift_costs_makespan_but_not_instructions_or_area():
    # a leading explicit wait delays completion by one step; the used-hex
    # set is unchanged (same layout, same trajectory, shifted in time)
    puzzle, plan = case("single_transport")
    base = compute_metrics(puzzle, plan)
    shifted = copy.deepcopy(plan)
    for ins in shifted["instructions"]:
        ins["t"] += 1
    shifted["instructions"].insert(0, {"t": 0, "arm": "m1", "action": "wait"})
    m = compute_metrics(puzzle, shifted)
    assert m["makespan"] == base["makespan"] + 1
    assert m["instructions"] == base["instructions"]
    assert m["area"] == base["area"]


def test_junk_tail_costs_instructions_but_not_makespan_or_area():
    # a pointless rotation after the product is already complete counts
    # against instructions but not against the @V metrics
    puzzle, plan = case("stabilized_water")
    base = compute_metrics(puzzle, plan)
    junk = copy.deepcopy(plan)
    junk["instructions"].append({"t": 13, "arm": "m1", "action": "rot_cw"})
    m = compute_metrics(puzzle, junk)
    assert m["instructions"] == base["instructions"] + 1
    assert m["makespan"] == base["makespan"]
    assert m["area"] == base["area"]


def test_area_two_atom_bond_hand_count():
    puzzle, plan = case("two_atom_bond")
    m = compute_metrics(puzzle, plan)
    # hand count: footprints (0,0),(1,0),(0,1),(-1,0),(-1,1),(0,-1),(1,-1)
    # (arm base, 2 inputs, 2 bonder hexes, 2 output hexes) = 7 hexes; the
    # replay only ever moves atoms/gripper around ring 1 -> area = 7
    assert m["area"] == 7, m


def test_invalid_plan_raises():
    puzzle, plan = case("single_transport")
    plan = copy.deepcopy(plan)
    plan["instructions"][0]["action"] = "drop"  # drop with empty hand
    try:
        compute_metrics(puzzle, plan)
    except Invalid:
        return
    raise AssertionError("metrics were computed for an invalid plan")


def test_flags_and_stubs():
    puzzle, plan = case("single_transport")
    m = compute_metrics(puzzle, plan)
    assert m["trackless"] is True  # vacuous: track not modeled
    assert m["overlap"] is False  # vacuous: validator forbids it
    assert m["rate"] is None  # stubbed: needs steady-state
    assert m["area_at_infinity"] is None
    assert m["looping"] is None
    for name in METRICS:
        assert name in m, f"registry metric {name} missing from output"


def test_leaderboard_metrics_are_real_and_numeric():
    puzzle, plan = case("single_transport")
    m = compute_metrics(puzzle, plan)
    names = leaderboard_metrics()
    assert "instructions" in names and "rate" not in names
    for name in names:
        assert not METRICS[name].stubbed
        assert isinstance(m[name], int), (name, m[name])


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
