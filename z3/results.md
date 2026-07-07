# Z3 arm benchmark results

z3-solver 4.16.0; times are wall-clock solve time in seconds (build/encode time listed separately); fast runs are the median of 5.

Strategies: `optimize` = z3.Optimize minimize(cost); `ramp-cost` = incremental cost<=k for k=0,1,... (first SAT is proven optimum); `descend-cost` = SAT then tighten cost until UNSAT (proven optimum); `oneshot` = single SAT check, NO optimality; `ramp-horizon` = incremental goal-at-h assumptions for h=1..T, first SAT horizon, cost not minimized.

Clingo reference (same box, clingo 5.8.0, ground+solve to optimality, fixed layout): trivial 0.009s, bond 0.148s, rigid 0.004s.

| instance | encoding | layout | strategy | status | cost | horizon | build s | solve s | runs | proven optimal |
|---|---|---|---|---|---|---|---|---|---|---|
| trivial | int | fixed | optimize | sat | 5 | 10 | 0.034 | 0.642 | 5 | True |
| trivial | int | fixed | ramp-cost | sat | 5 | 10 | 0.034 | 0.751 | 5 | True |
| trivial | int | fixed | descend-cost | sat | 5 | 10 | 0.034 | 0.515 | 5 | True |
| trivial | int | fixed | oneshot | sat | 10 | 10 | 0.034 | 0.030 | 5 |  |
| trivial | int | fixed | ramp-horizon | sat | 5 | 5 | 0.033 | 0.019 | 5 |  |
| trivial | int | free | optimize | sat | 5 | 10 | 0.034 | 2.137 | 1 | True |
| trivial | int | free | ramp-cost | sat | 5 | 10 | 0.034 | 1.426 | 5 | True |
| trivial | int | free | descend-cost | sat | 5 | 10 | 0.035 | 1.369 | 5 | True |
| trivial | int | free | oneshot | sat | 9 | 10 | 0.034 | 0.076 | 5 |  |
| trivial | int | free | ramp-horizon | sat | 5 | 5 | 0.034 | 0.077 | 5 |  |
| bond | int | fixed | optimize | sat | 12 | 16 | 0.081 | 15.951 | 1 | True |
| bond | int | fixed | ramp-cost | sat | 12 | 16 | 0.081 | 54.638 | 1 | True |
| bond | int | fixed | descend-cost | sat | 12 | 16 | 0.082 | 6.335 | 1 | True |
| bond | int | fixed | oneshot | sat | 14 | 16 | 0.081 | 0.280 | 5 |  |
| bond | int | fixed | ramp-horizon | sat | 12 | 12 | 0.080 | 0.750 | 5 |  |
| bond | int | free | optimize | sat | 12 | 16 | 0.087 | 82.395 | 1 | True |
| bond | int | free | ramp-cost | sat | 12 | 16 | 0.085 | 154.940 | 1 | True |
| bond | int | free | descend-cost | sat | 12 | 16 | 0.082 | 21.826 | 1 | True |
| bond | int | free | oneshot | sat | 13 | 16 | 0.083 | 1.285 | 5 |  |
| bond | int | free | ramp-horizon | sat | 12 | 12 | 0.082 | 2.884 | 5 |  |
| rigid | int | fixed | optimize | sat | 4 | 10 | 0.053 | 0.408 | 5 | True |
| rigid | int | fixed | ramp-cost | sat | 4 | 10 | 0.056 | 0.323 | 5 | True |
| rigid | int | fixed | descend-cost | sat | 4 | 10 | 0.054 | 0.287 | 5 | True |
| rigid | int | fixed | oneshot | sat | 8 | 10 | 0.054 | 0.068 | 5 |  |
| rigid | int | fixed | ramp-horizon | sat | 4 | 4 | 0.054 | 0.022 | 5 |  |
| rigid | int | free | optimize | sat | 4 | 10 | 0.055 | 2.911 | 1 | True |
| rigid | int | free | ramp-cost | sat | 4 | 10 | 0.054 | 0.538 | 5 | True |
| rigid | int | free | descend-cost | sat | 4 | 10 | 0.058 | 0.657 | 5 | True |
| rigid | int | free | oneshot | sat | 10 | 10 | 0.057 | 0.594 | 5 |  |
| rigid | int | free | ramp-horizon | sat | 4 | 4 | 0.058 | 0.064 | 5 |  |
| trivial | bool | fixed | optimize | sat | 5 | 10 | 0.241 | 0.040 | 5 | True |
| trivial | bool | fixed | descend-cost | sat | 5 | 10 | 0.252 | 0.075 | 5 | True |
| trivial | bool | fixed | oneshot | sat | 8 | 10 | 0.262 | 0.025 | 5 |  |
| bond | bool | fixed | optimize | sat | 12 | 16 | 0.723 | 0.834 | 5 | True |
| bond | bool | fixed | descend-cost | sat | 12 | 16 | 0.697 | 0.570 | 5 | True |
| bond | bool | fixed | oneshot | sat | 14 | 16 | 0.714 | 0.079 | 5 |  |
