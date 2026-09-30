import { useTrace } from "../lib/data";
import { pickShowcase } from "../lib/metrics";
import type { IndexRow } from "../lib/types";

export default function Caveats({ rows }: { rows: IndexRow[] }) {
  const pair = pickShowcase(rows);
  const { data: trace } = useTrace(pair ? pair.tools.run_id : null);
  const latencyMs = trace ? Math.round(trace.latency_s * 1000) : null;
  return (
    <section id="caveats" className="section">
      <div className="wrap">
        <h2>Caveats</h2>
        <ul className="caveats">
          <li>
            Prompt caching is on. Re-reading the same context is much cheaper than the raw token
            count suggests, so token ratios overstate the cost gap.
          </li>
          <li>
            The tool-per-system agent may call tools in parallel, which shortens its wall time
            compared with calling them one at a time.
          </li>
          <li>
            The SQL server loads whole tables and filters them locally. A real product would push
            filters down to each system's API.
          </li>
          <li>
            With many systems, the schema itself takes up context, and that cost grows with every
            system added.
          </li>
          <li>Reads only. Neither agent can write to any system.</li>
          <li>
            The SQL agent commits to its query up front. If the query is wrong, it has less room to
            notice and adjust than an agent that looks at each result.
          </li>
          <li>
            The data is synthetic
            {latencyMs !== null && `, and every API call takes a fixed ${latencyMs} ms`}. Real systems
            vary, and some are slower.
          </li>
        </ul>
      </div>
    </section>
  );
}
