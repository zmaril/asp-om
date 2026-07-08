import { readFileSync } from 'node:fs';
import { repoPath } from './repo';
import { firstTableAfter, inlineMdToHtml, inlineMdToText } from './markdown';

export type Rarity = 'core' | 'common' | 'niche' | 'one-off';

export interface MetricEntry {
  name: string;
  nameHtml: string;
  letter: string | null;
  definitionHtml: string;
  usedHtml: string | null;
  rarity: Rarity;
  rarityRaw: string;
  group: string;
  searchText: string;
}

interface SectionSpec {
  headingPrefix: string;
  group: string;
}

const SECTIONS: SectionSpec[] = [
  { headingPrefix: '### 1.1', group: 'Official in-game' },
  { headingPrefix: '### 1.2', group: 'Leaderboard values' },
  { headingPrefix: '### 1.3', group: 'Boolean flags' },
  { headingPrefix: '### 1.4', group: 'Composites' },
  { headingPrefix: '### 1.5', group: 'omsim-only' },
  { headingPrefix: '### 1.6', group: 'Tournament-only' },
];

function normalizeRarity(raw: string): Rarity {
  const t = raw.toLowerCase();
  if (t.includes('core')) return 'core';
  if (t.includes('common')) return 'common';
  if (t.includes('one-off')) return 'one-off';
  return 'niche';
}

function findColumn(headers: string[], candidates: string[]): number {
  const lower = headers.map((h) => h.toLowerCase());
  for (const c of candidates) {
    const i = lower.findIndex((h) => h.includes(c));
    if (i !== -1) return i;
  }
  return -1;
}

/** Parse the metric catalog (survey §1.1–1.6) out of docs/metrics-survey.md. */
export function loadMetricCatalog(): MetricEntry[] {
  const md = readFileSync(repoPath('docs', 'metrics-survey.md'), 'utf-8');
  const lines = md.split('\n');

  // Section boundaries: each entry ends at the next '#'-heading of depth <= 3.
  const headingIdx: number[] = [];
  lines.forEach((l, i) => {
    if (/^#{1,3} /.test(l)) headingIdx.push(i);
  });

  const entries: MetricEntry[] = [];
  for (const spec of SECTIONS) {
    const start = lines.findIndex((l) => l.startsWith(spec.headingPrefix));
    if (start === -1) continue;
    const end = headingIdx.find((i) => i > start) !== undefined
      ? headingIdx.filter((i) => i > start)[0]!
      : lines.length;
    const table = firstTableAfter(lines, start + 1, end);
    if (!table) continue;

    const nameCol = 0;
    const letterCol = findColumn(table.headers, ['letter', 'code']);
    const defCol = findColumn(table.headers, ['definition']);
    const usedCol = findColumn(table.headers, ['used', 'first/known uses']);
    const rarityCol = findColumn(table.headers, ['rarity']);
    if (defCol === -1 || rarityCol === -1) continue;

    for (const row of table.rows) {
      const rawName = row[nameCol] ?? '';
      const def = row[defCol] ?? '';
      const rarityRaw = row[rarityCol] ?? '';
      if (!rawName || !def) continue;
      const name = inlineMdToText(rawName);
      entries.push({
        name,
        nameHtml: inlineMdToHtml(rawName),
        letter: letterCol !== -1 && row[letterCol] && row[letterCol] !== '—'
          ? inlineMdToText(row[letterCol]!)
          : null,
        definitionHtml: inlineMdToHtml(def),
        usedHtml: usedCol !== -1 && row[usedCol] ? inlineMdToHtml(row[usedCol]!) : null,
        rarity: normalizeRarity(rarityRaw),
        rarityRaw: inlineMdToText(rarityRaw),
        group: spec.group,
        searchText: [name, inlineMdToText(def), spec.group, rarityRaw]
          .join(' ')
          .toLowerCase(),
      });
    }
  }
  return entries;
}
