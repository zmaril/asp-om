"""Independent forward simulator / validator for the phase-2 fragment
(Stabilized Water).

Shares NO logic with the encoder: it re-simulates the decoded layout +
instruction list from scratch (decoded trajectories are only used as an
optional cross-check) against the clingo-core2 semantics:

  * layout sanity: all parts on the board, bonder cells adjacent (dir<3),
    no two parts overlap, no part on a fixed product hex;
  * gripper (= base + dir(orient), length-1 arm) on the board always;
  * grab needs an empty hand and an atom under the gripper; drop needs a
    held atom;
  * rotating while holding rigidly rotates the held atom's whole
    bond-connected component (closure over the bond graph at time t)
    about the arm base; a swing leaving the board is illegal; unmoved
    atoms stay put;
  * no two atoms share a hex; atoms never sit on the arm base;
  * an elemental (water) atom on the calcifier hex at t is salt from t+1;
  * whenever both bonder cells are occupied at t the occupants are bonded
    at t (bonds symmetric, persist forever);
  * reagent input i's atom n+1 appears on the spawn hex at the first t+1
    when no atom that existed at t occupies that hex (bounded pool);
  * goal at the horizon: an exact salt--water dimer -- water atom W and
    salt atom S, adjacent, bonded to each other and to nothing else, both
    unheld (and on the instance's product hexes if those are fixed).

Returns a list of error strings; empty = valid.
"""

_DIRS = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]


def _board(radius):
    return set((q, r)
               for q in range(-radius, radius + 1)
               for r in range(-radius, radius + 1)
               if abs(q + r) <= radius)


def _rot(base, h, cw):
    q, r = h[0] - base[0], h[1] - base[1]
    if cw:
        return (base[0] - r, base[1] + q + r)
    return (base[0] + q + r, base[1] - q)


