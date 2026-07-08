#!/usr/bin/env python3
"""Tests for the incumbent store (selfplay/leaderboard/store.py).

Run either way:
    python3 selfplay/leaderboard/tests/test_store.py
    python3 -m pytest selfplay/leaderboard/tests/
"""

import copy
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.dirname(HERE))
from store import IncumbentStore  # noqa: E402

PUZZLES = os.path.join(REPO, "harness", "puzzles")
PLANS = os.path.join(REPO, "harness", "tests", "plans")


def case(name):
    with open(os.path.join(PUZZLES, name + ".json")) as f:
        puzzle = json.load(f)
    with open(os.path.join(PLANS, name + "_good.json")) as f:
        plan = json.load(f)
    return puzzle, plan


def wait_shifted(plan):
    """A strictly-worse-on-makespan but still valid variant."""
    worse = copy.deepcopy(plan)
    for ins in worse["instructions"]:
        ins["t"] += 1
    worse["instructions"].insert(
        0, {"t": 0, "arm": plan["instructions"][0]["arm"], "action": "wait"}
    )
    return worse


def test_first_submission_sets_all_incumbents():
    puzzle, plan = case("single_transport")
    store = IncumbentStore(path=None)
    result = store.submit(puzzle, plan, source="ref")
    assert result["accepted"]
    improved = {i["metric"] for i in result["improved"]}
    assert "instructions" in improved and "makespan" in improved
    assert all(i["old"] is None and i["delta"] is None for i in result["improved"])
    assert store.incumbent("single_transport", "makespan")["score"] == 5


def test_invalid_plan_rejected_and_changes_nothing():
    puzzle, plan = case("single_transport")
    bad = copy.deepcopy(plan)
    bad["instructions"][0]["action"] = "drop"
    store = IncumbentStore(path=None)
    result = store.submit(puzzle, bad)
    assert not result["accepted"]
    assert "drops with an empty hand" in result["reason"]
    assert result["improved"] == []
    assert store.records == {}


def test_better_plan_beats_incumbent_with_delta():
    puzzle, plan = case("single_transport")
    store = IncumbentStore(path=None)
    store.submit(puzzle, wait_shifted(plan), source="worse")  # makespan 6
    result = store.submit(puzzle, plan, source="better")  # makespan 5
    beaten = {i["metric"]: i for i in result["improved"]}
    assert "makespan" in beaten
    imp = beaten["makespan"]
    assert (imp["old"], imp["new"], imp["delta"]) == (6, 5, 1)
    rec = store.incumbent("single_transport", "makespan")
    assert rec["source"] == "better" and rec["score"] == 5
    # instructions were equal (ties do NOT replace the incumbent)
    assert store.incumbent("single_transport", "instructions")["source"] == "worse"


def test_persistence_round_trip():
    puzzle, plan = case("two_atom_bond")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "incumbents.json")
        store = IncumbentStore(path)
        store.submit(puzzle, plan, source="ref")
        reloaded = IncumbentStore(path)
        rec = reloaded.incumbent("two_atom_bond", "instructions")
        assert rec["score"] == 12
        assert rec["plan"]["instructions"] == plan["instructions"]
        # a duplicate submission after reload improves nothing
        result = reloaded.submit(puzzle, plan, source="ref2")
        assert result["accepted"] and result["improved"] == []


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
