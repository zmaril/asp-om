% ===========================================================================
% Opus Magnum (simplified fragment) -- MiniZinc core model
% ===========================================================================
% Bounded-horizon planning model matching the semantics of the clingo
% encoding asp/core2.lp (which subsumes asp/core.lp for the v1 tests):
%
%   * Bounded hex board in AXIAL coordinates (Q,R):
%       |Q| <= radius, |R| <= radius, |Q+R| <= radius.
%   * Six directions indexed 0..5 CLOCKWISE, dir 0 = (1,0):
%       dir = [(1,0),(0,1),(-1,1),(-1,0),(0,-1),(1,-1)]
%   * 60-degree rotation about the origin (maps dir D onto dir D+1):
%       cw : (Q,R) -> (-R, Q+R)      ccw: (Q,R) -> (Q+R, -Q)
%   * Time 0..T; at most one (arm, action) per step from
%     {rot_cw, rot_ccw, grab, drop}; idle step = wait.
%   * Arms: base hex, integer length, orientation 0..5; the gripper hex is
%     base + len*dir(orient). Arm bases block hexes for atoms.
%   * RIGID MOTION: rotating an arm that holds an atom rotates the whole
%     bond-connected component of that atom about the arm base.
%   * Glyph of bonding (two adjacent hexes): whenever both hexes carry
%     atoms, those atoms bond; bonds are symmetric and persist forever.
%   * Glyph of calcification (one hex): an elemental atom (air/earth/fire/
%     water) sitting on it at step t becomes salt at t+1.
%   * Goal: each product atom sits UNHELD on its target hex at time T
%     (optionally with a required element type), plus optionally
%     "some bond exists at time T" (require_any_bond).
%   * Objective: minimize the total number of actions (= non-wait steps,
%     since at most one action happens per step) -- same objective as both
%     clingo models.
%
% LAYOUT IS PART OF THE DECISION: arm base hexes and glyph hexes are
% decision variables ranging over the whole board. Include om_fixed.mzn
% instead of this file to pin the layout to the given_* parameters
% (that variant matches the clingo instances exactly).
% ===========================================================================

include "globals.mzn";

% --------------------------------------------------------------------------
% Parameters (supplied by a .dzn instance file)
% --------------------------------------------------------------------------
int: T;                          % horizon: states 0..T, actions at 0..T-1
int: radius;                     % board radius
int: nA;                         % number of atoms
int: nM;                         % number of arms

set of int: TIME = 0..T;
set of int: STEP = 0..T-1;
set of int: ATOM = 1..nA;
set of int: ARM  = 1..nM;

array[ARM] of int: arm_len;
array[ARM] of 0..5: init_ori;    % initial orientation (fixed, as in clingo)
array[ARM] of int: given_base_q; % layout used by om_fixed.mzn
array[ARM] of int: given_base_r;

array[ATOM] of int: init_q;
array[ATOM] of int: init_r;
% element codes: 1=salt 2=air 3=earth 4=fire 5=water  (elemental = 2..5)
array[ATOM] of 1..5: init_type;

int: nInitBond;
array[1..nInitBond, 1..2] of ATOM: init_bond;

int: nBonder;                    % glyphs of bonding (pairs of adjacent hexes)
set of int: BONDER = 1..nBonder;
array[BONDER, 1..4] of int: given_bonder;   % q1,r1,q2,r2 (om_fixed.mzn)

int: nCalc;                      % glyphs of calcification (single hexes)
set of int: CALC = 1..nCalc;
array[CALC, 1..2] of int: given_calc;       % q,r (om_fixed.mzn)

int: nProd;
array[1..nProd] of ATOM: prod_atom;
array[1..nProd] of int: prod_q;
array[1..nProd] of int: prod_r;
array[1..nProd] of 0..5: prod_type;  % 0 = don't care
bool: require_any_bond;

