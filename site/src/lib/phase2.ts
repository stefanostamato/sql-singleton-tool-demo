import { isAnswered, median, modelsOf, ratio, tokensRead, type Pair } from "./metrics";
import { VARIANTS, type Arm, type IndexRow, type Variant } from "./types";

export const filterVariant = (rows: IndexRow[], v: Variant): IndexRow[] => rows.filter((r) => r.variant === v);

/** Variants that have at least one run, in display order. */
export function variantsPresent(rows: IndexRow[]): Variant[] {
  const have = new Set(rows.map((r) => r.variant));
  return VARIANTS.filter((v) => have.has(v));
}

/** The model with the most runs; ties go to the one seen first. */
export function dominantModel(rows: IndexRow[]): string | null {
  let best: string | null = null;
  let bestN = 0;
  for (const m of modelsOf(rows)) {
    const c = rows.filter((r) => r.model === m).length;
    if (c > bestN) {
      best = m;
      bestN = c;
    }
  }
  return best;
}

export const isHaiku = (model: string) => model.toLowerCase().includes("haiku");

export interface ReplayPair extends Pair {
  key: string;
  n: number;
  seed: number | null;
  model: string;
  /** A trimmed-tools run of the same size, seed, model, variant and profile, if one exists. */
  lean: IndexRow | null;
}

const groupKey = (r: IndexRow) => `${r.variant}|${r.profile}|${r.n_matters}|${r.seed}|${r.model}`;

/** Every (N, seed, model) that has both a tools and a sql run, with its lean run when present. */
export function replayPairs(rows: IndexRow[]): ReplayPair[] {
  const groups = new Map<string, IndexRow[]>();
  for (const r of rows) groups.set(groupKey(r), [...(groups.get(groupKey(r)) ?? []), r]);
  const lowest = (rs: IndexRow[], arm: Arm) =>
    rs.filter((r) => r.arm === arm).sort((a, b) => a.rep - b.rep)[0] ?? null;
  const out: ReplayPair[] = [];
  for (const [key, rs] of groups) {
    const tools = lowest(rs, "tools");
    const sql = lowest(rs, "sql");
    if (!tools || !sql) continue;
    out.push({
      key,
      n: tools.n_matters,
      seed: tools.seed,
      model: tools.model,
      tools,
      sql,
      lean: lowest(rs, "tools-lean"),
    });
  }
  return out.sort((a, b) => a.n - b.n || (a.seed ?? 0) - (b.seed ?? 0) || a.model.localeCompare(b.model));
}

export interface Spread {
  median: number;
  min: number;
  max: number;
  count: number;
}

export function spread(xs: number[]): Spread | null {
  const m = median(xs);
  return m === null ? null : { median: m, min: Math.min(...xs), max: Math.max(...xs), count: xs.length };
}

export interface ArmStat extends Spread {
  n: number;
}

/**
 * Per-N median, min and max of a metric over answered runs of one arm, restricted to one model
 * (the most common in `rows` unless given). Ascending in N.
 */
export function armStats(
  rows: IndexRow[],
  arm: Arm,
  get: (r: IndexRow) => number,
  model: string | null = dominantModel(rows),
): ArmStat[] {
  const by = new Map<number, number[]>();
  for (const r of rows) {
    if (r.arm !== arm || !isAnswered(r) || r.model !== model) continue;
    by.set(r.n_matters, [...(by.get(r.n_matters) ?? []), get(r)]);
  }
  return [...by.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([n, v]) => ({ n, ...spread(v)! }));
}

export const HERO_N = 120;

/**
 * Answered base-variant v2 pairs (same seed and model) at N = 120, for the most common model, when
 * both arms have runs. Null otherwise, so the hero keeps the phase 1 showcase pair.
 */
export function heroPairs(rows: IndexRow[]): Pair[] | null {
  const at = rows.filter((r) => r.variant === "base" && r.profile === "v2" && r.n_matters === HERO_N && isAnswered(r));
  const model = dominantModel(at.filter((r) => r.arm === "tools" || r.arm === "sql"));
  const pairs = replayPairs(at.filter((r) => r.model === model)).map(({ tools, sql }) => ({ tools, sql }));
  return pairs.length ? pairs : null;
}

export interface HeroAggregate {
  count: number;
  tokensRatio: Spread | null;
  wallRatio: Spread | null;
  toolsTokens: number;
  sqlTokens: number;
  toolsCost: number;
  sqlCost: number;
  toolsF1: number | null;
  sqlF1: number | null;
}

const spreadOf = (xs: (number | null)[]) => spread(xs.filter((x): x is number => x !== null));

/** Median across pairs of each hero number, with the range of the two ratios. */
export function heroAggregate(pairs: Pair[]): HeroAggregate {
  const med = (f: (p: Pair) => number) => median(pairs.map(f)) ?? 0;
  const f1 = (arm: "tools" | "sql") =>
    median(pairs.filter((p) => isAnswered(p[arm]) && p[arm].f1 !== null).map((p) => p[arm].f1 as number));
  return {
    count: pairs.length,
    tokensRatio: spreadOf(pairs.map((p) => ratio(tokensRead(p.tools), tokensRead(p.sql)))),
    wallRatio: spreadOf(pairs.map((p) => ratio(p.tools.wall_ms, p.sql.wall_ms))),
    toolsTokens: med((p) => tokensRead(p.tools)),
    sqlTokens: med((p) => tokensRead(p.sql)),
    toolsCost: med((p) => p.tools.cost_usd),
    sqlCost: med((p) => p.sql.cost_usd),
    toolsF1: f1("tools"),
    sqlF1: f1("sql"),
  };
}
