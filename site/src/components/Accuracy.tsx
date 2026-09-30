import { Fragment, useState } from "react";
import { ARM_NAME, VARIANT_NAME, modelLabel, outcomeLabel } from "../config";
import { useTrace } from "../lib/data";
import { fmtPct } from "../lib/format";
import type { IndexRow } from "../lib/types";

function Detail({ runId }: { runId: string }) {
  const { data: trace, error } = useTrace(runId);
  if (error) return <>Could not load this run ({error}).</>;
  if (!trace) return <>Loading...</>;
  const s = trace.score;
  const err = trace.error && <div data-testid="acc-error">Error: {trace.error}</div>;
  if (!s)
    return (
      <>
        <div>{trace.turns.length === 0 ? "Did not start." : "No score: this run did not produce an answer."}</div>
        {err}
      </>
    );
  const list = (xs: string[]) =>
    xs.length ? xs.map((m) => <span key={m} className="mono">{m} </span>) : <span className="muted">none</span>;
  return (
    <>
      {err}
      <div>Expected {s.expected_count}, submitted {s.submitted_count}.</div>
      <div>False positives (submitted, not at risk): {list(s.false_positives)}</div>
      <div>False negatives (at risk, missed): {list(s.false_negatives)}</div>
      {s.errors_by_trap && Object.keys(s.errors_by_trap).length > 0 && (
        <div data-testid="errors-by-trap">
          <div>Errors by trap type:</div>
          <ul className="traps">
            {Object.entries(s.errors_by_trap).map(([trap, e]) => (
              <li key={trap} data-testid="trap-row">
                <b>{trap.replace(/_/g, " ")}</b>: {e.false_positives.length} false positive
                {e.false_positives.length === 1 ? "" : "s"} {list(e.false_positives)}, {e.false_negatives.length} false
                negative{e.false_negatives.length === 1 ? "" : "s"} {list(e.false_negatives)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

export default function Accuracy({ rows }: { rows: IndexRow[] }) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setOpen((o) => {
      const n = new Set(o);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const armOrder = ["tools", "tools-lean", "sql"];
  const sorted = [...rows].sort(
    (a, b) =>
      a.model.localeCompare(b.model) ||
      (a.seed ?? 0) - (b.seed ?? 0) ||
      a.n_matters - b.n_matters ||
      armOrder.indexOf(a.arm) - armOrder.indexOf(b.arm) ||
      a.rep - b.rep,
  );
  return (
    <section id="accuracy" className="section">
      <div className="wrap">
        <h2>Accuracy of every run</h2>
        <p className="muted">
          Precision is how many submitted matters were truly at risk. Recall is how many at-risk
          matters were found. F1 combines the two. Open a row to see the specific mistakes.
        </p>
        <div className="table-wrap">
          <table className="acc">
            <thead>
              <tr>
                <th>Variant</th>
                <th>Model</th>
                <th className="num">Seed</th>
                <th className="num">N</th>
                <th>Arm</th>
                <th className="num">Rep</th>
                <th>Stage</th>
                <th>Outcome</th>
                <th className="num">Precision</th>
                <th className="num">Recall</th>
                <th className="num">F1</th>
                <th>Grouping exact</th>
                <th>Mistakes</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <Fragment key={r.run_id}>
                  <tr data-testid="acc-row">
                    <td>{VARIANT_NAME[r.variant]}</td>
                    <td>{modelLabel(r.model)}</td>
                    <td className="num">{r.seed ?? "–"}</td>
                    <td className="num">{r.n_matters}</td>
                    <td>
                      <span className={`swatch ${r.arm}`} aria-hidden="true" />
                      {ARM_NAME[r.arm]}
                    </td>
                    <td className="num">{r.rep}</td>
                    <td>{r.stage}</td>
                    <td>{outcomeLabel(r.outcome)}</td>
                    <td className="num">{fmtPct(r.precision)}</td>
                    <td className="num">{fmtPct(r.recall)}</td>
                    <td className="num">{fmtPct(r.f1)}</td>
                    <td>{r.grouping_exact === null ? "–" : r.grouping_exact ? "yes" : "no"}</td>
                    <td>
                      <button
                        className="link"
                        aria-expanded={open.has(r.run_id)}
                        onClick={() => toggle(r.run_id)}
                      >
                        {open.has(r.run_id) ? "Hide" : "Show"}
                      </button>
                    </td>
                  </tr>
                  {open.has(r.run_id) && (
                    <tr className="detail">
                      <td colSpan={14}>
                        <Detail runId={r.run_id} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
