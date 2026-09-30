import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTrace, useTruth } from "../lib/data";
import { fmtSeconds } from "../lib/format";
import { modelLabel } from "../config";
import { modelsOf, pickShowcase } from "../lib/metrics";
import { replayPairs } from "../lib/phase2";
import { runEndMs } from "../lib/timeline";
import type { Arm, IndexRow, ToolCall } from "../lib/types";
import RunColumn from "./RunColumn";
import SidePanel from "./SidePanel";
import css from "./Replay.module.css";

const SPEEDS = [1, 4, 16, 64];

export default function Replay({ rows }: { rows: IndexRow[] }) {
  const pairs = useMemo(() => replayPairs(rows), [rows]);
  const multiModel = useMemo(() => modelsOf(rows).length > 1, [rows]);
  const [wanted, setWanted] = useState<string | null>(null);
  const [trimmed, setTrimmed] = useState(false);
  // The chosen pair, else the one at the showcase size, else the largest size.
  const pair = useMemo(() => {
    const chosen = pairs.find((p) => p.key === wanted);
    if (chosen) return chosen;
    const show = pickShowcase(rows);
    return pairs.find((p) => p.tools.run_id === show?.tools.run_id) ?? pairs[pairs.length - 1] ?? null;
  }, [pairs, wanted, rows]);
  const useLean = trimmed && !!pair?.lean;
  const toolsRow = useLean ? pair!.lean : (pair?.tools ?? null);
  const toolsArm: Arm = useLean ? "tools-lean" : "tools";
  const { data: tools, error: toolsErr } = useTrace(toolsRow?.run_id ?? null);
  const { data: sql, error: sqlErr } = useTrace(pair?.sql.run_id ?? null);
  const { data: truth } = useTruth(pair?.sql ?? null);

  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(16);
  const [picked, setPicked] = useState<{ arm: Arm; call: ToolCall } | null>(null);

  // A different pair of runs (variant filter, picker) restarts the shared clock.
  const runsKey = `${toolsRow?.run_id}|${pair?.sql.run_id}`;
  useEffect(() => {
    setT(0);
    setPlaying(false);
    setPicked(null);
  }, [runsKey]);

  // Built once per pair of traces, not on every animation frame.
  const end = useMemo(() => (tools && sql ? Math.max(runEndMs(tools), runEndMs(sql)) : 0), [tools, sql]);
  const maxCtx = tools && sql ? Math.max(tools.totals.context_peak_tokens, sql.totals.context_peak_tokens, 1) : 1;
  const loadError = toolsErr ?? sqlErr;

  const speedRef = useRef(speed);
  speedRef.current = speed;
  const endRef = useRef(end);
  endRef.current = end;

  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = now - last;
      last = now;
      let done = false;
      setT((prev) => {
        const next = prev + dt * speedRef.current;
        if (next >= endRef.current) {
          done = true;
          return endRef.current;
        }
        return next;
      });
      if (done) setPlaying(false);
      else raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  // expose the clock for automated screenshots
  useEffect(() => {
    (window as unknown as { __replay?: unknown }).__replay = { end, t, playing };
  }, [end, t, playing]);

  const changePair = (v: string) => {
    setWanted(v);
    setT(0);
    setPlaying(false);
    setPicked(null);
  };
  const close = useCallback(() => setPicked(null), []);
  const onPick = useCallback((arm: Arm, call: ToolCall) => setPicked({ arm, call }), []);

  if (pairs.length === 0)
    return (
      <section id="replay" className="section">
        <div className="wrap">
          <h2>Replay the runs side by side</h2>
          <p className="muted" data-testid="no-pairs">
            No paired runs yet. The replay needs a tool-per-system run and a SQL run at the same size.
          </p>
        </div>
      </section>
    );

  return (
    <section id="replay" className="section">
      <div className="wrap">
        <h2>Replay the runs side by side</h2>
        <p className="muted">
          Both runs share one clock in real run time, so the faster run visibly finishes first. Click
          any tool call to see what it sent and got back.
        </p>
        <div className={css.controls}>
          <label>
            Run
            <select
              value={pair?.key ?? ""}
              onChange={(e) => changePair(e.target.value)}
              data-testid="run-picker"
              aria-label="Run to replay"
            >
              {pairs.map((p) => (
                <option key={p.key} value={p.key}>
                  N = {p.n}
                  {p.seed !== null ? `, seed ${p.seed}` : ""}
                  {multiModel ? `, ${modelLabel(p.model)}` : ""}
                </option>
              ))}
            </select>
          </label>
          {pair?.lean && (
            <label className={css.toggle}>
              <input
                type="checkbox"
                checked={trimmed}
                onChange={(e) => {
                  setTrimmed(e.target.checked);
                  setT(0);
                  setPlaying(false);
                  setPicked(null);
                }}
                data-testid="lean-toggle"
              />
              Compare trimmed tools
            </label>
          )}
          <button
            className={css.btnPrimary}
            data-testid="play"
            onClick={() => {
              if (t >= end) setT(0);
              setPlaying((p) => !p);
            }}
          >
            {playing ? "Pause" : t >= end && end > 0 ? "Replay" : "Play"}
          </button>
          <button
            className={css.btn}
            data-testid="restart"
            onClick={() => {
              setT(0);
              setPlaying(false);
            }}
          >
            Restart
          </button>
          <button
            className={css.btn}
            data-testid="end"
            onClick={() => {
              setT(end);
              setPlaying(false);
            }}
          >
            Jump to end
          </button>
          <div className={css.speeds} role="group" aria-label="Speed">
            {SPEEDS.map((v) => (
              <button
                key={v}
                className={v === speed ? css.speedOn : css.speed}
                aria-pressed={v === speed}
                data-testid={`speed-${v}`}
                onClick={() => setSpeed(v)}
              >
                {v}x
              </button>
            ))}
          </div>
          <div className={css.scrub}>
            <input
              type="range"
              min={0}
              max={Math.max(end, 1)}
              step={50}
              value={Math.min(t, end)}
              aria-label="Time"
              data-testid="scrubber"
              onChange={(e) => {
                setT(Number(e.target.value));
                setPlaying(false);
              }}
            />
            <span className={css.clock} data-testid="clock">
              {fmtSeconds(Math.min(t, end))}
            </span>
          </div>
        </div>
        {loadError ? (
          <p role="alert" data-testid="replay-error">
            Could not load a run for this size ({loadError}).
          </p>
        ) : tools && sql ? (
          <div className={css.cols}>
            <RunColumn arm={toolsArm} trace={tools} t={t} speed={speed} maxCtx={maxCtx} truth={truth} onPick={onPick} />
            <RunColumn arm="sql" trace={sql} t={t} speed={speed} maxCtx={maxCtx} truth={truth} onPick={onPick} />
          </div>
        ) : (
          <p className="muted">Loading runs...</p>
        )}
        {picked && <SidePanel arm={picked.arm} call={picked.call} onClose={close} />}
      </div>
    </section>
  );
}
