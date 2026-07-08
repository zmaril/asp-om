// @ts-check
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'astro/config';

// Fully static site for Cloudflare Pages. All content is ingested at build
// time from the repo one level up (docs/, */NOTES.md, harness/, selfplay/) —
// see src/content.config.ts and src/lib/.
//
// Deliberately NO deploy adapter (in particular no @astrojs/cloudflare):
// every page is prerendered to plain HTML at build time, and the fs reads in
// src/lib/* only ever run during the build, never in a worker. The deployed
// dist/ must contain no _worker.js. On Cloudflare Pages use the Astro
// framework preset with build output `dist` — no adapter is needed.
export default defineConfig({
  // Pin the project root to this file's directory so the build is
  // independent of the CLI's working directory.
  root: fileURLToPath(new URL('.', import.meta.url)),
  output: 'static',
  trailingSlash: 'ignore',
});
