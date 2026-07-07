# MiniZinc Opus Magnum benchmark results

Machine: 4-core container, MiniZinc 2.9.7. Timeout 300 s per run.
All runs single-threaded (`-p 1`) except the `cp-sat p4` column (`-p 4`).
Cell = **objective** + wall-clock seconds (flattening included) when the
optimum was PROVED; `9? t/o` = incumbent 9 at timeout, optimality unproven;
`t/o` = timeout with no solution; `err` = solver overran --time-limit and was killed.

## fixed layout (om_fixed.mzn)

| instance | gecode p1 | chuffed p1 | cp-sat p1 | cp-sat p4 | highs p1 | coin-bc p1 |
|---|---|---|---|---|---|---|
| t1_transport | **5** 0.2s | **5** 0.2s | **5** 0.3s | **5** 0.3s | **5** 0.9s | **5** 6.0s |
| t2_bond | **12** 5.2s | **12** 0.4s | **12** 0.6s | **12** 0.6s | **12** 23.4s | t/o 300s |
| t3_rigid | **4** 0.3s | **4** 0.3s | **4** 0.4s | **4** 0.4s | **4** 0.8s | **4** 6.8s |
| t4_calc | **5** 0.2s | **5** 0.2s | **5** 0.3s | **5** 0.3s | **5** 0.8s | **5** 6.1s |
| stabilized_water | **9** 6.2s | **9** 0.6s | **9** 1.3s | **9** 1.3s | t/o 302s | t/o 302s |
| sw_1input | **11** 1.7s | **11** 0.3s | **11** 0.5s | **11** 0.5s | -- | -- |

## free layout (om.mzn)

| instance | gecode p1 | chuffed p1 | cp-sat p1 | cp-sat p4 | highs p1 | coin-bc p1 |
|---|---|---|---|---|---|---|
| t1_transport | **5** 0.3s | **5** 0.3s | **5** 0.3s | **5** 0.3s | **5** 0.8s | **5** 9.8s |
| t2_bond | **5** 0.8s | **5** 0.5s | **5** 0.9s | **5** 0.8s | **5** 257.3s | **5** 132.4s |
| t3_rigid | **4** 0.3s | **4** 0.3s | **4** 0.6s | **4** 0.4s | **4** 0.8s | **4** 5.8s |
| t4_calc | **5** 0.3s | **5** 0.2s | **5** 0.3s | **5** 0.3s | **5** 1.0s | **5** 7.8s |
| stabilized_water | 9? t/o 300s | **9** 225.9s | **9** 43.6s | **9** 3.8s | err 420s | err 420s |
| sw_1input | **11** 292.2s | **11** 0.4s | **11** 0.9s | **11** 0.8s | -- | -- |

## Full data

