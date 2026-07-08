import { readFileSync, readdirSync } from 'node:fs';
import { repoPath } from './repo';

export interface PuzzleInfo {
  file: string;
  name: string;
  description: string | null;
  boardRadius: number | null;
  tMax: number | null;
  reagents: number;
  products: number;
  parts: string[];
  raw: string;
}

interface PartLike {
  type?: string;
  id?: string;
  length?: number;
}

/** All canonical puzzles from harness/puzzles/*.json. */
export function loadPuzzles(): PuzzleInfo[] {
  const dir = repoPath('harness', 'puzzles');
  const files = readdirSync(dir).filter((f) => f.endsWith('.json')).sort();
  return files.map((file) => {
    const raw = readFileSync(repoPath('harness', 'puzzles', file), 'utf-8');
    const data = JSON.parse(raw) as Record<string, unknown>;
    const parts = Array.isArray(data.parts)
      ? (data.parts as PartLike[]).map((p) => {
          if (typeof p === 'string') return p;
          const len = p.length !== undefined ? `, length ${p.length}` : '';
          return `${p.type ?? 'part'} (${p.id ?? '?'}${len})`;
        })
      : [];
    return {
      file,
      name: typeof data.name === 'string' ? data.name : file.replace(/\.json$/, ''),
      description: typeof data.description === 'string' ? data.description : null,
      boardRadius: typeof data.board_radius === 'number' ? data.board_radius : null,
      tMax: typeof data.t_max === 'number' ? data.t_max : null,
      reagents: Array.isArray(data.reagents) ? data.reagents.length : 0,
      products: Array.isArray(data.products) ? data.products.length : 0,
      parts,
      raw: JSON.stringify(data, null, 2),
    };
  });
}
