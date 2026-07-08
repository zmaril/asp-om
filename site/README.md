# asp-om site

A static [Astro v5](https://astro.build) site presenting everything in this
repo: the five-way solver bake-off, the Opus Magnum metrics survey, the
self-play stack (learning curve + self-competition leaderboard), per-solver
lab notes, and the harness spec/puzzles.

## How content stays in sync with the repo

Nothing is hand-copied. All content is ingested **at build time** from the
repo one level up:

- `docs/*.md` — content collection (`docs`), rendered on `/comparison` and
  `/docs/<slug>`.
- `NOTES.md`, `picat/NOTES.md`, `z3/NOTES.md`, `sat/NOTES.md`,
  `minizinc/NOTES.md` — collection (`notes`) → `/solvers/<slug>`.
- `picat/results/*.md`, `minizinc/results/*.md`, `z3/results*.md`,
  `sat/results*.md` — collection (`results`), attached to the solver pages.
- `harness/SPEC.md` + `harness/puzzles/*.json` — `/puzzles`.
- `selfplay/expert_iteration/runs/*/curve.csv` — parsed into the SVG
  learning-curve chart on `/selfplay` (`src/lib/selfplay.ts`).
- `selfplay/leaderboard/incumbents.json` — the self-competition leaderboard
  tables on `/selfplay`.
- `docs/metrics-survey.md` §1.1–1.6 pipe tables — parsed into the searchable
  metric catalog on `/metrics` (`src/lib/metrics.ts`).

Edit the source files in the repo and rebuild; the site follows.

## Develop & build

```sh
cd site
npm install
npm run dev      # local dev server
npm run build    # emits static output to site/dist/
npm run preview  # serve the built output locally
```

Node 20+ (built and verified with Node 22). No other tooling required; all
JS/TS tooling is self-contained under `site/`.

The build does not depend on the working directory: the Astro project root
is pinned in `astro.config.mjs`, and every repo-file read resolves the repo
root from the module's own location (`src/lib/repo.ts`). Building via
`npm --prefix site run build` from the repo root works the same as
`cd site && npm run build`.

## Deploy to Cloudflare

The site is **fully static** — every page is prerendered at build time and
`dist/` is plain HTML/assets. **No deploy adapter is needed or wanted**; in
particular do not add `@astrojs/cloudflare`. The build fails on purpose
(`scripts/assert-static.mjs`, run as `postbuild`) if the output ever
contains a `_worker.js`, because server-rendering the pages in a worker
breaks the build-time `node:fs` reads.

### Workers Builds (current setup)

The Cloudflare project is a **Workers** project built with Workers Builds.
`wrangler.jsonc` declares an **assets-only Worker**: `assets.directory`
points at `./dist` and there is **no `main`**, so `wrangler deploy`
publishes plain static assets — no Worker script, no runtime code. Do not
let the dashboard's Astro framework detection add `@astrojs/cloudflare`;
the wrangler config is already the complete deploy story.

Dashboard → Workers & Pages → asp-om → Settings → Build:

- **Root directory**: `site`
- **Build command**: `npm run build`
- **Deploy command**: `npx wrangler deploy` (reads `site/wrangler.jsonc`
  and uploads `dist/` as static assets)
- **Environment variable**: `NODE_VERSION=22`
- Keep access to files outside the root directory enabled if the UI asks —
  the build reads markdown/JSON/CSV from the repo root (one level above
  `site/`).

To sanity-check the deploy config locally without credentials:

```sh
cd site && npx wrangler deploy --dry-run
```

### Classic Pages project (alternative)

Also works; no wrangler config involved:

- **Framework preset**: Astro (no adapter — the output is static files)
- **Build command**: `npm run build`
- **Build output directory**: `dist` (relative to the root directory)
- **Root directory**: `site`
- **Environment variable**: `NODE_VERSION=22`

### Direct upload from your machine

```sh
cd site
npm install
npm run build
npx wrangler deploy          # Workers project (uses wrangler.jsonc)
# or, for a classic Pages project:
npx wrangler pages deploy dist --project-name=<your-pages-project>
```

`wrangler` will prompt for login the first time; no secrets are stored in
this repo.
