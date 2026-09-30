import { describe, expect, it } from "vitest";
import {
  median,
  medianByN,
  pairedNs,
  pickShowcase,
  ratio,
  showcaseStats,
  tokensRead,
} from "./metrics";
import type { IndexRow } from "./types";

function row(over: Partial<IndexRow>): IndexRow {
  return {
    run_id: "x",
    stage: "proof",
    arm: "tools",
    n_matters: 10,
    rep: 1,
    model: "m",
    outcome: "answered",
    precision: 1,
    recall: 1,
    f1: 1,
    grouping_exact: true,
    variant: "base",
    profile: "v1",
    seed: null,
    turns: 1,
    tool_calls: 1,
    api_calls: 1,
    input_tokens: 100,
    cache_creation_input_tokens: 200,
    cache_read_input_tokens: 400,
    output_tokens: 7,
    context_peak_tokens: 0,
    result_bytes: 0,
    cost_usd: 1,
    wall_ms: 1000,
    model_ms: 0,
    tools_ms: 0,
    ...over,
  };
}

describe("tokensRead", () => {
  it("sums input, cache creation and cache read, and excludes output", () => {
    expect(
      tokensRead({
        input_tokens: 1,
        cache_creation_input_tokens: 20,
        cache_read_input_tokens: 300,
        output_tokens: 4000,
      }),
    ).toBe(321);
  });
});

describe("ratio and median", () => {
  it("divides and guards zero", () => {
    expect(ratio(10, 4)).toBe(2.5);
    expect(ratio(10, 0)).toBeNull();
  });
  it("median handles odd, even and empty", () => {
    expect(median([5, 1, 3])).toBe(3);
    expect(median([4, 1, 3, 2])).toBe(2.5);
    expect(median([])).toBeNull();
  });
});

describe("pickShowcase", () => {
  it("prefers the showcase stage", () => {
    const rows = [
      row({ run_id: "a", arm: "tools", n_matters: 40, stage: "proof" }),
      row({ run_id: "b", arm: "sql", n_matters: 40, stage: "proof" }),
      row({ run_id: "c", arm: "tools", n_matters: 80, stage: "showcase" }),
      row({ run_id: "d", arm: "sql", n_matters: 80, stage: "showcase" }),
    ];
    const p = pickShowcase(rows)!;
    expect([p.tools.run_id, p.sql.run_id]).toEqual(["c", "d"]);
  });
  it("falls back to the largest N with both arms at rep 1", () => {
    const rows = [
      row({ run_id: "a", arm: "tools", n_matters: 10 }),
      row({ run_id: "b", arm: "sql", n_matters: 10 }),
      row({ run_id: "c", arm: "tools", n_matters: 20 }),
      row({ run_id: "d", arm: "sql", n_matters: 20 }),
      row({ run_id: "e", arm: "tools", n_matters: 40 }), // no sql arm
      row({ run_id: "f", arm: "sql", n_matters: 5, rep: 2 }),
    ];
    const p = pickShowcase(rows)!;
    expect([p.tools.run_id, p.sql.run_id]).toEqual(["c", "d"]);
  });
  it("returns null when no pair exists", () => {
    expect(pickShowcase([row({})])).toBeNull();
  });
});

describe("pairedNs", () => {
  it("lists N values with both arms at rep 1, ascending", () => {
    const rows = [
      row({ arm: "tools", n_matters: 20 }),
      row({ arm: "sql", n_matters: 20 }),
      row({ arm: "tools", n_matters: 5 }),
      row({ arm: "sql", n_matters: 5 }),
      row({ arm: "tools", n_matters: 10 }),
    ];
    expect(pairedNs(rows)).toEqual([5, 20]);
  });
});

describe("showcaseStats", () => {
  it("computes ratios from the right fields", () => {
    const tools = row({
      arm: "tools",
      input_tokens: 1000,
      cache_creation_input_tokens: 2000,
      cache_read_input_tokens: 7000, // 10000 read
      output_tokens: 999999,
      wall_ms: 300000,
      cost_usd: 3,
    });
    const sql = row({
      arm: "sql",
      input_tokens: 100,
      cache_creation_input_tokens: 200,
      cache_read_input_tokens: 1700, // 2000 read
      output_tokens: 1,
      wall_ms: 30000,
      cost_usd: 0.3,
    });
    const s = showcaseStats({ tools, sql });
    expect(s.tokensRatio).toBe(5);
    expect(s.wallRatio).toBe(10);
    expect(s.toolsCost).toBe(3);
    expect(s.sqlCost).toBe(0.3);
  });
});

describe("medianByN", () => {
  it("uses only answered runs of the arm, per N, sorted by N", () => {
    const rows = [
      row({ arm: "tools", n_matters: 20, cost_usd: 1 }),
      row({ arm: "tools", n_matters: 20, cost_usd: 3 }),
      row({ arm: "tools", n_matters: 20, cost_usd: 100, outcome: "budget_stop" }),
      row({ arm: "tools", n_matters: 10, cost_usd: 5 }),
      row({ arm: "sql", n_matters: 10, cost_usd: 0.1 }),
    ];
    expect(medianByN(rows, "tools", (r) => r.cost_usd)).toEqual([
      { n: 10, value: 5 },
      { n: 20, value: 2 },
    ]);
  });
  it("omits N values that have no answered run", () => {
    const rows = [row({ arm: "tools", n_matters: 80, outcome: "budget_stop" })];
    expect(medianByN(rows, "tools", (r) => r.cost_usd)).toEqual([]);
  });
});
