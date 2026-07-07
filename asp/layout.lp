% ===========================================================================
% Free-layout module: let the SOLVER place the machine, not the instance.
% ===========================================================================
% Include this file (core2.lp + layout.lp + instance) and declare parts
% abstractly instead of writing base/spawn/glyph facts:
%
%   place_arm(M,L)       -- arm M with length L, position/orientation free
%   place_input(I,E,P)   -- reagent input I, atom type E, pool P
%   place_calc(G)        -- a glyph of calcification, position free
%   place_bond(G)        -- a glyph of bonding, position/orientation free
%
% The solver chooses every placement inside the bounded board (hex/2),
% subject to OM's rule that parts must not overlap. Instances may still fix
% any subset of the layout with ordinary facts (those parts just shouldn't
% also be declared with place_*).
% ===========================================================================

#defined place_arm/2.  #defined place_input/3.
#defined place_calc/1. #defined place_bond/1.

% --- arms ------------------------------------------------------------------
arm(M) :- place_arm(M,_).
{ base(M,Q,R) : hex(Q,R) } = 1 :- place_arm(M,_).
armlen(M,L) :- place_arm(M,L).
{ init_orient(M,D) : dir(D,_,_) } = 1 :- place_arm(M,_).

% --- reagent inputs ---------------------------------------------------------
{ spawn(I,Q,R) : hex(Q,R) } = 1 :- place_input(I,_,_).
spawn_type(I,E) :- place_input(I,E,_).
pool(I,P)       :- place_input(I,_,P).

% --- glyph of calcification (1 hex) -----------------------------------------
{ calc_at(G,Q,R) : hex(Q,R) } = 1 :- place_calc(G).
glyph_calc(Q,R) :- calc_at(G,Q,R).

% --- glyph of bonding (2 adjacent hexes; D<3 breaks the mirror symmetry) ----
{ bond_at(G,Q,R,D) : hex(Q,R), dir(D,_,_), D < 3 } = 1 :- place_bond(G).
:- bond_at(G,Q,R,D), dir(D,DQ,DR), not hex(Q+DQ,R+DR).
glyph_bond(Q,R,Q+DQ,R+DR) :- bond_at(G,Q,R,D), dir(D,DQ,DR), hex(Q+DQ,R+DR).

% --- parts must not overlap (OM rule) ----------------------------------------
foot(arm(M),Q,R)  :- base(M,Q,R).
foot(inp(I),Q,R)  :- spawn(I,Q,R).
foot(calc(G),Q,R) :- calc_at(G,Q,R).
foot(bnd(G),Q,R)  :- bond_at(G,Q,R,_).
foot(bnd(G),Q+DQ,R+DR) :- bond_at(G,Q,R,D), dir(D,DQ,DR).
:- foot(P1,Q,R), foot(P2,Q,R), P1 < P2.
