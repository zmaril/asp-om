#!/usr/bin/env python3
"""Proposers for Loop 1 (expert iteration / solver-as-teacher).

A *proposal* is a partial plan in the harness plan format: a complete
`placements` list (one entry per arm/glyph part, per reagent input and
per product output) plus an instruction tape. In this minimal loop the
proposed tape is always EMPTY -- the proposer decides the machine
LAYOUT and the solver-teacher writes the whole program for it. (Tape
prefixes as part of the proposal are a documented next step, see
README.md.)

Two implementations:

    RandomProposer   uniform over layout-legal placements (footprints
                     pairwise disjoint, everything on the board,
                     gripper on the board). The untrained baseline.
    LearnedProposer  the same candidate space, but sampled from a
                     tabular softmax policy: one weight per
                     (puzzle, slot, candidate). Trained by REINFORCE
                     with a per-puzzle running-mean baseline from the
                     loop's OWN validated records -- never from
                     external solutions (see the invariant in
                     README.md).

Both guarantee layout legality by construction (candidates are
enumerated on-board and sampled with footprint masking), so a proposal
can only fail *dynamically* (the layout admits no valid program within
t_max). Learning to avoid those layouts is exactly the training signal.

Candidate rotations for outputs are restricted to the geometrically
distinct ("canonical") ones, matching the clingo adapter's product
symmetry dedup -- pinning a non-canonical rotation confuses the
adapter's out_at choice rule. Bonder rotations are restricted to 0..2
(the (p,k) == (p+dir[k], k+3) flip equivalence of SPEC.md).
"""

import json
import math
import os
import random

DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]


def rot_k(q, r, k):
    for _ in range(k % 6):
        q, r = -r, q + r
    return (q, r)


def on_board(h, radius):
    return abs(h[0]) <= radius and abs(h[1]) <= radius and abs(h[0] + h[1]) <= radius


def board_hexes(radius):
    return [
        (q, r)
        for q in range(-radius, radius + 1)
        for r in range(-radius, radius + 1)
        if abs(q + r) <= radius
    ]


def canonical_rotations(atoms, bonds):
    """Rotation indices giving geometrically distinct placements of a
    molecule (same dedup as harness/adapters/clingo/adapter.py)."""
    keep, seen = [], set()
    for d in range(6):
        cells = [rot_k(q, r, d) for _, (q, r) in atoms]
        anchor = min(cells)
        norm = frozenset(
            ((c[0] - anchor[0], c[1] - anchor[1]), el)
            for (el, _), c in zip(atoms, cells, strict=False)
        )
        nbonds = frozenset(
            frozenset(
                (
                    (cells[i][0] - anchor[0], cells[i][1] - anchor[1]),
                    (cells[j][0] - anchor[0], cells[j][1] - anchor[1]),
                )
            )
            for i, j in (sorted(b) for b in bonds)
        )
        key = (norm, nbonds)
        if key not in seen:
            seen.add(key)
            keep.append(d)
    return keep


def molecule(m):
    atoms = [(a["element"], tuple(a["pos"])) for a in m["atoms"]]
    bonds = {frozenset(b) for b in m.get("bonds", [])}
    return atoms, bonds


# ---------------------------------------------------------------------------
# Candidate space: slots and their (placement, footprint) candidates
# ---------------------------------------------------------------------------
def _mol_footprint(atoms, pos, rot):
    out = []
    for _, (q, r) in atoms:
        dq, dr = rot_k(q, r, rot)
        out.append((pos[0] + dq, pos[1] + dr))
    return out


