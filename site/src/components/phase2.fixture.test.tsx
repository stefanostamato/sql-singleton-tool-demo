import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { row } from "../lib/testrows";
import Accuracy from "./Accuracy";
import Scaling from "./Scaling";

// Small inline fixture: a math-variant set with a trimmed-tools arm and a second model.
const m = { variant: "math" as const, profile: "v2" as const, seed: 11 };
const rows = [
  row({ ...m, run_id: "math-tools-n40-s11-sonnet", arm: "tools", n_matters: 40, cost_usd: 0.2, f1: 0.9 }),
  row({ ...m, run_id: "math-tools-lean-n40-s11-sonnet", arm: "tools-lean", n_matters: 40, cost_usd: 0.1 }),
  row({ ...m, run_id: "math-sql-n40-s11-sonnet", arm: "sql", n_matters: 40, cost_usd: 0.05 }),
  row({ ...m, seed: 12, run_id: "math-sql-n40-s12-sonnet", arm: "sql", n_matters: 40, cost_usd: 0.07 }),
  row({ ...m, run_id: "math-tools-n40-s11-haiku", arm: "tools", n_matters: 40, model: "claude-haiku-4-5", cost_usd: 0.02 }),
];

describe("Scaling with phase 2 rows", () => {
  const html = renderToStaticMarkup(<Scaling rows={rows} />);
  it("shows the trimmed tools arm by name and with its own series", () => {
    expect(html).toContain("Trimmed tools");
    expect(html).toContain('data-testid="series-tools-lean"');
    expect(html).toContain('data-arm="tools-lean"');
  });
  it("draws a square for the Haiku run and circles for Sonnet", () => {
    expect(html).toMatch(/<rect[^>]*data-model="claude-haiku-4-5"/);
    expect(html).toMatch(/<circle[^>]*data-model="claude-sonnet-5-5"/);
  });
  it("draws a min to max band only where an arm has two or more runs", () => {
    expect(html).toContain('data-testid="band-sql"'); // sql has seeds 11 and 12 at N = 40
    expect(html).not.toContain('data-testid="band-tools-lean"');
  });
  it("lists the math runs in the data table", () => {
    expect(html).toContain("math-tools-lean-n40-s11-sonnet");
  });
});

describe("Accuracy with phase 2 rows", () => {
  const html = renderToStaticMarkup(<Accuracy rows={rows} />);
  it("shows variant, model, seed and the trimmed arm", () => {
    expect(html).toContain("Math");
    expect(html).toContain("Haiku 4.5");
    expect(html).toContain("Trimmed tools");
    expect(html).toMatch(/<th[^>]*>Seed<\/th>/);
    expect(html.match(/data-testid="acc-row"/g)).toHaveLength(rows.length);
  });
});
