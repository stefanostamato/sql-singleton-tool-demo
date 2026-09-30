import { useState, type CSSProperties } from "react";
import { scaleLog } from "d3-scale";
import { area, line } from "d3-shape";
import { ARM_NAME, modelLabel } from "../config";
import { fmtCost, fmtInt, fmtSeconds, fmtTokens } from "../lib/format";
import { isAnswered, modelsOf, tokensRead } from "../lib/metrics";
import { armStats, dominantModel, isHaiku, type ArmStat } from "../lib/phase2";
import type { Arm, IndexRow } from "../lib/types";
import css from "./Charts.module.css";

interface Metric {
  key: string;
  title: string;
  caption: (models: string[]) => string;
  get: (r: IndexRow) => number;
  fmt: (v: number) => string;
}

const METRICS: Metric[] = [
  {
    key: "tokens",
    title: "Tokens read",
    caption: () => "Everything the model read across all turns: fresh input plus cached context, re-read every turn.",
    get: (r) => tokensRead(r),
    fmt: fmtTokens,
  },
  {
    key: "output",
    title: "Output tokens",
    caption: () => "What the model wrote: reasoning, tool calls and the final answer.",
    get: (r) => r.output_tokens,
    fmt: fmtInt,
  },
  {
    key: "wall",
    title: "Wall time (s)",
    caption: () => "From the first model call to the end of the run, including every API call.",
    get: (r) => r.wall_ms / 1000,
    fmt: (v) => fmtSeconds(v * 1000),
  },
  {
    key: "cost",
    title: "Cost ($)",
    caption: (models) =>
      `Priced at the list rates for ${models.map(modelLabel).join(" and ")}, with cached reads billed at the cheaper cache price.`,
    get: (r) => r.cost_usd,
    fmt: fmtCost,
  },
];

const W = 300;
const H = 220;
const M = { t: 10, r: 88, b: 34, l: 64 };
const ARMS: Arm[] = ["tools", "tools-lean", "sql"];
const SHORT: Record<Arm, string> = { tools: "Tools", "tools-lean": "Trimmed", sql: "SQL" };
const armsIn = (rows: IndexRow[]) => ARMS.filter((a) => rows.some((r) => r.arm === a));

