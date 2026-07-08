"""Independent forward simulator / plan validator.

Deliberately shares NO logic with the encoder: it re-simulates the plan
forward from only the decoded layout and instruction list (the decoded
trajectories are used solely as an optional cross-check) and verifies the
brief's phase-1 mechanics:

  * layout sanity: base on the board, glyph cells on-board and adjacent;
  * gripper (= base + length*dir(orient)) stays on the board at all times;
  * grab requires an empty hand and an atom under the gripper;
  * drop requires a held atom;
  * a held atom rides the gripper; free atoms never move;
  * no two atoms ever share a hex; atoms stay on the board;
  * bonds form whenever both glyph cells are occupied (held or not) and
    persist forever;
  * rotating while holding a bonded atom is forbidden (phase-1 rule);
  * goal: every product atom sits UNHELD on its target hex at the horizon,
    and (case b) at least one bond exists at the horizon.

Returns a list of error strings; empty list = plan valid.
"""

from typing import Any

# Direction table re-declared here on purpose (fixed by the shared brief);
# do not import it from the encoder.
_DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]


def _board(radius):
    return {
        (q, r)
        for q in range(-radius, radius + 1)
        for r in range(-radius, radius + 1)
        if abs(q + r) <= radius
    }


def validate_plan(inst, plan, cross_check_traj=True):
    errors = []
    board = _board(inst.radius)
    base = tuple(plan["base"])
    length = plan["length"]
    orient = plan["orient0"]
    instructions = plan["instructions"]
    glyph = plan.get("glyph")
    T = len(instructions)

    # ---- layout sanity ----
    if base not in board:
        errors.append(f"arm base {base} is off the board")
    if not (1 <= length <= inst.max_arm_len):
        errors.append(f"arm length {length} outside 1..{inst.max_arm_len}")
    if inst.has_glyph:
        if glyph is None:
            errors.append("instance has a bonding glyph but plan places none")
        else:
            c1, c2 = tuple(glyph[0]), tuple(glyph[1])
            if c1 not in board or c2 not in board:
                errors.append(f"glyph cells {c1},{c2} not both on the board")
            d = (c2[0] - c1[0], c2[1] - c1[1])
            if d not in _DIRS:
                errors.append(f"glyph cells {c1},{c2} are not adjacent")
    elif glyph is not None:
        errors.append("plan places a glyph but the instance has none")
    if errors:
        return errors  # layout broken; simulation would be meaningless

    def gripper(d):
        return (base[0] + length * _DIRS[d][0], base[1] + length * _DIRS[d][1])

    # ---- simulate ----
    pos = {x: tuple(h) for x, h in inst.init_at.items()}
    held = None
    bonds = set()
    sim_traj = {x: [pos[x]] for x in pos}

    def state_checks(t):
        if gripper(orient) not in board:
            errors.append(f"t={t}: gripper {gripper(orient)} off the board")
        for x, h in pos.items():
            if h not in board:
                errors.append(f"t={t}: atom {x} off the board at {h}")
        seen: dict[tuple[int, int], Any] = {}
        for x, h in pos.items():
            if h in seen:
                errors.append(f"t={t}: atoms {seen[h]} and {x} collide at {h}")
            seen[h] = x

    def update_bonds(t):
        if glyph is None:
            return
        c1, c2 = tuple(glyph[0]), tuple(glyph[1])
        occ1 = [x for x, h in pos.items() if h == c1]
        occ2 = [x for x, h in pos.items() if h == c2]
        if occ1 and occ2 and occ1[0] != occ2[0]:
            bonds.add(frozenset((occ1[0], occ2[0])))

    state_checks(0)
    update_bonds(0)

    for t, act in enumerate(instructions):
        if act == "grab":
            if held is not None:
                errors.append(f"step {t}: grab with hand already holding {held}")
            target = [x for x, h in pos.items() if h == gripper(orient)]
            if not target:
                errors.append(f"step {t}: grab with nothing under the gripper")
            else:
                held = target[0]
        elif act == "drop":
            if held is None:
                errors.append(f"step {t}: drop with empty hand")
            held = None
        elif act in ("rot_cw", "rot_ccw"):
            if held is not None and any(held in b for b in bonds):
                errors.append(f"step {t}: rotation while holding bonded atom {held}")
            orient = (orient + (1 if act == "rot_cw" else 5)) % 6
            if held is not None:
                pos[held] = gripper(orient)
        elif act == "wait":
            pass
        else:
            errors.append(f"step {t}: unknown instruction {act!r}")
        for x in pos:
            sim_traj[x].append(pos[x])
        state_checks(t + 1)
        update_bonds(t + 1)

    # ---- goal ----
    for x, target in inst.products.items():
        if pos[x] != tuple(target):
            errors.append(f"goal: product {x} at {pos[x]}, wanted {tuple(target)}")
        if held == x:
            errors.append(f"goal: product {x} still held at the horizon")
    if inst.require_bond and not bonds:
        errors.append("goal: no bond exists at the horizon")

    # ---- optional cross-check against the decoder's claimed trajectories ----
    if cross_check_traj and "traj" in plan:
        for x in inst.atoms:
            claimed = [tuple(h) for h in plan["traj"][x]]
            if claimed != sim_traj[x]:
                errors.append(
                    f"decoded trajectory of {x} disagrees with re-simulation: "
                    f"decoded {claimed} vs simulated {sim_traj[x]}"
                )
        if "bonds" in plan and glyph is not None and bool(plan["bonds"][T]) != bool(bonds):
            errors.append("decoded final bond state disagrees with re-simulation")

    return errors
