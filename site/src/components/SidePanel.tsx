import { useEffect } from "react";
import { ARM_NAME, SYSTEM_NAME } from "../config";
import { fmtInt } from "../lib/format";
import type { Arm, ToolCall } from "../lib/types";
import css from "./Replay.module.css";

/** The SQL text of a sql_query input, shown as written instead of as an escaped JSON string. */
function sqlOf(input: unknown): string | null {
  const sql = (input as { sql?: unknown } | null)?.sql;
  return typeof sql === "string" ? sql : null;
}

export default function SidePanel({
  arm,
  call,
  onClose,
}: {
  arm: Arm;
  call: ToolCall;
  onClose: () => void;
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <>
      <div className={css.overlay} onClick={onClose} />
      <aside className={css.side} role="dialog" aria-label={`Tool call ${call.name}`} data-testid="side-panel">
        <button className={`${css.btn} ${css.close}`} onClick={onClose}>
          Close
        </button>
        <h3>{call.name}</h3>
        <div className="muted small">
          {ARM_NAME[arm]}
          {call.is_error && <span className={css.tagBad}>error</span>}
        </div>
        <h4>Input</h4>
        {sqlOf(call.input) !== null ? (
          <pre data-testid="sql-input">{sqlOf(call.input)}</pre>
        ) : (
          <pre>{JSON.stringify(call.input, null, 2)}</pre>
        )}
        <h4>Result size</h4>
        <div>
          {fmtInt(call.result_bytes)} bytes, about {fmtInt(call.result_tokens_est)} tokens
        </div>
        {call.name === "sql_query" && typeof call.load_ms === "number" && (
          <div data-testid="load-ms">of which local load: {fmtInt(call.load_ms)} ms</div>
        )}
        <h4>API calls ({call.api_calls.length})</h4>
        {call.api_calls.length ? (
          <div className={css.apiScroll}>
            <table className={css.apiTable}>
              <thead>
                <tr>
                  <th>system</th>
                  <th>endpoint</th>
                  <th>params</th>
                  <th>start</th>
                  <th>ms</th>
                  <th>bytes</th>
                </tr>
              </thead>
              <tbody>
                {call.api_calls.map((a, i) => (
                  <tr key={i}>
                    <td>{SYSTEM_NAME[a.source]}</td>
                    <td>{a.endpoint}</td>
                    <td>{JSON.stringify(a.params)}</td>
                    <td>{a.started_ms}</td>
                    <td>{a.duration_ms}</td>
                    <td>{fmtInt(a.bytes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="muted small">None. This call does not touch a system.</div>
        )}
        <h4>Result preview</h4>
        <pre>{call.preview}</pre>
      </aside>
    </>
  );
}
