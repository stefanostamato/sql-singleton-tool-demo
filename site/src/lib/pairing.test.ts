import { describe, expect, it } from "vitest";
import { lowestRepPair, modelsOf, pairedNs } from "./metrics";
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
    input_tokens: 1,
    cache_creation_input_tokens: 1,
    cache_read_input_tokens: 1,
    output_tokens: 1,
    context_peak_tokens: 0,
    result_bytes: 0,
    cost_usd: 1,
    wall_ms: 1000,
    model_ms: 0,
    tools_ms: 0,
    ...over,
  };
}

describe("lowestRepPair", () => {
  it("uses rep 1 when both arms have it", () => {
    const rows = [
      row({ arm: "tools", rep: 2, run_id: "t2" }),
      row({ arm: "sql", rep: 2, run_id: "s2" }),
      row({ arm: "tools", rep: 1, run_id: "t1" }),
      row({ arm: "sql", rep: 1, run_id: "s1" }),
    ];
    const p = lowestRepPair(rows, 10)!;
    expect([p.tools.run_id, p.sql.run_id]).toEqual(["t1", "s1"]);
  });
  it("falls back to the lowest rep that has both arms", () => {
    const rows = [
      row({ arm: "tools", rep: 3, run_id: "t3" }),
      row({ arm: "sql", rep: 3, run_id: "s3" }),
      row({ arm: "tools", rep: 2, run_id: "t2" }),
      row({ arm: "sql", rep: 2, run_id: "s2" }),
    ];
    const p = lowestRepPair(rows, 10)!;
    expect([p.tools.run_id, p.sql.run_id]).toEqual(["t2", "s2"]);
  });
  it("is null when no rep has both arms, and pairedNs skips that N", () => {
    const rows = [
      row({ arm: "tools", rep: 1, n_matters: 5 }),
      row({ arm: "sql", rep: 2, n_matters: 5 }),
      row({ arm: "tools", rep: 2, n_matters: 8 }),
      row({ arm: "sql", rep: 2, n_matters: 8 }),
    ];
    expect(lowestRepPair(rows, 5)).toBeNull();
    expect(pairedNs(rows)).toEqual([8]);
  });
});

describe("modelsOf", () => {
  it("lists distinct models in order of first appearance", () => {
    const rows = [row({ model: "b" }), row({ model: "a" }), row({ model: "b" })];
    expect(modelsOf(rows)).toEqual(["b", "a"]);
  });
});
