# Z3 arm benchmark results

z3-solver 4.16.0; times are wall-clock solve time in seconds (build/encode time listed separately); fast runs are the median of 5.

Strategies: `optimize` = z3.Optimize minimize(cost); `ramp-cost` = incremental cost<=k for k=0,1,... (first SAT is proven optimum); `descend-cost` = SAT then tighten cost until UNSAT (proven optimum); `oneshot` = single SAT check, NO optimality; `ramp-horizon` = incremental goal-at-h assumptions for h=1..T, first SAT horizon, cost not minimized.

Clingo reference (same box, clingo 5.8.0, ground+solve to optimality, fixed layout): trivial 0.009s, bond 0.148s, rigid 0.004s, water 0.06s.

`water` = Stabilized Water (omsim P007) in the simplified v2 semantics; fixed-layout optimum is 10, free layout finds a 3-instruction layout (glyphs under the reagent hexes).

| instance | encoding | layout | strategy | status | cost | horizon | build s | solve s | runs | proven optimal |
|---|---|---|---|---|---|---|---|---|---|---|
| trivial | int | fixed | optimize | sat | 5 | 10 | 0.033 | 0.640 | 5 | True |
| trivial | int | fixed | ramp-cost | sat | 5 | 10 | 0.032 | 0.740 | 5 | True |
| trivial | int | fixed | descend-cost | sat | 5 | 10 | 0.033 | 0.490 | 5 | True |
| trivial | int | fixed | oneshot | sat | 10 | 10 | 0.033 | 0.029 | 5 |  |
| trivial | int | fixed | ramp-horizon | sat | 5 | 5 | 0.033 | 0.020 | 5 |  |
| trivial | int | free | optimize | sat | 5 | 10 | 0.033 | 2.152 | 1 | True |
| trivial | int | free | ramp-cost | sat | 5 | 10 | 0.034 | 1.404 | 5 | True |
| trivial | int | free | descend-cost | sat | 5 | 10 | 0.034 | 1.321 | 5 | True |
| trivial | int | free | oneshot | sat | 9 | 10 | 0.034 | 0.076 | 5 |  |
| trivial | int | free | ramp-horizon | sat | 5 | 5 | 0.034 | 0.077 | 5 |  |
| bond | int | fixed | optimize | sat | 12 | 16 | 0.081 | 15.859 | 1 | True |
| bond | int | fixed | ramp-cost | sat | 12 | 16 | 0.080 | 53.090 | 1 | True |
| bond | int | fixed | descend-cost | sat | 12 | 16 | 0.082 | 6.202 | 1 | True |
| bond | int | fixed | oneshot | sat | 14 | 16 | 0.079 | 0.266 | 5 |  |
| bond | int | fixed | ramp-horizon | sat | 12 | 12 | 0.080 | 0.749 | 5 |  |
| bond | int | free | optimize | sat | 12 | 16 | 0.082 | 82.588 | 1 | True |
| bond | int | free | ramp-cost | sat | 12 | 16 | 0.082 | 157.278 | 1 | True |
| bond | int | free | descend-cost | sat | 12 | 16 | 0.084 | 22.465 | 1 | True |
| bond | int | free | oneshot | sat | 13 | 16 | 0.083 | 1.349 | 5 |  |
| bond | int | free | ramp-horizon | sat | 12 | 12 | 0.082 | 2.836 | 5 |  |
| rigid | int | fixed | optimize | sat | 4 | 10 | 0.052 | 0.409 | 5 | True |
| rigid | int | fixed | ramp-cost | sat | 4 | 10 | 0.056 | 0.327 | 5 | True |
| rigid | int | fixed | descend-cost | sat | 4 | 10 | 0.052 | 0.288 | 5 | True |
| rigid | int | fixed | oneshot | sat | 8 | 10 | 0.052 | 0.065 | 5 |  |
| rigid | int | fixed | ramp-horizon | sat | 4 | 4 | 0.052 | 0.023 | 5 |  |
| rigid | int | free | optimize | sat | 4 | 10 | 0.052 | 3.068 | 1 | True |
| rigid | int | free | ramp-cost | sat | 4 | 10 | 0.054 | 0.561 | 5 | True |
| rigid | int | free | descend-cost | sat | 4 | 10 | 0.053 | 0.659 | 5 | True |
| rigid | int | free | oneshot | sat | 10 | 10 | 0.053 | 0.565 | 5 |  |
| rigid | int | free | ramp-horizon | sat | 4 | 4 | 0.053 | 0.060 | 5 |  |
| water | int | fixed | optimize | sat | 10 | 12 | 0.080 | 7.751 | 1 | True |
| water | int | fixed | ramp-cost | sat | 10 | 12 | 0.079 | 7.656 | 1 | True |
| water | int | fixed | descend-cost | sat | 10 | 12 | 0.079 | 2.289 | 5 | True |
| water | int | fixed | oneshot | sat | 11 | 12 | 0.078 | 0.360 | 5 |  |
| water | int | fixed | ramp-horizon | sat | 10 | 10 | 0.078 | 0.383 | 5 |  |
| water | int | free | optimize | sat | 3 | 12 | 0.083 | 2.508 | 1 | True |
| water | int | free | ramp-cost | sat | 3 | 12 | 0.081 | 0.562 | 5 | True |
| water | int | free | descend-cost | sat | 3 | 12 | 0.081 | 4.409 | 1 | True |
| water | int | free | oneshot | sat | 9 | 12 | 0.082 | 0.467 | 5 |  |
| water | int | free | ramp-horizon | sat | 3 | 3 | 0.082 | 0.107 | 5 |  |
| trivial | bool | fixed | optimize | sat | 5 | 10 | 0.242 | 0.036 | 5 | True |
| trivial | bool | fixed | descend-cost | sat | 5 | 10 | 0.239 | 0.069 | 5 | True |
| trivial | bool | fixed | oneshot | sat | 6 | 10 | 0.246 | 0.026 | 5 |  |
| bond | bool | fixed | optimize | sat | 12 | 16 | 0.708 | 0.556 | 5 | True |
| bond | bool | fixed | descend-cost | sat | 12 | 16 | 0.708 | 0.550 | 5 | True |
| bond | bool | fixed | oneshot | sat | 14 | 16 | 0.726 | 0.074 | 5 |  |
| water | bool | fixed | optimize | sat | 10 | 12 | 0.598 | 0.215 | 5 | True |
| water | bool | fixed | descend-cost | sat | 10 | 12 | 0.594 | 0.165 | 5 | True |
| water | bool | fixed | oneshot | sat | 11 | 12 | 0.619 | 0.084 | 5 |  |
