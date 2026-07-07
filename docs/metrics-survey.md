# Opus Magnum metrics survey: game, leaderboard, and tournament scoring

A survey of every solution metric used competitively for
[Opus Magnum](https://www.zachtronics.com/opus-magnum/) — in the official game,
on the community leaderboard ([zlbb.faendir.com](https://zlbb.faendir.com/)),
and across the community tournament scene (2019–2026) — with precise-enough
definitions to compute each metric from a solution trace / machine
description, and an assessment of what this repo's solver-comparison harness
would need in order to compute each one.

Ground-truth definitions come from the community simulator
[omsim](https://github.com/ianh/omsim) (ianh/panic), read at commit
[`930c5dc`](https://github.com/ianh/omsim/tree/930c5dc798b4c6c59226c706d9e26e9e584efd11)
— the same simulator the leaderboard embeds for verification
([zlbb help](https://zlbb.faendir.com/help)). Claims that could not be
confirmed against a primary source are marked **UNVERIFIED**.

Contents:

1. [Metric catalog](#1-metric-catalog)
2. [Taxonomy: how the metrics organize into implementable tiers](#2-taxonomy)
3. [Tournament survey](#3-tournament-survey)
4. [Implications for this repo's harness](#4-implications-for-the-harness)
5. [Source index and unverified items](#5-source-index-and-unverified-items)

Notation used throughout: `A > B > C` means "rank by A, break ties by B, then
C" (community convention). Letter codes: **G** cost, **C** cycles, **A** area,
**I** instructions, **R** rate, **H** height, **W** width, **B** bounding
hexagon, **T** trackless, **O** overlap, **L** looping.

---

## 1. Metric catalog

Rarity tiers used below:

- **core** — visible in the official game; the 2017-era leaderboard was built
  on these.
- **common** — long-standing community-standard metrics: published to the
  [r/opus_magnum wiki](https://www.reddit.com/r/opus_magnum/wiki/index) by the
  leaderboard bot and/or recurring across many tournaments.
- **niche** — established on the leaderboard or recurring in events, but
  outside the headline set (geometry, @∞ family, flags-as-categories).
- **one-off** — appeared in a single tournament week / side event.

### 1.1 Official in-game baseline

The game's win screen scores every normal puzzle on **cost, cycles, area**
(with player-base histograms), and **production puzzles replace area with
instructions** (cost, cycles, instructions)
([biggieblog](https://biggieblog.com/tracking-the-global-opus-magnum-records/);
Steam pitch: "the simplest, fastest, and most compact solutions",
[store page](https://store.steampowered.com/app/558990/Opus_Magnum/)). The
hidden fourth value is still computed by the game engine in both directions:
"Production puzzles don't show this value [area] in game, but it is computed
in the same way", and instructions likewise for non-production puzzles
([zlbb help](https://zlbb.faendir.com/help)).

| Metric | Letter | omsim metric string | Definition | Used | Rarity |
|---|---|---|---|---|---|
| Cost | G | `cost` | Sum of part prices over all placed parts, recomputed from the part list (never trusted from the solution file). Price table: calcification/bonder/unbonder 10; animismus, projection, dispersion, purification, duplication, unification, rejection, division 20; triplex bonder 20; multi-bonder 30; arm (1-armed) 20; 2/3/6-armed arm 30; piston 40; Van Berlo's wheel 30; Ravari's wheel 30; proliferation 40; track 5 per track hex. Inputs, outputs, conduits, equilibrium, disposal cost 0 ([decode.c L1298-1349](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/decode.c#L1298-L1349)). | game, zlbb, tournaments | core |
| Cycles | C | `cycles` | The (1-based) cycle on which the last required product was dropped, where completion = every output has produced ≥ `6 × output_scale` products (min over all outputs) ([sim.c L1828-1850](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/sim.c#L1828-L1850), [decode.c L1294](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/decode.c#L1294)). Each cycle executes one instruction slot on every arm's tape in parallel. | game, zlbb, tournaments | core |
| Area | A | `area` | Total count of hexes ever "used" during the run: (a) initial part footprints — cabinet walls, input/output atom hexes, glyph footprints, conduits, arm bases, track hexes; (b) every hex covered by any arm's grabber axis on any cycle; (c) the intermediate hexes swept by rotations of length-2 arms (3 extra hexes per swing) and length-3 arms (6 extra); (d) every hex any atom ever occupies. Each hex counts once ([sim.c L2041-2123](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/sim.c#L2041-L2123), [L1393-1417](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/sim.c#L1393-L1417), [L829-864](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/sim.c#L829-L864), [L2407-2418](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/sim.c#L2407-L2418)). | game (normal puzzles; computed but hidden for production), zlbb, tournaments | core |
| Instructions | I | `instructions` | Total non-blank instruction-tape slots across all arms, with repeat/reset instructions expanded to their contained primitives, and wait (blank) and halt markers not counted ([decode.c L1351-1361](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/decode.c#L1351-L1361); [zlbb help](https://zlbb.faendir.com/help)). | game (production puzzles; computed but hidden for normal), zlbb, tournaments | core |

### 1.2 Leaderboard value metrics beyond the game's

All verified against the zlbb help page
([zlbb.faendir.com/help](https://zlbb.faendir.com/help), source at
[HelpView.tsx](https://github.com/F43nd1r/zachtronics-leaderboard-bot/blob/master/web/src/views/om/help/HelpView.tsx))
and the bot's metric model
([OmMetric.kt](https://raw.githubusercontent.com/F43nd1r/zachtronics-leaderboard-bot/master/src/main/kotlin/com/faendir/zachtronics/bot/om/model/OmMetric.kt)),
with computation semantics from omsim.

| Metric | Letter | omsim expression | Definition | Used | Rarity |
|---|---|---|---|---|---|
| Rate | R (internal alias C′) | `per repetition cycles` ÷ `per repetition outputs`, leaderboard-rounded as `ceil(100·x)/100` ([test-against-leaderboard.py L12-18](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/test-against-leaderboard.py#L12-L18)) | "Average cycles between outputs in the steady state." Requires a looping solution; a solution which outputs 3 times every 49 cycles has rate 49/3 regardless of spacing. **Rounded up to 2 decimal places, so 10/3 is treated as the same rate as 3.34** — a deliberate anti-epsilon rule ([zlbb help](https://zlbb.faendir.com/help)). Equal to 1/throughput. Not itself an omsim metric string — derived by callers ([main.c L213-223](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/main.c#L213-L223)). | zlbb (@∞ manifolds), tournaments (from 2020 W2, as "Throughput") | common |
| Height | H | `height` = min over the three axis projections of `height at 0/60/120 degrees` | Number of rows in the **used-area footprint** (the same hex set as the area metric, not just atoms): for each used hex, project onto one of the three hex axes; height = max − min + 1; the reported value is the minimum over the three orientations (rotation-invariant) ([verifier.c L369-379](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L369-L379), [L518-524](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L518-L524)). | zlbb (@hV/@h∞ manifolds), tournaments | niche |
| Width | W | `width*2 / 2` (omsim's canonical integer form is `width*2`) | Number of columns of the used-area footprint, along the three perpendicular (doubled) projections; each projection value = max − min + 2, which is **twice** the width because the projection steps by 2 per column — width is fundamentally a half-integer metric, and all leaderboard widths are `width*2` halved ([verifier.c L374-378](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L374-L378), [L525-531](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L525-L531)). Min over the three orientations. | zlbb (@wV/@w∞), rare in tournaments | niche |
| Bounding hexagon ("Bestagon") | B | `minimum hexagon` | Side length of the smallest regular hexagon (flat orientation, any center) containing all used hexes: `1 + max(h0/2, h60/2, h120/2, (max0+max60+max120+2)/3, (−min0−min60−min120+2)/3)` over the three height-axis extents/extremes ([verifier.c L415-426](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L415-L426); [zlbb help](https://zlbb.faendir.com/help)). | zlbb (@bV/@b∞), 2024 Weeklies W3 | niche |
| Area @∞ (3 levels) | A@∞ / A′ / A″ | level 0: `steady state area`; level 1: `per repetition area` ÷ outputs; level 2: `per repetition^2 area` ÷ outputs² ([test-against-leaderboard.py L26-35](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/test-against-leaderboard.py#L26-L35)) | Asymptotic area class + value. Bounded growth → finite A@∞; linear growth (escaping chains, none swinging) → **A′** = "the average amount the area increases per output in the steady state"; quadratic growth (chains swung around an arm) → **A″**, "normalized such that a chain that grows 1 atom longer every output which swings across 60 degrees has A″=1" ([zlbb help](https://zlbb.faendir.com/help)). No cubic or higher class exists ([omsim steady-state.c](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/steady-state.c#L239-L507)). The Pareto visualizer renders A′ as 100000 area-units and A″ as 1e10. | zlbb (@a∞/@i∞), 2025 tournament S7, 2025 Weeklies W2 | niche |
| H@∞, W@∞, B@∞ | — | `steady state height`, `steady state width*2 / 2`, `steady state minimum hexagon` | The same geometry metrics measured over the steady-state loop; may simply be ∞ if chains keep escaping. Direction-dependent invalidation: a chain translating with direction (du,dv) invalidates the height/width axes it grows along; any swinging chain invalidates all of them ([verifier.c L633-657](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L633-L657)). | zlbb (@h∞/@w∞/@b∞) | niche |

### 1.3 Boolean flags ("modifiers")

The leaderboard derives all three from omsim quantities; **omsim itself has no
metric named "trackless", "looping", or an overlap flag** — the mapping below
is exactly how the leaderboard bot computes them
([test-against-leaderboard.py L37-52](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/test-against-leaderboard.py#L37-L52)).

| Flag | Letter | Derivation | Definition | Used | Rarity |
|---|---|---|---|---|---|
| Trackless | T | `number of track segments == 0` (sum over parts of track-hex counts) ([verifier.c L777-781](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L777-L781)) | Solution contains no track hexes. Trackless is *better* (reverse-ordered tiebreaker); a leading T in a category name means trackless-only admission ([zlbb help](https://zlbb.faendir.com/help)). | zlbb (T-categories, tiebreaker in all manifolds), tournaments ("Trackless Instructions" etc.) | common |
| Overlap | O | `overlap != 0`, where `overlap` counts hexes of static part overlap at setup — parts marked in order (walls → reagent/product hexes → glyphs → conduits → arm bases → track); each already-used hex increments the count; track under an arm base is exempt (legal in normal play); track-on-track self-overlap detected separately at decode time and added ([sim.c L2041-2097](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/sim.c#L2041-L2097), [decode.c L950-953](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/decode.c#L950-L953)) | Parts sharing hexes — an exploit (file editing or an in-game shift-click trick). Overlap makes a solution strictly worse, all else equal; normal categories implicitly require no-overlap; a leading O means overlap *allowed* (`ANYTHING_GOES`) ([zlbb help](https://zlbb.faendir.com/help)). | zlbb (O-categories), 2021+ tournaments (selectively legalized) | common |
| Looping | L | `reaches steady state` = solution provably returns to an identical past state within the cycle limit ([verifier.c L850-856](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L850-L856)) | Solution returns to an identical past state and outputs during the steady state; "indicates that a clean GIF of the solution ... is possible". Only used on @V manifolds — @∞ manifolds outright require looping. Predictably growing chains (polymers) are allowed in the steady state; conditional wasteballs with ever-growing gaps are not ([zlbb help](https://zlbb.faendir.com/help)). | zlbb (tiebreaker), 2024 tournament W3 (explicit tiebreaker) | common |

### 1.4 Leaderboard composite metrics

| Metric | Code | Definition | Used | Rarity |
|---|---|---|---|---|
| Sum | Sum | G+C+A (normal), G+C+I (production) ([zlbb help](https://zlbb.faendir.com/help)) | zlbb category (on the r/opus_magnum wiki headline set), tournaments since 2020 W1 | common |
| Sum4 | Sum4 | G+C+A+I ([zlbb help](https://zlbb.faendir.com/help)) | zlbb category, 2023 tournament W4, 2025 Weeklies W9 | niche |
| Product | X | "In the @V measure point, it is G·C·A, or G·C·I in production. In the @∞ measure point, it is R·G·I." As a tiebreaker letter inside 2-letter categories, X = the product of the two metrics *not* named (e.g. GX = min cost, tiebreak by C·A). Code objects: PRODUCT_GC, PRODUCT_GA, PRODUCT_GI, PRODUCT_CA, PRODUCT_CI, PRODUCT_GCA, PRODUCT_GCI, PRODUCT_INF ([zlbb help](https://zlbb.faendir.com/help); [OmMetric.kt](https://raw.githubusercontent.com/F43nd1r/zachtronics-leaderboard-bot/master/src/main/kotlin/com/faendir/zachtronics/bot/om/model/OmMetric.kt)) | zlbb (GX/CX/AX/IX/ORX categories), tournament tiebreakers | niche |

### 1.5 omsim-only metrics (diagnostics, exotic-metric building blocks)

Everything below is exposed by omsim's verifier
(`verifier_evaluate_metric` /
`verifier_evaluate_approximate_metric`, dispatcher at
[verifier.c L764-1063](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L764-L1063))
but is not a leaderboard category by itself. Several of these are exactly the
primitives tournament hosts build exotic metrics from (the verifier API is
"designed for bots to use",
[verifier.h L4](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.h#L4);
the up-to-date metric list is hosted at
`http://events.critelli.technology/static/metrics.html`,
[verifier.h L86-87](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.h#L86-L87)).

| omsim metric string | Definition | Rarity |
|---|---|---|
| `parsed cycles` / `parsed cost` / `parsed area` / `parsed instructions` | The scores stored in the `.solution` file header (present only if saved as solved; 0 otherwise) ([verifier.c L769-776](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L769-L776)) | niche (validation) |
| `number of track segments` | Total track hexes placed; basis of the Trackless flag and of "Tracks + Instructions" / "Number of Tracks" tournament metrics ([verifier.c L777-781](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L777-L781)) | common (as flag basis) |
| `parts of type <name>` | Count of parts by solution-file name (`arm1`, `arm2`, `arm3`, `arm6`, `piston`, `baron`, `ravari`, `track`, `bonder`, `unbonder`, `bonder-speed`, `bonder-prisma`, `glyph-calcification`, `glyph-duplication`, `glyph-projection`, `glyph-purification`, `glyph-life-and-death`, `glyph-disposal`, `glyph-dispersion`, `glyph-unification`, `glyph-marker`, `input`, `out-std`, `out-rep`, `pipe`, plus modded names) ([verifier.c L782-789](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L782-L789)). Building block for Cycles×Bonders, Amarms, triplex-count metrics, No-Pistons constraints. | niche |
| `duplicate reagents` / `duplicate products` | Copies beyond the first of input/output parts referencing the same puzzle reagent/product index — an exploit detector ([verifier.c L792-814](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L792-L814)) | niche (legality) |
| `maximum track gap^2` | Max squared hex distance between consecutive track hexes within a track part; > 1 = the "quantum track" exploit ([verifier.c L815-828](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L815-L828)) | niche (legality) |
| `maximum absolute part coordinate` | Max over parts of max(\|q\|,\|r\|,\|s\|) of the part origin in cube coordinates — detects far-offscreen placement ([verifier.c L829-843](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L829-L843)); the leaderboard rejects parts farther than 16384 tiles from origin ([zlbb help](https://zlbb.faendir.com/help)) | niche (legality) |
| `instructions with hotkey <letters>` | Tape slots equal to any of the given letters (`a` rotate CCW, `d` rotate CW, `w` extend, `s` retract, `r` drop, `f` grab, `e` pivot CW, `q` pivot CCW, `g`/`t` track ∓, `b` halt) ([verifier.c L907-943](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L907-L943)). Basis of "Pivots", "Instructions except grab/drop/pivots", "Times Fire is grabbed"-style metrics. | one-off basis |
| `instruction tape period` | Longest tape length among non-halting arms = cycles after which every looping tape repeats ([decode.c L1281-1282](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/decode.c#L1281-L1282)). The tournament "Period" metric (2023 W5, 2024 W6, WAHT 2024 W1, 2024 Weeklies W1/W3). | niche |
| `number of arms` | Count of decoded arm mechanisms, all arm/wheel/piston types ([verifier.c L948-951](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L948-L951)). Basis of Tarcles and Amarms. | niche |
| `cabinet violations` / `conduit violations` | Boolean production-legality flags (glyph/arm/track/IO outside cabinet, arm reaching across wall, isolation violated, conduit altered/misplaced) ([decode.h L7-15](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/decode.h#L7-L15)) | niche (legality) |
| `overlap` | Integer overlap-hex count (see §1.3) | common (as flag basis) |
| `executed instructions` | Tape slots that executed at least once by the stopping cycle (each counted once even across tape loops) ([verifier.c L428-454](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L428-L454)). Suggested metric of the 2025 tournament break week. | one-off |
| `instruction executions` (+ `with hotkey <letters>`) | Total executions including tape repetitions up to the stopping cycle ([verifier.c L536-557](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L536-L557)) | one-off basis |
| `atoms grabbed` (+ `of type <name>`) | Times a grab instruction closed on an atom, optionally per element (`salt air earth fire water quicksilver gold silver copper iron tin lead vitae mors quintessence`) ([sim.c L1091-1097](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/sim.c#L1091-L1097), [verifier.c L458-496](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L458-L496)). Used in 2024 Weeklies W4 ("Times Fire is grabbed > Times Salt is grabbed"). | one-off |
| `number of atoms` (+ `of type <name>`) | Atoms on the board at the stopping cycle (excluding Van Berlo/Ravari wheel atoms) ([verifier.c L399-404](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L399-L404)) | niche |
| `per repetition cycles` / `per repetition outputs` | Steady-state loop length in cycles / products dropped per loop (min over outputs; polymer outputs rescaled by feed rate) ([verifier.c L857-866](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L857-L866)); the two components of Rate | common (via Rate) |
| `per repetition area` / `per repetition^2 area` | Linear / quadratic area-growth coefficients per loop (the latter a double, from angular-wedge integration of swung chains) ([verifier.c L867-875](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L867-L875), [steady-state.c L416-485](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/steady-state.c#L416-L485)) | niche (via A@∞) |
| `throughput waste` | 0/1: solution ejects unbounded waste/product chains each loop ([verifier.c L633-656](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L633-L656)) | niche |
| `visual loop start cycle` / `visual loop end cycle` | Verified loop boundaries; end = start + period, or + 2·period under pivot parity (for seamless GIFs) ([verifier.c L881-896](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L881-L896)) | niche (tooling) |
| Output intervals ("lexicographic cycles") | Dedicated API, not a metric string: interval 0 = cycle of the first product; interval i = cycles between the i-th and (i+1)-th product (min-across-outputs counter), with the repeating block minimized once steady state is reached ([verifier.h L95-104](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.h#L95-L104), [verifier.c L674-762](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L674-L762)). The tournament "LexC" metric (2023 W1, 2022 Weeklies W10, 2025 Weeklies W10) and the basis of **Latency** (cycles to first product = interval 0; 2022 W6, 2025 S1). | niche |
| Prefix modifiers `product <N> …` / `cycle <N> …` / `steady state …` | Re-target any per-cycle metric to: first N products per output; exactly N cycles; or the steady-state loop ([verifier.c L981-1045](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L981-L1045)). Basis of Area@1 (2025 S1) and Start Height (2026 Weeklies W1). | one-off basis |

omsim details that matter for reimplementation: the default cycle limit is
150,000 cycles (collision-check limit 2×10¹⁰), overridable
([verifier.c L133-140](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L133-L140));
metrics error with −1 and a source class of `puzzle file` / `solution file` /
`metric` / `simulation`
([verifier.c L229-232](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/verifier.c#L229-L232)).
Known omsim gaps: conduit "spooky action at a distance" cloning is
unimplemented, and track-reset differs from the game in some
overlapping-track situations
([README L16-21](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/README#L16-L21)).

### 1.6 Tournament-only metrics (not on the leaderboard)

All from the events archive at
[events.critelli.technology](https://events.critelli.technology/) unless noted;
per-week citations in §3.

| Metric | Definition | First/known uses | Rarity |
|---|---|---|---|
| Latency | Cycles to first product (output interval 0) | 2022 tournament W6 Fulmination; 2025 S1; 2023 Weeklies W1; 2026 Weeklies W1 | niche |
| LexC (Lexicographic Cycles) | Compare cycles to 1st output, then 2nd, ... (must complete normally) | 2022 Weeklies W10; 2023 tournament W1; 2025 Weeklies W10 | niche |
| Period | Cycles for the instruction tape to loop (= omsim `instruction tape period`) | 2023 tournament W5; 2024 W6; WAHT 2024 W1 | niche |
| Period / Rate | Maximize wasted motion per output (idle ratio) | 2024 Weeklies W1 Pitch Drop Experiment | one-off |
| Tarcles | (arms + track hexes) × cycles | 2022 tournament W3 (unnamed); named in 2024 W2 | one-off |
| Amarms | area − number of arms | 2024 tournament W5; 2025 Weeklies W5 | one-off |
| MechA (Mechanism Area) | Area of the solution after deleting everything except arms/track/Van Berlo ([biggieblog](https://biggieblog.com/introducing-mecha-the-opus-magnum-metric-of-your-nightmares/)) | 2025 tournament S5 | one-off |
| Mechanism Cost | Cost counting basic 20g arms only ([biggieblog](https://biggieblog.com/introducing-mecha-the-opus-magnum-metric-of-your-nightmares/)) | 2020 tournament (week UNVERIFIED) | one-off |
| Tracks + Instructions | track hexes + instruction count | 2022 tournament W4/W8; 2023 Weeklies W10; 2024 Weeklies W10; Speed Solve 3 W3 | niche |
| Cycles × Bonders | 2020 W6 plain; 2022 Weeklies W7 weighted (bonder 1, multibonder 3, debonder 0) | as listed | one-off |
| Cycles × Reagents | cycles × number of input glyphs placed | 2023 Weeklies W4 | one-off |
| Weighted scalars | Cost/5 + Cycles + Area (2022 W9 & 2023 W8 finales); Cost/5 + Cycles×20 + Area (2022 Weeklies W6); Cost + Cycles×5 + Area (2025 Weeklies W8 Boozesort); Cost + Cycles/6 + Area, maximized over 25 test cases (2024 Weeklies W8 Look-And-Say); Instructions + Cost/5g (2020 W3); 5ISum = G+C+5I (Salt of Saturn Ex.5); Sum + 50×(distinct instruction types used) (2025 Weeklies W11) | as listed | one-off each |
| max(Cost, 100) | Floor-clamped cost — values below 100 give no advantage | 2022 Weeklies W13 Hot Ice | one-off |
| Max Area (No Unnecessary Parts) | Area **maximization**; disqualified if the solution still validates with any single part removed | 2022 Weeklies W1 Sweeper Rod | one-off |
| Cycles/triplex, Cost − 20·triplex | Cycles divided by triplex-bonder count; cost with triplex bonders free | WAHT 2024 W2 Children's Toys | one-off |
| Cost–Cycles Pareto Frontier score | Score computed from ALL of a player's submissions against the global cost–cycles frontier | 2024 Weeklies W5 Sophick Mercury; 2025 Weeklies W4 Pareto Poppers | one-off |
| Two-phase adversarial hybrid ranking | Phase 1: max(area₁,area₂) × max(cost₁,cost₂) over a player's two submissions; phase 2: submissions cross-combined, scored by rank of best hybrid, then second-best, ... | WAHT 2025 Silver Apple of Discord | one-off |
| Vintage Instructions | 2022 Weeklies W11 Brazing Cathode (exact rule per event page) | as listed | one-off |
| Start Height | Height at start (measurement-point-tagged geometry) | 2026 Weeklies W1 | one-off |
| Aesthetics / Shitpost | Community vote, no objective formula | Weeklies finale every season since 2022 | niche (recurring but subjective) |
| Time to solve | Wall-clock minutes from release to submission | Speed Solve seasons (category 1 of every puzzle; even a tiebreaker in Speed Solve 2.4) | niche |

---

## 2. Taxonomy

Organized as implementation tiers: each tier only needs the capabilities of
the tiers before it.

### 2.1 Primary (atomic) metrics

Grouped by what part of a solution they read:

1. **Static / file-level (@0)** — no simulation needed:
   cost (part price table), instructions (expanded tape slots), number of
   track segments → trackless flag, parts-of-type counts, number of arms,
   instruction tape period, overlap count → overlap flag, legality
   diagnostics (`duplicate reagents/products`, `maximum track gap^2`,
   `maximum absolute part coordinate`, cabinet/conduit violations).
   The leaderboard's measure-point enum calls this **@0 / START**
   ([OmMetric.kt](https://raw.githubusercontent.com/F43nd1r/zachtronics-leaderboard-bot/master/src/main/kotlin/com/faendir/zachtronics/bot/om/model/OmMetric.kt)).
2. **Run-to-victory (@V)** — simulate until every output reaches
   6×output_scale products; "everything beyond that point is ignored"
   ([zlbb help](https://zlbb.faendir.com/help)):
   cycles, area, height, width, bounding hexagon, executed instructions,
   instruction executions, atoms grabbed, number of atoms, latency and the
   full output-interval sequence (LexC). biggiemac42's older notation for
   @V is @6 ([biggieblog](https://biggieblog.com/tracking-the-global-opus-magnum-records/)).
3. **Asymptotic (@∞)** — requires steady-state detection (only defined for
   looping solutions): rate, A@∞ (3 growth classes), H@∞/W@∞/B@∞,
   throughput waste, visual loop bounds.
4. **Out-of-band** — not computable from the trace at all: wall-clock time
   to solve (Speed Solve), community votes (Aesthetics/Shitpost),
   field-relative scores (Pareto-frontier metrics, WAHT hybrid ranking).

### 2.2 Composite metrics (arithmetic over primaries)

- **Sums**: Sum (G+C+A / G+C+I), Sum4 (G+C+A+I), variant sums
  (G+C+I in 2025 Weeklies W1), weighted scalars (Cost/5 + Cycles + Area
  etc.), 5ISum.
- **Products**: X (G·C·A / G·C·I / R·G·I), pairwise products as tiebreakers
  (C·A in GX, etc.), Cycles×Bonders, Cycles×Reagents, Tarcles.
- **Differences/ratios/clamps**: Amarms (A − arms), Period/Rate,
  Cycles/triplex, max(Cost, 100).

All composites are trivially computable once their primaries exist; the only
subtlety is measure-point consistency (X at @∞ is R·G·I, not C-based).

### 2.3 Constraint flags

Booleans that either gate admission to a category or act as
reverse-ordered tiebreakers: **Trackless** (T), **Overlap** (O),
**Looping** (L) — plus tournament-local constraints in the same shape:
No Pistons (2025 Weeklies W6), "no grabbing mors" (2023 Weeklies W6), budget
caps (cost ≤ 1000, 2025 tournament S6), finite-area / finite-rate /
must-loop / must-run-to-completion restrictions
([tournament archive](https://events.critelli.technology/)). On the
leaderboard, flags participate in the Pareto frontier as ordered dimensions
(better = trackless, non-overlap, looping)
([zlbb help](https://zlbb.faendir.com/help)).

### 2.4 Asymptotic / throughput machinery

The distinguishing capability is **steady-state detection**: omsim snapshots
the full machine state at exponentially-spaced, tape-period-aligned cycles
and compares (arms up to 2/3/6-fold symmetry, atom grid, per-output counts;
atoms outside the parts' bounding box become "chain atoms" that must move by
pure translation each loop)
([steady-state.c L239-507](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/steady-state.c#L239-L507)).
On top of it: rate = loop cycles ÷ loop outputs (rounded up to 0.01 by the
leaderboard); area growth classified none/linear/quadratic → A@∞/A′/A″;
polymer outputs rescaled by feed rate. A harness can stage this: (a) exact
state-repeat detection is enough for Looping + Rate on bounded machines;
(b) chain-atom translation tracking adds polymer/waste solutions;
(c) the wedge-integration for A″ is only needed for the rarest categories.

### 2.5 Tournament scoring transforms (turning metrics into season points)

Three regimes, in chronological order
(details and citations in §3):

1. **2019–2022: metric points + rank points (10 per category).**
   Metric points = 5 × (best value ÷ your value) — ratio-to-best
   normalization on the primary metric only; rank points =
   5 × ((N + 1 − rank) / N) for field size N. Category winner always gets
   exactly 10 ([2020 rules doc](https://docs.google.com/document/d/1Et7kFFcWYdhgPWgSBZnjZ_Mpjub4qBF0i_pQGu8uiNs/);
   worked example [pastebin](https://pastebin.com/MZsxkZBL)).
2. **2023–present: pure fixed rank points, 300 / (rank + 29), capped at 10**
   (rank 1 = 10, 2nd = 9.677, 3rd = 9.375, ...). Ties share a rank with a gap
   after. Independent of field size and metric magnitude — adopted precisely
   because ratio normalization under-weighted easy-to-match metrics and
   "allowed more creative metrics without scoring complications"
   ([2023 rules](https://events.critelli.technology/OM2023_Intro),
   [2023 recap](https://biggieblog.com/recapping-the-2023-opus-magnum-tournament/)).
3. **Per-event deviations**: single-scalar computation finales with a
   +10 completion bounty (2022 W9, 2023 W8); best-2-of-3 metrics (2024 W7);
   drop-two-worst-weeks (2026); Pareto-frontier-as-score and vote-based
   categories (Weeklies); wall-clock scoring (Speed Solve).

Tiebreak doctrine across all years: categories are lexicographic chains;
full ties score identically; **submission timestamp is explicitly never a
tiebreaker** in the annual tournament
([2020 rules doc](https://docs.google.com/document/d/1Et7kFFcWYdhgPWgSBZnjZ_Mpjub4qBF0i_pQGu8uiNs/))
— though Speed Solve 2.4 used wall-clock as a tiebreaker deliberately.

### 2.6 The leaderboard's structural layer: manifolds, categories, frontiers

Since the **January 2023 "pareto manifold split"** (driven by 12345ieee,
[biggieblog](https://biggieblog.com/tracking-the-global-opus-magnum-records/)),
each solution's score splits into per-measure-point subscores. A **manifold**
= one measure point + one "arealike" metric choice; each keeps its own Pareto
frontier ([OmScoreManifold.kt](https://raw.githubusercontent.com/F43nd1r/zachtronics-leaderboard-bot/master/src/main/kotlin/com/faendir/zachtronics/bot/om/model/OmScoreManifold.kt);
[zlbb help](https://zlbb.faendir.com/help)):

| Manifold | Puzzle types | Frontier metrics (ordered) |
|---|---|---|
| @aV VICTORY_AREA | normal + 3 polymer types | O, G, C, A, L, I, T |
| @iV VICTORY_PROD | production | O, G, C, I, L, A, T |
| @hV VICTORY_HEIGHT | normal, polymer-height | O, G, C, H, L, I, T |
| @wV VICTORY_WIDTH | normal, polymer-width | O, G, C, W, L, I, T |
| @bV VICTORY_BHEX | normal | O, G, C, B, L, I, T |
| @a∞ INFINITY_AREA | normal + polymer types | O, G, R, A@∞, I, T |
| @i∞ INFINITY_PROD | production | O, G, R, I, A@∞, T |
| @h∞ INFINITY_HEIGHT | normal, polymer-height | O, G, R, H@∞, I, T |
| @w∞ INFINITY_WIDTH | normal, polymer-width | O, G, R, W@∞, I, T |
| @b∞ INFINITY_BHEX | normal | O, G, R, B@∞, I, T |

Consequence: "solutions that optimize metric combinations that never exist in
the same manifold (such as C and R, or A@V and H@V) are not included on the
leaderboard" ([zlbb help](https://zlbb.faendir.com/help)). A solution is on a
frontier if no other is at least equal in all metrics and better in one; only
frontier solutions are accepted; full ties are rejected ("This biases toward
earlier-submitted solutions.").

**Categories** (61 as of 2026-07-07, per the
[JSON API](https://zlbb.faendir.com/om/categories) cross-checked against
[OmCategory.kt](https://raw.githubusercontent.com/F43nd1r/zachtronics-leaderboard-bot/master/src/main/kotlin/com/faendir/zachtronics/bot/om/model/OmCategory.kt)):
a name is a letter sequence — first letter = primary metric minimized, each
further letter a tiebreaker; leading O = overlap allowed, leading T =
trackless-only. Beyond named letters the default tiebreak order is
"O G [C R] [A B H W] L I T, or O G [C R] I L A T for production, only
counting the metrics that are in the category's manifold"
([zlbb help](https://zlbb.faendir.com/help)). The full list:

- **@V normal/polymer (@aV)**: GC, GA, GI, GX, CG, CA, CI, CX, AG, AC, AI,
  AX, IG, IC, IA, Sum, Sum4; overlap OGC, OCX, OAC, OIC; trackless TG, TC,
  TIG, TIC.
- **@V production (@iV)**: GC, GI, GX, CG, CI, CX, IG, IC, IX, Sum; plus
  OGC, OCX, OIC and TG, TC, TIG, TIC production variants (`_P` ids,
  displayed with the same names).
- **@V geometry**: HG, HC, WG, WC, BG, BC.
- **@∞**: RG, RA, RI, HR, WR, BR, TIA (the one trackless @∞ category — the
  help page warns "TIA is @∞, and thus may have a higher instructions score
  than a solution in TIG, which is @V"), and overlap ORG, ORX.

**Rarity structure within the categories** (no numeric rarity score exists;
the `OmCategory` enum declaration order is the canonical display order):

- *Core*: the 6 permutations of G/C/A (G/C/I for production) — these date to
  the original 2017–2018 Reddit leaderboard
  ([biggieblog](https://biggieblog.com/tracking-the-global-opus-magnum-records/)).
- *Community-standard*: what the bot publishes to the r/opus_magnum wiki —
  exactly four columns per puzzle, Cost / Cycles / Area(or Instructions) /
  Sum, drawn from category sets {GC, GA, GX, GI_P, ...}, {CG, CA, CX, CI_P},
  {AG, AC, AX, IG_P, IC_P, IX_P}, {SUM, SUM_P}
  ([OmRedditWikiGenerator.kt](https://github.com/F43nd1r/zachtronics-leaderboard-bot/blob/master/src/main/kotlin/com/faendir/zachtronics/bot/om/repository/OmRedditWikiGenerator.kt);
  the rendered wiki page itself is UNVERIFIED — reddit blocks unauthenticated
  fetches — but its content is determined by that generator).
- *Niche/exotic*: geometry (H/W/B), the @∞ family, trackless-instruction and
  overlap categories — none appear in the wiki subset; biggieblog presents
  Rate and the geometry metrics as later, omsim-enabled additions.

Leaderboard legality floor (rejected regardless of category): out-of-chamber
parts in production puzzles, added/moved conduits, >16384 instructions,
parts >16384 tiles from origin, disabled parts/instructions, duplicate
inputs/outputs, multiple Van Berlo/disposal/proliferation/Ravari, gaps in
track ([zlbb help](https://zlbb.faendir.com/help)).

Leaderboard history in one line each
([biggieblog](https://biggieblog.com/tracking-the-global-opus-magnum-records/)):
Oct 2017 Obyekt starts a cycles-first Reddit leaderboard (ties by cost, then
area); early 2018 biggiemac42 expands to all 6 metric permutations, then
product tiebreakers and a Sum category; 12345ieee rewrites the bot with
Pareto-frontier support; omsim enables Rate and the geometry metrics; 2021
F43nd1r integrates Discord + the zlbb site; Jan 2023 the manifold split.
(The domain **om-leaderboard.dev does not resolve** as of 2026-07-07;
UNVERIFIED that it ever hosted the leaderboard. The GitHub repos
F43nd1r/om-leaderboard and 12345ieee/om-leaderboard-archive hold current and
pre-bot record data respectively; their README contents are UNVERIFIED.)

---

## 3. Tournament survey

### 3.1 The annual tournament (2019–2026, one per year)

No 2018 tournament existed: the series started January 2019, and the 2025
and 2026 editions call themselves the 7th and 8th annual
([OM2025 intro](https://events.critelli.technology/OM2025_Intro),
[OM2026 intro](https://events.critelli.technology/4d281c19a003d1999e05ce2d8e6c4415)).
Common format across all years: weekly **custom puzzles** (never base-game
puzzles), made by the host and unseen by competitors; usually **two metric
categories per puzzle**; ~9–11 day windows; cumulative season score;
distribution via Google Drive / the event site rather than Steam Workshop
(Workshop would leak scores via histograms — 2020 rules doc). Master puzzle
collection: [Steam Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=2597159271).

| Year | Host | Venue | Scoring | Winner | Notes |
|---|---|---|---|---|---|
| 2019 | RP0 | r/opus_magnum + Steam ([announcement](https://www.reddit.com/r/opus_magnum/comments/abpxj8/opus_magnum_tourney/), body UNVERIFIED; [Steam cross-post](https://steamcommunity.com/app/558990/discussions/0/1742230617613451391/)) | 5×(best/yours) + 5×((N+1−rank)/N) per category (the 2020 doc says "Scoring is identical to the previous tournament") | biggiemac42 ([2022 recap](https://biggieblog.com/recapping-the-2022-opus-magnum-tournament/)) | 9 custom puzzles (Unwinding → Panacea). Per-week categories UNVERIFIED (Reddit-only). |
| 2020 | biggiemac42 | Reddit + Discord + Steam ([rules doc](https://docs.google.com/document/d/1Et7kFFcWYdhgPWgSBZnjZ_Mpjub4qBF0i_pQGu8uiNs/), [announcement](https://steamcommunity.com/app/558990/discussions/0/1741138639068562529/)) | Same 5+5 system; max 20 pts/week over 2 categories | PentaPig, of 44 entrants ([results](https://steamcommunity.com/app/558990/discussions/0/2143092024482266512/)) | By design category 1's primary is always a game-tracked metric, category 2 "slightly more contrived". Notable weeks: W2 Throughput > Cost (non-looping DQ'd); W3 Instructions + Cost/5g; W6 Cycles×Bonders; W8 Metal Calculus computation finale (categories UNVERIFIED). A "Mechanism Cost" category appeared this year (week UNVERIFIED, [biggieblog](https://biggieblog.com/introducing-mecha-the-opus-magnum-metric-of-your-nightmares/)). |
| 2021 | brookieoz | Zachtronics Discord + Reddit + Steam ([announcement](https://steamcommunity.com/app/558990/discussions/0/2997674644668131713/)) | Same 5+5 system ([explainer](https://pastebin.com/MZsxkZBL)) | biggiemac42 | 10 scored puzzles. First deliberate legalization of overlap in at least one puzzle, with throughput scoring ([biggieblog](https://biggieblog.com/playing-opus-magnum-by-different-rules/)). Per-week category list UNVERIFIED. |
| 2022 | OMGITSABIST ("Bist") | events.critelli.technology + Discord, Twitch result streams ([recap](https://biggieblog.com/recapping-the-2022-opus-magnum-tournament/), [pages](https://events.critelli.technology/collection/om2022)) | Still "half points from rank and half from metric" per the 2023 recap; exact wording UNVERIFIED | PentaPig (72 players submitted ≥ once) | First year on the event site (built by panic). W3 introduced (Tracks+Arms)×Cycles, later named "Tarcles"; W6 Throughput and Latency; W9 Transmutation CX computation finale scored as the single scalar Cost/5 + Cycles + Area with +10 for solving. |
| 2023 | panic (Ian Henderson) | events.critelli.technology + Discord ([intro](https://events.critelli.technology/OM2023_Intro), [recap](https://biggieblog.com/recapping-the-2023-opus-magnum-tournament/)) | **New: 300/(rank+29), capped at 10** — pure rank points, used ever since | PentaPig (3rd title; 67 submitters) | W1 LexC; W2 Trackless Instructions and Height; W5 Period; W6 Rate; W8 Habitability Detector finale (single scalar Cost/5 + Cycles + Area, +10 bounty; optional warmup puzzle worth 10 unranked bonus points). |
| 2024 | zorflax | events.critelli.technology + Discord ([pages](https://events.critelli.technology/collection/om2024); [ermsta recap](https://ermsta.com/posts/20240506)) | 300/(rank+29) ("same scoring system as panic did in 2023") | UNVERIFIED (kaliuresis led much of it) | W2 Tarcles by name; W3 Product (Cost×Area) and a Looping tiebreaker; W4 production cabinet with conduits; W5 Amarms (Area − Arms); W6 polymer output with Height > Period > Cycles; W7 Critellium finale with THREE metrics, best 2 counting. |
| 2025 | Haxton | events.critelli.technology + Discord ([intro](https://events.critelli.technology/OM2025_Intro), [pages](https://events.critelli.technology/collection/om2025)) | 300/(rank+29) | UNVERIFIED | "The Alchemical Symposium" (sessions framed as talks). S1 Latency and Area@1; S2 Sum with NO tiebreakers; S3 trackless-constrained cost; S4 special-rules universal duplicator; S5 MechA; S6 budget cap (cost ≤ 1000) cycles race; S7 Rate > Cost > Area@∞; S8 Memory Lane, a design-your-own-encoding computation finale (encode a 5-atom fire/salt stick, 32 cases, into a 2-atom metal molecule, 36 cases, and decode it back). |
| 2026 | Kazyan | events.critelli.technology + Discord ([intro](https://events.critelli.technology/4d281c19a003d1999e05ce2d8e6c4415)) | 300/(rank+29), two metrics/puzzle, **two lowest-scoring weeks dropped** | ran Mar 6 – May 17, 2026 | 10 puzzles (Snow Amputation → One Last Favor). Mods/external editors allowed during development; final solution must run in the vanilla game. Per-week metrics UNVERIFIED (hash-URL pages not scraped). |

### 3.2 Opus Magnum Weeklies (2022–2026, ongoing)

Community-authored off-season puzzles (rotating "Weeklies Gang"), hosted on
the event site + Discord, **no cumulative score**
([biggieblog](https://biggieblog.com/battling-the-entire-world-in-opus-magnum/);
collections [OM2022Weeklies](https://events.critelli.technology/collection/OM2022Weeklies)
… OM2026Weeklies). This is where the most exotic metrics appear; highlights:

- Area **maximization** with a no-unnecessary-parts rule (2022 W1); the
  "Puzzle Creator vs the World" megateam format (2022 W4 Nightmare Fuel — the
  world beat the author 28 vs 31 cycles); Vintage Instructions (2022 W11);
  floor-clamped max(Cost,100) (2022 W13).
- Overlap Area (2023 W1); Pivots-executed (2023 W3); Cycles×Reagents
  (2023 W4); a design-your-own-reagent generator (2023 W2); a "never grab
  mors" constraint (2023 W6).
- Period/Rate idle-ratio maximization (2024 W1); Bounding Hexagon as a
  primary (2024 W3); per-element grab counts (2024 W4); the first
  Pareto-frontier-as-score metric (2024 W5 Sophick Mercury); a
  max-over-25-test-cases computation scalar (2024 W8 Look-And-Say).
- Trackless Instructions > Area@INF (2025 W2); No Pistons (2025 W6);
  Sum + 50×distinct-instruction-types (2025 W11); Start Height (2026 W1).
- Every season ends with a vote-scored **Aesthetics / Shitpost** week.

### 3.3 Speed Solve seasons

Sprint format: category 1 is literally **wall-clock time to solve/submit**
(server upload time), category 2 a normal metric under a 1–2 hour hard limit
([collections](https://events.critelli.technology/collection/speedsolve2),
[season 3](https://events.critelli.technology/collection/speedsolve3);
season 1 presumed to exist but not listed — UNVERIFIED). Speed Solve 2.4
even used time-to-submission as a *tiebreaker* on a Sum category — notable
because the annual tournament explicitly refuses timestamps as tiebreakers.

### 3.4 Whose Ad-Hoc Tournament (WAHT, 2024 & 2025)

Community side event ([2024](https://events.critelli.technology/collection/2024_waht),
[2025](https://events.critelli.technology/collection/2025_waht)); the 2025
edition displaced the main tournament's Week 0. Organizer UNVERIFIED (name
and timing suggest the player "who"). WAHT 2024 was Christmas-themed
(W1 Tinsel — Period > Cycles > Instructions; W2 Children's Toys —
Cycles/triplex > (Cost − 20·triplex) > Cycles). WAHT 2025 was a single
puzzle, "Silver Apple of Discord", with the two-phase adversarial metric of
§1.6 (the page notes "Submissions will not be directly evaluated").

### 3.5 Other events

- **Trixie Kagami's Tournament Takeover** (2026) — four-puzzle narrative
  event ([collection](https://events.critelli.technology/collection/tournamenttakeover));
  metrics include Number of Tracks as a tiebreaker and a
  Cycles + Steady-State Area composite. Host identity UNVERIFIED.
- **The Method of the Salt of Saturn** — five-exercise series, distinctive
  for **four** metric categories per exercise (most events use two),
  including 5ISum = G+C+5I
  ([collection](https://events.critelli.technology/collection/salt%20of%20saturn)).
  Organizer UNVERIFIED.
- **Alchademy** — narrative series with orientation constraints; metrics
  UNVERIFIED ([collection](https://events.critelli.technology/collection/444)).
- **DarkBrick's Miscellaneous Events** — puzzle pages written in an
  in-fiction cipher, *including the metrics*; decoding is part of the event.
  Actual metrics UNVERIFIED
  ([collection](https://events.critelli.technology/collection/darkbrick)).
- **Overlap community challenges** — e.g. a Nov 2021 perfect-throughput
  overlap challenge; overlap has its own cycles/area/cost leaderboard
  variants ([biggieblog](https://biggieblog.com/playing-opus-magnum-by-different-rules/)).
- **"12 Days of Crafting"** — NOT FOUND. No such Opus Magnum event surfaced
  in any search; UNVERIFIED / possibly misremembered. Nearest matches: the
  Christmas-themed WAHT 2024, or a Discord-only event that never got a web
  page.

---

## 4. Implications for the harness

### 4.1 What the repo computes today

The solver-comparison harness (branch `harness`; `harness/SPEC.md`,
`harness/validate.py`, `harness/bench.py`) replays a plan JSON against a
puzzle JSON and reports two numbers per solver arm:

- **Plan length** = number of non-`wait` instructions — the benchmark
  metric (`harness/README.md`, SPEC §4).
- **Makespan** — implicit: the plan must complete every product by some
  `t ≤ t_max`; the horizon `t_max` is a puzzle parameter, and the clingo arm
  additionally proves makespan optimality by UNSAT at `t_max − 1`
  (`NOTES.md` results table).

The model is deliberately simplified (SPEC §6): **sequential arms** (one
instruction per timestep across all arms — so "makespan" is *not* the game's
cycles metric, which executes all arm tapes in parallel), endpoint-only
collision (no swept arcs), bounded board and input pools, one product copy
with a non-consuming output, part subset {arm, calcifier, bonder}, no
pistons/track/tape loops/pivots.

### 4.2 Cheap now (no model changes)

| Metric | Why cheap | Caveat |
|---|---|---|
| Instructions (I) | Already the benchmark metric (non-wait plan length). Matches the game definition because the model has no repeat/reset instructions to expand and waits are excluded ([decode.c L1351-1361](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/decode.c#L1351-L1361)). | — |
| Cost (G) | Pure function of the placement list + a price table (arm-1 = 20, bonder = 10, calcification = 10 per omsim's table, [decode.c L1298-1349](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/decode.c#L1298-L1349)); every part in a plan JSON has a known type. A ~10-line addition to `validate.py`/`bench.py`. | Table only matters more when pistons/track/multi-arms get modeled. |
| Number of arms, parts-of-type | Count the placements. | — |
| Latency / completion cycle | The validator already detects product completion at a specific `t`; report it. With one product copy, latency = makespan. | Sequential-arm timestep ≠ game cycle. |
| Trackless (T) | Vacuously true — track isn't modeled. Worth reporting only once track exists. | — |
| Overlap (O) | Vacuously false — the validator enforces footprint disjointness (SPEC §4 "Footprint disjointness"), which *is* the no-overlap rule. An overlap-allowed mode = relaxing that check and counting duplicate-hex marks in omsim's part order. | — |
| Sum / weighted scalars / products over {G, I, makespan} | Trivial arithmetic once components exist (§2.2). | Measure-point consistency once @∞ exists. |

### 4.3 Needs model extensions

Ordered by increasing model surgery:

1. **Area (A) and the geometry family (H, W, B).** Needs a "used hex"
   accumulator in the validator: initial part footprints + every hex an atom
   ever occupies + arm-axis hexes each step. Two gaps vs the game: (a) the
   model checks endpoint-only collision and so doesn't know **rotation sweep
   hexes** — omsim adds 3 extra hexes per swing for length-2 arms and 6 for
   length-3 ([sim.c L829-864](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/sim.c#L829-L864));
   with only length-1 arms currently in the instances this gap is zero, and
   precomputed swept-arc tables would close it in general (already listed in
   NOTES.md as the swept-collision fix). (b) The board is bounded, so area
   is capped at the disc size (19 hexes at radius 2) — fine for these
   instances. Given the used-hex set, H/W/B are the closed-form projections
   of §1.2 (height = max−min+1 per axis, min of three; width via the
   doubled projections, max−min+2, reported as `width*2` to stay integral;
   bounding hex via the minimum-hexagon formula).
2. **True cycles (C).** Requires **parallel arm execution** — all arms fire
   one tape slot per cycle — which NOTES.md already identifies as the main
   model-gap item ("parallel arm execution ... removes the
   sequential-interleaving symmetry"). Until then, makespan is a defensible
   stand-in but should be labeled `makespan`, not `cycles`.
3. **Six-output victory semantics.** The game's cycle/area scores are
   defined at 6×output_scale products with a consuming output
   ([decode.c L1294](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/decode.c#L1294));
   the harness builds one non-consumed copy. Needed for any metric to be
   comparable with real leaderboard numbers, and a prerequisite for rate.
4. **Constraint flags as first-class category modifiers.** Once track/
   pistons exist: trackless = no track hexes; piston bans, budget caps and
   clamped metrics (§2.3) are pure post-hoc checks on plan/score.
5. **Rate (R) and Looping (L).** Needs tape loops (modular-time encoding —
   also on the NOTES.md roadmap) plus **steady-state detection**: hash the
   full state (arm directions/held atoms, atom grid, per-output counts) at
   tape-period-aligned cycles and detect repetition, omsim-style
   ([steady-state.c L239-507](https://github.com/ianh/omsim/blob/930c5dc798b4c6c59226c706d9e26e9e584efd11/steady-state.c#L239-L507)).
   On a bounded board with bounded pools there are no escaping chains, so
   the exact-repeat check suffices (no chain-atom translation tracking).
   Report rate as loop cycles ÷ loop outputs with the leaderboard's
   `ceil(100·x)/100` rounding. Note: a *solver* optimizing rate is a much
   deeper change (optimize a ratio over a periodic schedule) than a
   *validator* measuring it.
6. **@∞ geometry and A′/A″.** Only meaningful with unbounded chains
   (polymers), which need an unbounded board — out of scope for the current
   bounded-disc model; omsim's linear/quadratic growth classification
   (§2.4) is the reference if it ever lands.
7. **Out-of-band metrics** (wall-clock, votes, field-relative Pareto
   scoring) — `bench.py` already measures wall time per adapter, which is
   Speed Solve's category 1; frontier scoring across solver arms would be a
   bench-level feature (compute the Pareto frontier of, say, {G, I,
   makespan} across all arms' plans), not a validator feature.

### 4.4 Suggested implementation order

1. **Cost** + **latency/completion-cycle reporting** + rename the time
   metric to `makespan` (a day of work, all in `validate.py`/`bench.py`,
   no encoding changes).
2. **Used-hex area** + **H/W/B** from the same accumulator (validator-only;
   exact for length-1 arms).
3. **Composites** (Sum, X, weighted scalars) + a small metric-expression
   layer so bench tables can declare categories like `GC` = minimize G,
   tiebreak C — mirroring the leaderboard's category naming.
4. **Parallel arms + 6-output victory** (encoding + validator) → true
   cycles; then re-derive area/geometry under real semantics.
5. **Track + pistons** → trackless flag, real cost variety, Tarcles-style
   mechanism metrics.
6. **Tape loops + steady-state detection** → Looping, Rate, Period; this
   unlocks the whole @∞ tier except unbounded-chain cases.
7. Skip A′/A″, conduits, and production cabinets until there's a concrete
   need; they are the rarest tiers (§1.2, §1.5) and the most simulator
   surgery.

---

## 5. Source index and unverified items

Primary sources used throughout:

- omsim source at commit `930c5dc` — https://github.com/ianh/omsim
  (all `verifier.c` / `sim.c` / `decode.c` / `steady-state.c` /
  `test-against-leaderboard.py` / `main.c` permalinks above are pinned to
  that SHA).
- zlbb leaderboard help — https://zlbb.faendir.com/help (source:
  [HelpView.tsx](https://github.com/F43nd1r/zachtronics-leaderboard-bot/blob/master/web/src/views/om/help/HelpView.tsx));
  category JSON — https://zlbb.faendir.com/om/categories; bot model classes
  [OmMetric.kt](https://raw.githubusercontent.com/F43nd1r/zachtronics-leaderboard-bot/master/src/main/kotlin/com/faendir/zachtronics/bot/om/model/OmMetric.kt),
  [OmScoreManifold.kt](https://raw.githubusercontent.com/F43nd1r/zachtronics-leaderboard-bot/master/src/main/kotlin/com/faendir/zachtronics/bot/om/model/OmScoreManifold.kt),
  [OmCategory.kt](https://raw.githubusercontent.com/F43nd1r/zachtronics-leaderboard-bot/master/src/main/kotlin/com/faendir/zachtronics/bot/om/model/OmCategory.kt),
  [OmRedditWikiGenerator.kt](https://github.com/F43nd1r/zachtronics-leaderboard-bot/blob/master/src/main/kotlin/com/faendir/zachtronics/bot/om/repository/OmRedditWikiGenerator.kt).
- Event archive — https://events.critelli.technology/ (per-week puzzle pages
  and collections as cited in §3).
- biggiemac42's blog — https://biggieblog.com/tracking-the-global-opus-magnum-records/,
  https://biggieblog.com/recapping-the-2022-opus-magnum-tournament/,
  https://biggieblog.com/recapping-the-2023-opus-magnum-tournament/,
  https://biggieblog.com/introducing-mecha-the-opus-magnum-metric-of-your-nightmares/,
  https://biggieblog.com/playing-opus-magnum-by-different-rules/,
  https://biggieblog.com/battling-the-entire-world-in-opus-magnum/.
- 2020 tournament rules doc —
  https://docs.google.com/document/d/1Et7kFFcWYdhgPWgSBZnjZ_Mpjub4qBF0i_pQGu8uiNs/;
  scoring worked example — https://pastebin.com/MZsxkZBL.
- Tournament master collection —
  https://steamcommunity.com/sharedfiles/filedetails/?id=2597159271;
  participant recap — https://ermsta.com/posts/20240506.

Unverified queue (kept explicit; do not treat as fact):

- **om-leaderboard.dev** as a former leaderboard home — the domain does not
  resolve (DNS NXDOMAIN, 2026-07-07) and no evidence ties it to the project.
- The rendered r/opus_magnum wiki page (reddit unreachable; content is
  determined by the cited generator source).
- README contents of F43nd1r/om-leaderboard and
  12345ieee/om-leaderboard-archive.
- 2019 per-week metric categories; 2020 W7/W8 categories; the 2021 full
  category list; exact 2022 scoring wording; the week of the 2020
  "Mechanism Cost" category.
- 2024 and 2025 tournament champions; 2026 per-week metrics/results.
- Speed Solve season 1; Alchademy metrics; DarkBrick's decoded metrics;
  "Surrender Flare Salt Modifications" details; WAHT organizer; "Trixie
  Kagami" and Salt of Saturn organizer identities.
- **"12 Days of Crafting"** — existence unconfirmed; no such event found.
- "G = gold" as the origin of the cost letter (biggieblog says cost is in
  Guilders; the gold gloss is common usage but unconfirmed).
- All reddit.com announcement-thread bodies (2019–2026), cited by URL only.
