% Trivial instance 1: transport a single salt atom.
% Arm base at origin, length 1. Atom starts on the reagent hex (1,0)
% (directly under the gripper at t=0); deliver it to the product hex (-1,0).
% Optimal plan: grab, rotate x3, drop  (5 instructions).

base(0,0).
init_orient(0).

atom(a1).
init_at(a1, 1, 0).

product(a1, -1, 0).
