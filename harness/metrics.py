#!/usr/bin/env python3
"""Metric computation for the multi-solver Opus Magnum harness.

Given a puzzle JSON and a plan JSON, compute the solution metrics of the
self-competition leaderboard (selfplay/leaderboard/). Definitions follow
docs/metrics-survey.md (branch metrics-survey), which cross-checks every
metric against omsim; the deviations forced by this harness's simplified
world model (sequential arms, bounded board, one product copy -- see
harness/SPEC.md section 6) are called out per metric below.

Every metric is computed from the CANONICAL replay: this module calls
harness/validate.py's validate() with a state observer and never
re-implements the world semantics. compute_metrics() therefore raises
Invalid/Malformed on a bad plan -- metrics exist only for valid plans.

Implemented (the survey's "cheap tier"):
    instructions   non-wait instruction count (= the bench plan-length
                   metric; matches the game definition because the model
                   has no repeat/reset instructions and waits are free).
    makespan       time t at which the LAST product completes. This is
                   the model's stand-in for the game's "cycles" metric;
                   it is deliberately named makespan, not cycles, because
                   the model runs arms sequentially (one instruction per
                   timestep) while the game runs all arm tapes in
                   parallel (survey section 4.3).
    area           omsim-style used-hex count, measured run-to-victory
                   (states t = 0..makespan, the @V measure point):
                   part footprints + every hex covered by an arm's
                   grabber axis in any state + every hex any atom ever
                   occupies. Rotation-sweep hexes of length>=2 arms are
                   NOT counted (the shared instances only have length-1
                   arms, for which omsim adds no sweep hexes either).
    cost           sum of part prices over placed parts, from omsim's
                   price table (decode.c): arm 20, bonder 10,
                   calcifier 10; inputs and outputs are free. Prices are
                   parameterizable via the `prices` argument. Note: the
                   harness currently requires every puzzle part to be
                   placed, so cost cannot vary between plans for the
                   same puzzle until part selection becomes optional.
    sum / sum4 / product_* composites over (G=cost, C=makespan, A=area,
                   I=instructions), mirroring the leaderboard's Sum
                   (G+C+A), Sum4 (G+C+A+I), X (G*C*A) and the pairwise
                   product tiebreakers GC, GA, CA.

Constraint flags (reported, but vacuous under the current model -- they
are NOT leaderboard dimensions until the model can vary them):
    trackless      always True  (track is not modeled).
    overlap        always False (the validator enforces footprint
                   disjointness, which IS the no-overlap rule).

Stubbed (None), with the reason:
    rate, area_at_infinity, looping
                   All three need steady-state detection: the replay
                   would have to detect that the machine returns to an
                   identical past state (arm directions + held atoms +
                   atom grid + per-output counts) and then measure the
                   loop, omsim-style (steady-state.c). The current model
                   also lacks the prerequisites that make these metrics
                   meaningful: tape loops and multi-copy consuming
                   outputs (products complete once and are never
                   consumed, so no plan produces outputs forever).
                   TODO(steady-state): implement per survey section 4.3
                   items 5-6 once tape loops / 6-output victory land.

Importable API:
    compute_metrics(puzzle, plan, prices=None) -> dict  (raises Invalid)
    METRICS: {name: Metric} registry (ordering, comparability, stubs)
    leaderboard_metrics() -> [name] (the metrics worth competing on)

Usage:
    python3 harness/metrics.py <puzzle.json> <plan.json>
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from validate import (DIRS, Invalid, plan_length, resolve_layout,  # noqa: E402
                      transform, validate)

# omsim's part price table (decode.c L1298-1349), restricted to the part
# types the harness models. Inputs/outputs cost 0 there too.
PART_PRICES = {
    "arm": 20,          # 1-armed arm
    "bonder": 10,       # glyph of bonding
    "calcifier": 10,    # glyph of calcification
    "input": 0,
    "output": 0,
}


class Metric:
    """Static description of one metric.

    lower_is_better: ordering for the self-leaderboard (all current
        numeric metrics are minimized).
    stubbed: True = compute_metrics always returns None for it.
    competed: True = a sensible self-leaderboard dimension today
        (numeric, not stubbed, not vacuous under the current model).
    """

    def __init__(self, name, description, lower_is_better=True,
                 stubbed=False, competed=True):
        self.name = name
        self.description = description
        self.lower_is_better = lower_is_better
        self.stubbed = stubbed
        self.competed = competed


METRICS = {m.name: m for m in [
    Metric("instructions", "non-wait instruction count (I)"),
    Metric("makespan", "completion time of the last product "
                       "(sequential-arm stand-in for cycles, C)"),
    Metric("area", "used hexes, run-to-victory (A)"),
    Metric("cost", "part-price sum (G)"),
    Metric("sum", "G + C + A (leaderboard Sum)"),
    Metric("sum4", "G + C + A + I (leaderboard Sum4)"),
    Metric("product_gca", "G * C * A (leaderboard X)"),
    Metric("product_gc", "G * C"),
    Metric("product_ga", "G * A"),
    Metric("product_ca", "C * A"),
    Metric("trackless", "no track hexes -- vacuously True (track not "
                        "modeled)", competed=False),
    Metric("overlap", "parts share hexes -- vacuously False (validator "
                      "forbids it)", competed=False),
    Metric("rate", "steady-state cycles per output -- STUB, needs "
                   "steady-state detection", stubbed=True, competed=False),
    Metric("area_at_infinity", "asymptotic area -- STUB, needs "
                               "steady-state detection", stubbed=True,
           competed=False),
    Metric("looping", "returns to an identical past state -- STUB, needs "
                      "steady-state detection", stubbed=True,
           competed=False),
]}


def leaderboard_metrics():
    """Names of the metrics the self-leaderboard competes on."""
    return [m.name for m in METRICS.values() if m.competed]


def part_cost(puzzle, plan, prices=None):
    """Cost (G): price sum over the plan's placements.

    Unknown part types raise Invalid rather than silently pricing at 0,
    so the price table must grow with the model.
    """
    prices = dict(PART_PRICES, **(prices or {}))
    total = 0
    for pl in plan.get("placements", []):
        ptype = pl.get("type")
        if ptype not in prices:
            raise Invalid(f"cost: no price for part type {ptype!r} "
                          f"(pass it via `prices`)")
        total += prices[ptype]
    return total


def _footprint_hexes(puzzle, lay):
    """All hexes statically occupied by placed parts (omsim area part a)."""
    reagents = {m["id"]: m for m in puzzle["reagents"]}
    products = {m["id"]: m for m in puzzle["products"]}
    hexes = set()
    for a in lay.arms.values():
        hexes.add(a["base"])
    for rid, ipl in lay.inputs.items():
        for atom in reagents[rid]["atoms"]:
            hexes.add(transform(ipl["position"], ipl["rotation"],
                                tuple(atom["pos"])))
    for pid, opl in lay.outputs.items():
        for atom in products[pid]["atoms"]:
            hexes.add(transform(opl["position"], opl["rotation"],
                                tuple(atom["pos"])))
    hexes.update(lay.calcifiers.values())
    for h1, h2 in lay.bonders.values():
        hexes.add(h1)
        hexes.add(h2)
    return hexes


def compute_metrics(puzzle, plan, prices=None):
    """Compute all metrics for a plan; raises Invalid/Malformed if the
    plan does not validate (metrics are only defined for valid plans).

    Returns {metric name: value}; stubbed metrics are None.
    """
    lay = resolve_layout(puzzle, plan)
    states = []                     # (t, snapshot) straight from the replay
    complete_at = validate(puzzle, plan,
                           on_state=lambda t, s: states.append((t, s)))
    makespan = max(complete_at.values())

    # area: used hexes over states t = 0..makespan (@V measure point)
    used = _footprint_hexes(puzzle, lay)
    for t, snap in states:
        if t > makespan:
            break
        for mid, arm in lay.arms.items():
            d = DIRS[snap["orient"][mid]]
            bq, br = arm["base"]
            for k in range(1, arm["length"] + 1):   # grabber axis hexes
                used.add((bq + k * d[0], br + k * d[1]))
        used.update(snap["pos"].values())

    g = part_cost(puzzle, plan, prices)
    c = makespan
    a = len(used)
    i = plan_length(plan)
    return {
        "instructions": i,
        "makespan": c,
        "area": a,
        "cost": g,
        "sum": g + c + a,
        "sum4": g + c + a + i,
        "product_gca": g * c * a,
        "product_gc": g * c,
        "product_ga": g * a,
        "product_ca": c * a,
        "trackless": True,          # vacuous: track not modeled
        "overlap": False,           # vacuous: validator forbids overlap
        "rate": None,               # STUB: needs steady-state detection
        "area_at_infinity": None,   # STUB: needs steady-state detection
        "looping": None,            # STUB: needs steady-state detection
    }


def main():
    ap = argparse.ArgumentParser(
        description="Compute metrics for a plan JSON against a puzzle "
                    "JSON (the plan must validate).")
    ap.add_argument("puzzle")
    ap.add_argument("plan")
    args = ap.parse_args()
    with open(args.puzzle) as f:
        puzzle = json.load(f)
    with open(args.plan) as f:
        plan = json.load(f)
    print(json.dumps(compute_metrics(puzzle, plan), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
