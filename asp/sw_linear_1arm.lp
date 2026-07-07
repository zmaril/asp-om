% "Stabilized Water" linear product with a SINGLE arm -- provably UNSAT.
% A held molecule can only be rotated about the one fixed arm base, so its
% final resting placement is always a 60k-degree rotation of the
% configuration it had when its bond formed. Extending a chain colinearly
% (salt-water-salt in a line via two bonder events) requires a translation,
% which no sequence of rotations about a single pivot can produce.
% Exhaustive BFS over all 144 single-arm ring layouts confirms: none works.
% clingo should report UNSAT at any horizon (useful as an UNSAT benchmark;
% same layout as asp/sw_bent.lp, only the goal differs).

arm(m1).
base(m1,0,0).
armlen(m1,1).
init_orient(m1,0).

spawn(1, 1,0).
spawn_type(1,water).
pool(1,4).

glyph_calc(1,-1).
glyph_bond(0,1,-1,1).

% --- product: exact linear salt-water-salt --------------------------------
deg(X,T,N) :- exists(X,T), time(T), N = #count { Y : bond(X,Y,T) }.

complete(T) :-
    at(W,Q,R,T), type(W,water,T), deg(W,T,2), not held(W,T),
    dir(D,DQ,DR), D < 3,
    at(S1,Q+DQ,R+DR,T), type(S1,salt,T), deg(S1,T,1), not held(S1,T),
    at(S2,Q-DQ,R-DR,T), type(S2,salt,T), deg(S2,T,1), not held(S2,T),
    bond(W,S1,T), bond(W,S2,T).

goal_met :- complete(T).

#show complete/1.
