"""Decode a SAT model back into a human-readable plan: the chosen machine
layout, the per-timestep instruction program, and the atom trajectories."""

try:
    from instances import ACTIONS, DIRS
except ImportError:
    from sat.instances import ACTIONS, DIRS


def decode_model(enc, model):
    """Decode `model` (list of int literals) of `enc` (Encoder) into a plan
    dict:
      {base, length, orient0, glyph (None or (cell1, cell2)),
       instructions: [action]*T,
       orient: [d]*(T+1),
       gripper: [(q,r)]*(T+1),
       traj: {atom: [(q,r)]*(T+1)},
       hold: [atom or None]*(T+1),
       bonds: [set of frozenset pairs]*(T+1)}
    """
    true = {lit for lit in model if lit > 0}

    def tv(*key):
        return enc.v(*key) in true

    inst, T = enc.inst, enc.T
    plan = {}
    plan["base"] = next(h for h in enc.hexes if tv("base", h))
    plan["length"] = next(ln for ln in enc.lengths if tv("alen", ln))
    plan["orient0"] = next(d for d in range(6) if tv("orient", d, 0))
    plan["glyph"] = None
    if inst.has_glyph:
        gp = next(h for h in enc.hexes if tv("gpos", h))
        gd = next(d for d in range(6) if tv("gdir", d))
        plan["glyph"] = (gp, (gp[0] + DIRS[gd][0], gp[1] + DIRS[gd][1]))

    plan["instructions"] = [next(a for a in ACTIONS if tv("do", a, t)) for t in range(T)]
    plan["orient"] = [next(d for d in range(6) if tv("orient", d, t)) for t in range(T + 1)]
    plan["gripper"] = [next(h for h in enc.hexes if tv("grip", h, t)) for t in range(T + 1)]
    plan["traj"] = {
        x: [next(h for h in enc.hexes if tv("at", x, h, t)) for t in range(T + 1)]
        for x in inst.atoms
    }
    plan["hold"] = [next((x for x in inst.atoms if tv("hold", x, t)), None) for t in range(T + 1)]
    plan["bonds"] = [{frozenset(p) for p in enc.pairs if tv("bond", p, t)} for t in range(T + 1)]
    return plan


def format_plan(plan, inst):
    """Pretty-print a decoded plan."""
    T = len(plan["instructions"])
    lines = []
    lines.append(
        f"layout: base={plan['base']} length={plan['length']} "
        f"init_orient={plan['orient0']}"
        + (f" glyph_bond={plan['glyph'][0]}-{plan['glyph'][1]}" if plan["glyph"] else "")
    )
    lines.append(
        f"plan ({T} steps, {sum(1 for a in plan['instructions'] if a != 'wait')} non-wait):"
    )
    for t in range(T + 1):
        atoms = "  ".join(f"{x}@{plan['traj'][x][t]}" for x in inst.atoms)
        held = f" holding={plan['hold'][t]}" if plan["hold"][t] else ""
        bonds = ""
        if plan["bonds"][t]:
            bonds = " bonds=" + ",".join(
                "-".join(sorted(p)) for p in sorted(plan["bonds"][t], key=sorted)
            )
        state = f"  t={t:2d} grip={plan['gripper'][t]} D={plan['orient'][t]}  {atoms}{held}{bonds}"
        lines.append(state)
        if t < T:
            lines.append(f"       step {t}: {plan['instructions'][t]}")
    return "\n".join(lines)