% clockwise direction table, dir 0 = (1,0)
array[0..5] of int: DQ = array1d(0..5, [1, 0, -1, -1,  0,  1]);
array[0..5] of int: DR = array1d(0..5, [0, 1,  1,  0, -1, -1]);

% --------------------------------------------------------------------------
% Layout decision variables (the "machine" being designed)
% --------------------------------------------------------------------------
array[ARM] of var -radius..radius: base_q :: output;
array[ARM] of var -radius..radius: base_r :: output;
constraint forall(m in ARM)(abs(base_q[m] + base_r[m]) <= radius);

array[BONDER] of var -radius..radius: bonder_q1 :: output;
array[BONDER] of var -radius..radius: bonder_r1 :: output;
array[BONDER] of var -radius..radius: bonder_q2 :: output;
array[BONDER] of var -radius..radius: bonder_r2 :: output;
constraint forall(g in BONDER)(
    abs(bonder_q1[g] + bonder_r1[g]) <= radius /\
    abs(bonder_q2[g] + bonder_r2[g]) <= radius /\
    % the two glyph hexes are adjacent
    exists(d in 0..5)(bonder_q2[g] = bonder_q1[g] + DQ[d] /\
                      bonder_r2[g] = bonder_r1[g] + DR[d]));

array[CALC] of var -radius..radius: calc_q :: output;
array[CALC] of var -radius..radius: calc_r :: output;
constraint forall(g in CALC)(abs(calc_q[g] + calc_r[g]) <= radius);

% Parts may not overlap: arm bases, bonder hexes and calc hexes are
% pairwise distinct cells. (Cell id = linearised (q,r).)
int: W = 2*radius + 1;
function var int: cell(var int: q, var int: r) = (q + radius)*W + (r + radius);
constraint alldifferent(
    [cell(base_q[m], base_r[m]) | m in ARM] ++
    [cell(bonder_q1[g], bonder_r1[g]) | g in BONDER] ++
    [cell(bonder_q2[g], bonder_r2[g]) | g in BONDER] ++
    [cell(calc_q[g], calc_r[g]) | g in CALC]);

% --------------------------------------------------------------------------
% State variables
% --------------------------------------------------------------------------
array[TIME, ATOM] of var -radius..radius: aq :: output;   % atom position
array[TIME, ATOM] of var -radius..radius: ar :: output;
constraint forall(t in TIME, a in ATOM)(abs(aq[t,a] + ar[t,a]) <= radius);

array[TIME, ATOM] of var 0..nM: held :: output;    % 0 = free, m = held by m
array[TIME, ATOM] of var 1..5:  typ  :: output;    % element
array[TIME, ARM]  of var 0..5:  ori  :: output;    % arm orientation
array[TIME, ARM]  of var -radius..radius: gq :: output;   % gripper hex
array[TIME, ARM]  of var -radius..radius: gr :: output;
constraint forall(t in TIME, m in ARM)(abs(gq[t,m] + gr[t,m]) <= radius);

% bonds: symmetric, only a<b stored; bonded[t,a,b] with a>=b is fixed false
array[TIME, ATOM, ATOM] of var bool: bonded :: output;
constraint forall(t in TIME, a, b in ATOM where a >= b)(not bonded[t,a,b]);
function var bool: bnd(int: t, int: a, int: b) =
    if a < b then bonded[t,a,b] elseif b < a then bonded[t,b,a]
    else false endif;

% --------------------------------------------------------------------------
% Actions: at most one (arm, action) per step
% --------------------------------------------------------------------------
array[STEP, ARM] of var bool: doCW   :: output;
array[STEP, ARM] of var bool: doCCW  :: output;
array[STEP, ARM] of var bool: doGrab :: output;
array[STEP, ARM] of var bool: doDrop :: output;
constraint forall(t in STEP)(
    sum(m in ARM)(doCW[t,m] + doCCW[t,m] + doGrab[t,m] + doDrop[t,m]) <= 1);

