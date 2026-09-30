import { tokensRead } from "./metrics";
import { SOURCES, type Source, type Trace } from "./types";

export type EventKind = "turn_start" | "thinking_end" | "api_start" | "api_end" | "turn_end";

export interface TimelineEvent {
  t: number;
  kind: EventKind;
  turn: number;
  source?: Source;
}

const ORDER: Record<EventKind, number> = {
  turn_start: 0,
  thinking_end: 1,
  api_start: 2,
  api_end: 3,
  turn_end: 4,
};

/** All replay events for a run, sorted by time (ties broken by kind, then turn). */
export function buildEvents(trace: Trace): TimelineEvent[] {
  const ev: TimelineEvent[] = [];
  trace.turns.forEach((turn, i) => {
    const toolsStart = turn.started_ms + turn.model_ms;
    ev.push({ t: turn.started_ms, kind: "turn_start", turn: i });
    ev.push({ t: toolsStart, kind: "thinking_end", turn: i });
    for (const tc of turn.tool_calls) {
      for (const ac of tc.api_calls) {
        ev.push({ t: toolsStart + ac.started_ms, kind: "api_start", turn: i, source: ac.source });
        ev.push({
          t: toolsStart + ac.started_ms + ac.duration_ms,
          kind: "api_end",
          turn: i,
          source: ac.source,
        });
      }
    }
    ev.push({ t: toolsStart + turn.tools_ms, kind: "turn_end", turn: i });
  });
  return ev.sort((a, b) => a.t - b.t || ORDER[a.kind] - ORDER[b.kind] || a.turn - b.turn);
}

/** When the run ends: the latest turn end (or api call end). */
export function runEndMs(trace: Trace): number {
  let end = 0;
  for (const e of buildEvents(trace)) end = Math.max(end, e.t);
  return end;
}

export type Phase = "idle" | "thinking" | "tools" | "done";

export interface ReplayState {
  t: number;
  elapsedMs: number;
  done: boolean;
  phase: Phase;
  /** Number of turns that have started (they are shown in the list). */
  turns: number;
  visibleTurns: number;
  toolCalls: number;
  apiCalls: number;
  bySource: Record<Source, number>;
  activeSources: Record<Source, boolean>;
  /** Run time (ms) at which each source last started an api call, or null. */
  lastApiStart: Record<Source, number | null>;
  tokensRead: number;
  outputTokens: number;
  cost: number;
  contextTokens: number;
  /** Index of the turn currently in progress, or -1. */
  currentTurn: number;
}

const zeroBy = <T,>(v: T): Record<Source, T> =>
  Object.fromEntries(SOURCES.map((s) => [s, v])) as Record<Source, T>;

export function stateAt(trace: Trace, t: number, events?: TimelineEvent[]): ReplayState {
  const ev = events ?? buildEvents(trace);
  const end = ev.length ? ev[ev.length - 1].t : 0;
  const s: ReplayState = {
    t,
    elapsedMs: Math.min(Math.max(t, 0), end),
    done: t >= end,
    phase: "idle",
    turns: 0,
    visibleTurns: 0,
    toolCalls: 0,
    apiCalls: 0,
    bySource: zeroBy(0),
    activeSources: zeroBy(false),
    lastApiStart: zeroBy<number | null>(null),
    tokensRead: 0,
    outputTokens: 0,
    cost: 0,
    contextTokens: 0,
    currentTurn: -1,
  };
  const active = zeroBy(0);
  for (const e of ev) {
    if (e.t > t) break;
    const turn = trace.turns[e.turn];
    switch (e.kind) {
      case "turn_start":
        s.turns++;
        s.tokensRead += tokensRead(turn.usage);
        s.contextTokens = turn.context_tokens;
        s.currentTurn = e.turn;
        s.phase = "thinking";
        break;
      case "thinking_end":
        s.outputTokens += turn.usage.output_tokens;
        s.cost += turn.cost_usd;
        s.toolCalls += turn.tool_calls.length;
        s.phase = "tools";
        break;
      case "api_start":
        s.apiCalls++;
        s.bySource[e.source!]++;
        active[e.source!]++;
        s.lastApiStart[e.source!] = e.t;
        break;
      case "api_end":
        active[e.source!]--;
        break;
      case "turn_end":
        break;
    }
  }
  for (const src of SOURCES) s.activeSources[src] = active[src] > 0;
  s.visibleTurns = s.turns;
  if (s.done && s.turns > 0) {
    s.phase = "done";
    s.currentTurn = -1;
  }
  return s;
}
