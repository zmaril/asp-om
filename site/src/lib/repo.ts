import { fileURLToPath } from 'node:url';
import path from 'node:path';

/** Absolute path to the repo root (one level above site/). */
export const REPO_ROOT = fileURLToPath(new URL('../../..', import.meta.url));

export function repoPath(...parts: string[]): string {
  return path.join(REPO_ROOT, ...parts);
}
