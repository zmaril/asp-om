% Optional symmetry breaker: all actions form a PREFIX of the tape (idle
% steps only at the end). Kills the wait-padding permutation symmetry that
% makes optimality proofs blow up at slack horizons (e.g. the true
% Stabilized Water instance at t_max=20 goes from >300 s to ~2 s).
%
% CAVEAT: only sound when an optimal plan never needs a mid-plan wait
% (e.g. idling while a reagent respawns). True for all instances in this
% repo (verified against BFS optima), but not in general -- opt in
% deliberately:
%
%   python3 run.py asp/core2.lp asp/stabilized_water.lp asp/nowait.lp --tmax 20

acted(T) :- do(M,A,T).
:- do(M,A,T), T > 0, not acted(T-1).
