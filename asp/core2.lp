% ===========================================================================
% Opus Magnum -- core ASP encoding, v2 (phase 2)
% ===========================================================================
% Extends v1 (asp/core.lp) with:
%   * RIGID MOLECULE MOTION: rotating an arm that holds an atom rigidly
%     rotates the atom's whole bond-connected component about the arm base.
%   * Multiple arms (at most one arm acts per timestep; idle = wait),
%     per-arm length (armlen/2).
%   * Atom element types, glyph of calcification (elemental -> salt).
%   * Glyph(s) of bonding moved into the core (glyph_bond/4 facts).
%   * Respawning reagent inputs: spawn(I,Q,R) + spawn_type(I,E) + pool(I,P)
%     facts (I = input index). r(I,1) is present at t=0; r(I,N+1) appears
%     as soon as input I's hex is free again (bounded pool of P atoms per
%     input approximates OM's unlimited inputs).
%   * Goal is instance-defined: the instance must derive goal_met.
%
% Hex rotation about the origin in axial coords, matching the clockwise
% dir/3 indexing below (verified: maps dir D onto dir D+1):
%   rot_cw : (Q,R) -> (-R, Q+R)
%   rot_ccw: (Q,R) -> (Q+R, -Q)
%
% An instance supplies: arm/1, base/3, armlen/2, init_orient/2,
% init_at/3, init_type/2, init_bond/2, glyph_bond/4, glyph_calc/2,
% spawn/3, spawn_type/2, pool/2, goal_met rules, and consts t_max/radius.
% ===========================================================================

#const t_max=10.
#const radius=2.

#defined init_at/3.  #defined init_type/2.  #defined init_bond/2.
#defined spawn/3.    #defined spawn_type/2. #defined pool/2.
#defined glyph_bond/4.  #defined glyph_calc/2.

time(0..t_max).
step(0..t_max-1).

hex(Q,R) :- Q = -radius..radius, R = -radius..radius, |Q+R| <= radius.

dir(0,  1,  0).
dir(1,  0,  1).
dir(2, -1,  1).
dir(3, -1,  0).
dir(4,  0, -1).
dir(5,  1, -1).

% ---------------------------------------------------------------------------
% Atoms: pre-placed ones plus the reagent pool r(1..nreagent).
% ---------------------------------------------------------------------------
elemental(air; earth; fire; water).

exists(X,0) :- init_at(X,_,_).
at(X,Q,R,0) :- init_at(X,Q,R).
type(X,E,0) :- init_type(X,E).
bond(X,Y,0) :- init_bond(X,Y).
bond(Y,X,0) :- init_bond(X,Y).

exists(r(I,1),0) :- spawn(I,_,_), pool(I,P), P > 0.
at(r(I,1),Q,R,0) :- spawn(I,Q,R), pool(I,P), P > 0.
type(r(I,1),E,0) :- spawn(I,_,_), spawn_type(I,E), pool(I,P), P > 0.

exists(X,T+1) :- exists(X,T), step(T).
% hex occupied at T+1 by an atom that already existed at T:
occ_old(Q,R,T+1) :- at(X,Q,R,T+1), exists(X,T), step(T).
% input I's next reagent atom appears as soon as its hex is clear:
spawns(r(I,N+1),T+1) :- exists(r(I,N),T), not exists(r(I,N+1),T),
                        pool(I,P), N < P,
                        spawn(I,Q,R), not occ_old(Q,R,T+1), step(T).
exists(X,T) :- spawns(X,T).
at(r(I,N),Q,R,T) :- spawns(r(I,N),T), spawn(I,Q,R).
type(r(I,N),E,T) :- spawns(r(I,N),T), spawn_type(I,E).

% ---------------------------------------------------------------------------
% Arms and actions: at most one (arm, action) per timestep; idle = wait.
% ---------------------------------------------------------------------------
action(rot_cw; rot_ccw; grab; drop).
{ do(M,A,T) : arm(M), action(A) } 1 :- step(T).

orient(M,D,0) :- init_orient(M,D).
turns(M,T) :- do(M,rot_cw,T).
turns(M,T) :- do(M,rot_ccw,T).
orient(M,(D+1) \ 6, T+1) :- orient(M,D,T), do(M,rot_cw,T).
orient(M,(D+5) \ 6, T+1) :- orient(M,D,T), do(M,rot_ccw,T).
orient(M,D,T+1)          :- orient(M,D,T), not turns(M,T), step(T).

gripper(M, BQ+L*DQ, BR+L*DR, T) :-
    base(M,BQ,BR), armlen(M,L), orient(M,D,T), dir(D,DQ,DR).
