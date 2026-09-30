import { SYSTEM_NAME } from "../config";
import { SOURCES } from "../lib/types";

const SYS_Y = [50, 140, 230, 320];
const W = 520;
const H = 370;
const CY = 185;

function Node({
  x,
  y,
  w,
  h = 44,
  label,
  kind,
  mono,
  sub,
}: {
  x: number;
  y: number;
  w: number;
  h?: number;
  label: string;
  kind: string;
  mono?: boolean;
  sub?: string;
}) {
  return (
    <g className={`pl-node ${kind}`}>
      <rect x={x} y={y - h / 2} width={w} height={h} rx={8} />
      <text x={x + w / 2} y={sub ? y - 8 : y} className={mono ? "mono" : undefined}>
        {label}
      </text>
      {sub && (
        <text x={x + w / 2} y={y + 10} className="mono">
          {sub}
        </text>
      )}
    </g>
  );
}

const wire = (x1: number, y1: number, x2: number, y2: number) => {
  const mx = (x1 + x2) / 2;
  return <path key={`${x1}-${y1}-${x2}-${y2}`} className="pl-wire" d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`} />;
};

export default function Pipeline() {
  const toolNames = ["matters_list", "docket_entries", "mail_search", "time_entries"];
  return (
    <section id="pipeline" className="section">
      <div className="wrap">
        <h2>How each agent reaches the data</h2>
        <div className="two">
          <div>
            <h3>
              <span className="swatch tools" aria-hidden="true" />
              Tool per system
            </h3>
            <div className="panel">
              <svg
                viewBox={`0 0 ${W} ${H}`}
                role="img"
                aria-label="The agent calls four tools, each wired to one system."
              >
                {SYS_Y.map((y) => wire(80, CY, 150, y))}
                {SYS_Y.map((y) => wire(300, y, 390, y))}
                <Node x={10} y={CY} w={70} label="Agent" kind="agent" />
                {toolNames.map((t, i) => (
                  <Node key={t} x={150} y={SYS_Y[i]} w={150} label={t} kind="tools" mono />
                ))}
                {SOURCES.map((s, i) => (
                  <Node key={s} x={390} y={SYS_Y[i]} w={120} label={SYSTEM_NAME[s]} kind="system" />
                ))}
              </svg>
            </div>
            <p className="muted small">
              The model does the joins. It reads each result, remembers it, and matches matters
              across systems itself, one call at a time.
            </p>
          </div>
          <div>
            <h3>
              <span className="swatch sql" aria-hidden="true" />
              SQL singleton
            </h3>
            <div className="panel">
              <svg
                viewBox={`0 0 ${W} ${H}`}
                role="img"
                aria-label="The agent calls one SQL tool, which runs in a SQL engine wired to all four systems."
              >
                {wire(80, CY, 105, CY)}
                {wire(195, CY, 215, CY)}
                {SYS_Y.map((y) => wire(335, CY, 390, y))}
                <Node x={10} y={CY} w={70} label="Agent" kind="agent" />
                <Node x={105} y={CY} w={90} label="sql_query" kind="sql" mono />
                <Node x={215} y={CY} w={120} h={60} label="SQL engine" sub="(DuckDB)" kind="sql" />
                {SOURCES.map((s, i) => (
                  <Node key={s} x={390} y={SYS_Y[i]} w={120} label={SYSTEM_NAME[s]} kind="system" />
                ))}
              </svg>
            </div>
            <p className="muted small">
              The server does the joins. The model writes one SQL query, and the engine pulls from
              all four systems and joins them before the model sees anything.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