def validate_plan2(inst, plan, cross_check_traj=True):
    errors = []
    board = _board(inst.radius)
    base = tuple(plan["base"])
    orient = plan["orient0"]
    spawns = [tuple(h) for h in plan["spawns"]]
    calc = tuple(plan["calc"])
    g1, g2 = tuple(plan["glyph"][0]), tuple(plan["glyph"][1])
    instructions = plan["instructions"]
    T = len(instructions)

    # ---- layout sanity ----
    for h, what in ([(base, "arm base"), (calc, "calcifier"),
                     (g1, "bonder cell 1"), (g2, "bonder cell 2")]
                    + [(s, f"input {i+1}") for i, s in enumerate(spawns)]):
        if h not in board:
            errors.append(f"{what} {h} is off the board")
    d = (g2[0] - g1[0], g2[1] - g1[1])
    if d not in _DIRS[:3]:
        errors.append(f"bonder cells {g1},{g2} not adjacent with dir<3")
    feet = [(base, "arm base"), (calc, "calcifier"), (g1, "bonder"),
            (g2, "bonder")] + [(s, f"input{i+1}")
                               for i, s in enumerate(spawns)]
    for i in range(len(feet)):
        for j in range(i + 1, len(feet)):
            if feet[i][0] == feet[j][0] and not (
                    feet[i][1] == feet[j][1] == "bonder"):
                errors.append(f"parts overlap at {feet[i][0]}: "
                              f"{feet[i][1]} and {feet[j][1]}")
    if inst.products:
        prod = set(tuple(h) for h in inst.products.values())
        for h, what in feet:
            if h in prod:
                errors.append(f"{what} overlaps product hex {h}")
    if errors:
        return errors

    # ---- simulate ----
    # atom state: pos[x], salt[x] (else water), spawned pool count per input
    pos, salt = {}, {}
    npool = {}
    for i, s in enumerate(spawns):
        npool[i] = 1
        pos[(i + 1, 1)] = s
        salt[(i + 1, 1)] = False
    held = None
    bonds = set()

    def gripper():
        return (base[0] + _DIRS[orient][0], base[1] + _DIRS[orient][1])

    def component(x):
        comp, todo = {x}, [x]
        while todo:
            y = todo.pop()
            for b in bonds:
                if y in b:
                    (z,) = b - {y}
                    if z not in comp:
                        comp.add(z)
                        todo.append(z)
        return comp

    def state_checks(t):
        if gripper() not in board:
            errors.append(f"t={t}: gripper {gripper()} off the board")
        seen = {}
        for x, h in pos.items():
            if h not in board:
                errors.append(f"t={t}: atom {x} off the board at {h}")
            if h == base:
                errors.append(f"t={t}: atom {x} on the arm base {h}")
            if h in seen:
                errors.append(f"t={t}: atoms {seen[h]} and {x} collide "
                              f"at {h}")
            seen[h] = x

    def update_bonds(t):
        occ1 = [x for x, h in pos.items() if h == g1]
        occ2 = [x for x, h in pos.items() if h == g2]
        if occ1 and occ2 and occ1[0] != occ2[0]:
            bonds.add(frozenset((occ1[0], occ2[0])))

    sim_traj = {x: {0: pos[x]} for x in pos}
    state_checks(0)
    update_bonds(0)

    for t, act in enumerate(instructions):
        # calcification is decided by positions at t, applied at t+1
        calcify = [x for x, h in pos.items() if h == calc and not salt[x]]
        if act == "grab":
            if held is not None:
                errors.append(f"step {t}: grab with hand full ({held})")
            target = [x for x, h in pos.items() if h == gripper()]
            if not target:
                errors.append(f"step {t}: grab over an empty hex")
            else:
                held = target[0]
        elif act == "drop":
            if held is None:
                errors.append(f"step {t}: drop with empty hand")
            held = None
        elif act in ("rot_cw", "rot_ccw"):
            cw = act == "rot_cw"
            if held is not None:
                for x in component(held):
                    h2 = _rot(base, pos[x], cw)
                    if h2 not in board:
                        errors.append(
                            f"step {t}: rotation swings atom {x} off the "
                            f"board to {h2}")
                    pos[x] = h2
            orient = (orient + (1 if cw else 5)) % 6
        elif act == "wait":
            pass
        else:
            errors.append(f"step {t}: unknown instruction {act!r}")

        # spawns: input i's next atom appears if no atom that existed at t
        # sits on the spawn hex at t+1
        old_atoms = set(pos)
        for i, s in enumerate(spawns):
            if npool[i] < inst.pools[i]:
                if not any(pos[x] == s for x in old_atoms):
                    npool[i] += 1
                    x = (i + 1, npool[i])
                    pos[x] = s
                    salt[x] = False
                    sim_traj[x] = {}
        for x in calcify:
            salt[x] = True
        for x in pos:
            sim_traj[x][t + 1] = pos[x]
        state_checks(t + 1)
        update_bonds(t + 1)

    # ---- goal: exact salt--water dimer at the horizon ----
    ok = False
    for b in bonds:
        x, y = tuple(b)
        pair_ok = (salt[x] != salt[y]
                   and held not in (x, y)
                   and sum(1 for bb in bonds if x in bb) == 1
                   and sum(1 for bb in bonds if y in bb) == 1)
        s_atom, w_atom = (x, y) if salt[x] else (y, x)
        diff = (pos[s_atom][0] - pos[w_atom][0],
                pos[s_atom][1] - pos[w_atom][1])
        if diff not in _DIRS:
            pair_ok = False
        if pair_ok and inst.products:
            if (pos[s_atom] != tuple(inst.products["salt"])
                    or pos[w_atom] != tuple(inst.products["water"])):
                pair_ok = False
        if pair_ok:
            ok = True
    if not ok:
        errors.append("goal: no exact unheld salt--water dimer at the "
                      "horizon" + (" on the product hexes"
                                   if inst.products else ""))

    # ---- optional cross-check against decoded state ----
    if cross_check_traj and "traj" in plan:
        for x in inst.atoms:
            claimed = plan["traj"][x]
            claimed_ex = plan["exists"][x]
            for t in range(T + 1):
                sim_h = sim_traj.get(x, {}).get(t)
                cl_h = tuple(claimed[t]) if claimed[t] is not None else None
                if bool(claimed_ex[t]) != (sim_h is not None):
                    errors.append(
                        f"decoded existence of {x} at t={t} disagrees with "
                        f"re-simulation")
                elif sim_h is not None and cl_h != sim_h:
                    errors.append(
                        f"decoded position of {x} at t={t} ({cl_h}) "
                        f"disagrees with re-simulation ({sim_h})")
            if claimed_ex[T] and x in salt:
                if bool(plan["salt"][x][T]) != salt[x]:
                    errors.append(
                        f"decoded final type of {x} disagrees with "
                        f"re-simulation")
        if plan.get("bonds") is not None:
            if plan["bonds"][T] != bonds:
                errors.append("decoded final bond set disagrees with "
                              "re-simulation")

    return errors
