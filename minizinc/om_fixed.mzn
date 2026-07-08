% ===========================================================================
% Fixed-layout variant: same model as om.mzn, but arm bases and glyph
% positions are pinned to the given_* parameters from the instance file.
% This variant matches the clingo instances (asp/*.lp) exactly.
% Usage: minizinc --solver gecode minizinc/om_fixed.mzn minizinc/instances/t1_transport.dzn
% ===========================================================================

include "om.mzn";

constraint forall(m in ARM)(
    base_q[m] = given_base_q[m] /\ base_r[m] = given_base_r[m]);
constraint forall(g in BONDER)(
    bonder_q1[g] = given_bonder[g,1] /\ bonder_r1[g] = given_bonder[g,2] /\
    bonder_q2[g] = given_bonder[g,3] /\ bonder_r2[g] = given_bonder[g,4]);
constraint forall(g in CALC)(
    calc_q[g] = given_calc[g,1] /\ calc_r[g] = given_calc[g,2]);
