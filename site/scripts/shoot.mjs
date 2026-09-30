// Screenshots each section, drives the replay, and logs every network request.
// Usage: node scripts/shoot.mjs [baseUrl] [outDir]
// Needs `npx playwright install chromium` once. The app must already be serving baseUrl.
import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { chromium } from "playwright";

const base = process.argv[2] ?? process.env.SHOOT_URL ?? "http://127.0.0.1:4000";
const out = resolve(process.argv[3] ?? process.env.SHOOT_OUT ?? "shots");
mkdirSync(out, { recursive: true });

const origin = new URL(base).origin;
const requests = [];
const checks = {};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("request", (r) => requests.push({ url: r.url(), sameOrigin: new URL(r.url()).origin === origin }));

await page.goto(base, { waitUntil: "networkidle" });
await page.waitForSelector("[data-testid=col-tools]");
await page.waitForSelector("[data-testid=point]");

await page.addStyleTag({ content: ".topnav{position:static !important}" });
const shot = (name, loc) =>
  (loc ?? page).screenshot({ path: join(out, name) });

const sections = [
  ["01-hero", "#top"],
  ["02-pipeline", "#pipeline"],
  ["03-replay-start", "#replay"],
  ["04-scaling", "#scaling"],
  ["05-accuracy", "#accuracy"],
  ["06-caveats", "#caveats"],
];
for (const [name, sel] of sections) {
  const loc = page.locator(sel);
  await loc.scrollIntoViewIfNeeded();
  await shot(`${name}.png`, loc);
}
await shot("07-footer.png", page.locator("footer"));

// Replay: play at 64x until the SQL column finishes, record the tools column state then.
const replay = page.locator("#replay");
await replay.scrollIntoViewIfNeeded();
await page.getByTestId("restart").click();
await page.getByTestId("speed-64").click();
await page.getByTestId("play").click();
await page.waitForFunction(
  () => document.querySelector("[data-testid=status-sql]")?.textContent === "finished",
  null,
  { timeout: 60000 },
);
checks.at_sql_finish = {
  sql: await page.getByTestId("status-sql").textContent(),
  tools: await page.getByTestId("status-tools").textContent(),
  clock: await page.getByTestId("clock").textContent(),
};
await page.getByTestId("play").click(); // pause
await shot("08-replay-sql-finished.png", replay);

// Mid-way: scrub to half of the whole run.
const end = await page.evaluate(() => window.__replay.end);
await page.getByTestId("scrubber").evaluate((el, v) => {
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  set.call(el, String(v));
  el.dispatchEvent(new Event("input", { bubbles: true }));
}, Math.round(end / 2));
checks.mid = {
  clock: await page.getByTestId("clock").textContent(),
  tools: await page.getByTestId("status-tools").textContent(),
  sql: await page.getByTestId("status-sql").textContent(),
};
await shot("09-replay-midway.png", replay);

// Side panels: a sql_query call (SQL column) and a mail_search call (tools column), at the end
// of the run so that every chip is shown.
await page.getByTestId("end").click();
checks.side_panels = {};
for (const [file, arm, name] of [
  ["10-side-panel-sql-query.png", "sql", "sql_query"],
  ["10-side-panel-mail-search.png", "tools", "mail_search"],
]) {
  await page.getByTestId(`col-${arm}`).getByTestId("chip").filter({ hasText: name }).first().click();
  await page.getByTestId("side-panel").waitFor();
  checks.side_panels[name] = await page.getByTestId("side-panel").locator("h3").textContent();
  await page.screenshot({ path: join(out, file) });
  await page.keyboard.press("Escape");
  await page.getByTestId("side-panel").waitFor({ state: "detached" });
}

// End state.
await page.getByTestId("end").click();
await page.getByTestId("outcome").first().waitFor();
checks.end = {
  tools: await page.getByTestId("status-tools").textContent(),
  sql: await page.getByTestId("status-sql").textContent(),
  outcomes: await page.getByTestId("outcome").allTextContents(),
};
await shot("11-replay-end.png", replay);

// Narrow viewport.
await page.setViewportSize({ width: 800, height: 1000 });
await page.evaluate(() => window.scrollTo(0, 0));
await page.screenshot({ path: join(out, "12-narrow-800.png"), fullPage: true });

checks.sections = {};
for (const id of ["top", "pipeline", "replay", "scaling", "accuracy", "caveats"])
  checks.sections[id] = (await page.locator(`#${id}`).count()) === 1;
checks.variant_buttons = await page.locator("button[data-testid^=variant-]").allTextContents();
checks.variant_filter_before_replay = await page.evaluate(
  () =>
    !!document.querySelector("[data-testid=variant-filter]") &&
    !!(document.querySelector("[data-testid=variant-filter]").compareDocumentPosition(document.querySelector("#replay")) & Node.DOCUMENT_POSITION_FOLLOWING),
);
checks.lean_toggle_present = (await page.getByTestId("lean-toggle").count()) > 0;
checks.scaling_points = await page.getByTestId("point").count();
checks.accuracy_rows = await page.getByTestId("acc-row").count();
checks.picker_value = await page.getByTestId("run-picker").inputValue();
checks.page_errors = errors;
checks.request_count = requests.length;
checks.cross_origin_requests = requests.filter((r) => !r.sameOrigin).map((r) => r.url);

writeFileSync(join(out, "network.log"), requests.map((r) => `${r.sameOrigin ? "same-origin" : "CROSS-ORIGIN"} ${r.url}`).join("\n") + "\n");
writeFileSync(join(out, "checks.json"), JSON.stringify(checks, null, 2) + "\n");
await browser.close();
console.log(JSON.stringify(checks, null, 2));
if (checks.cross_origin_requests.length || errors.length) process.exitCode = 1;
