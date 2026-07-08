// Fails the build unless dist/ is a plain static site.
//
// This site must deploy to Cloudflare Pages as prerendered HTML/assets only.
// If a deploy adapter (e.g. @astrojs/cloudflare) ever sneaks into the build
// — the CF framework preset has been observed injecting one — the output
// grows a _worker.js and pages render at request time inside a worker,
// where the node:fs reads in src/lib/* break. Catch that at build time.
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const dist = fileURLToPath(new URL('../dist', import.meta.url));

const problems = [];
if (!existsSync(path.join(dist, 'index.html'))) {
  problems.push('dist/index.html is missing — pages were not prerendered');
}
for (const artifact of ['_worker.js', '_routes.json']) {
  if (existsSync(path.join(dist, artifact))) {
    problems.push(
      `dist/${artifact} exists — a server adapter was applied; ` +
        'this site must build fully static (output: "static", no adapter)',
    );
  }
}

if (problems.length > 0) {
  console.error('assert-static: build output is not fully static:');
  for (const p of problems) console.error(`  - ${p}`);
  process.exit(1);
}
console.log('assert-static: dist/ is fully static (no _worker.js, index.html present)');
