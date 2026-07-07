# Self-competition leaderboard

Every incumbent below is one of this system's OWN solutions,
verified by the canonical validator (`harness/validate.py`) at
submission time. The external column is read-only comparison
data only -- never a training target, never an incumbent.

Store: 16 submissions processed.

## single_transport

| metric | our best | source | submission # | external best (read-only, comparison only) |
|---|---|---|---|---|
| instructions | 3 | solver:clingo | 4 | - |
| makespan | 5 | reference plan+junk-rot(x1) | 2 | - |
| area | 3 | solver:clingo | 4 | - |
| cost | 20 | reference plan+wait-shift(1) | 1 | - |
| sum | 29 | solver:clingo | 4 | - |
| sum4 | 32 | solver:clingo | 4 | - |
| product_gca | 360 | solver:clingo | 4 | - |
| product_gc | 100 | reference plan+junk-rot(x1) | 2 | - |
| product_ga | 60 | solver:clingo | 4 | - |
| product_ca | 18 | solver:clingo | 4 | - |

## stabilized_water

| metric | our best | source | submission # | external best (read-only, comparison only) |
|---|---|---|---|---|
| instructions | 12 | solver:clingo+wait-shift(2) | 8 | - |
| makespan | 12 | solver:clingo+junk-rot(x2) | 9 | - |
| area | 7 | reference plan+wait-shift(1) | 5 | - |
| cost | 40 | reference plan+wait-shift(1) | 5 | - |
| sum | 59 | solver:clingo+junk-rot(x2) | 9 | - |
| sum4 | 71 | solver:clingo | 12 | - |
| product_gca | 3360 | solver:clingo+junk-rot(x2) | 9 | - |
| product_gc | 480 | solver:clingo+junk-rot(x2) | 9 | - |
| product_ga | 280 | reference plan+wait-shift(1) | 5 | - |
| product_ca | 84 | solver:clingo+junk-rot(x2) | 9 | - |

## two_atom_bond

| metric | our best | source | submission # | external best (read-only, comparison only) |
|---|---|---|---|---|
| instructions | 11 | solver:clingo | 16 | - |
| makespan | 12 | reference plan+junk-rot(x1) | 14 | - |
| area | 7 | reference plan+wait-shift(1) | 13 | - |
| cost | 30 | reference plan+wait-shift(1) | 13 | - |
| sum | 49 | reference plan+junk-rot(x1) | 14 | - |
| sum4 | 61 | reference plan | 15 | - |
| product_gca | 2520 | reference plan+junk-rot(x1) | 14 | - |
| product_gc | 360 | reference plan+junk-rot(x1) | 14 | - |
| product_ga | 210 | reference plan+wait-shift(1) | 13 | - |
| product_ca | 84 | reference plan+junk-rot(x1) | 14 | - |

Stubbed metrics (not yet computed, not on the board): area_at_infinity, looping, rate.
