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

## Deploy to Cloudflare Pages (by hand)

The site is **fully static** — every page is prerendered at build time and
`dist/` is plain HTML/assets. **No deploy adapter is needed or wanted**; in
particular do not add `@astrojs/cloudflare`. The build fails on purpose
(`scripts/assert-static.mjs`, run as `postbuild`) if the output ever
contains a `_worker.js`, because server-rendering the pages in a worker
breaks the build-time `node:fs` reads.

Option A — Git integration (recommended):

1. Cloudflare dashboard → Workers & Pages → Create → Pages →
   "Connect to Git" and pick this repository.
2. Settings:
   - **Framework preset**: Astro (no adapter — the output is static files)
   - **Build command**: `npm run build`
   - **Build output directory**: `dist` (with **Root directory** set to
     `site` this field is relative to `site/`, i.e. `site/dist` in repo
     terms)
   - **Root directory**: `site`
   - **Environment variable**: `NODE_VERSION=22`
3. Save and deploy. Every push to the production branch redeploys.

Note: the build reads markdown/JSON/CSV from the repo root (one level above
`site/`), so keep "Include files outside root directory" enabled (it is the
default) if the UI asks.

Option B — direct upload from your machine:

```sh
cd site
npm install
npm run build
npx wrangler pages deploy dist --project-name=<your-pages-project>
```

`wrangler` will prompt for login the first time; no secrets are stored in
this repo.