% --------------------------------------------------------------------------
% Initial state
% --------------------------------------------------------------------------
constraint forall(a in ATOM)(
    aq[0,a] = init_q[a] /\ ar[0,a] = init_r[a] /\
    held[0,a] = 0 /\ typ[0,a] = init_type[a]);
constraint forall(m in ARM)(ori[0,m] = init_ori[m]);

% initial bonds (glyph-formed bonds at t=0 are added by the bond rule below)
function bool: is_init_bond(int: a, int: b) =
    exists(k in 1..nInitBond)(
        (init_bond[k,1] = a /\ init_bond[k,2] = b) \/
        (init_bond[k,1] = b /\ init_bond[k,2] = a));

% --------------------------------------------------------------------------
% Gripper geometry: gripper = base + len * dir(orient)
% --------------------------------------------------------------------------
constraint forall(t in TIME, m in ARM)(
    gq[t,m] = base_q[m] + arm_len[m] * DQ[ori[t,m]] /\
    gr[t,m] = base_r[m] + arm_len[m] * DR[ori[t,m]]);

% redundant (implied) channel: a held atom sits on its holder's gripper hex
constraint forall(t in TIME, a in ATOM, m in ARM)(
    (held[t,a] = m) -> (aq[t,a] = gq[t,m] /\ ar[t,a] = gr[t,m]));

% --------------------------------------------------------------------------
% Orientation transition
% --------------------------------------------------------------------------
constraint forall(t in STEP, m in ARM)(
    ori[t+1,m] = (ori[t,m] + doCW[t,m] - doCCW[t,m] + 6) mod 6);

% --------------------------------------------------------------------------
% Bond formation (glyph of bonding) and persistence
% --------------------------------------------------------------------------
function var bool: on_hex(int: t, int: a, var int: q, var int: r) =
    aq[t,a] = q /\ ar[t,a] = r;
function var bool: formed(int: t, int: a, int: b) =
    exists(g in BONDER)(
        (on_hex(t, a, bonder_q1[g], bonder_r1[g]) /\
         on_hex(t, b, bonder_q2[g], bonder_r2[g])) \/
        (on_hex(t, a, bonder_q2[g], bonder_r2[g]) /\
         on_hex(t, b, bonder_q1[g], bonder_r1[g])));

constraint forall(a, b in ATOM where a < b)(
    bonded[0,a,b] = (is_init_bond(a,b) \/ formed(0,a,b)));
constraint forall(t in STEP, a, b in ATOM where a < b)(
    bonded[t+1,a,b] = (bonded[t,a,b] \/ formed(t+1,a,b)));

% --------------------------------------------------------------------------
% Held connected component (bond-transitive closure from the held atom),
% computed by unrolling reachability nA-1 times.
% --------------------------------------------------------------------------
set of int: CSTG = 0..nA-1;
array[STEP, ARM, ATOM, CSTG] of var bool: compS;
constraint forall(t in STEP, m in ARM, a in ATOM)(
    compS[t,m,a,0] = (held[t,a] = m));
constraint forall(t in STEP, m in ARM, a in ATOM, k in 1..nA-1)(
    compS[t,m,a,k] = (compS[t,m,a,k-1] \/
        exists(b in ATOM where b != a)(compS[t,m,b,k-1] /\ bnd(t,a,b))));
array[STEP, ARM, ATOM] of var bool: comp;
constraint forall(t in STEP, m in ARM, a in ATOM)(
    comp[t,m,a] = compS[t,m,a,nA-1]);

% a rotation may not tear an atom out of another arm's hand
constraint forall(t in STEP, m in ARM, a in ATOM)(
    ((doCW[t,m] \/ doCCW[t,m]) /\ comp[t,m,a]) ->
        (held[t,a] = 0 \/ held[t,a] = m));

