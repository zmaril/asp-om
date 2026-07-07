"""Test-case instance definitions for the SAT arm.

Coordinates, direction table and mechanics follow the shared design brief
(and asp/core.lp): axial hex coordinates (Q,R), board = hex ball of radius
`radius` (|Q|<=r, |R|<=r, |Q+R|<=r), directions indexed 0..5:

    D: 0=(1,0) 1=(0,1) 2=(-1,1) 3=(-1,0) 4=(0,-1) 5=(1,-1)

Instances (a) and (b) mirror asp/trivial_instance.lp and asp/bond_instance.lp
exactly.  The `fixed_layout` field records the clingo arm's layout so that
--fixed-layout mode can pin the layout variables with unit assumptions.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

Hex = Tuple[int, int]

DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]

ACTIONS = ["rot_cw", "rot_ccw", "grab", "drop", "wait"]


def hex_ball(radius: int):
    """All hexes of the axial hex ball of the given radius, sorted."""
    out = []
    for q in range(-radius, radius + 1):
        for r in range(-radius, radius + 1):
            if abs(q + r) <= radius:
                out.append((q, r))
    return sorted(out)


@dataclass
class FixedLayout:
    base: Hex
    length: int
    orient: int                      # initial orientation D in 0..5
    glyph_pos: Optional[Hex] = None  # first bonder cell
    glyph_dir: Optional[int] = None  # second cell = glyph_pos + dir(glyph_dir)


@dataclass
class Instance:
    name: str
    radius: int
    atoms: Tuple[str, ...]
    init_at: Dict[str, Hex]
    products: Dict[str, Hex]         # atom -> target hex (must be unheld there)
    has_glyph: bool                  # glyph of bonding present (placeable)
    require_bond: bool               # goal: at least one bond at t_max
    t_max_default: int               # clingo arm's t_max, for optimization parity
    fixed_layout: FixedLayout = field(default=None)
    max_arm_len: int = 2             # arm length domain 1..max_arm_len (free layout)


# (a) trivial: transport one salt atom from (1,0) to (-1,0).
CASE_A = Instance(
    name="a-transport",
    radius=2,
    atoms=("a1",),
    init_at={"a1": (1, 0)},
    products={"a1": (-1, 0)},
    has_glyph=False,
    require_bond=False,
    t_max_default=10,
    fixed_layout=FixedLayout(base=(0, 0), length=1, orient=0),
)

# (b) bond: two salt atoms, glyph of bonding on (-1,0)/(0,-1).
# Second glyph cell (0,-1) = (-1,0) + dir(5) = (-1,0)+(1,-1).
CASE_B = Instance(
    name="b-bond",
    radius=2,
    atoms=("a1", "a2"),
    init_at={"a1": (1, 0), "a2": (0, 1)},
    products={"a1": (-1, 0), "a2": (0, -1)},
    has_glyph=True,
    require_bond=True,
    t_max_default=16,
    fixed_layout=FixedLayout(
        base=(0, 0), length=1, orient=0, glyph_pos=(-1, 0), glyph_dir=5
    ),
)

CASES = {"a": CASE_A, "b": CASE_B}
