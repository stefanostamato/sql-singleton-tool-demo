import { useEffect, useMemo, useRef, type CSSProperties } from "react";
import { ARM_NAME, SYSTEM_NAME, outcomeLabel } from "../config";
import { fmtCost, fmtInt, fmtSeconds } from "../lib/format";
import { argSummary } from "../lib/summary";
import { buildEvents, stateAt } from "../lib/timeline";
import { SOURCES, type Arm, type ToolCall, type Trace, type Truth } from "../lib/types";
import css from "./Replay.module.css";

const FLASH_WALL_MS = 450; // how long a node stays lit, in wall-clock time
const SYS_Y = [16, 52, 88, 124];

function Outcome({ trace, truth }: { trace: Trace; truth: Truth | null }) {
  const label = trace.turns.length === 0 ? "Did not start" : outcomeLabel(trace.outcome);
  const truthSet = new Set((truth?.at_risk ?? []).flatMap((g) => g.matters));
  const subSet = new Set((trace.answer?.at_risk ?? []).flatMap((g) => g.matters));
  const missed = truth ? [...truthSet].filter((m) => !subSet.has(m)) : (trace.score?.false_negatives ?? []);
  const isExtra = (m: string) => (truth ? !truthSet.has(m) : !!trace.score?.false_positives.includes(m));
  return (
    <div className={css.result} data-testid="outcome">
      <h4>
        {label}
        {trace.score && <> · F1 {trace.score.f1.toFixed(2)}</>}
      </h4>
      {trace.error && (
        <div className={css.runError} data-testid="run-error">
          {trace.error}
        </div>
      )}
      {!trace.answer && <div className="muted">No answer was submitted, so there is nothing to score.</div>}
      {trace.answer && (
        <>
          <div className="muted small">At-risk matters submitted, by attorney:</div>
          <ul>
            {trace.answer.at_risk.map((g) => (
              <li key={g.attorney}>
                {g.attorney}:{" "}
                {g.matters.map((m, i) => (
                  <span key={m} className="mono">
                    {i > 0 && ", "}
                    {m}
                    {isExtra(m) && <span className={css.tagBad}>extra</span>}
                  </span>
                ))}
              </li>
            ))}
          </ul>
          {missed.length > 0 ? (
            <div>
              Missed vs. the truth:{" "}
              {missed.map((m) => (
                <span key={m} className="mono">
                  {m}
                  <span className={css.tagBad}>missed</span>{" "}
                </span>
              ))}
            </div>
          ) : (
            <div className="muted small">Nothing missed.</div>
          )}
        </>
      )}
    </div>
  );
}

