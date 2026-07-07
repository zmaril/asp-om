% ===========================================================================
% Opus Magnum (trivial fragment) -- core ASP encoding
% ===========================================================================
% World model (deliberately minimal, phase 1):
%   * Bounded hex grid in axial coordinates (Q,R), radius `radius`.
%   * One arm: fixed base, length 1, orientation D in 0..5 (indexes dir/3).
%     Its gripper hex is base + dir(D).
%   * Actions, exactly one per timestep: rot_cw, rot_ccw, grab, drop, wait.
%   * Atoms occupy hexes; a held atom rides on the gripper hex.
%   * Goal: every product(X,Q,R) atom X sits (unheld) on hex (Q,R) at t_max.
%
% An instance file supplies: base/2, atom/1, init_at/3, init_orient/1,
% product/3, and optionally glyph/bond rules.
% ===========================================================================

#const t_max=10.
#const radius=2.

time(0..t_max).
step(0..t_max-1).

% Axial hex grid: |Q|<=radius, |R|<=radius, |Q+R|<=radius.
hex(Q,R) :- Q = -radius..radius, R = -radius..radius, |Q+R| <= radius.

% The 6 axial direction vectors, indexed 0..5 going clockwise.
dir(0,  1,  0).
dir(1,  0,  1).
dir(2, -1,  1).
dir(3, -1,  0).
dir(4,  0, -1).
dir(5,  1, -1).

% --------------------------------------------------------------------------
% Actions: exactly one instruction per timestep (the arm's instruction tape).
% --------------------------------------------------------------------------
action(rot_cw; rot_ccw; grab; drop; wait).
{ do(A,T) : action(A) } = 1 :- step(T).

% --------------------------------------------------------------------------
% Arm orientation and gripper position.
% --------------------------------------------------------------------------
orient(D, 0) :- init_orient(D).
orient((D+1) \ 6, T+1) :- orient(D,T), do(rot_cw,T).
orient((D+5) \ 6, T+1) :- orient(D,T), do(rot_ccw,T).
orient(D,       T+1) :- orient(D,T), do(A,T), A != rot_cw, A != rot_ccw.

gripper(BQ+DQ, BR+DR, T) :- base(BQ,BR), orient(D,T), dir(D,DQ,DR).
:- gripper(Q,R,T), not hex(Q,R).          % gripper must stay on the board

% --------------------------------------------------------------------------
% Grabbing and dropping. The arm holds at most one atom.
% --------------------------------------------------------------------------
holding(X,T+1) :- do(grab,T), at(X,Q,R,T), gripper(Q,R,T).
holding(X,T+1) :- holding(X,T), not do(drop,T), step(T).

held(T)        :- holding(X,T).
occupied(Q,R,T):- at(X,Q,R,T).

:- do(grab,T), held(T).                                  % hand already full
:- do(grab,T), gripper(Q,R,T), not occupied(Q,R,T).      % nothing to grab
:- do(drop,T), not held(T).                              % nothing to drop

% --------------------------------------------------------------------------
% Atom positions: held atoms ride the gripper; free atoms are inert.
% --------------------------------------------------------------------------
at(X,Q,R,0)   :- init_at(X,Q,R).
at(X,Q,R,T+1) :- holding(X,T+1), gripper(Q,R,T+1).
at(X,Q,R,T+1) :- at(X,Q,R,T), not holding(X,T+1), step(T).

:- at(X,Q1,R1,T), at(X,Q2,R2,T), (Q1,R1) < (Q2,R2).      % atom in one place
:- at(X,Q,R,T), at(Y,Q,R,T), X < Y.                      % no collisions

% --------------------------------------------------------------------------
% Goal: each product atom delivered (unheld, on its target hex) at t_max.
% --------------------------------------------------------------------------
delivered(X) :- product(X,Q,R), at(X,Q,R,t_max), not holding(X,t_max).
:- product(X,Q,R), not delivered(X).

% Prefer short plans: minimize the number of non-wait instructions.
#minimize { 1,T : do(A,T), A != wait }.

#show do/2.
