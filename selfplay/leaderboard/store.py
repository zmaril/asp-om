#!/usr/bin/env python3
"""Incumbent store for the self-competition leaderboard (Loop 3).

INVARIANT: incumbents are populated ONLY by the system's OWN
solutions, each verified by the canonical validator
(harness/validate.py) at submission time. External solutions are never
stored here, never used as incumbents, and never used as training
targets; external numbers may only ever appear in a clearly-separated
read-only comparison column of the rendered leaderboard (driver.py).

The store is keyed by (puzzle name, metric name). Each record keeps the
best (lowest) score seen for that metric on that puzzle, the FULL plan
JSON that achieved it, the full metric vector of that plan, and
provenance (source label + submission counter).

The interface Loops 1 (expert iteration) and 2 (curriculum) consume:

    store = IncumbentStore("selfplay/leaderboard/incumbents.json")
    result = store.submit(puzzle, plan, source="clingo")

    result["accepted"]  bool -- False iff the canonical validator
                        rejected the plan (reason in result["reason"]);
                        rejected plans change nothing.
    result["metrics"]   the full metric vector (harness/metrics.py).
    result["improved"]  [{"metric", "old", "new", "delta"}, ...] --
                        one entry per (puzzle, metric) record this plan
                        beat. `old`/`delta` are None for a first-ever
                        record on that key; otherwise delta = old - new
                        > 0. This list is the self-competition REWARD
                        SIGNAL: an empty list means the plan taught the
                        leaderboard nothing; a non-empty list quantifies
                        how much the system just improved on itself.

Persistence is a single JSON file, rewritten after every accepted
submission (atomic rename).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "harness"))
from metrics import METRICS, compute_metrics, leaderboard_metrics  # noqa: E402
from validate import Invalid, Malformed  # noqa: E402

FORMAT_VERSION = 1


class IncumbentStore:
    """Self-leaderboard incumbents, keyed by (puzzle, metric)."""

    def __init__(self, path):
        self.path = path
        self.submissions = 0     # accepted-or-rejected counter (provenance)
        self.records = {}        # puzzle -> metric -> record dict
        if path and os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            if data.get("format") != FORMAT_VERSION:
                raise ValueError(f"{path}: unknown store format "
                                 f"{data.get('format')!r}")
            self.records = data["records"]
            self.submissions = data.get("submissions", 0)

    def submit(self, puzzle, plan, source="unlabeled"):
        """Submit one of OUR OWN candidate solutions.

        1. Validates via the canonical validator; invalid plans are
           rejected and change nothing.
        2. Computes the full metric vector (harness/metrics.py).
        3. Updates every (puzzle, metric) incumbent the plan beats.
        4. Returns the improvement deltas (the reward signal) -- see the
           module docstring for the result shape.
        """
        self.submissions += 1
        name = puzzle.get("name", "?")
        try:
            metric_values = compute_metrics(puzzle, plan)
        except (Invalid, Malformed) as e:
            return {"accepted": False, "puzzle": name,
                    "reason": f"{type(e).__name__}: {e}",
                    "metrics": None, "improved": []}

        improved = []
        per_puzzle = self.records.setdefault(name, {})
        for metric in leaderboard_metrics():
            new = metric_values[metric]
            record = per_puzzle.get(metric)
            old = record["score"] if record else None
            better = (old is None
                      or (new < old if METRICS[metric].lower_is_better
                          else new > old))
            if not better:
                continue
            per_puzzle[metric] = {
                "score": new,
                "source": source,
                "submission": self.submissions,
                "metrics": metric_values,
                "plan": plan,
            }
            improved.append({"metric": metric, "old": old, "new": new,
                             "delta": None if old is None else old - new})
        if improved:
            self.save()
        return {"accepted": True, "puzzle": name, "reason": None,
                "metrics": metric_values, "improved": improved}

    def incumbent(self, puzzle_name, metric):
        """The current best record for (puzzle, metric), or None."""
        return self.records.get(puzzle_name, {}).get(metric)

    def save(self):
        if not self.path:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"format": FORMAT_VERSION,
                       "submissions": self.submissions,
                       "records": self.records}, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, self.path)
