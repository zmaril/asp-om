#!/usr/bin/env python3
"""Loop 1: expert iteration (solver-as-teacher), minimal viable loop.

    propose -> teacher completes/relaxes -> canonical validation ->
    record -> update the learnable proposer

INVARIANT (see README.md): every training record is a solution produced
by THIS loop's proposer + solver-teacher and verified by
harness/validate.py before being recorded. No external solutions enter
the dataset or the policy update, ever.

Per iteration, per puzzle:
  1. The proposer proposes a machine layout (partial plan, empty tape).
  2. The teacher (clingo adapter) tries to complete the proposal with
     the layout pinned; on UNSAT/timeout it relaxes to its cached
     from-scratch solution (teacher.py documents the coupling).
  3. The resulting plan is validated by harness/validate.py (canonical
     validator, called directly here) and submitted to a fresh
     leaderboard IncumbentStore (selfplay/leaderboard/store.py), whose
     improvement deltas feed the reward.
  4. The verified (puzzle, proposal, solution, metrics, reward) record
     is appended to records.jsonl.
  5. The learnable proposer updates:
       - REINFORCE on its own proposal with
             reward = 0                                (infeasible)
             reward = 1 + (ref_len - len)/ref_len
                        + 0.1 * #leaderboard-metrics-improved (feasible)
         where ref_len is the teacher's from-scratch plan length;
       - plus, when the proposal was infeasible, one imitation
         (cross-entropy) step toward the teacher's own relaxed layout
         -- the expert-iteration "learn from the expert's solution"
         signal. The imitated layout is self-generated (the solver's),
         never external.

Outputs under selfplay/expert_iteration/runs/<name>/:
    records.jsonl    verified training records (the dataset)
    curve.csv        per-iteration learning curve
    run.log          human-readable log + end-of-run summary
    incumbents.json  the run's own leaderboard store
    weights.json     learned policy weights (learned proposer only)

Usage (the committed demo run):
    python3 selfplay/expert_iteration/loop.py \
        --puzzles harness/puzzles/single_transport.json \
                  harness/puzzles/two_atom_bond.json \
        --iterations 80 --proposer learned --seed 0 --run-name demo
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "harness"))
sys.path.insert(0, os.path.join(REPO, "selfplay", "leaderboard"))
sys.path.insert(0, HERE)

from proposer import LearnedProposer, make_proposer, puzzle_slots  # noqa: E402
from store import IncumbentStore  # noqa: E402
from teacher import ClingoTeacher  # noqa: E402

from validate import Invalid, Malformed, plan_length, validate  # noqa: E402

DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]


def plan_choices(puzzle, plan):
    """Map a plan's placements onto (slot_key, cand_key) choices so the
    learned proposer can imitate the teacher's layout. Returns None if
    any placement falls outside the proposer's candidate space."""
    by_id = {(pl["type"], pl["id"]): pl for pl in plan["placements"]}
    choices = []
    for slot in puzzle_slots(puzzle):
        kind, pid = slot["key"].split("/", 1)
        ptype = {
            "arm": "arm",
            "input": "input",
            "output": "output",
            "calcifier": "calcifier",
            "bonder": "bonder",
        }[kind]
        pl = by_id.get((ptype, pid))
        if pl is None:
            return None
        q, r = pl["position"]
        rot = pl.get("rotation", 0) % 6
        if kind == "bonder" and rot >= 3:  # flip to the canonical half
            q, r = q + DIRS[rot][0], r + DIRS[rot][1]
            rot -= 3
        key = f"{q},{r}" if kind == "calcifier" else f"{q},{r},{rot}"
        if key not in {c[0] for c in slot["candidates"]}:
            return None
        choices.append((slot["key"], key))
    return choices


