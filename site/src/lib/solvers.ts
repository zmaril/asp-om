/** Static routing/description map for the five solver arms. The page
 * content itself (notes + results) is loaded from the repo's markdown
 * files via content collections — this map only says where those files
 * live and how to title them. */

export interface SolverMeta {
  slug: string;
  name: string;
  tech: string;
  tagline: string;
  notesId: string;
  notesPath: string;
  resultIds: string[];
}

export const SOLVERS: SolverMeta[] = [
  {
    slug: 'clingo',
    name: 'clingo',
    tech: 'Answer Set Programming',
    tagline:
      'The reference arm. Fastest at finding plans (optimal-length plans in ~1 s) but proves optimality only on the easiest instance.',
    notesId: 'notes',
    notesPath: 'NOTES.md',
    resultIds: [],
  },
  {
    slug: 'picat',
    name: 'Picat',
    tech: 'Tabled planner (best_plan, iterative deepening)',
    tagline:
      'Most natural model to write; proof is the only mode it has — all three canonical optima proved in ≤62.6 s.',
    notesId: 'picat/notes',
    notesPath: 'picat/NOTES.md',
    resultIds: ['picat/results/canonical'],
  },
  {
    slug: 'z3',
    name: 'Z3',
    tech: 'SMT / bounded model checking',
    tagline:
      'Pure-boolean encoding ~10× faster than Int; discovered the cost-3 glyphs-under-inputs speedrun trick on its own; plan omsim-verified against the real game.',
    notesId: 'z3/notes',
    notesPath: 'z3/NOTES.md',
    resultIds: ['z3/results', 'z3/results-frontier'],
  },
  {
    slug: 'sat',
    name: 'SAT',
    tech: 'PySAT · CaDiCaL / Glucose / kissat',
    tagline:
      'The optimality-proof winner: all three canonical optima proved in ≤9.6 s, UNSAT certificates 10–14× faster than clingo; plan omsim-verified against the real game.',
    notesId: 'sat/notes',
    notesPath: 'sat/NOTES.md',
    resultIds: ['sat/results-trivial', 'sat/results-stabilized-water'],
  },
  {
    slug: 'minizinc',
    name: 'MiniZinc',
    tech: 'CP/MIP — Gecode, Chuffed, CP-SAT, HiGHS, COIN-BC',
    tagline:
      'One model, five engines: multi-core CP-SAT is the only engine that proves optimality as the horizon grows; MIP backends are hopeless beyond toys.',
    notesId: 'minizinc/notes',
    notesPath: 'minizinc/NOTES.md',
    resultIds: ['minizinc/results/benchmarks', 'minizinc/results/canonical'],
  },
];
