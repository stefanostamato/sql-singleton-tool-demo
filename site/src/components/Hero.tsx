import { ARM_NAME, OUTCOME_LABEL, modelLabel, outcomeLabel } from "../config";
import { useTrace } from "../lib/data";
import { fmtCost, fmtRatio, fmtSeconds, fmtSeeds, fmtTokens } from "../lib/format";
import { pickShowcase, showcaseStats } from "../lib/metrics";
import { heroAggregate, heroPairs, HERO_N, type Spread } from "../lib/phase2";
import type { IndexRow, Outcome } from "../lib/types";

const range = (s: Spread | null) =>
  s && s.count > 1 ? (
    <div className="t-range" data-testid="hero-range">
      range {fmtRatio(s.min)} to {fmtRatio(s.max)}
    </div>
  ) : null;

function Row({ arm, children }: { arm: "tools" | "sql"; children: React.ReactNode }) {
  return (
    <div className="t-row">
      <span>
        <span className={`swatch ${arm}`} aria-hidden="true" />
        {ARM_NAME[arm]}
      </span>
      {children}
    </div>
  );
}

export default function Hero({ rows }: { rows: IndexRow[] }) {
  // Phase 2 medians replace the single showcase pair once base v2 runs at N = 120 exist for both arms.
  const multi = heroPairs(rows);
  const pair = multi ? multi[0] : pickShowcase(rows);
  const agg = multi ? heroAggregate(multi) : null;
  const { data: trace } = useTrace(pair ? pair.tools.run_id : null);
  const s = pair ? showcaseStats(pair) : null;
  const f1 = (v: number | null, outcome: Outcome) =>
    v !== null ? (
      <b>{v.toFixed(2)}</b>
    ) : (
      <span className="t-outcome">{outcomeLabel(outcome).toLowerCase()}</span>
    );

  return (
    <section id="top" className="section" style={{ borderTop: "none" }}>
      <div className="wrap">
        <h1>One SQL tool vs. one tool per system</h1>
        <p className="lede">
          The same AI agent answers the same question over four systems at a law firm, once with a
          tool for each system and once with a single SQL tool over all of them.
        </p>
        <p className="note" aria-hidden="true">same question, same data, three ways to ask</p>
        <div className="question">
          <div className="label">The question</div>
          <div>{trace ? trace.question : " "}</div>
        </div>
        {pair && s && (
          <>
            <p className="muted small">
              {agg
                ? `Median of ${agg.count} paired run${agg.count === 1 ? "" : "s"} with ${HERO_N} matters (${modelLabel(pair.tools.model)}, ${fmtSeeds(multi!.map((p) => p.tools.seed).filter((s): s is number => s != null))}).`
                : `Showing the run with ${pair.tools.n_matters} matters (${pair.tools.stage} stage).`}
            </p>
            {!agg && (s.toolsOutcome !== "answered" || s.sqlOutcome !== "answered") && (
              <p className="muted small" data-testid="hero-note">
                {(["tools", "sql"] as const)
                  .filter((a) => (a === "tools" ? s.toolsOutcome : s.sqlOutcome) !== "answered")
                  .map((a) => `${ARM_NAME[a]}: ${OUTCOME_LABEL[a === "tools" ? s.toolsOutcome : s.sqlOutcome]}, so it has no F1 score.`)
                  .join(" ")}
              </p>
            )}
            <div className="tiles">
              <div className="tile">
                <div className="t-label">Tokens read</div>
                <div className="t-big">{fmtRatio(agg ? (agg.tokensRatio?.median ?? null) : s.tokensRatio)}</div>
                {range(agg?.tokensRatio ?? null)}
                <div className="t-sub">
                  {ARM_NAME.tools} read {fmtTokens(agg ? agg.toolsTokens : s.toolsTokens)} tokens, {ARM_NAME.sql} read{" "}
                  {fmtTokens(agg ? agg.sqlTokens : s.sqlTokens)}.

                </div>
              </div>
              <div className="tile">
                <div className="t-label">Wall time</div>
                <div className="t-big">{fmtRatio(agg ? (agg.wallRatio?.median ?? null) : s.wallRatio)}</div>
                {range(agg?.wallRatio ?? null)}
                {!agg && (
                  <div className="t-sub">
                    {fmtSeconds(pair.tools.wall_ms)} vs. {fmtSeconds(pair.sql.wall_ms)}.
                  </div>
                )}
              </div>
              <div className="tile">
                <div className="t-label">Cost</div>
                <div className="t-pair">
                  <Row arm="tools">
                    <b>{fmtCost(agg ? agg.toolsCost : s.toolsCost)}</b>
                  </Row>
                  <Row arm="sql">
                    <b>{fmtCost(agg ? agg.sqlCost : s.sqlCost)}</b>
                  </Row>
                </div>
              </div>
              <div className="tile">
                <div className="t-label">F1 score (accuracy)</div>
                <div className="t-pair">
                  <Row arm="tools">
                    {f1(agg ? agg.toolsF1 : s.toolsF1, s.toolsOutcome)}
                  </Row>
                  <Row arm="sql">
                    {f1(agg ? agg.sqlF1 : s.sqlF1, s.sqlOutcome)}
                  </Row>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
