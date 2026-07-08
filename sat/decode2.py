"""Decode a phase-2 SAT model into a plan dict: the chosen machine layout,
the instruction program, and per-timestep atom state."""

try:
    from instances import DIRS
    from encode2 import ACTIONS2
except ImportError:
    from sat.instances import DIRS
    from sat.encode2 import ACTIONS2


def decode_model2(enc, model):
    true = set(l for l in model if l > 0)

    def tv(*key):
        return enc.v(*key) in true

    inst, T = enc.inst, enc.T
    X = enc.atoms
    plan = {}
    plan["base"] = next(h for h in enc.hexes if tv("base", h))
    plan["orient0"] = next(d for d in range(6) if tv("orient", d, 0))
    plan["spawns"] = [next(h for h in enc.hexes if tv("spawn", i, h))
                      for i in range(1, len(inst.pools) + 1)]
    plan["calc"] = next(h for h in enc.hexes if tv("cpos", h))
    gp = next(h for h in enc.hexes if tv("gpos", h))
    gd = next(d for d in range(3) if tv("gdir", d))
    plan["glyph"] = (gp, (gp[0] + DIRS[gd][0], gp[1] + DIRS[gd][1]))
    plan["instructions"] = [
        next(a for a in ACTIONS2 if tv("do", a, t)) for t in range(T)]
    plan["orient"] = [
        next(d for d in range(6) if tv("orient", d, t)) for t in range(T + 1)]
    plan["gripper"] = [
        next(h for h in enc.hexes if tv("grip", h, t)) for t in range(T + 1)]
    plan["exists"] = {
        x: [tv("ex", x, t) for t in range(T + 1)] for x in X}
    plan["traj"] = {
        x: [next((h for h in enc.hexes if tv("at", x, h, t)), None)
            for t in range(T + 1)]
        for x in X}
    plan["salt"] = {
        x: [tv("salt", x, t) for t in range(T + 1)] for x in X}
    plan["hold"] = [
        next((x for x in X if tv("hold", x, t)), None)
        for t in range(T + 1)]
    plan["bonds"] = [
        set(frozenset(p) for p in enc.pairs if tv("bond", p, t))
        for t in range(T + 1)]
    return plan


def _aname(x):
    return f"r{x[0]}.{x[1]}"


def format_plan2(plan, inst):
    T = len(plan["instructions"])
    lines = []
    spawns = " ".join(f"in{i+1}={h}" for i, h in enumerate(plan["spawns"]))
    lines.append(
        f"layout: base={plan['base']} init_orient={plan['orient0']} "
        f"{spawns} calc={plan['calc']} "
        f"bonder={plan['glyph'][0]}-{plan['glyph'][1]}")
    lines.append(f"plan ({T} steps, "
                 f"{sum(1 for a in plan['instructions'] if a != 'wait')} "
                 f"non-wait):")
    for t in range(T + 1):
        atoms = "  ".join(
            f"{_aname(x)}[{'salt' if plan['salt'][x][t] else 'water'}]"
            f"@{plan['traj'][x][t]}"
            for x in inst.atoms if plan["exists"][x][t])
        held = (f" holding={_aname(plan['hold'][t])}"
                if plan["hold"][t] else "")
        bonds = ""
        if plan["bonds"][t]:
            bonds = " bonds=" + ",".join(
                "-".join(_aname(a) for a in sorted(p))
                for p in sorted(plan["bonds"][t], key=sorted))
        lines.append(f"  t={t:2d} grip={plan['gripper'][t]} "
                     f"D={plan['orient'][t]}  {atoms}{held}{bonds}")
        if t < T:
            lines.append(f"       step {t}: {plan['instructions'][t]}")
    return "\n".join(lines)