export default function RunColumn({
  arm,
  trace,
  t,
  speed,
  maxCtx,
  truth,
  onPick,
}: {
  arm: Arm;
  trace: Trace;
  t: number;
  speed: number;
  maxCtx: number;
  truth: Truth | null;
  onPick: (arm: Arm, call: ToolCall) => void;
}) {
  const events = useMemo(() => buildEvents(trace), [trace]);
  const s = stateAt(trace, t, events);
  const listRef = useRef<HTMLDivElement>(null);

  const shownChips = trace.turns.reduce(
    (n, turn, i) => (i < s.turns && t >= turn.started_ms + turn.model_ms ? n + turn.tool_calls.length : n),
    0,
  );
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [s.turns, shownChips]);

  const style = {
    "--arm": `var(--${arm})`,
    "--arm-tint": `var(--${arm}-tint)`,
    "--arm-ink": `var(--${arm}-ink)`,
  } as CSSProperties;
  const flash = (src: (typeof SOURCES)[number]) => {
    const last = s.lastApiStart[src];
    return last !== null && t - last < FLASH_WALL_MS * speed && t - last >= 0;
  };
  const status = trace.turns.length === 0 ? "did not start" : s.done ? "finished" : s.phase === "thinking" ? "thinking" : s.phase === "tools" ? "calling tools" : "starting";
  const readNow = s.tokensRead;

  return (
    <div className={css.col} style={style} data-testid={`col-${arm}`}>
      <div className={css.colHead}>
        <h3>{ARM_NAME[arm]}</h3>
        <span className={css.status} data-testid={`status-${arm}`}>
          {status}
        </span>
      </div>

      <svg className={css.mini} viewBox="0 0 360 140" role="img" aria-label={`${ARM_NAME[arm]} mini pipeline`}>
        {SYS_Y.map((y, i) => (
          <path
            key={i}
            className={flash(SOURCES[i]) ? css.wireOn : css.wire}
            d={`M70,70 C140,70 130,${y} 200,${y}`}
          />
        ))}
        <g className={css.agentNode}>
          <rect x={6} y={50} width={64} height={40} rx={8} />
          <text x={38} y={70}>
            Agent
          </text>
        </g>
        {SOURCES.map((src, i) => (
          <g key={src} className={`${css.sys} ${flash(src) ? css.sysOn : ""}`} data-testid={`sys-${arm}-${src}`}>
            <rect x={200} y={SYS_Y[i] - 14} width={152} height={28} rx={6} />
            <text x={210} y={SYS_Y[i]}>
              {SYSTEM_NAME[src]}
            </text>
            <text x={344} y={SYS_Y[i]} className={css.cnt}>
              {s.bySource[src]}
            </text>
          </g>
        ))}
      </svg>

      <div className={css.ctxLabel}>
        <span>Context (what the model reads this turn)</span>
        <span className="mono">{fmtInt(s.contextTokens)} tokens</span>
      </div>
      <div className={css.ctxTrack}>
        <div className={css.ctxFill} style={{ width: `${(s.contextTokens / maxCtx) * 100}%` }} />
      </div>

      <div className={css.counters}>
        <div className={css.counter}>
          <span>Model turns</span>
          <b>{s.turns}</b>
        </div>
        <div className={css.counter}>
          <span>Tool calls</span>
          <b>{s.toolCalls}</b>
        </div>
        <div className={css.counter}>
          <span>API calls</span>
          <b>{s.apiCalls}</b>
        </div>
        <div className={css.counter}>
          <span>Tokens read</span>
          <b>{fmtInt(readNow)}</b>
        </div>
        <div className={css.counter}>
          <span>Output tokens</span>
          <b>{fmtInt(s.outputTokens)}</b>
        </div>
        <div className={css.counter}>
          <span>Cost so far</span>
          <b>{fmtCost(s.cost)}</b>
        </div>
        <div className={css.counter}>
          <span>Elapsed</span>
          <b>{fmtSeconds(s.elapsedMs)}</b>
        </div>
      </div>

      <div className={css.list} ref={listRef} data-testid={`list-${arm}`}>
        {s.turns === 0 && <div className={css.empty}>Waiting to start.</div>}
        {trace.turns.slice(0, s.turns).map((turn, i) => {
          const toolsStarted = t >= turn.started_ms + turn.model_ms;
          return (
            <div className={css.turn} key={i}>
              <div className={css.turnHead}>
                <span className={css.turnNo}>#{turn.index + 1}</span>
                <span>
                  {turn.text.length > 140 ? turn.text.slice(0, 140) + "..." : turn.text}
                  {!toolsStarted && <span className={css.think}> thinking...</span>}
                  {(turn.retries ?? 0) > 0 && (
                    <span className={css.think}>
                      {" "}
                      (retried {turn.retries}x
                      {turn.retry_wait_ms ? `, waited ${fmtSeconds(turn.retry_wait_ms)}` : ""})
                    </span>
                  )}
                </span>
              </div>
              {toolsStarted && turn.tool_calls.length > 0 && (
                <div className={css.chips}>
                  {turn.tool_calls.map((c) => (
                    <button
                      key={c.id}
                      data-testid="chip"
                      className={c.is_error ? css.chipErr : css.chip}
                      onClick={() => onPick(arm, c)}
                      title={`Open ${c.name}`}
                    >
                      {c.name}
                      {argSummary(c) && ` ${argSummary(c)}`}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {s.done && <Outcome trace={trace} truth={truth} />}
    </div>
  );
}
