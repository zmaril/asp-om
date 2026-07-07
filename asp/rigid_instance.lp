% Rigid-motion test: a pre-bonded 2-atom molecule a1-(1,0) -- a2-(2,0).
% Grab a1 (the end at distance 1) and rotate: a2 must swing rigidly about
% the arm base, two hexes of arc per 60-degree step (it sits at distance 2).
% Goal: a1 at (-1,1), a2 at (-2,2), unheld -- exactly two cw rotations away.
% Optimal plan: grab, rot_cw, rot_cw, drop (4 instructions).

arm(m1).
base(m1,0,0).
armlen(m1,1).
init_orient(m1,0).

init_at(a1,1,0).   init_type(a1,salt).
init_at(a2,2,0).   init_type(a2,salt).
init_bond(a1,a2).

goal_met :- at(a1,-1,1,t_max), at(a2,-2,2,t_max),
            not held(a1,t_max), not held(a2,t_max).
