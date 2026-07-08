// @ts-check
import { defineConfig } from 'astro/config';

// Static site for Cloudflare Pages.
// All content is ingested at build time from the repo one level up
// (docs/, */NOTES.md, harness/, selfplay/) — see src/content.config.ts
// and src/lib/.
export default defineConfig({
  output: 'static',
  trailingSlash: 'ignore',
});
