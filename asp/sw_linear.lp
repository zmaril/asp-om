% "Stabilized Water" (Opus Magnum chapter 1), linear-product spec.
% Reagent: single water atom (respawning input). Product: salt-water-salt
% in a straight line, exact molecule match, anywhere on the board, unheld.
% Parts: glyph of calcification, glyph of bonding, arms.
%
% A single arm cannot build this product: a held molecule only ever rotates
% about the one fixed base, so its final placement is a 60k-degree rotation
% of the configuration it had when the bond formed -- but extending a chain
% colinearly requires a TRANSLATION. Two arms compose rotations about two
% different pivots into a one-hex translation (rotate +60 about base1, then
% -60 about base2). Exhaustive BFS over ring layouts confirms: 0/144
% single-arm layouts solve this; the two-arm layout below does, optimally
% in 36 instructions. Run with --tmax 36.
%
% Layout: arm m1 base (0,0) len 1; arm m2 base (1,0) len 2 (its gripper can
% only occupy orients 2..4 on the radius-2 board, which is all it needs);
% reagent input (0,1); calcification (1,-1); bonder on (-1,0)/(-1,1).

arm(m1;m2).
base(m1,0,0).   armlen(m1,1).   init_orient(m1,0).
base(m2,1,0).   armlen(m2,2).   init_orient(m2,3).

spawn(1, 0,1).
spawn_type(1,water).
pool(1,4).

glyph_calc(1,-1).
glyph_bond(-1,0,-1,1).

% --- product: exact linear salt-water-salt --------------------------------
deg(X,T,N) :- exists(X,T), time(T), N = #count { Y : bond(X,Y,T) }.

complete(T) :-
    at(W,Q,R,T), type(W,water,T), deg(W,T,2), not held(W,T),
    dir(D,DQ,DR), D < 3,                     % 3 axes suffice for a line
    at(S1,Q+DQ,R+DR,T), type(S1,salt,T), deg(S1,T,1), not held(S1,T),
    at(S2,Q-DQ,R-DR,T), type(S2,salt,T), deg(S2,T,1), not held(S2,T),
    bond(W,S1,T), bond(W,S2,T).

goal_met :- complete(T).

#show complete/1.