% --------------------------------------------------------------------------
% Grab / drop legality and the held-state transition
% --------------------------------------------------------------------------
array[STEP, ARM, ATOM] of var bool: grabA;   % arm m grabs atom a at step t
constraint forall(t in STEP, m in ARM, a in ATOM)(
    grabA[t,m,a] = (doGrab[t,m] /\ aq[t,a] = gq[t,m] /\ ar[t,a] = gr[t,m]));

constraint forall(t in STEP, m in ARM)(
    doGrab[t,m] -> forall(a in ATOM)(held[t,a] != m));       % hand empty
constraint forall(t in STEP, m in ARM)(
    doGrab[t,m] -> exists(a in ATOM)(grabA[t,m,a]));         % something there
constraint forall(t in STEP, m in ARM, a in ATOM)(
    grabA[t,m,a] -> held[t,a] = 0);                          % target is free
constraint forall(t in STEP, m in ARM)(
    doDrop[t,m] -> exists(a in ATOM)(held[t,a] = m));        % something held

array[STEP, ATOM] of var bool: dropA;        % atom a is released at step t
constraint forall(t in STEP, a in ATOM)(
    dropA[t,a] = exists(m in ARM)(doDrop[t,m] /\ held[t,a] = m));

constraint forall(t in STEP, m in ARM, a in ATOM)(
    grabA[t,m,a] -> held[t+1,a] = m);
constraint forall(t in STEP, a in ATOM)(
    dropA[t,a] -> held[t+1,a] = 0);
constraint forall(t in STEP, a in ATOM)(
    (not dropA[t,a] /\ forall(m in ARM)(not grabA[t,m,a])) ->
        held[t+1,a] = held[t,a]);

% --------------------------------------------------------------------------
% Motion: rotating an arm rigidly rotates its held component about its base;
% everything else is inert.
% --------------------------------------------------------------------------
array[STEP, ATOM] of var bool: movedA;
constraint forall(t in STEP, a in ATOM)(
    movedA[t,a] = exists(m in ARM)((doCW[t,m] \/ doCCW[t,m]) /\ comp[t,m,a]));

% cw about (BQ,BR): (Q,R) -> (BQ+BR-R, Q+R-BQ)
constraint forall(t in STEP, m in ARM, a in ATOM)(
    (doCW[t,m] /\ comp[t,m,a]) ->
        (aq[t+1,a] = base_q[m] + base_r[m] - ar[t,a] /\
         ar[t+1,a] = aq[t,a] + ar[t,a] - base_q[m]));
% ccw about (BQ,BR): (Q,R) -> (Q+R-BR, BQ+BR-Q)
constraint forall(t in STEP, m in ARM, a in ATOM)(
    (doCCW[t,m] /\ comp[t,m,a]) ->
        (aq[t+1,a] = aq[t,a] + ar[t,a] - base_r[m] /\
         ar[t+1,a] = base_q[m] + base_r[m] - aq[t,a]));
constraint forall(t in STEP, a in ATOM)(
    (not movedA[t,a]) -> (aq[t+1,a] = aq[t,a] /\ ar[t+1,a] = ar[t,a]));

% --------------------------------------------------------------------------
% Occupancy: no two atoms on one hex; arm bases block hexes for atoms
% --------------------------------------------------------------------------
constraint forall(t in TIME)(
    alldifferent([cell(aq[t,a], ar[t,a]) | a in ATOM]));
constraint forall(t in TIME, a in ATOM, m in ARM)(
    aq[t,a] != base_q[m] \/ ar[t,a] != base_r[m]);

% --------------------------------------------------------------------------
% Glyph of calcification: elemental atom on the glyph at step t -> salt at t+1
% --------------------------------------------------------------------------
array[STEP, ATOM] of var bool: calcifies;
constraint forall(t in STEP, a in ATOM)(
    calcifies[t,a] = (typ[t,a] >= 2 /\
        exists(g in CALC)(on_hex(t, a, calc_q[g], calc_r[g]))));
