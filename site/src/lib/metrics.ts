import type { Arm, IndexRow, Outcome, Usage } from "./types";

/** What the model read: fresh input plus cache writes plus cache reads. Output is excluded. */
export function tokensRead(u: Usage): number {
  return u.input_tokens + u.cache_creation_input_tokens + u.cache_read_input_tokens;
}

export function ratio(a: number, b: number): number | null {
  return b === 0 ? null : a / b;
}

export function median(xs: number[]): number | null {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export const isAnswered = (r: { outcome: string }) => r.outcome === "answered";

export interface Pair {
  tools: IndexRow;
  sql: IndexRow;
}

function pairAt(rows: IndexRow[], n: number, pred: (r: IndexRow) => boolean): Pair | null {
  const tools = rows.find((r) => r.arm === "tools" && r.n_matters === n && pred(r));
  const sql = rows.find((r) => r.arm === "sql" && r.n_matters === n && pred(r));
  return tools && sql ? { tools, sql } : null;
}

/** The pair at size n from the lowest rep that has both arms (rep 1 when present), or null. */
export function lowestRepPair(rows: IndexRow[], n: number): Pair | null {
  const reps = [...new Set(rows.filter((r) => r.n_matters === n).map((r) => r.rep))].sort((a, b) => a - b);
  for (const rep of reps) {
    const p = pairAt(rows, n, (r) => r.rep === rep);
    if (p) return p;
  }
  return null;
}

/** N values that have both arms at some rep, ascending. */
export function pairedNs(rows: IndexRow[]): number[] {
  const ns = [...new Set(rows.map((r) => r.n_matters))].sort((a, b) => a - b);
  return ns.filter((n) => lowestRepPair(rows, n));
}

/** Distinct model names, in order of first appearance. */
export function modelsOf(rows: IndexRow[]): string[] {
  return [...new Set(rows.map((r) => r.model))];
}

/** The showcase pair, or else the largest N where both arms exist with rep 1. */
export function pickShowcase(everything: IndexRow[]): Pair | null {
  // Phase 1 data only: the showcase never mixes in phase 2 variants or profiles.
  const rows = everything.filter((r) => r.variant === "base" && r.profile === "v1");
  const shows = rows.filter((r) => r.stage === "showcase");
  const ns = [...new Set(shows.map((r) => r.n_matters))].sort((a, b) => b - a);
  for (const n of ns) {
    const p = pairAt(shows, n, () => true);
    if (p) return p;
  }
  const all = pairedNs(rows);
  if (!all.length) return null;
  return lowestRepPair(rows, all[all.length - 1]);
}

export interface ShowcaseStats {
  toolsTokens: number;
  sqlTokens: number;
  tokensRatio: number | null;
  wallRatio: number | null;
  toolsCost: number;
  sqlCost: number;
  toolsF1: number | null;
  sqlF1: number | null;
  toolsOutcome: Outcome;
  sqlOutcome: Outcome;
}

export function showcaseStats(p: Pair): ShowcaseStats {
  const toolsTokens = tokensRead(p.tools);
  const sqlTokens = tokensRead(p.sql);
  return {
    toolsTokens,
    sqlTokens,
    tokensRatio: ratio(toolsTokens, sqlTokens),
    wallRatio: ratio(p.tools.wall_ms, p.sql.wall_ms),
    toolsCost: p.tools.cost_usd,
    sqlCost: p.sql.cost_usd,
    toolsF1: isAnswered(p.tools) ? p.tools.f1 : null,
    sqlF1: isAnswered(p.sql) ? p.sql.f1 : null,
    toolsOutcome: p.tools.outcome,
    sqlOutcome: p.sql.outcome,
  };
}

/** Per-N median of a metric over answered runs of one arm, ascending in N. */
export function medianByN(
  rows: IndexRow[],
  arm: Arm,
  get: (r: IndexRow) => number,
): { n: number; value: number }[] {
  const by = new Map<number, number[]>();
  for (const r of rows) {
    if (r.arm !== arm || !isAnswered(r)) continue;
    by.set(r.n_matters, [...(by.get(r.n_matters) ?? []), get(r)]);
  }
  return [...by.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([n, v]) => ({ n, value: median(v)! }));
}
