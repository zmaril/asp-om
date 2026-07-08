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

Hex = tuple[int, int]

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
    orient: int  # initial orientation D in 0..5
    glyph_pos: Hex | None = None  # first bonder cell
    glyph_dir: int | None = None  # second cell = glyph_pos + dir(glyph_dir)


@dataclass
class Instance:
    name: str
    radius: int
    atoms: tuple[str, ...]
    init_at: dict[str, Hex]
    products: dict[str, Hex]  # atom -> target hex (must be unheld there)
    has_glyph: bool  # glyph of bonding present (placeable)
    require_bond: bool  # goal: at least one bond at t_max
    t_max_default: int  # clingo arm's t_max, for optimization parity
    fixed_layout: FixedLayout | None = field(default=None)
    max_arm_len: int = 2  # arm length domain 1..max_arm_len (free layout)


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
    fixed_layout=FixedLayout(base=(0, 0), length=1, orient=0, glyph_pos=(-1, 0), glyph_dir=5),
)

CASES = {"a": CASE_A, "b": CASE_B}


# ===========================================================================
# Phase 2: Stabilized Water (Opus Magnum campaign puzzle P007).
#
# Mechanics fragment = the clingo arm's asp/core2.lp (branch
# stabilized-water): rigid molecule motion, atom types + glyph of
# calcification, glyph of bonding, respawning bounded-pool reagent inputs,
# exact-molecule goal.  Single arm of length 1 (the clingo free-layout SW
# instance also fixes length 1 via place_arm(m1,1)).
# ===========================================================================


@dataclass
class InstanceSW:
    """A phase-2 instance: single arm (length 1), water inputs, one
    calcification glyph, one bonding glyph, salt--water dimer goal."""

    name: str
    radius: int
    pools: tuple[int, ...]  # pool size per reagent input (1-based)
    spawn_fixed: tuple[Hex, ...]  # fixed-layout spawn hex per input
    base: Hex  # fixed-layout arm base
    orient0: int  # fixed-layout initial orientation
    calc: Hex  # fixed-layout calcification hex
    glyph_pos: Hex  # fixed-layout bonder cell 1
    glyph_dir: int  # bonder cell 2 = cell1 + dir; 0..2 only
    products: dict[str, Hex] | None = None
    # products=None: goal is the exact salt--water dimer resting UNHELD
    #   anywhere on the board (matches asp/stabilized_water.lp).
    # products={"salt": hex, "water": hex}: additionally the dimer must
    #   rest exactly on these two hexes (models a real output part; used
    #   by the omsim-exportable variant).
    t_max_default: int = 10

    @property
    def atoms(self):
        """Atom ids (input_index, pool_index), both 1-based."""
        return tuple((i, n) for i, p in enumerate(self.pools, 1) for n in range(1, p + 1))


# The clingo arm's exact fixed layout (asp/stabilized_water.lp): radius-2
# board, t_max 10; arm at origin; two water inputs, pool 2 each; calcifier
# at (1,-1); bonder on (-1,0)/(-1,1) (dir 1).  clingo results to match:
# fixed layout optimum 10 instructions; free layout min makespan 9
# (t_max=8 proven UNSAT).
SW = InstanceSW(
    name="sw",
    radius=2,
    pools=(2, 2),
    spawn_fixed=((1, 0), (0, 1)),
    base=(0, 0),
    orient0=0,
    calc=(1, -1),
    glyph_pos=(-1, 0),
    glyph_dir=1,  # second cell (-1,0)+dir1 = (-1,1)
    products=None,
    t_max_default=10,
)

# omsim-exportable variant: the machine layout of the known-good reference
# solution for P007 (jinyou archive, decoded in the design brief), one
# water input (a real P007 solution may use either/both inputs), pool 2,
# radius-3 board.  The product must rest exactly on the reference
# solution's output cells: salt@(1,0), water@(2,0) (out-std part at (1,0)
# rot 0).  No part overlaps another or the output cells, so a plan for
# this instance maps onto a game-legal .solution file.
SW_OMSIM = InstanceSW(
    name="sw-omsim",
    radius=3,
    pools=(2,),
    spawn_fixed=((2, -2),),
    base=(2, -1),
    orient0=4,
    calc=(1, -1),
    glyph_pos=(3, -2),
    glyph_dir=1,  # second cell (3,-2)+dir1 = (3,-1)
    products={"salt": (1, 0), "water": (2, 0)},
    t_max_default=16,
)

SW_CASES = {"sw": SW, "sw-omsim": SW_OMSIM}


def sw_scaled(radius):
    """The SW puzzle on a larger board (for free-layout scaling probes).
    Same parts and goal; the fixed layout stays the radius-2 one (it is
    still on-board), only the search space grows."""
    from dataclasses import replace

    return replace(SW, name=f"sw-r{radius}", radius=radius)
