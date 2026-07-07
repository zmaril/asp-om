% "Stabilized Water", bent-product variant, single arm.
% Reagent: water (respawning input). Product: one water atom bonded to two
% salt atoms at 120 degrees (a bent salt-water-salt trimer), exact molecule
% match (no extra bonds), anywhere on the board, unheld.
%
% NOTE ON THE PRODUCT SHAPE: a *linear* salt-water-salt trimer is provably
% impossible with a single arm and a single bonder (a held molecule can only
% ever be rotated about the one fixed base, and extending a chain colinearly
% requires a translation; see asp/sw_linear.lp for the two-arm version).
% The bent variant is the hardest product a one-arm machine can build.
%
% Layout (found by exhaustive BFS over all single-arm ring layouts;
% optimum = 25 instructions, so run with --tmax 25):
%   arm base (0,0) len 1, reagent input (1,0), calcification (1,-1),
%   bonder on (0,1)/(-1,1).

arm(m1).
base(m1,0,0).
armlen(m1,1).
init_orient(m1,0).

spawn(1, 1,0).
spawn_type(1,water).
pool(1,4).

glyph_calc(1,-1).
glyph_bond(0,1,-1,1).

% --- product: exact bent salt-water-salt ---------------------------------
% bond degree of every atom (0 if no bonds)
deg(X,T,N) :- exists(X,T), time(T), N = #count { Y : bond(X,Y,T) }.

complete(T) :-
    at(W,Q,R,T), type(W,water,T), deg(W,T,2), not held(W,T),
    dir(D1,DQ1,DR1), dir((D1+2)\6,DQ2,DR2), D1 < 6,
    at(S1,Q+DQ1,R+DR1,T), type(S1,salt,T), deg(S1,T,1), not held(S1,T),
    at(S2,Q+DQ2,R+DR2,T), type(S2,salt,T), deg(S2,T,1), not held(S2,T),
    bond(W,S1,T), bond(W,S2,T).

goal_met :- complete(T).

#show complete/1.
