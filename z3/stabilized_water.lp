% ===========================================================================
% Stabilized Water (omsim P007) as a clingo instance for asp/core2.lp.
% ===========================================================================
% Defined by the Z3 arm for apples-to-apples timing (there was no clingo
% instance for this puzzle).  Identical to the "water" instance in
% z3/om_solver.py -- see z3/NOTES.md for the modelling choices:
%   * two 1-atom WATER reagents = two spawn hexes with a 1-atom pool each,
%     which under core2's spawn/nreagent machinery degenerates to two
%     init_at facts (output_scale=1: only one product is needed);
%   * product = salt on (-1,0) bonded to water on (0,-1); the slots are
%     anonymous (either atom may fill either slot);
%   * fixed layout: arm at origin, calcification glyph at (-1,1) on the
%     carry path, bonding glyph on the product hexes.
%
% Run:  python3 run.py asp/core2.lp z3/stabilized_water.lp --tmax 12
% (run.py's trace printer only understands v1 predicates and crashes after
%  printing Result/cost on core2 models; solving is unaffected.)
% Expected optimum: 10.
% ===========================================================================

#const t_max=12.

arm(m1).
base(m1,0,0).
armlen(m1,1).
init_orient(m1,0).

init_at(w1,1,0).    init_type(w1,water).
init_at(w2,1,-1).   init_type(w2,water).

glyph_bond(-1,0,0,-1).
glyph_calc(-1,1).

% Product: a salt--water molecule on the two product hexes, unheld, bonded.
salt_slot(X)  :- at(X,-1,0,t_max), type(X,salt,t_max),  not held(X,t_max).
water_slot(Y) :- at(Y,0,-1,t_max), type(Y,water,t_max), not held(Y,t_max).
goal_met :- salt_slot(X), water_slot(Y), bond(X,Y,t_max).