def puzzle_slots(puzzle):
    """Ordered decision slots for a puzzle. Each slot is a dict:
        {"key": str, "candidates": [(cand_key, placement_dict, footprint)]}
    Slots respecting any puzzle pins (a pinned part has exactly one
    candidate). Order: arms, inputs, outputs, calcifiers, bonders --
    deterministic so the learned policy's masking context is replayable.
    """
    radius = puzzle["board_radius"]
    hexes = board_hexes(radius)
    slots = []

    def pinned_positions(spec):
        return [tuple(spec["position"])] if "position" in spec else hexes

    def pinned_rotations(spec, options):
        return [spec["rotation"] % 6] if "rotation" in spec else options

    for p in (p for p in puzzle["parts"] if p["type"] == "arm"):
        cands = []
        for pos in pinned_positions(p):
            for rot in pinned_rotations(p, range(6)):
                grip = (pos[0] + p["length"] * DIRS[rot][0], pos[1] + p["length"] * DIRS[rot][1])
                if on_board(grip, radius):
                    cands.append(
                        (
                            f"{pos[0]},{pos[1]},{rot}",
                            {
                                "type": "arm",
                                "id": p["id"],
                                "position": list(pos),
                                "rotation": rot,
                                "length": p["length"],
                            },
                            [pos],
                        )
                    )
        slots.append({"key": f"arm/{p['id']}", "candidates": cands})

    for kind, items, ptype in (
        ("input", puzzle["reagents"], "input"),
        ("output", puzzle["products"], "output"),
    ):
        for m in items:
            atoms, bonds = molecule(m)
            rots = canonical_rotations(atoms, bonds)
            cands = []
            for pos in pinned_positions(m):
                for rot in pinned_rotations(m, rots):
                    foot = _mol_footprint(atoms, pos, rot)
                    if all(on_board(h, radius) for h in foot):
                        cands.append(
                            (
                                f"{pos[0]},{pos[1]},{rot}",
                                {
                                    "type": ptype,
                                    "id": m["id"],
                                    "position": list(pos),
                                    "rotation": rot,
                                },
                                foot,
                            )
                        )
            slots.append({"key": f"{kind}/{m['id']}", "candidates": cands})

    for p in (p for p in puzzle["parts"] if p["type"] == "calcifier"):
        cands = [
            (
                f"{pos[0]},{pos[1]}",
                {"type": "calcifier", "id": p["id"], "position": list(pos)},
                [pos],
            )
            for pos in pinned_positions(p)
        ]
        slots.append({"key": f"calcifier/{p['id']}", "candidates": cands})

    for p in (p for p in puzzle["parts"] if p["type"] == "bonder"):
        cands = []
        rot_opts = pinned_rotations(p, range(3))  # flip equivalence
        for pos in pinned_positions(p):
            for rot in rot_opts:
                other = (pos[0] + DIRS[rot][0], pos[1] + DIRS[rot][1])
                if on_board(other, radius):
                    cands.append(
                        (
                            f"{pos[0]},{pos[1]},{rot}",
                            {
                                "type": "bonder",
                                "id": p["id"],
                                "position": list(pos),
                                "rotation": rot,
                            },
                            [pos, other],
                        )
                    )
        slots.append({"key": f"bonder/{p['id']}", "candidates": cands})

    return slots


def _masked(slot, used):
    """Candidates of a slot whose footprint avoids already-used hexes."""
    return [c for c in slot["candidates"] if not any(h in used for h in c[2])]


# ---------------------------------------------------------------------------
# Proposers
# ---------------------------------------------------------------------------
class Proposer:
    """Interface: propose(puzzle) -> proposal dict.

    The proposal is a partial plan: {"puzzle", "placements",
    "instructions" (empty), "meta": {"choices": [(slot_key, cand_key)]}}.
    "meta" is loop bookkeeping (needed to train the learned policy) and
    is ignored by the validator/teacher.
    """

    name = "abstract"

    def propose(self, puzzle):
        raise NotImplementedError

    def update(self, puzzle, proposal, reward):
        """Learn from one of OUR OWN loop records. No-op by default."""

    def _sample(self, puzzle, weight_fn, rng):
        """Sequential masked sampling shared by both implementations.
        weight_fn(slot_key, cand_keys) -> list of positive weights."""
        used: set[tuple[int, int]] = set()
        placements, choices = [], []
        for slot in puzzle_slots(puzzle):
            cands = _masked(slot, used)
            if not cands:
                # Dead end (earlier choices blocked every candidate).
                # Rare on these boards; retry from scratch.
                return None
            weights = weight_fn(slot["key"], [c[0] for c in cands])
            cand_key, placement, foot = rng.choices(cands, weights=weights)[0]
            used.update(foot)
            placements.append(placement)
            choices.append((slot["key"], cand_key))
        return {
            "puzzle": puzzle["name"],
            "placements": placements,
            "instructions": [],
            "meta": {"proposer": self.name, "choices": choices},
        }

    def propose_with_retries(self, puzzle, rng, tries=50):
        for _ in range(tries):
            prop = self._sample_entry(puzzle, rng)
            if prop is not None:
                return prop
        raise RuntimeError(f"no layout-legal proposal found for {puzzle['name']} in {tries} tries")

    def _sample_entry(self, puzzle, rng):
        raise NotImplementedError


