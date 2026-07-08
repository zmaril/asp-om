import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';

// Every collection reads straight from the repo working tree (one level
// above site/), so the site content always derives from the repo files.

/** The three long-form docs: solver-comparison, metrics-survey, self-play-design. */
const docs = defineCollection({
  loader: glob({ pattern: '*.md', base: '../docs' }),
});

/** Each solver arm's NOTES.md (clingo's lives at the repo root). */
const notes = defineCollection({
  loader: glob({
    pattern: ['NOTES.md', '{picat,z3,sat,minizinc}/NOTES.md'],
    base: '..',
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
    base: '..',
  }),
});

/** The harness spec. */
const harness = defineCollection({
  loader: glob({ pattern: ['SPEC.md', 'README.md'], base: '../harness' }),
});

/** The self-competition leaderboard page + expert-iteration README. */
const selfplay = defineCollection({
  loader: glob({
    pattern: ['leaderboard/LEADERBOARD.md', 'expert_iteration/README.md'],
    base: '../selfplay',
  }),
});

export const collections = { docs, notes, results, harness, selfplay };
