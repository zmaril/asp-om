"""Data model for forward-generated (puzzle, plan) pairs.

Everything here is a thin layer over existing repo code:

  * the FORWARD ENGINE is ``validate.py``'s ``replay_v2`` (the repo's
    proven pure-Python replay of the asp/core2.lp semantics) -- imported
    verbatim, never reimplemented.  harness/SPEC.md's reconciliation
    decision 2 adopts exactly this timing, so a machine replayed here
    behaves identically under harness/validate.py (single-atom reagents;
    every emitted pair is re-checked through the harness validator
    anyway);
  * OUTPUT FORMATS are the common harness formats (harness/SPEC.md):
    puzzle JSON + plan JSON, emitted by ``emit_puzzle`` / ``emit_plan``;
  * coordinates and rotation conventions (axial hexes, clockwise dir 0..5,
    rot_cw (q,r)->(-r,q+r)) are the shared project conventions.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import validate as omval  # noqa: E402  (master's proven replay simulator)

DIRS = omval.DIRS
ATOM_TYPES = ("air", "earth", "fire", "water", "salt")


def load_harness_validator():
    """Import harness/validate.py under a non-clashing module name (the
    repo root also has a validate.py)."""
    import importlib.util
    path = REPO_ROOT / "harness" / "validate.py"
    spec = importlib.util.spec_from_file_location("harness_validate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Machine description (layout + tape)
# ---------------------------------------------------------------------------
@dataclass
class Arm:
    name: str
    base: tuple[int, int]
    length: int
    orient: int  # 0..5, clockwise dir index

    def gripper0(self) -> tuple[int, int]:
        dq, dr = DIRS[self.orient]
        return (self.base[0] + self.length * dq,
                self.base[1] + self.length * dr)


@dataclass
class Input:
    index: int
    hex: tuple[int, int]
    type: str
    pool: int


@dataclass
class Machine:
    radius: int
    arms: list[Arm]
    inputs: list[Input]
    calcs: list[tuple[int, int]]                        # calcifier hexes
    bonders: list[tuple[tuple[int, int], tuple[int, int]]]  # adjacent pairs
    tape: dict[int, tuple[str, str]] = field(default_factory=dict)
    tmax: int = 0

    def part_footprint(self) -> set[tuple[int, int]]:
        """All part hexes (arm bases, inputs, calcifiers, bonders). The
        output part must be placed on hexes disjoint from these
        (harness/SPEC.md footprint-disjointness rule)."""
        feet = {a.base for a in self.arms}
        feet |= {i.hex for i in self.inputs}
        feet |= set(self.calcs)
        for h1, h2 in self.bonders:
            feet |= {h1, h2}
        return feet

    def footprint_ok(self) -> bool:
        """Part non-overlap + on-board + initial gripper on board."""
        board = omval.hexes(self.radius)
        feet: list[tuple[int, int]] = []
        for a in self.arms:
            feet.append(a.base)
            if a.base not in board or a.gripper0() not in board:
                return False
        for i in self.inputs:
            feet.append(i.hex)
            if i.hex not in board:
                return False
        for h in self.calcs:
            feet.append(h)
            if h not in board:
                return False
        for h1, h2 in self.bonders:
            feet.append(h1)
            feet.append(h2)
            if h1 not in board or h2 not in board:
                return False
            if (h2[0] - h1[0], h2[1] - h1[1]) not in DIRS:
                return False
        return len(feet) == len(set(feet))

    def to_F(self) -> dict:
        """Build the fact dict that validate.replay_v2 consumes (the same
        shape validate.extract() builds from a clingo answer set)."""
        return {
            "arm": [a.name for a in self.arms],
            "base": {a.name: a.base for a in self.arms},
            "armlen": {a.name: a.length for a in self.arms},
            "init_orient": {a.name: a.orient for a in self.arms},
            "init_at": {}, "init_type": {}, "init_bond": set(),
            "spawn": {i.index: i.hex for i in self.inputs},
            "spawn_type": {i.index: i.type for i in self.inputs},
            "pool": {i.index: i.pool for i in self.inputs},
            "glyph_calc": set(self.calcs),
            "glyph_bond": {(h1, h2) for h1, h2 in self.bonders},
            "product": {},
            "plan": dict(self.tape),
            "v1_base": None, "v1_orient": None,
            "claim_at": {}, "claim_type": {}, "claim_bond": {},
            "claim_held": {},
        }

    def replay(self):
        """Run the machine forward with the repo validator's replay_v2.
        Returns (states, err); err is None iff every step is legal."""
        return omval.replay_v2(self.to_F(), self.tmax, self.radius,
                               lambda *a: None)

    def instruction_count(self) -> int:
        return len(self.tape)


# ---------------------------------------------------------------------------
# Molecules: extraction from a replay state + canonicalization
# ---------------------------------------------------------------------------
def components(state) -> list[dict]:
    """Bond-connected components of a replay_v2 state snapshot.

    Returns a list of dicts {atoms: {name: (q,r)}, types: {name: type},
    bonds: set[(name,name)], held: bool}."""
    pos, typ, bonds, held = (state["pos"], state["typ"],
                             state["bonds"], state["held"])
    adj: dict[str, set[str]] = {x: set() for x in pos}
    for x, y in bonds:
        adj[x].add(y)
        adj[y].add(x)
    seen: set[str] = set()
    out = []
    for start in sorted(pos):
        if start in seen:
            continue
        comp = {start}
        stack = [start]
        while stack:
            c = stack.pop()
            for n in adj[c]:
                if n not in comp:
                    comp.add(n)
                    stack.append(n)
        seen |= comp
        out.append({
            "atoms": {x: pos[x] for x in comp},
            "types": {x: typ[x] for x in comp},
            "bonds": {(x, y) for x, y in bonds if x in comp},
            "held": any(x in held for x in comp),
        })
    return out


def rot_cw_k(q: int, r: int, k: int) -> tuple[int, int]:
    for _ in range(k % 6):
        q, r = omval.rot_cw(q, r)
    return (q, r)


def canonical_molecule(atoms: list[tuple[int, int, str]],
                       bonds: set[frozenset[tuple[int, int]]]):
    """Canonical form of a molecule under translation + the 6 hex rotations
    (matching the model: no reflection symmetry -- arms cannot mirror a
    molecule).

    atoms: [(q, r, type)];  bonds: set of frozensets of two (q, r) hexes.
    Returns (canon_atoms, canon_bonds, sha1hex) where canon_atoms is a
    sorted tuple of (q, r, type) and canon_bonds a sorted tuple of
    ((q1,r1),(q2,r2)) bond hex pairs, both in the least placement.
    """
    best = None
    for k in range(6):
        rot_pos = {(q, r): rot_cw_k(q, r, k) for q, r, _ in atoms}
        pts = sorted(rot_pos.values())
        oq, or_ = pts[0]
        norm_atoms = tuple(sorted(
            (rot_pos[(q, r)][0] - oq, rot_pos[(q, r)][1] - or_, t)
            for q, r, t in atoms))
        norm_bonds = tuple(sorted(
            tuple(sorted((rot_pos[h][0] - oq, rot_pos[h][1] - or_)
                         for h in b))
            for b in bonds))
        cand = (norm_atoms, norm_bonds)
        if best is None or cand < best:
            best = cand
    blob = json.dumps(best, sort_keys=True).encode()
    return best[0], best[1], hashlib.sha1(blob).hexdigest()


def component_to_molecule(comp: dict):
    """(atoms list, bonds set) in canonical_molecule's input shape."""
    atoms = [(q, r, comp["types"][x])
             for x, (q, r) in sorted(comp["atoms"].items())]
    bonds = {frozenset((comp["atoms"][x], comp["atoms"][y]))
             for x, y in comp["bonds"]}
    return atoms, bonds


