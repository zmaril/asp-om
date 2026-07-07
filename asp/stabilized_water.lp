% "Stabilized Water" -- Opus Magnum campaign puzzle P007, TRUE decoded spec
% (byte-decoded from the game's puzzle file via omsim's parser):
%   reagents: TWO inputs, each a single unbonded WATER atom;
%   product:  ONE molecule = salt normal-bonded to water (2 atoms);
%   allowed parts: arms/piston/track, bonder, unbonder, multi-bonder,
%                  glyph of calcification.
% Intended solve: calcify one water into salt, bond it to the other water.
%
% Simplifications kept from core2: product completion = the exact molecule
% (salt deg-1 bonded to water deg-1) resting anywhere on the board, once
% (the game wants 6 copies delivered to a fixed output area).
%
% Layout (fixed facts; hand-designed, cross-checked by BFS -- optimum is
% 10 instructions, so t_max=10, the core default, suffices):
%   arm base (0,0) len 1; input 1 at (1,0); input 2 at (0,1);
%   calcification at (1,-1); bonder on (-1,0)/(-1,1).
% Plan: grab water 1, swing it ccw across the calcifier to (-1,0), drop;
% swing back, grab water 2, drop it on (-1,1) -> bond -> product.

arm(m1).
base(m1,0,0).
armlen(m1,1).
init_orient(m1,0).

spawn(1, 1,0).   spawn_type(1,water).   pool(1,2).
spawn(2, 0,1).   spawn_type(2,water).   pool(2,2).

glyph_calc(1,-1).
glyph_bond(-1,0,-1,1).

% --- product: exact salt--water dimer --------------------------------------
deg(X,T,N) :- exists(X,T), time(T), N = #count { Y : bond(X,Y,T) }.

complete(T) :-
    at(W,Q,R,T),        type(W,water,T), deg(W,T,1), not held(W,T),
    dir(D,DQ,DR),
    at(S,Q+DQ,R+DR,T),  type(S,salt,T),  deg(S,T,1), not held(S,T),
    bond(W,S,T).

goal_met :- complete(T).

#show complete/1.
