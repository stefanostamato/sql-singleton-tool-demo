import { describe, expect, it } from "vitest";
import { armStats, dominantModel, filterVariant, heroAggregate, heroPairs, replayPairs, spread, variantsPresent } from "./phase2";
import { pickShowcase } from "./metrics";
import { row } from "./testrows";

const SON = "claude-sonnet-5-5";
const HAI = "claude-haiku-4-5";

describe("variant filtering", () => {
  const rows = [
    row({ run_id: "a" }),
    row({ run_id: "b", variant: "math" }),
    row({ run_id: "c", variant: "math", arm: "sql" }),
  ];
  it("keeps only the chosen variant", () => {
    expect(filterVariant(rows, "math").map((r) => r.run_id)).toEqual(["b", "c"]);
    expect(filterVariant(rows, "base").map((r) => r.run_id)).toEqual(["a"]);
    expect(filterVariant(rows, "textdeadlines")).toEqual([]);
  });
  it("lists only variants that have runs, in display order", () => {
    expect(variantsPresent(rows)).toEqual(["base", "math"]);
    expect(variantsPresent([row({ variant: "textdeadlines" }), row()])).toEqual(["base", "textdeadlines"]);
  });
  it("keeps phase 2 runs out of the phase 1 showcase", () => {
    const only2 = [row({ arm: "tools", variant: "math" }), row({ arm: "sql", variant: "math" })];
    expect(pickShowcase(only2)).toBeNull();
  });
});

describe("replayPairs and the lean toggle", () => {
  const base = { variant: "base" as const, profile: "v2" as const, n_matters: 40 };
  const rows = [
    row({ ...base, run_id: "t11", arm: "tools", seed: 11 }),
    row({ ...base, run_id: "s11", arm: "sql", seed: 11 }),
    row({ ...base, run_id: "l11", arm: "tools-lean", seed: 11 }),
    row({ ...base, run_id: "t12", arm: "tools", seed: 12 }),
    row({ ...base, run_id: "s12", arm: "sql", seed: 12 }),
    row({ ...base, run_id: "l12h", arm: "tools-lean", seed: 12, model: HAI }),
    row({ ...base, run_id: "t13", arm: "tools", seed: 13 }),
  ];
  const pairs = replayPairs(rows);
  it("pairs by seed and skips a seed with a missing arm", () => {
    expect(pairs.map((p) => [p.seed, p.tools.run_id, p.sql.run_id])).toEqual([
      [11, "t11", "s11"],
      [12, "t12", "s12"],
    ]);
  });
  it("attaches a lean run only when N, seed, model and variant all match", () => {
    expect(pairs[0].lean?.run_id).toBe("l11");
    expect(pairs[1].lean).toBeNull(); // the only seed-12 lean run is another model
  });
  it("does not use a lean run from another variant or size", () => {
    const more = [
      ...rows,
      row({ ...base, run_id: "l12m", arm: "tools-lean", seed: 12, variant: "math" }),
      row({ ...base, run_id: "l12n", arm: "tools-lean", seed: 12, n_matters: 120 }),
    ];
    expect(replayPairs(more)[1].lean).toBeNull();
  });
  it("still pairs phase 1 rows (no seed) once per N at the lowest rep", () => {
    const p1 = [
      row({ run_id: "t2", arm: "tools", rep: 2 }),
      row({ run_id: "s2", arm: "sql", rep: 2 }),
      row({ run_id: "t1", arm: "tools", rep: 1 }),
      row({ run_id: "s1", arm: "sql", rep: 1 }),
    ];
    const ps = replayPairs(p1);
    expect(ps).toHaveLength(1);
    expect(ps[0].tools.run_id).toBe("t1");
    expect(ps[0].lean).toBeNull();
  });
});

describe("median and range", () => {
  it("computes median, min, max and count", () => {
    expect(spread([3, 1, 2])).toEqual({ median: 2, min: 1, max: 3, count: 3 });
    expect(spread([1, 4])).toEqual({ median: 2.5, min: 1, max: 4, count: 2 });
    expect(spread([])).toBeNull();
  });
  const rows = [
    row({ run_id: "a", n_matters: 40, cost_usd: 1 }),
    row({ run_id: "b", n_matters: 40, cost_usd: 3 }),
    row({ run_id: "c", n_matters: 40, cost_usd: 2 }),
    row({ run_id: "d", n_matters: 40, cost_usd: 99, outcome: "budget_stop" }),
    row({ run_id: "e", n_matters: 40, cost_usd: 50, model: HAI }),
    row({ run_id: "f", n_matters: 40, cost_usd: 60, model: HAI }),
    row({ run_id: "g", n_matters: 120, cost_usd: 5 }),
  ];
  it("uses answered runs of the most common model only", () => {
    expect(dominantModel(rows)).toBe(SON);
    expect(armStats(rows, "tools", (r) => r.cost_usd)).toEqual([
      { n: 40, median: 2, min: 1, max: 3, count: 3 },
      { n: 120, median: 5, min: 5, max: 5, count: 1 },
    ]);
  });
  it("can be asked for a specific model", () => {
    expect(armStats(rows, "tools", (r) => r.cost_usd, HAI)[0]).toMatchObject({ median: 55, min: 50, max: 60 });
  });
});

describe("hero", () => {
  const mk = (seed: number, toolsIn: number, sqlIn: number, extra = {}) => [
    row({ variant: "base", profile: "v2", n_matters: 120, seed, arm: "tools", run_id: `t${seed}`, input_tokens: toolsIn, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, ...extra }),
    row({ variant: "base", profile: "v2", n_matters: 120, seed, arm: "sql", run_id: `s${seed}`, input_tokens: sqlIn, cache_creation_input_tokens: 0, cache_read_input_tokens: 0, ...extra }),
  ];
  it("is null when there is no base v2 pair at N = 120", () => {
    expect(heroPairs([row({ arm: "tools", n_matters: 120 }), row({ arm: "sql", n_matters: 120 })])).toBeNull();
    expect(heroPairs(mk(11, 100, 10).map((r) => ({ ...r, n_matters: 40 })))).toBeNull();
    expect(heroPairs(mk(11, 100, 10).map((r) => ({ ...r, variant: "math" as const })))).toBeNull();
    expect(heroPairs([mk(11, 100, 10)[0]])).toBeNull();
  });
  it("uses the median of per-seed ratios and reports the range", () => {
    const pairs = heroPairs([...mk(11, 100, 10), ...mk(12, 300, 10), ...mk(13, 200, 10)])!;
    const a = heroAggregate(pairs);
    expect(a.count).toBe(3);
    expect(a.tokensRatio).toMatchObject({ median: 20, min: 10, max: 30 });
  });
  it("ignores runs that did not answer", () => {
    const pairs = heroPairs([...mk(11, 100, 10), ...mk(12, 900, 10, { outcome: "budget_stop" })])!;
    expect(pairs).toHaveLength(1);
  });
});
