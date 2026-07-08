import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { REPO_ROOT, repoPath } from './lib/repo';

// Every collection reads straight from the repo working tree (one level
// above site/), so the site content always derives from the repo files.
// Bases are absolute (resolved from this module's location, see
// src/lib/repo.ts) so the build works no matter which directory the
// Astro CLI is invoked from — CI systems like Cloudflare Pages do not
// necessarily run the build with site/ as the working directory.

/** The three long-form docs: solver-comparison, metrics-survey, self-play-design. */
const docs = defineCollection({
  loader: glob({ pattern: '*.md', base: repoPath('docs') }),
});

/** Each solver arm's NOTES.md (clingo's lives at the repo root). */
const notes = defineCollection({
  loader: glob({
    pattern: ['NOTES.md', '{picat,z3,sat,minizinc}/NOTES.md'],
    base: REPO_ROOT,
  }),
});

/** Per-arm results/benchmark markdown files. */
const results = defineCollection({
  loader: glob({
    pattern: [
      'picat/results/*.md',
      'minizinc/results/*.md',
      'z3/results*.md',
      'sat/results*.md',
    ],
    base: REPO_ROOT,
  }),
});

/** The harness spec. */
const harness = defineCollection({
  loader: glob({ pattern: ['SPEC.md', 'README.md'], base: repoPath('harness') }),
});

/** The self-competition leaderboard page + expert-iteration README. */
const selfplay = defineCollection({
  loader: glob({
    pattern: ['leaderboard/LEADERBOARD.md', 'expert_iteration/README.md'],
    base: repoPath('selfplay'),
  }),
});

export const collections = { docs, notes, results, harness, selfplay };
