// Fails the build unless every page was prerendered into dist/.
//
// This site deploys to Cloudflare as plain prerendered HTML/assets (see
// wrangler.jsonc: assets-only Worker, no main). Cloudflare's Astro
// framework preset has been observed injecting the @astrojs/cloudflare
// adapter; that is tolerated — every page still prerenders thanks to
// `export const prerender = true`, and public/.assetsignore keeps the
// emitted _worker.js out of the uploaded assets (wrangler otherwise
// hard-errors on it) — but the prerendered HTML must all be there.
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const dist = fileURLToPath(new URL('../dist', import.meta.url));

// Fixed routes plus one representative per dynamic route family
// (docs/[slug] from docs/*.md, solvers/[slug] from src/lib/solvers.ts).
const expected = [
  'index.html',
  'comparison/index.html',
  'metrics/index.html',
  'puzzles/index.html',
  'selfplay/index.html',
  'solvers/index.html',
  'solvers/clingo/index.html',
  'solvers/picat/index.html',
  'solvers/z3/index.html',
  'solvers/sat/index.html',
  'solvers/minizinc/index.html',
  'docs/metrics-survey/index.html',
  'docs/solver-comparison/index.html',
  'docs/self-play-design/index.html',
  '.assetsignore',
];

const missing = expected.filter((f) => !existsSync(path.join(dist, f)));
if (missing.length > 0) {
  console.error('assert-static: build output is missing prerendered files:');
  for (const f of missing) console.error(`  - dist/${f}`);
  process.exit(1);
}

if (existsSync(path.join(dist, '_worker.js'))) {
  console.warn(
    'assert-static: WARNING — dist/_worker.js exists (a deploy adapter was ' +
      'applied). All pages are prerendered and .assetsignore excludes the ' +
      'worker bundle from the asset upload, so the deploy stays static, ' +
      'but consider removing the adapter from the build.',
  );
}

console.log(`assert-static: all ${expected.length} expected prerendered files present in dist/`);