def find_output_placement(canon_atoms, rest_hexes: dict):
    """Find (position, rotation) such that placing the canonical product
    molecule there covers exactly the hexes it actually rests on in the
    replay's final state, with matching elements per hex.

    canon_atoms: tuple of (q, r, type) (canonical form);
    rest_hexes:  {(q, r): type} on the board.
    """
    actual = sorted(rest_hexes)
    for k in range(6):
        rot = sorted((rot_cw_k(q, r, k), t) for q, r, t in canon_atoms)
        pos = (actual[0][0] - rot[0][0][0], actual[0][1] - rot[0][0][1])
        if all(((h[0] + pos[0], h[1] + pos[1]) in rest_hexes
                and rest_hexes[(h[0] + pos[0], h[1] + pos[1])] == t)
               for h, t in rot):
            return pos, k
    raise AssertionError("no rotation maps the canonical product onto its "
                         "resting hexes -- canonicalization bug")


# ---------------------------------------------------------------------------
# Common harness format emission (harness/SPEC.md sections 3-4)
# ---------------------------------------------------------------------------
def molecule_json(canon_atoms, canon_bonds) -> dict:
    """Canonical molecule -> harness molecule JSON (atoms + index bonds)."""
    idx = {(q, r): i for i, (q, r, _) in enumerate(canon_atoms)}
    return {
        "atoms": [{"element": t, "pos": [q, r]} for q, r, t in canon_atoms],
        "bonds": sorted(sorted((idx[h1], idx[h2])) for h1, h2 in canon_bonds),
    }


