// Copies run data from ../results into public/data. Fails if there is no data to copy.
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const site = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(site, "..", "results");
const out = join(site, "public", "data");

if (!existsSync(join(src, "index.json"))) {
  console.error(
    "sync-data: ../results/index.json not found. Run the experiment first (or restore results/) so there are runs to show.",
  );
  process.exit(1);
}

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "traces"), { recursive: true });
mkdirSync(join(out, "truth"), { recursive: true });

cpSync(join(src, "index.json"), join(out, "index.json"));
const jsonFiles = (d) => (existsSync(d) ? readdirSync(d).filter((f) => f.endsWith(".json")) : []);
for (const f of jsonFiles(join(src, "traces"))) cpSync(join(src, "traces", f), join(out, "traces", f));
for (const f of jsonFiles(join(src, "truth"))) cpSync(join(src, "truth", f), join(out, "truth", f));

const rows = JSON.parse(readFileSync(join(out, "index.json"), "utf8")).length;
console.log(`sync-data: ${rows} runs, ${jsonFiles(join(out, "traces")).length} traces`);