:- gripper(M,Q,R,T), not hex(Q,R).

% ---------------------------------------------------------------------------
% Grab / drop.
% ---------------------------------------------------------------------------
holding(M,X,T+1) :- do(M,grab,T), gripper(M,Q,R,T), at(X,Q,R,T).
holding(M,X,T+1) :- holding(M,X,T), not do(M,drop,T), step(T).
held(X,T)    :- holding(M,X,T).
armfull(M,T) :- holding(M,X,T).
occupied(Q,R,T) :- at(X,Q,R,T).

:- do(M,grab,T), armfull(M,T).                            % hand already full
:- do(M,grab,T), gripper(M,Q,R,T), not occupied(Q,R,T).   % nothing to grab
:- do(M,grab,T), gripper(M,Q,R,T), at(X,Q,R,T), held(X,T).% held by other arm
:- do(M,drop,T), not armfull(M,T).                        % nothing to drop

% ---------------------------------------------------------------------------
% Bonds (symmetric, persistent) and the held connected component.
% ---------------------------------------------------------------------------
bond(X,Y,T)   :- glyph_bond(Q1,R1,Q2,R2), at(X,Q1,R1,T), at(Y,Q2,R2,T), X != Y.
bond(Y,X,T)   :- bond(X,Y,T).
bond(X,Y,T+1) :- bond(X,Y,T), step(T).

comp(M,X,T) :- holding(M,X,T).
comp(M,X,T) :- comp(M,Y,T), bond(Y,X,T).

% a rotation may not tear an atom out of another arm's hand
:- turns(M,T), comp(M,X,T), holding(M2,X,T), M2 != M.

% ---------------------------------------------------------------------------
% Motion: rotating an arm rigidly rotates its held component about its base.
% rotimg_*(M,Q,R,NQ,NR): the image of board hex (Q,R) under a 60-degree
% rotation about M's base. Precomputing this per (arm, hex) keeps the
% grounder's over-approximation of at/4 inside the board -- deriving
% off-board positions and pruning them later makes grounding explode
% (two pivots generate an unbounded position closure).
% ---------------------------------------------------------------------------
rotimg_cw(M,Q,R, BQ-(R-BR), BR+(Q-BQ)+(R-BR)) :- base(M,BQ,BR), hex(Q,R).
rotimg_ccw(M,Q,R, BQ+(Q-BQ)+(R-BR), BR-(Q-BQ)) :- base(M,BQ,BR), hex(Q,R).

moved(X,T) :- turns(M,T), comp(M,X,T).
at(X,NQ,NR,T+1) :- do(M,rot_cw,T),  comp(M,X,T), at(X,Q,R,T),
                   rotimg_cw(M,Q,R,NQ,NR),  hex(NQ,NR).
at(X,NQ,NR,T+1) :- do(M,rot_ccw,T), comp(M,X,T), at(X,Q,R,T),
                   rotimg_ccw(M,Q,R,NQ,NR), hex(NQ,NR).
% a rotation that would swing any held-component atom off the board is illegal
:- do(M,rot_cw,T),  comp(M,X,T), at(X,Q,R,T),
   rotimg_cw(M,Q,R,NQ,NR),  not hex(NQ,NR).
:- do(M,rot_ccw,T), comp(M,X,T), at(X,Q,R,T),
   rotimg_ccw(M,Q,R,NQ,NR), not hex(NQ,NR).

at(X,Q,R,T+1) :- at(X,Q,R,T), not moved(X,T), step(T).

% Legality of every atom position, incl. atoms swung by a rotation.
:- at(X,Q1,R1,T), at(X,Q2,R2,T), (Q1,R1) < (Q2,R2).  % functionality
:- at(X,Q,R,T), at(Y,Q,R,T), X < Y.                  % no collisions
:- at(X,Q,R,T), base(M,Q,R).                         % arm bases block hexes

% ---------------------------------------------------------------------------
% Glyph of calcification: an elemental atom on the glyph turns to salt.
% ---------------------------------------------------------------------------
calcifies(X,T) :- glyph_calc(Q,R), at(X,Q,R,T), type(X,E,T), elemental(E),
                  step(T).
type(X,salt,T+1) :- calcifies(X,T).
type(X,E,T+1)    :- type(X,E,T), not calcifies(X,T), step(T).

% ---------------------------------------------------------------------------
% Goal: the instance must derive goal_met.
% ---------------------------------------------------------------------------
:- not goal_met.

#minimize { 1,M,A,T : do(M,A,T) }.

#show do/3.