class RandomProposer(Proposer):
    """Uniform over layout-legal placements. The untrained baseline."""

    name = "random"

    def __init__(self, seed=None):
        self.rng = random.Random(seed)

    def propose(self, puzzle):
        return self.propose_with_retries(puzzle, self.rng)

    def _sample_entry(self, puzzle, rng):
        return self._sample(puzzle, lambda k, cks: [1.0] * len(cks), rng)


class LearnedProposer(Proposer):
    """Tabular softmax policy over the same candidate space.

    Policy: at each slot, P(candidate) ~ exp(w[puzzle][slot][cand])
    over the footprint-masked candidates.

    Update: REINFORCE with a per-puzzle running-mean baseline. For a
    record with reward r, advantage a = r - baseline, and for each slot
    decision (chosen candidate c among masked set S):

        w[c]  += lr * a * (1 - pi(c))
        w[c'] -= lr * a * pi(c')          for c' in S, c' != c

    which is exact gradient ascent on a * log pi(c) for the softmax.
    The masked set S is replayed deterministically from the recorded
    choice sequence, so updates can be applied from JSONL records.

    This is deliberately the smallest honest learner: no torch (not
    installed in this environment), no features, no generalization
    across puzzles -- per-puzzle tables only. See README.md next steps.
    """

    name = "learned"

    def __init__(self, seed=None, lr=1.0, baseline_decay=0.9, weights_path=None):
        self.rng = random.Random(seed)
        self.lr = lr
        self.baseline_decay = baseline_decay
        self.weights = {}  # puzzle -> slot_key -> cand_key -> w
        self.baseline = {}  # puzzle -> running mean reward
        self.weights_path = weights_path
        if weights_path and os.path.exists(weights_path):
            with open(weights_path) as f:
                data = json.load(f)
            self.weights = data["weights"]
            self.baseline = data["baseline"]

    def _w(self, puzzle_name, slot_key):
        return self.weights.setdefault(puzzle_name, {}).setdefault(slot_key, {})

    def _probs(self, puzzle_name, slot_key, cand_keys):
        w = self._w(puzzle_name, slot_key)
        logits = [w.get(ck, 0.0) for ck in cand_keys]
        mx = max(logits)
        exps = [math.exp(x - mx) for x in logits]
        z = sum(exps)
        return [e / z for e in exps]

    def propose(self, puzzle):
        return self.propose_with_retries(puzzle, self.rng)

    def _sample_entry(self, puzzle, rng):
        name = puzzle["name"]
        return self._sample(puzzle, lambda sk, cks: self._probs(name, sk, cks), rng)

    def update(self, puzzle, proposal, reward):
        """REINFORCE update from one of this loop's own records."""
        name = puzzle["name"]
        base = self.baseline.get(name, 0.0)
        self.baseline[name] = self.baseline_decay * base + (1 - self.baseline_decay) * reward
        self._apply_gradient(puzzle, proposal["meta"]["choices"], reward - base)

    def imitate(self, puzzle, choices, weight=1.0):
        """Cross-entropy step toward a SELF-GENERATED expert layout
        (the teacher's own solution -- never an external one). Same
        gradient as REINFORCE with a fixed positive advantage and no
        baseline involvement."""
        self._apply_gradient(puzzle, choices, weight)

    def _apply_gradient(self, puzzle, choices, adv):
        """adv * grad(log pi(choices)) ascent, replaying the sequential
        footprint-masking context deterministically from the choices."""
        if adv == 0.0:
            return
        name = puzzle["name"]
        chosen = dict(choices)
        used: set[tuple[int, int]] = set()
        for slot in puzzle_slots(puzzle):
            cands = _masked(slot, used)
            cand_keys = [c[0] for c in cands]
            ck = chosen[slot["key"]]
            probs = self._probs(name, slot["key"], cand_keys)
            w = self._w(name, slot["key"])
            for k, p in zip(cand_keys, probs, strict=False):
                grad = (1.0 - p) if k == ck else -p
                w[k] = w.get(k, 0.0) + self.lr * adv * grad
            foot = next(c[2] for c in cands if c[0] == ck)
            used.update(foot)

    def save(self, path=None):
        path = path or self.weights_path
        if not path:
            return
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(
                {"weights": self.weights, "baseline": self.baseline}, f, indent=1, sort_keys=True
            )
        os.replace(tmp, path)


def make_proposer(kind, seed=None, weights_path=None):
    if kind == "random":
        return RandomProposer(seed=seed)
    if kind == "learned":
        return LearnedProposer(seed=seed, weights_path=weights_path)
    raise ValueError(f"unknown proposer kind {kind!r}")