def emit_puzzle(name: str, machine: Machine, canon_atoms, canon_bonds,
                product_hash: str) -> dict:
    """Harness puzzle JSON. Nothing is pinned: layout is the solver's job
    (the reference plan proves a layout exists)."""
    product = molecule_json(canon_atoms, canon_bonds)
    product["id"] = "product"
    parts = [{"type": "arm", "id": a.name, "length": a.length}
             for a in machine.arms]
    parts += [{"type": "calcifier", "id": f"c{g}"}
              for g, _ in enumerate(machine.calcs, 1)]
    parts += [{"type": "bonder", "id": f"b{g}"}
              for g, _ in enumerate(machine.bonders, 1)]
    return {
        "name": name,
        "description": ("Forward-generated instance: a random legal machine "
                        "was simulated with the exact model semantics and "
                        "whatever it produced became the product, so the "
                        "puzzle is solvable by construction "
                        f"(product hash {product_hash})."),
        "board_radius": machine.radius,
        "t_max": machine.tmax,
        "reagents": [
            {"id": f"r{i.index}", "pool": i.pool,
             "atoms": [{"element": i.type, "pos": [0, 0]}], "bonds": []}
            for i in machine.inputs
        ],
        "products": [product],
        "parts": parts,
    }


def emit_plan(name: str, machine: Machine, output_pos, output_rot) -> dict:
    """Harness plan JSON: the generating machine itself, as the reference
    solution."""
    placements = [
        {"type": "arm", "id": a.name, "position": list(a.base),
         "rotation": a.orient}
        for a in machine.arms
    ]
    placements += [
        {"type": "input", "id": f"r{i.index}", "position": list(i.hex),
         "rotation": 0}
        for i in machine.inputs
    ]
    placements += [
        {"type": "calcifier", "id": f"c{g}", "position": list(h)}
        for g, h in enumerate(machine.calcs, 1)
    ]
    for g, (h1, h2) in enumerate(machine.bonders, 1):
        rot = DIRS.index((h2[0] - h1[0], h2[1] - h1[1]))
        placements.append({"type": "bonder", "id": f"b{g}",
                           "position": list(h1), "rotation": rot})
    placements.append({"type": "output", "id": "product",
                       "position": list(output_pos), "rotation": output_rot})
    return {
        "puzzle": name,
        "solver": "selfplay/generator forward-generation reference tape",
        "placements": placements,
        "instructions": [{"t": t, "arm": m, "action": a}
                         for t, (m, a) in sorted(machine.tape.items())],
    }
