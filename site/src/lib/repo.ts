import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

// Locate the repo root by walking up from this module's real location on
// disk until we find unmistakable repo-root markers. A fixed relative hop
// (e.g. `new URL('../../..', import.meta.url)`) is NOT safe here: after
// bundling, import.meta.url points at the compiled chunk, whose directory
// depth differs between dev (`site/src/lib/`), a plain static build
// (`site/dist/chunks/`), and adapter builds (`site/dist/_worker.js/chunks/`).
// The Cloudflare Pages failure was exactly that: the chunk sat one level
// deeper, so the fixed hop resolved to `site/` instead of the repo root.
// Walking up until the markers match is depth- and CWD-independent.
function findRepoRoot(startDir: string): string {
  let dir = startDir;
  for (;;) {
    if (
      existsSync(path.join(dir, 'harness', 'puzzles')) &&
      existsSync(path.join(dir, 'docs', 'metrics-survey.md'))
    ) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      throw new Error(
        `Could not locate the asp-om repo root walking up from ${startDir} ` +
          '(expected to find harness/puzzles and docs/metrics-survey.md)',
      );
    }
    dir = parent;
  }
}

/** Absolute path to the repo root (the directory containing site/). */
export const REPO_ROOT = findRepoRoot(
  path.dirname(fileURLToPath(import.meta.url)),
);

export function repoPath(...parts: string[]): string {
  return path.join(REPO_ROOT, ...parts);
}
