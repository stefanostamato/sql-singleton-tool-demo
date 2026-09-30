import { describe, expect, it } from "vitest";
import { buildEvents, runEndMs, stateAt } from "./timeline";
import type { Trace, Turn } from "./types";

const usage = (i: number, o: number) => ({
  input_tokens: i,
  cache_creation_input_tokens: 0,
  cache_read_input_tokens: 0,
  output_tokens: o,
});

function turn(over: Partial<Turn>): Turn {
  return {
    index: 0,
    started_ms: 0,
    model_ms: 1000,
    tools_ms: 500,
    usage: usage(100, 10),
    context_tokens: 100,
    cost_usd: 0.5,
    stop_reason: "tool_use",
    text: "",
    tool_calls: [],
    ...over,
  };
}

const call = (id: string, source: "matters" | "docket", at: number) => ({
  id,
  name: "t",
  input: {},
  is_error: false,
  duration_ms: 150,
  result_bytes: 1,
  result_tokens_est: 1,
  preview: "",
  api_calls: [{ source, endpoint: "e", params: {}, started_ms: at, duration_ms: 150, bytes: 1 }],
});

const trace = {
  turns: [
    turn({
      index: 0,
      started_ms: 0,
      model_ms: 1000,
      tools_ms: 500,
      context_tokens: 100,
      tool_calls: [call("a", "matters", 0), call("b", "docket", 100)],
    }),
    turn({
      index: 1,
      started_ms: 1500,
      model_ms: 2000,
      tools_ms: 0,
      usage: usage(300, 40),
      context_tokens: 300,
      cost_usd: 1,
      stop_reason: "end_turn",
    }),
  ],
  totals: { wall_ms: 3500 },
} as unknown as Trace;

describe("buildEvents", () => {
  it("is sorted by time and places api calls at turn start + model_ms + offset", () => {
    const ev = buildEvents(trace);
    const times = ev.map((e) => e.t);
    expect(times).toEqual([...times].sort((a, b) => a - b));
    const api = ev.filter((e) => e.kind === "api_start");
    expect(api.map((e) => e.t)).toEqual([1000, 1100]);
    expect(api.map((e) => e.source)).toEqual(["matters", "docket"]);
    expect(ev.find((e) => e.kind === "thinking_end" && e.turn === 1)!.t).toBe(3500);
  });
  it("runEndMs is the last turn end", () => {
    expect(runEndMs(trace)).toBe(3500);
  });
});

describe("stateAt", () => {
  it("is empty before anything happens beyond the first turn start", () => {
    const s = stateAt(trace, 0);
    expect(s.turns).toBe(1);
    expect(s.phase).toBe("thinking");
    expect(s.apiCalls).toBe(0);
    expect(s.outputTokens).toBe(0);
    expect(s.cost).toBe(0);
  });
  it("counts api calls only once they have started, per source", () => {
    const s = stateAt(trace, 1050);
    expect(s.phase).toBe("tools");
    expect(s.toolCalls).toBe(2);
    expect(s.apiCalls).toBe(1);
    expect(s.bySource.matters).toBe(1);
    expect(s.bySource.docket).toBe(0);
    expect(s.activeSources.matters).toBe(true);
    expect(s.activeSources.docket).toBe(false);
    expect(s.outputTokens).toBe(10);
    expect(s.cost).toBe(0.5);
  });
  it("remembers when each source last started an api call", () => {
    const s = stateAt(trace, 1050);
    expect(s.lastApiStart.matters).toBe(1000);
    expect(s.lastApiStart.docket).toBeNull();
    expect(stateAt(trace, 1200).lastApiStart.docket).toBe(1100);
  });
  it("accumulates tokens read per started turn and tracks context", () => {
    const s = stateAt(trace, 1600);
    expect(s.turns).toBe(2);
    expect(s.tokensRead).toBe(400);
    expect(s.contextTokens).toBe(300);
    expect(s.apiCalls).toBe(2);
  });
  it("marks done at the end with full totals", () => {
    const s = stateAt(trace, 99999);
    expect(s.done).toBe(true);
    expect(s.phase).toBe("done");
    expect(s.elapsedMs).toBe(3500);
    expect(s.outputTokens).toBe(50);
    expect(s.cost).toBe(1.5);
    expect(s.visibleTurns).toBe(2);
  });
});
