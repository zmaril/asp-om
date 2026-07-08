import { readFileSync, existsSync } from 'node:fs';
import { repoPath } from './repo';

export interface CurvePoint {
  iteration: number;
  validity: number;
}

export interface CurveSeries {
  run: string;
  puzzle: string;
  label: string;
  points: CurvePoint[];
}

/** Learning curves from selfplay/expert_iteration/runs/<run>/curve.csv. */
export function loadLearningCurves(): CurveSeries[] {
  const runs = ['demo', 'random-control'];
  const series: CurveSeries[] = [];
  for (const run of runs) {
    const file = repoPath('selfplay', 'expert_iteration', 'runs', run, 'curve.csv');
    if (!existsSync(file)) continue;
    const lines = readFileSync(file, 'utf-8').trim().split('\n');
    const headers = lines[0]!.split(',');
    const iterCol = headers.indexOf('iteration');
    const puzzleCol = headers.indexOf('puzzle');
    const validityCol = headers.indexOf('window_validity');
    const byPuzzle = new Map<string, CurvePoint[]>();
    for (const line of lines.slice(1)) {
      const cells = line.split(',');
      const puzzle = cells[puzzleCol]!;
      const pt = {
        iteration: Number(cells[iterCol]),
        validity: Number(cells[validityCol]),
      };
      if (!byPuzzle.has(puzzle)) byPuzzle.set(puzzle, []);
      byPuzzle.get(puzzle)!.push(pt);
    }
    for (const [puzzle, points] of byPuzzle) {
      series.push({
        run,
        puzzle,
        label: `${run === 'demo' ? 'expert iteration' : 'random control'} · ${puzzle}`,
        points,
      });
    }
  }
  return series;
}

export interface IncumbentCell {
  metric: string;
  score: number | string;
  source: string;
  submission: number;
}

export interface PuzzleBoard {
  puzzle: string;
  cells: IncumbentCell[];
}

interface IncumbentRecord {
  score: number | string;
  source: string;
  submission: number;
}

/** The self-competition incumbent store (selfplay/leaderboard/incumbents.json). */
export function loadLeaderboard(): PuzzleBoard[] {
  const file = repoPath('selfplay', 'leaderboard', 'incumbents.json');
  const data = JSON.parse(readFileSync(file, 'utf-8')) as {
    records: Record<string, Record<string, IncumbentRecord>>;
  };
  const boards: PuzzleBoard[] = [];
  for (const [puzzle, metrics] of Object.entries(data.records)) {
    const cells: IncumbentCell[] = [];
    for (const [metric, rec] of Object.entries(metrics)) {
      cells.push({
        metric,
        score: rec.score,
        source: rec.source,
        submission: rec.submission,
      });
    }
    boards.push({ puzzle, cells });
  }
  return boards;
}
