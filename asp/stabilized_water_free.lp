% "Stabilized Water" (true 2-atom spec), FREE LAYOUT variant: the solver
% places the arm, both water inputs, the calcification glyph and the bonder
% anywhere on the board (see asp/layout.lp) AND plans the instruction tape.
%
%   python3 run.py asp/core2.lp asp/layout.lp asp/stabilized_water_free.lp --tmax 10
%
% Compare with asp/stabilized_water.lp (identical puzzle, hand-fixed layout).

place_arm(m1,1).
place_input(1,water,2).
place_input(2,water,2).
place_calc(g1).
place_bond(g2).

% --- product: exact salt--water dimer (same goal as the fixed instance) ----
deg(X,T,N) :- exists(X,T), time(T), N = #count { Y : bond(X,Y,T) }.

complete(T) :-
    at(W,Q,R,T),        type(W,water,T), deg(W,T,1), not held(W,T),
    dir(D,DQ,DR),
    at(S,Q+DQ,R+DR,T),  type(S,salt,T),  deg(S,T,1), not held(S,T),
    bond(W,S,T).

goal_met :- complete(T).

#show complete/1.
#show base/3.
#show init_orient/2.
#show spawn/3.
#show glyph_calc/2.
#show glyph_bond/4.