| instance | variant | engine | threads | status | objective | solve_s | flatten_s | wall_s | notes |
|---|---|---|---|---|---|---|---|---|---|
| t1_transport | fixed | gecode | 1 | OPTIMAL | 5 | 0.01 | 0.21 | 0.25 |  |
| t1_transport | fixed | chuffed | 1 | OPTIMAL | 5 | 0.01 | 0.20 | 0.24 |  |
| t1_transport | fixed | cp-sat | 1 | OPTIMAL | 5 | 0.07 | 0.19 | 0.30 |  |
| t1_transport | fixed | highs | 1 | OPTIMAL | 5 | 0.60 | 0.29 | 0.95 |  |
| t1_transport | fixed | coin-bc | 1 | OPTIMAL | 5 | 5.64 | 0.30 | 6.00 |  |
| t1_transport | free | gecode | 1 | OPTIMAL | 5 | 0.04 | 0.24 | 0.33 |  |
| t1_transport | free | chuffed | 1 | OPTIMAL | 5 | 0.01 | 0.23 | 0.28 |  |
| t1_transport | free | cp-sat | 1 | OPTIMAL | 5 | 0.08 | 0.20 | 0.32 |  |
| t1_transport | free | highs | 1 | OPTIMAL | 5 | 0.42 | 0.32 | 0.81 |  |
| t1_transport | free | coin-bc | 1 | OPTIMAL | 5 | 9.35 | 0.34 | 9.76 |  |
| t2_bond | fixed | gecode | 1 | OPTIMAL | 12 | 4.88 | 0.25 | 5.20 |  |
| t2_bond | fixed | chuffed | 1 | OPTIMAL | 12 | 0.12 | 0.25 | 0.42 |  |
| t2_bond | fixed | cp-sat | 1 | OPTIMAL | 12 | 0.31 | 0.26 | 0.64 |  |
| t2_bond | fixed | highs | 1 | OPTIMAL | 12 | 22.73 | 0.58 | 23.43 |  |
| t2_bond | fixed | coin-bc | 1 | UNKNOWN |  | 300.15 | 0.58 | 300.89 | timeout 300s, no solution |
| t2_bond | free | gecode | 1 | OPTIMAL | 5 | 0.50 | 0.25 | 0.82 |  |
| t2_bond | free | chuffed | 1 | OPTIMAL | 5 | 0.09 | 0.28 | 0.45 |  |
| t2_bond | free | cp-sat | 1 | OPTIMAL | 5 | 0.52 | 0.26 | 0.86 |  |
| t2_bond | free | highs | 1 | OPTIMAL | 5 | 256.39 | 0.72 | 257.33 |  |
| t2_bond | free | coin-bc | 1 | OPTIMAL | 5 | 131.58 | 0.65 | 132.43 |  |
| t3_rigid | fixed | gecode | 1 | OPTIMAL | 4 | 0.01 | 0.21 | 0.26 |  |
| t3_rigid | fixed | chuffed | 1 | OPTIMAL | 4 | 0.01 | 0.23 | 0.28 |  |
| t3_rigid | fixed | cp-sat | 1 | OPTIMAL | 4 | 0.14 | 0.21 | 0.39 |  |
| t3_rigid | fixed | highs | 1 | OPTIMAL | 4 | 0.34 | 0.40 | 0.80 |  |
| t3_rigid | fixed | coin-bc | 1 | OPTIMAL | 4 | 6.35 | 0.40 | 6.83 |  |
| t3_rigid | free | gecode | 1 | OPTIMAL | 4 | 0.06 | 0.20 | 0.29 |  |
| t3_rigid | free | chuffed | 1 | OPTIMAL | 4 | 0.02 | 0.22 | 0.29 |  |
| t3_rigid | free | cp-sat | 1 | OPTIMAL | 4 | 0.23 | 0.26 | 0.56 |  |
| t3_rigid | free | highs | 1 | OPTIMAL | 4 | 0.29 | 0.45 | 0.82 |  |
| t3_rigid | free | coin-bc | 1 | OPTIMAL | 4 | 5.23 | 0.43 | 5.76 |  |
| t4_calc | fixed | gecode | 1 | OPTIMAL | 5 | 0.01 | 0.20 | 0.25 |  |
| t4_calc | fixed | chuffed | 1 | OPTIMAL | 5 | 0.01 | 0.20 | 0.25 |  |
| t4_calc | fixed | cp-sat | 1 | OPTIMAL | 5 | 0.07 | 0.20 | 0.31 |  |
| t4_calc | fixed | highs | 1 | OPTIMAL | 5 | 0.40 | 0.30 | 0.77 |  |
| t4_calc | fixed | coin-bc | 1 | OPTIMAL | 5 | 5.70 | 0.31 | 6.10 |  |
| t4_calc | free | gecode | 1 | OPTIMAL | 5 | 0.03 | 0.21 | 0.28 |  |
| t4_calc | free | chuffed | 1 | OPTIMAL | 5 | 0.01 | 0.20 | 0.25 |  |
| t4_calc | free | cp-sat | 1 | OPTIMAL | 5 | 0.09 | 0.19 | 0.32 |  |
| t4_calc | free | highs | 1 | OPTIMAL | 5 | 0.64 | 0.31 | 1.01 |  |
| t4_calc | free | coin-bc | 1 | OPTIMAL | 5 | 7.42 | 0.30 | 7.78 |  |
| stabilized_water | fixed | gecode | 1 | OPTIMAL | 9 | 5.87 | 0.29 | 6.25 |  |
| stabilized_water | fixed | chuffed | 1 | OPTIMAL | 9 | 0.10 | 0.35 | 0.57 |  |
| stabilized_water | fixed | cp-sat | 1 | OPTIMAL | 9 | 0.81 | 0.35 | 1.28 |  |
| stabilized_water | fixed | highs | 1 | UNKNOWN |  |  |  | 302.86 | timeout 300s, no solution |
| stabilized_water | fixed | coin-bc | 1 | UNKNOWN |  |  |  | 302.88 | timeout 300s, no solution |
| stabilized_water | free | gecode | 1 | SATISFIED | 9 | 299.70 | 0.30 | 300.10 | timeout 300s, best=9 |
| stabilized_water | free | chuffed | 1 | OPTIMAL | 9 | 225.28 | 0.38 | 225.86 |  |
| stabilized_water | free | cp-sat | 1 | OPTIMAL | 9 | 43.12 | 0.33 | 43.60 |  |
| stabilized_water | free | highs | 1 | ERROR |  |  |  | 420.10 | hard timeout (minizinc did not stop itself) |
| stabilized_water | free | coin-bc | 1 | ERROR |  |  |  | 420.10 | hard timeout (minizinc did not stop itself) |
| sw_1input | fixed | gecode | 1 | OPTIMAL | 11 | 1.41 | 0.22 | 1.67 |  |
| sw_1input | fixed | chuffed | 1 | OPTIMAL | 11 | 0.01 | 0.25 | 0.32 |  |
| sw_1input | fixed | cp-sat | 1 | OPTIMAL | 11 | 0.19 | 0.23 | 0.47 |  |
| sw_1input | free | gecode | 1 | OPTIMAL | 11 | 291.96 | 0.22 | 292.23 |  |
| sw_1input | free | chuffed | 1 | OPTIMAL | 11 | 0.08 | 0.24 | 0.39 |  |
| sw_1input | free | cp-sat | 1 | OPTIMAL | 11 | 0.63 | 0.23 | 0.93 |  |
| t1_transport | fixed | cp-sat | 4 | OPTIMAL | 5 | 0.05 | 0.19 | 0.28 |  |
| t1_transport | free | cp-sat | 4 | OPTIMAL | 5 | 0.06 | 0.19 | 0.29 |  |
| t2_bond | fixed | cp-sat | 4 | OPTIMAL | 12 | 0.34 | 0.23 | 0.64 |  |
| t2_bond | free | cp-sat | 4 | OPTIMAL | 5 | 0.44 | 0.24 | 0.75 |  |
| t3_rigid | fixed | cp-sat | 4 | OPTIMAL | 4 | 0.11 | 0.21 | 0.36 |  |
| t3_rigid | free | cp-sat | 4 | OPTIMAL | 4 | 0.18 | 0.21 | 0.44 |  |
| t4_calc | fixed | cp-sat | 4 | OPTIMAL | 5 | 0.05 | 0.19 | 0.29 |  |
| t4_calc | free | cp-sat | 4 | OPTIMAL | 5 | 0.08 | 0.20 | 0.31 |  |
| stabilized_water | fixed | cp-sat | 4 | OPTIMAL | 9 | 0.84 | 0.34 | 1.29 |  |
| stabilized_water | free | cp-sat | 4 | OPTIMAL | 9 | 3.28 | 0.35 | 3.80 |  |
| sw_1input | fixed | cp-sat | 4 | OPTIMAL | 11 | 0.13 | 0.26 | 0.45 |  |
| sw_1input | free | cp-sat | 4 | OPTIMAL | 11 | 0.44 | 0.23 | 0.75 |  |

