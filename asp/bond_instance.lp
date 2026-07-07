% Trivial instance 2: bond two salt atoms with a glyph of bonding.
% Arm base at origin, length 1. Atoms a1 at (1,0) and a2 at (0,1).
% A glyph of bonding occupies the adjacent hexes (-1,0) and (0,-1);
% when both hexes are occupied a bond forms between the occupants.
% Goal: a1 on (-1,0), a2 on (0,-1), bonded, at t_max.
% Run with -c t_max=16 (default core horizon of 10 is too short).

base(0,0).
init_orient(0).

atom(a1; a2).
init_at(a1, 1, 0).
init_at(a2, 0, 1).

glyph_bond(-1,0, 0,-1).

product(a1, -1, 0).
product(a2,  0,-1).

% Bond forms whenever both glyph hexes are occupied; bonds persist.
bond(X,Y,T)   :- glyph_bond(Q1,R1,Q2,R2), at(X,Q1,R1,T), at(Y,Q2,R2,T), X != Y.
bond(X,Y,T+1) :- bond(X,Y,T), step(T).

% Phase-1 simplification: a length-1 arm rotating a bonded atom would have
% to drag the whole molecule (rigid-body rotation about the base). We do not
% model multi-atom molecule movement yet, so forbid rotating while holding a
% bonded atom.
bondpart(X,T) :- bond(X,Y,T).
bondpart(X,T) :- bond(Y,X,T).
:- do(rot_cw,T),  holding(X,T), bondpart(X,T).
:- do(rot_ccw,T), holding(X,T), bondpart(X,T).

% Goal additionally requires the bond to exist at the end.
goal_bond :- bond(X,Y,t_max).
:- not goal_bond.

#show bond/3.