class Run:
    def __init__(self, out_dir, echo=True):
        os.makedirs(out_dir, exist_ok=True)
        self.dir = out_dir
        self.echo = echo
        # Handles stay open for the lifetime of the run; Run.close() closes them.
        self.logf = open(os.path.join(out_dir, "run.log"), "w")  # noqa: SIM115
        self.records = open(os.path.join(out_dir, "records.jsonl"), "w")  # noqa: SIM115
        self.curve = open(os.path.join(out_dir, "curve.csv"), "w")  # noqa: SIM115
        self.curve.write(
            "iteration,puzzle,mode,seeded_ok,reward,plan_len,ref_len,improved,window_validity\n"
        )

    def log(self, msg):
        self.logf.write(msg + "\n")
        self.logf.flush()
        if self.echo:
            print(msg, flush=True)

    def record(self, rec):
        self.records.write(json.dumps(rec, sort_keys=True) + "\n")
        self.records.flush()

    def curve_row(self, *cols):
        self.curve.write(",".join(str(c) for c in cols) + "\n")
        self.curve.flush()

    def close(self):
        for f in (self.logf, self.records, self.curve):
            f.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--puzzles",
        nargs="+",
        required=True,
        help="puzzle JSON paths (keep these trivial: the teacher's ceiling is low, see README.md)",
    )
    ap.add_argument("--iterations", type=int, default=40, help="iterations per puzzle")
    ap.add_argument("--proposer", choices=("random", "learned"), default="learned")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--run-name", default=None)
    ap.add_argument(
        "--seeded-limit",
        type=float,
        default=15.0,
        help="clingo time limit (s) for proposal-pinned solves",
    )
    ap.add_argument(
        "--relaxed-limit",
        type=float,
        default=60.0,
        help="clingo time limit (s) for the one from-scratch reference solve per puzzle",
    )
    args = ap.parse_args()

    name = args.run_name or f"{args.proposer}-{int(time.time())}"
    out_dir = os.path.join(HERE, "runs", name)
    run = Run(out_dir)
    store = IncumbentStore(os.path.join(out_dir, "incumbents.json"))
    weights_path = os.path.join(out_dir, "weights.json")
    proposer = make_proposer(args.proposer, seed=args.seed, weights_path=weights_path)
    teacher = ClingoTeacher(
        os.path.join(out_dir, "scratch"),
        seeded_limit=args.seeded_limit,
        relaxed_limit=args.relaxed_limit,
    )

    run.log(
        f"# expert iteration run {name!r}: proposer={args.proposer} "
        f"seed={args.seed} iterations={args.iterations}/puzzle"
    )
    summary = {}
    for path in args.puzzles:
        with open(path) as f:
            puzzle = json.load(f)
        pname = puzzle["name"]
        run.log(f"\n## puzzle {pname}")

        # From-scratch reference (also warms the teacher's relax cache).
        t0 = time.time()
        ref_plan = teacher.relaxed_solve(puzzle)
        if ref_plan is None:
            run.log(
                f"  teacher cannot solve {pname} from scratch within "
                f"{args.relaxed_limit}s -- skipping (competence "
                f"ceiling, see README.md)"
            )
            continue
        validate(puzzle, ref_plan)  # canonical check; raises on failure
        ref_len = plan_length(ref_plan)
        ref_sub = store.submit(puzzle, ref_plan, source="teacher/relaxed")
        run.record(
            {
                "kind": "reference",
                "puzzle": pname,
                "plan": ref_plan,
                "metrics": ref_sub["metrics"],
                "improved": ref_sub["improved"],
            }
        )
        run.log(f"  reference from-scratch solve: {ref_len} instructions ({time.time() - t0:.1f}s)")
        ref_choices = plan_choices(puzzle, ref_plan)
        if ref_choices is None:
            run.log(
                "  note: reference layout outside proposer candidate "
                "space; imitation disabled for this puzzle"
            )

        window = []
        stats = []  # (seeded_ok, reward, plan_len or None)
        for it in range(args.iterations):
            proposal = proposer.propose(puzzle)
            t0 = time.time()
            taught = teacher.teach(puzzle, proposal)
            solver_s = time.time() - t0
            plan, mode = taught["plan"], taught["mode"]
            seeded_ok = taught["seeded_ok"]

            reward, plan_len, improved = 0.0, None, []
            if plan is not None:
                try:
                    validate(puzzle, plan)  # canonical validator, always
                except (Invalid, Malformed) as e:
                    # Teacher output failing the canonical validator is a
                    # bug; treat as failure, record nothing.
                    run.log(f"  it={it} WARNING teacher plan invalid: {e}")
                    plan, mode, seeded_ok = None, "none", False
            if plan is not None:
                sub = store.submit(puzzle, plan, source=f"loop1/{args.proposer}/{mode}")
                assert sub["accepted"], sub["reason"]
                improved = sub["improved"]
                plan_len = plan_length(plan)
                if seeded_ok:
                    reward = 1.0 + (ref_len - plan_len) / max(ref_len, 1) + 0.1 * len(improved)
                run.record(
                    {
                        "kind": "iteration",
                        "iteration": it,
                        "puzzle": pname,
                        "proposal": proposal,
                        "mode": mode,
                        "seeded_ok": seeded_ok,
                        "plan": plan,
                        "metrics": sub["metrics"],
                        "improved": improved,
                        "reward": reward,
                        "solver_seconds": round(solver_s, 3),
                    }
                )

            # policy update -- from this loop's own outcomes only
            if isinstance(proposer, LearnedProposer):
                proposer.update(puzzle, proposal, reward)
                if not seeded_ok and ref_choices is not None:
                    proposer.imitate(puzzle, ref_choices)
                proposer.save()

            window.append(1 if seeded_ok else 0)
            window = window[-10:]
            wv = sum(window) / len(window)
            stats.append((seeded_ok, reward, plan_len if seeded_ok else None))
            run.curve_row(
                it,
                pname,
                mode,
                int(seeded_ok),
                f"{reward:.3f}",
                plan_len if plan_len else "",
                ref_len,
                len(improved),
                f"{wv:.2f}",
            )
            run.log(
                f"  it={it:3d} mode={mode:7s} seeded_ok={int(seeded_ok)} "
                f"reward={reward:5.2f} "
                f"len={plan_len if plan_len is not None else '-':>2} "
                f"(ref {ref_len}) window_validity={wv:.2f} "
                f"[{solver_s:.2f}s]"
            )

        h = len(stats) // 2
        first, second = stats[:h], stats[h:]

        def rate(xs):
            return sum(1 for ok, _, _ in xs if ok) / max(len(xs), 1)

        def mean_reward(xs):
            return sum(r for _, r, _ in xs) / max(len(xs), 1)

        summary[pname] = {
            "validity_first_half": round(rate(first), 3),
            "validity_second_half": round(rate(second), 3),
            "mean_reward_first_half": round(mean_reward(first), 3),
            "mean_reward_second_half": round(mean_reward(second), 3),
            "reference_len": ref_len,
        }
        run.log(
            f"  summary {pname}: proposal validity "
            f"{summary[pname]['validity_first_half']:.2f} -> "
            f"{summary[pname]['validity_second_half']:.2f} "
            f"(first vs second half), mean reward "
            f"{summary[pname]['mean_reward_first_half']:.2f} -> "
            f"{summary[pname]['mean_reward_second_half']:.2f}"
        )

    run.log("\n# learning-curve summary (first half vs second half)")
    run.log(json.dumps(summary, indent=2, sort_keys=True))
    run.close()
    print(f"\nrun artifacts in {out_dir}")


if __name__ == "__main__":
    main()