constraint forall(t in STEP, a in ATOM)(
    typ[t+1,a] = if calcifies[t,a] then 1 else typ[t,a] endif);

% --------------------------------------------------------------------------
% Goal at time T
% --------------------------------------------------------------------------
constraint forall(k in 1..nProd)(
    aq[T, prod_atom[k]] = prod_q[k] /\
    ar[T, prod_atom[k]] = prod_r[k] /\
    held[T, prod_atom[k]] = 0 /\
    (prod_type[k] = 0 \/ typ[T, prod_atom[k]] = prod_type[k]));
constraint require_any_bond ->
    exists(a, b in ATOM where a < b)(bonded[T,a,b]);

% --------------------------------------------------------------------------
% Objective: minimize total number of actions (non-wait steps)
% --------------------------------------------------------------------------
var 0..T: total_actions :: output;
constraint total_actions =
    sum(t in STEP, m in ARM)(doCW[t,m] + doCCW[t,m] + doGrab[t,m] + doDrop[t,m]);

% Dominance constraint (single-arm only): with one arm nothing in the world
% changes during a wait (no spawning is modelled), so any legal plan can be
% compacted so that all actions form a prefix and all waits come last,
% preserving legality, bond/calcification effects and the action count.
% Restricting the search to such compacted plans keeps the optimum identical
% and collapses the search space (without it Gecode finds nothing on
% t2_bond in minutes). NOT valid for nM > 1 (arms synchronise), so gated.
array[STEP] of var bool: acted;
constraint forall(t in STEP)(
    acted[t] = exists(m in ARM)(doCW[t,m] \/ doCCW[t,m] \/
                                doGrab[t,m] \/ doDrop[t,m]));
constraint if nM = 1 then
    forall(t in 1..T-1)(acted[t] -> acted[t-1]) endif;

% Chronological search over the action program (then the layout vars),
% preferring "no action". Without this annotation Gecode's default and
% free search find no solution on t2_bond within minutes; Chuffed and
% CP-SAT solve the model quickly with or without it.
array[int] of var bool: action_seq =
    [ [doGrab[t,m], doDrop[t,m], doCW[t,m], doCCW[t,m]][k]
    | t in STEP, m in ARM, k in 1..4 ];

solve :: seq_search([
        bool_search(action_seq, input_order, indomain_min),
        int_search(base_q ++ base_r ++ bonder_q1 ++ bonder_r1 ++
                   bonder_q2 ++ bonder_r2 ++ calc_q ++ calc_r,
                   first_fail, indomain_min)])
      minimize total_actions;

output [
    "total_actions = \(total_actions)\n" ] ++
    [ "arm \(m): base=(\(base_q[m]),\(base_r[m])) len=\(arm_len[m])\n"
    | m in ARM ] ++
    [ "bonder \(g): (\(bonder_q1[g]),\(bonder_r1[g]))-(\(bonder_q2[g]),\(bonder_r2[g]))\n"
    | g in BONDER ] ++
    [ "calc \(g): (\(calc_q[g]),\(calc_r[g]))\n" | g in CALC ] ++
    [ "t=\(t) " ++
      concat([" arm\(m) dir=\(ori[t,m]) grip=(\(gq[t,m]),\(gr[t,m]))" | m in ARM ]) ++
      concat([" a\(a)@(\(aq[t,a]),\(ar[t,a]))" ++
              if fix(held[t,a]) > 0 then "[held:\(held[t,a])]" else "" endif
             | a in ATOM ]) ++
      if t < T then
        concat([ if fix(doCW[t,m])   then "  action: arm\(m) rot_cw"
            elseif fix(doCCW[t,m])  then "  action: arm\(m) rot_ccw"
            elseif fix(doGrab[t,m]) then "  action: arm\(m) grab"
            elseif fix(doDrop[t,m]) then "  action: arm\(m) drop"
            else "" endif | m in ARM ])
      else "" endif ++ "\n"
    | t in TIME ];