function Chart({ rows, m }: { rows: IndexRow[]; m: Metric }) {
  const models = modelsOf(rows);
  const arms = armsIn(rows);
  const main = dominantModel(rows);
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const pts = rows.map((r) => ({ r, v: m.get(r) })).filter((p) => p.v > 0);
  const ns = [...new Set(rows.map((r) => r.n_matters))].sort((a, b) => a - b);
  const x = scaleLog()
    .base(2)
    .domain([ns[0], ns[ns.length - 1]])
    .range([M.l + 14, W - M.r]);
  const vals = pts.map((p) => p.v);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const y = scaleLog()
    .base(10)
    .domain([lo / 1.4, hi * 1.4])
    .range([H - M.b, M.t]);
  const [d0, d1] = y.domain();
  const yTicks: number[] = [];
  for (let e = Math.floor(Math.log10(d0)); e <= Math.ceil(Math.log10(d1)); e++)
    for (const k of [1, 2, 5]) {
      const v = k * 10 ** e;
      if (v >= d0 && v <= d1) yTicks.push(v);
    }
  const jitter = (r: IndexRow) => (arms.indexOf(r.arm) - (arms.length - 1) / 2) * 7 + ((r.rep + (r.seed ?? 0)) % 3 - 1) * 2;
  const path = line<ArmStat>()
    .x((d) => x(d.n))
    .y((d) => y(d.median));
  const band = area<ArmStat>()
    .x((d) => x(d.n))
    .y0((d) => y(d.min))
    .y1((d) => y(d.max))
    .defined((d) => d.count >= 2);

  // Direct labels sit at the last median of each arm, nudged apart so they never overlap.
  const stats = arms.map((arm) => ({
    arm,
    st: armStats(rows, arm, (r) => m.get(r), main).filter((d) => d.min > 0),
  }));
  const labelY = new Map<Arm, number>();
  const ends = stats
    .filter((a) => a.st.length)
    .map((a) => ({ arm: a.arm, y: y(a.st[a.st.length - 1].median) }))
    .sort((a, b) => a.y - b.y);
  ends.forEach((e, i) => {
    if (i > 0) e.y = Math.max(e.y, ends[i - 1].y + 12);
    labelY.set(e.arm, e.y);
  });

  return (
    <figure className={css.fig}>
      <figcaption className={css.title}>{m.title}</figcaption>
      <div className={css.plot}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${m.title} versus number of matters, the arms`}>
          {yTicks.map((v) => (
            <g key={v}>
              <line className={css.grid} x1={M.l} x2={W - M.r} y1={y(v)} y2={y(v)} />
              <text className={css.tick} x={M.l - 6} y={y(v)} textAnchor="end" dominantBaseline="central">
                {m.fmt(v)}
              </text>
            </g>
          ))}
          {ns.map((n) => (
            <text key={n} className={css.tick} x={x(n)} y={H - M.b + 16} textAnchor="middle">
              {n}
            </text>
          ))}
          <line className={css.axis} x1={M.l} x2={W - M.r} y1={H - M.b} y2={H - M.b} />
          <text className={css.tick} x={(M.l + W - M.r) / 2} y={H - 4} textAnchor="middle">
            matters (N)
          </text>
          {stats.map(({ arm, st }) => {
            const last = st[st.length - 1];
            return (
              <g key={arm} data-testid={`series-${arm}`}>
                {st.some((d) => d.count >= 2) && (
                  <path
                    data-testid={`band-${arm}`}
                    d={band(st) ?? ""}
                    fill={`var(--${arm}-tint)`}
                    stroke="none"
                  />
                )}
                {st.length > 1 && (
                  <path
                    data-testid={`median-${arm}`}
                    d={path(st) ?? ""}
                    fill="none"
                    stroke={`var(--${arm})`}
                    strokeWidth={2}
                  />
                )}
                {last && (
                  <text
                    className={css.direct}
                    style={{ "--arm-ink": `var(--${arm}-ink)` } as CSSProperties}
                    x={x(last.n) + 20}
                    y={labelY.get(arm)}
                    dominantBaseline="central"
                  >
                    {SHORT[arm]}
                  </text>
                )}
              </g>
            );
          })}
          {pts.map(({ r, v }) => {
            const cx = x(r.n_matters) + jitter(r);
            const cy = y(v);
            const ok = isAnswered(r);
            const shared = {
              "data-testid": "point",
              "data-arm": r.arm,
              "data-model": r.model,
              fill: ok ? `var(--${r.arm})` : "var(--surface)",
              stroke: ok ? "var(--surface)" : `var(--${r.arm})`,
              strokeWidth: 2,
              onMouseEnter: () =>
                setTip({
                  x: (cx / W) * 100,
                  y: (cy / H) * 100,
                  text: `${r.run_id}: ${m.fmt(v)}${ok ? "" : " (no answer)"}`,
                }),
              onMouseLeave: () => setTip(null),
            };
            return isHaiku(r.model) ? (
              <rect key={r.run_id} x={cx - 4.5} y={cy - 4.5} width={9} height={9} rx={1} {...shared}>
                <title>{`${r.run_id}: ${m.fmt(v)}`}</title>
              </rect>
            ) : (
              <circle key={r.run_id} cx={cx} cy={cy} r={5} {...shared}>
                <title>{`${r.run_id}: ${m.fmt(v)}`}</title>
              </circle>
            );
          })}
        </svg>
        {tip && (
          <div className={css.tip} style={{ left: `${tip.x}%`, top: `${tip.y}%` }} role="tooltip">
            {tip.text}
          </div>
        )}
      </div>
      <p className="muted small">{m.caption(models)}</p>
    </figure>
  );
}

export default function Scaling({ rows }: { rows: IndexRow[] }) {
  const arms = armsIn(rows);
  const models = modelsOf(rows);
  const main = dominantModel(rows);
  if (rows.length === 0) return null;
  return (
    <section id="scaling" className="section">
      <div className="wrap">
        <h2>How each arm scales with the number of matters</h2>
        <p className="muted">
          One mark per run, every seed and model. The line joins the median, at each size, of runs that
          gave an answer{main ? ` with ${modelLabel(main)}` : ""}. The light band spans the smallest to
          the largest of those runs when there are two or more. Both axes are logarithmic, so a
          straight line means steady multiplication.
        </p>
        <div className={css.legend} aria-label="Legend">
          {arms.map((a) => (
            <span key={a}>
              <span className={`swatch ${a}`} aria-hidden="true" />
              {ARM_NAME[a]}
            </span>
          ))}
          {models.map((mo) => (
            <span key={mo}>
              <svg width="12" height="12" aria-hidden="true">
                {isHaiku(mo) ? (
                  <rect x="1.5" y="1.5" width="9" height="9" rx="1" fill="var(--ink-2)" />
                ) : (
                  <circle cx="6" cy="6" r="5" fill="var(--ink-2)" />
                )}
              </svg>{" "}
              {modelLabel(mo)}
            </span>
          ))}
          <span>
            <svg width="12" height="12" aria-hidden="true">
              <circle cx="6" cy="6" r="4.5" fill="none" stroke="var(--ink-2)" strokeWidth="2" />
            </svg>{" "}
            Hollow: no answer (run stopped early)
          </span>
        </div>
        <div className={css.grid4}>
          {METRICS.map((m) => (
            <Chart key={m.key} rows={rows} m={m} />
          ))}
        </div>
        <details className={css.details}>
          <summary>Show the data as a table</summary>
          <div className="table-wrap">
            <table className="acc">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Model</th>
                  <th className="num">Seed</th>
                  <th className="num">N</th>
                  <th className="num">Tokens read</th>
                  <th className="num">Output tokens</th>
                  <th className="num">Wall time (s)</th>
                  <th className="num">Cost ($)</th>
                </tr>
              </thead>
              <tbody>
                {[...rows]
                  .sort((a, b) => a.n_matters - b.n_matters || a.arm.localeCompare(b.arm) || a.rep - b.rep)
                  .map((r) => (
                    <tr key={r.run_id}>
                      <td className="mono">{r.run_id}</td>
                      <td>{modelLabel(r.model)}</td>
                      <td className="num">{r.seed ?? "–"}</td>
                      <td className="num">{r.n_matters}</td>
                      <td className="num">{fmtInt(tokensRead(r))}</td>
                      <td className="num">{fmtInt(r.output_tokens)}</td>
                      <td className="num">{(r.wall_ms / 1000).toFixed(1)}</td>
                      <td className="num">{r.cost_usd.toFixed(4)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </details>
      </div>
    </section>
  );
}