## Tractability frontier (stabilized_water, free layout)

Probes shrink/grow the horizon T and board radius of stabilized_water.dzn
(data: `frontier.csv`; probe .dzn files are one-line edits of the instance).
Probes ran up to 3 single-threaded streams in parallel (4-core box), except
the cp-sat p4 row which ran alone. `9? t/o` = optimal-valued incumbent found
but optimality unproven at timeout; `t/o none` = no solution found at all.

| probe | gecode p1 | chuffed p1 | cp-sat p1 | cp-sat p4 |
|---|---|---|---|---|
| T=10, r=2 | 9? t/o 300s | **9** 28.6s | **9** 11.4s | not run |
| T=12, r=2 (base) | 9? t/o 600s | **9** 225.9s | **9** 43.6s | **9** 3.8s |
| T=14, r=2 | 9? t/o 300s | 9? t/o 300s | t/o none | **9** 12.9s |
| T=16, r=2 | not run | 9? t/o 300s | t/o none | not run |
| T=20, r=2 | not run | 9? t/o 300s | t/o none | not run |
| T=12, r=3 | not run | 9? t/o 300s | **9** 95.7s | not run |
| T=16, r=3 | not run | 9? t/o 300s | t/o none | not run |

Where each engine gives up (proving optimality, 300 s budget):

- **Gecode**: below T=10 — it cannot prove ANY free-layout spawn variant
  (finds the optimum-valued incumbent 9 every time, proves nothing, even
  with 600 s on the base instance). Its only free-layout SW-class proof is
  the 2-atom sw_1input (292 s, just under the limit).
- **Chuffed**: T=12 at radius 2 is its edge (225.9 s); T=14 and radius 3
  both push it over. It always finds the incumbent 9 within the budget.
- **CP-SAT single-thread**: proves T=10/12 at r=2 and tolerates board growth
  well (T=12 r=3 in 95.7 s), but has a cliff at T>=14: it returns NO
  solution at all — a portfolio/search artifact, since...
- **CP-SAT -p 4**: ...the 4-thread portfolio proves T=14 in 12.9 s (and the
  base instance in 3.8 s). Parallel CP-SAT extends the frontier past every
  single-threaded engine; the other p4 probes were not run (time-capped).
- **HiGHS / COIN-BC**: give up before the frontier begins — no incumbent on
  the base SW instance in 300 s (either variant); on SW free both overran
  the time limit and were hard-killed. One line: MIP flattens but is
  hopeless on SW-class instances.
