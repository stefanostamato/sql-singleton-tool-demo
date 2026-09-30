import type { IndexRow } from "./types";

/** A complete index row for tests, with overrides. */
export function row(over: Partial<IndexRow> = {}): IndexRow {
  return {
    run_id: "x",
    stage: "proof",
    arm: "tools",
    n_matters: 10,
    rep: 1,
    model: "claude-sonnet-5-5",
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
