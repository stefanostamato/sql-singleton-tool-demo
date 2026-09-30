# sql-singleton-tool demo

An experiment on whether an AI agent does better with one tool per system or with one SQL tool over everything. Three
arms (tools, trimmed tools and SQL) answer the same question over four fake systems of a fictional law firm (Harbor & Vale
LLP): matters, court dockets, email and billing. Two harder task variants and a Haiku repeat test the edges. The design
and results are in WRITEUP.md. All data is generated and fake. A static site in `site/` presents the results.

## Run

| Task | Command |
|---|---|
| Install | `uv sync --locked` and `cd site && npm ci` |
| Run locally | `cd site && npm run dev` (port 4000) |
| Test | `uv run pytest` and `cd site && npm test` |
| Build | `cd site && npm run build` |
| Deploy | Push to `main`; GitHub Actions does it |

## Notes

- Live site: https://sql-singleton-tool-demo.lab.zarins.tech
- DNS for the live URL is managed outside this repo.
- Runs that call the API spend money and are capped by results/ledger.json; do not run sweeps without being asked.
- Everything in this repo is public. `scripts/check_public.sh` must print clean before any commit.
