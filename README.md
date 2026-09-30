# sql-singleton-tool demo

Does an AI agent do better with one tool per system, or with one SQL tool over everything?

Does the answer change with the arm? Three arms (tools, trimmed tools and SQL) answer the same question over four fake
systems of a fictional law firm (Harbor & Vale LLP): matters (Clio-like), court dockets (CourtListener-like), email
(Microsoft Graph-like) and billing (Clio activities-like). Two harder task variants and a Haiku repeat test the edges. The
design and results are in [WRITEUP.md](WRITEUP.md). All data is generated and fake.

Live: https://sql-singleton-tool-demo.lab.zarins.tech. Code and results: this repo.

- **tools arm**: one MCP tool per system. The agent pages through each API and joins the results itself. A third arm, **tools-lean**, is the same four tools with each record trimmed to the SQL columns.
- **sql arm**: one MCP SQL tool. The server loads everything once into DuckDB and the agent writes queries.

The question: which open litigation matters are at risk of being neglected (an upcoming court deadline,
but no client email and no billable time in the last two weeks). The correct answer is computed in plain
Python, so every run is scored exactly.

## Setup

```
uv sync --locked
uv run pytest
scripts/check_public.sh
```

## Run

```
# one run (needs ANTHROPIC_API_KEY in the environment or an env file)
uv run python -m experiment.run --arm sql --n 5 --rep 1 --model claude-haiku-4-5 \
  --stage dev --pot dev --out runs --env-file path/to/anthropic.env

# how big is one matter's data, in tokens (uses the free token counting endpoint)
uv run python -m experiment.size_payloads --env-file path/to/anthropic.env

# write ground truth
uv run python -c "from experiment.truth import write_truth; write_truth(40, 7, 'results/truth')"
```

Runs refuse to overwrite an existing trace unless you pass `--force`. Spend is capped per pot in `results/ledger.json`. The trace format is in `docs/trace-format.md`.

## Results

The full results, predictions and caveats are in [WRITEUP.md](WRITEUP.md). Per-run data is in
`results/index.json` and `results/results.csv`, and the raw traces are in `results/traces/`.

Reproduce the sweep (paid, capped by the ledger) and the tables:

```
uv run python -m experiment.sweep run --env-file path/to/anthropic.env
uv run python -m experiment.sweep --report
uv run python -m experiment.sweep2 run --env-file path/to/anthropic.env   # phase 2 (robustness), capped
uv run python -m experiment.sweep2 report
uv run python -m experiment.writeup_tables
```

`sweep run --only sql` reruns just one arm's missing runs, and `uv run python -m experiment.sweep rescore`
re-scores every trace from the ground truth and rewrites the index (free, no API calls).

## Site

A small web app in `site/` shows the results. It reads the files in `results/`.

```
cd site
npm ci
npm run dev      # http://localhost:4000
npm run build
npm test
```

It needs Node 22.12 or newer.

## Deploy

The site deploys to Cloudflare Pages from GitHub Actions on every push to `main` (`.github/workflows/ci.yml`): tests, site build, then `wrangler pages deploy site/dist`. The two secrets, `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`, live in the repo's `production` environment, and only `main` deploys. `CLOUDFLARE_API_TOKEN` is a token with only Cloudflare Pages Edit on this account, with no zone or DNS rights.
