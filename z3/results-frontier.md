# Stabilized Water tractability frontier (Z3)

Instance `water` (see NOTES.md), descend-cost to proven optimum, budget 120s per configuration (z3-solver 4.16.0).  Fixed-layout optimum is 10; free-layout optimum is 3.  `timeout(k)` = best (unproven) cost k when the budget ran out.

| encoding | layout | radius | t_max | status | cost | build s | solve s |
|---|---|---|---|---|---|---|---|
| bool | fixed | 2 | 12 | opt | 10 | 0.65 | 0.16 |
| bool | fixed | 2 | 16 | opt | 10 | 0.78 | 4.37 |
| bool | fixed | 2 | 20 | timeout(10) | 10 | 0.98 | 120.00 |
| bool | fixed | 2 | 24 | timeout(10) | 10 | 1.21 | 120.00 |
| bool | fixed | 2 | 30 | timeout(10) | 10 | 1.44 | 120.00 |
| bool | fixed | 3 | 12 | opt | 10 | 1.79 | 0.20 |
| bool | fixed | 3 | 16 | opt | 10 | 2.41 | 4.12 |
| bool | fixed | 3 | 20 | opt | 10 | 2.84 | 105.68 |
| int | fixed | 2 | 12 | opt | 10 | 0.09 | 2.64 |
| int | fixed | 2 | 16 | opt | 10 | 0.11 | 118.24 |
| int | fixed | 2 | 20 | timeout(10) | 10 | 0.13 | 120.00 |
| int | free | 2 | 12 | opt | 3 | 0.08 | 2.67 |
| int | free | 2 | 16 | opt | 3 | 0.11 | 20.38 |
| int | free | 2 | 20 | opt | 3 | 0.13 | 63.81 |
| int | free | 3 | 12 | opt | 3 | 0.08 | 6.31 |
| int | free | 3 | 16 | opt | 3 | 0.12 | 19.80 |
