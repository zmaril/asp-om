/** Tiny helpers for reading pipe tables + inline markdown out of the
 * repo's markdown docs at build time. Deliberately minimal — just enough
 * for the metric catalog cards. */

export interface PipeTable {
  headers: string[];
  rows: string[][];
}

/** Split a pipe-table line into cells, honouring `\|` escapes. */
function splitRow(line: string): string[] {
  const cells: string[] = [];
  let cur = '';
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '\\' && line[i + 1] === '|') {
      cur += '|';
      i++;
    } else if (ch === '|') {
      cells.push(cur.trim());
      cur = '';
    } else {
      cur += ch;
    }
  }
  cells.push(cur.trim());
  // Leading/trailing pipes produce empty first/last cells.
  if (cells.length && cells[0] === '') cells.shift();
  if (cells.length && cells[cells.length - 1] === '') cells.pop();
  return cells;
}

function isSeparatorRow(cells: string[]): boolean {
  return cells.length > 0 && cells.every((c) => /^:?-{2,}:?$/.test(c));
}

/** First pipe table found in `lines` starting at `from`. */
export function firstTableAfter(lines: string[], from: number, until: number): PipeTable | null {
  for (let i = from; i < until - 1; i++) {
    const line = lines[i]!;
    if (!line.trimStart().startsWith('|')) continue;
    const headers = splitRow(line.trim());
    const sep = splitRow((lines[i + 1] ?? '').trim());
    if (!isSeparatorRow(sep)) continue;
    const rows: string[][] = [];
    for (let j = i + 2; j < until; j++) {
      const l = (lines[j] ?? '').trim();
      if (!l.startsWith('|')) break;
      rows.push(splitRow(l));
    }
    return { headers, rows };
  }
  return null;
}

function escapeHtml(s: string): string {
  return s
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

/** Render inline markdown (code spans, links, bold, italics) to HTML. */
export function inlineMdToHtml(md: string): string {
  let s = escapeHtml(md);
  // code spans first so their contents are left alone afterwards
  s = s.replace(/`([^`]+)`/g, (_m, c: string) => `<code>${c}</code>`);
  // links
  s = s.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    (_m, text: string, href: string) =>
      `<a href="${href}" rel="noopener">${text}</a>`,
  );
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  return s;
}

/** Strip inline markdown to plain text (for search indexing). */
export function inlineMdToText(md: string): string {
  return md
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1');
}
