"""Sweep: pilot, proof and showcase runs under hard caps, plus the results index and a report.

    python -m experiment.sweep run --env-file path/to/anthropic.env
    python -m experiment.sweep run --only sql --env-file path/to/anthropic.env   # just one arm's missing runs
    python -m experiment.sweep index
    python -m experiment.sweep rescore   # re-score every trace from the ground truth (free, no API)
    python -m experiment.sweep --report

Exit code 3 means a checkpoint failed (projection over budget); stop and look at the table.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

from experiment.ledger import Ledger
from experiment.run import score_answer
from experiment.generate import generate
from experiment.truth import matter_kinds, write_truth

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
MODEL = "claude-sonnet-5-5"
PROOF_CAP = 2.0
SHOWCASE_CAP = 7.0
SHOWCASE_FRACTION = 0.85
SHOWCASE_CANDIDATES = (120, 100, 80, 60)
EXIT_CHECKPOINT = 3

PILOT = [("sql", 10, 1), ("tools", 10, 1)]
PROOF = [
    ("sql", 5, 1), ("tools", 5, 1),
    ("sql", 20, 1), ("tools", 20, 1),
    ("sql", 20, 2), ("tools", 20, 2),
    ("sql", 20, 3), ("tools", 20, 3),
    ("sql", 40, 1), ("tools", 40, 1),
]
TOTAL_FIELDS = [
    "turns", "tool_calls", "api_calls", "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
    "output_tokens", "context_peak_tokens", "result_bytes", "cost_usd", "wall_ms", "model_ms", "tools_ms",
]
INDEX_FIELDS = (
    ["run_id", "stage", "arm", "variant", "profile", "seed", "n_matters", "rep", "model", "outcome"]
    + TOTAL_FIELDS
    + ["precision", "recall", "f1", "grouping_exact"]
)


def run_id(arm: str, n: int, rep: int) -> str:
    return f"{arm}-n{n}-r{rep}"


# ---------- index ----------

def load_traces(results: Path) -> list[dict]:
    traces = [json.loads(p.read_text()) for p in sorted((results / "traces").glob("*.json"))]
    return sorted(traces, key=lambda t: (t["started_at"], t["run_id"]))


def index_row(t: dict) -> dict:
    row = {k: t[k] for k in ("run_id", "stage", "arm", "n_matters", "rep", "model", "outcome")}
    row["variant"] = t.get("variant", "base")
    row["profile"] = t.get("profile", "v1")
    row["seed"] = t.get("seed", 7)
    row = {k: row[k] for k in ("run_id", "stage", "arm", "variant", "profile", "seed", "n_matters", "rep", "model", "outcome")}
    totals = t.get("totals") or {}
    for k in TOTAL_FIELDS:
        row[k] = totals.get(k, 0)
    score = t.get("score") or {}
    for k in ("precision", "recall", "f1", "grouping_exact"):
        row[k] = score.get(k)
    return row


def build_index(results: Path) -> list[dict]:
    rows = [index_row(t) for t in load_traces(results)]
    (results / "index.json").write_text(json.dumps(rows, indent=1) + "\n")
    with open(results / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=INDEX_FIELDS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return rows


def rescore(results: Path) -> int:
    """Re-score every trace from the ground truth and rewrite the traces and the index. No API calls."""
    count = 0
    for p in sorted((results / "traces").glob("*.json")):
        t = json.loads(p.read_text())
        profile, variant = t.get("profile", "v1"), t.get("variant", "base")
        truth = json.loads(write_truth(t["n_matters"], t["seed"], results / "truth", profile, variant).read_text())
        kinds = matter_kinds(generate(t["n_matters"], t["seed"], profile, variant))
        t["score"] = score_answer(t["answer"], truth, kinds)
        p.write_text(json.dumps(t, indent=2, ensure_ascii=False) + "\n")
        count += 1
    build_index(results)
    return count


# ---------- resumability ----------

def is_done(results: Path, rid: str) -> bool:
    p = results / "traces" / f"{rid}.json"
    if not p.exists():
        return False
    return json.loads(p.read_text()).get("outcome") != "error"


# ---------- projection ----------

def tools_cost(cost_n10: float, n: int) -> float:
    return cost_n10 * (n / 10) ** 2


def sql_cost(cost_n10: float, n: int) -> float:
    return cost_n10 * max(1.0, n / 10)


def project_proof(cost_tools_n10: float, cost_sql_n10: float) -> tuple[float, list[tuple]]:
    """Projected cost of the proof runs (excluding the pilot). Returns (total, rows of arm, N, rep, dollars)."""
    rows = []
    for arm, n, rep in PROOF:
        c = tools_cost(cost_tools_n10, n) if arm == "tools" else sql_cost(cost_sql_n10, n)
        rows.append((arm, n, rep, c))
    return sum(r[3] for r in rows), rows


def fit_ab(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Least squares cost = a*N + b*N^2 with a, b >= 0."""
    if not points:
        return 0.0, 0.0
    s2 = sum(n * n for n, _ in points)
    s3 = sum(n ** 3 for n, _ in points)
    s4 = sum(n ** 4 for n, _ in points)
    y1 = sum(n * c for n, c in points)
    y2 = sum(n * n * c for n, c in points)
    cands = []
    det = s2 * s4 - s3 * s3
    if det > 1e-12:
        a, b = (y1 * s4 - y2 * s3) / det, (s2 * y2 - s3 * y1) / det
        if a >= 0 and b >= 0:
            cands.append((a, b))
    cands.append((y1 / s2, 0.0))
    cands.append((0.0, y2 / s4))

    def sse(ab):
        return sum((ab[0] * n + ab[1] * n * n - c) ** 2 for n, c in points)

    return min(cands, key=sse)


def pick_showcase_n(a: float, b: float, sql_est: float, budget: float = SHOWCASE_FRACTION * SHOWCASE_CAP):
    """Largest candidate N whose projected tools + sql cost fits the budget. Returns (n or None, table)."""
    table = [(n, a * n + b * n * n, sql_est, a * n + b * n * n + sql_est) for n in SHOWCASE_CANDIDATES]
    for n, _, _, total in table:
        if total <= budget:
            return n, table
    return None, table


def answered_costs(traces: list[dict], arm: str) -> list[tuple[int, float]]:
    return [
        (t["n_matters"], t["totals"]["cost_usd"])
        for t in traces
        if t["arm"] == arm and t["outcome"] == "answered" and t["stage"] in ("pilot", "proof")
    ]


# ---------- running ----------

def run_one(arm: str, n: int, rep: int, stage: str, pot: str, env_file: str, out: Path) -> None:
    cmd = [
        sys.executable, "-m", "experiment.run", "--arm", arm, "--n", str(n), "--rep", str(rep),
        "--model", MODEL, "--effort", "medium", "--seed", "7", "--latency", "0.15",
        "--stage", stage, "--pot", pot, "--out", str(out), "--env-file", env_file,
        "--ledger", str(out / "ledger.json"), "--force",
    ]
    print(f"[sweep] {run_id(arm, n, rep)} stage={stage} pot={pot}", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=False)
    build_index(out)


def trace_of(results: Path, rid: str) -> dict | None:
    p = results / "traces" / f"{rid}.json"
    return json.loads(p.read_text()) if p.exists() else None


def run_stage(runs, stage, pot, env_file, results, executor=run_one, only=None):
    for arm, n, rep in runs:
        if only and arm != only:
            continue
        rid = run_id(arm, n, rep)
        if is_done(results, rid):
            print(f"[sweep] skip {rid} (trace exists)", flush=True)
            continue
        executor(arm, n, rep, stage, pot, env_file, results)


def print_table(title: str, header: list[str], rows: list[list]) -> None:
    print(title)
    print("  " + " | ".join(header))
    for r in rows:
        print("  " + " | ".join(f"{c:.4f}" if isinstance(c, float) else str(c) for c in r))


def cmd_run(args, executor=run_one) -> int:
    results = Path(args.results)
    ledger_path = results / "ledger.json"
    env = args.env_file
    only = getattr(args, "only", None)

    run_stage(PILOT, "pilot", "proof", env, results, executor, only)
    ct = trace_of(results, run_id("tools", 10, 1))
    cs = trace_of(results, run_id("sql", 10, 1))
    if not ct or not cs or ct["outcome"] != "answered" or cs["outcome"] != "answered":
        print("pilot did not produce two answered runs; stopping", file=sys.stderr)
        return EXIT_CHECKPOINT
    _, rows = project_proof(ct["totals"]["cost_usd"], cs["totals"]["cost_usd"])
    # the proof pot has spent the pilot (and anything else already in it)
    spent = Ledger(ledger_path).spent("proof")
    remaining = sum(r[3] for r in rows if not is_done(results, run_id(r[0], r[1], r[2])))
    print_table("Proof projection", ["arm", "N", "rep", "projected $"], [list(r) for r in rows])
    print(f"pot spent ${spent:.4f} + projected remaining ${remaining:.4f} = ${spent + remaining:.4f} vs cap ${PROOF_CAP:.2f}")
    if spent + remaining > PROOF_CAP:
        print("projection is over the proof cap: STOP")
        return EXIT_CHECKPOINT

    run_stage(PROOF, "proof", "proof", env, results, executor, only)

    traces = load_traces(results)
    tools_pts = answered_costs(traces, "tools")
    sql_obs = [c for _, c in answered_costs(traces, "sql")]
    if not sql_obs or not tools_pts:
        print("no answered runs to fit the showcase projection: STOP")
        return EXIT_CHECKPOINT
    a, b = fit_ab(tools_pts)
    sql_est = 1.5 * max(sql_obs)
    n, table = pick_showcase_n(a, b, sql_est)
    print(f"tools fit: cost = {a:.6f}*N + {b:.6f}*N^2; sql estimate ${sql_est:.4f}")
    print_table("Showcase projection", ["N", "tools $", "sql $", "total $"], [list(r) for r in table])
    print(f"budget ${SHOWCASE_FRACTION * SHOWCASE_CAP:.2f}; picked N = {n}")
    if n is None:
        print("no showcase N fits: STOP")
        return EXIT_CHECKPOINT
    run_stage([("sql", n, 1), ("tools", n, 1)], "showcase", "showcase", env, results, executor, only)
    return 0


# ---------- report ----------

def report(results: Path) -> str:
    out: list[str] = []
    traces = load_traces(results)
    hdr = ["run_id", "stage", "outcome", "turns", "tool_calls", "api_calls", "tokens_read", "out_tokens", "wall_s", "cost_usd", "f1", "grouping_exact"]
    out.append(" | ".join(hdr))
    for t in traces:
        x = t["totals"]
        s = t["score"] or {}
        read = x["input_tokens"] + x["cache_creation_input_tokens"] + x["cache_read_input_tokens"]
        out.append(" | ".join(str(v) for v in [
            t["run_id"], t["stage"], t["outcome"], x["turns"], x["tool_calls"], x["api_calls"], read,
            x["output_tokens"], round(x["wall_ms"] / 1000, 1), f"{x['cost_usd']:.4f}", s.get("f1", "-"), s.get("grouping_exact", "-"),
        ]))
    ledger = Ledger(results / "ledger.json")
    out.append("")
    out.append("Spend per pot")
    total = 0.0
    for pot, d in ledger.data["pots"].items():
        total += d["spent"]
        out.append(f"  {pot}: ${d['spent']:.4f} of ${d['cap']:.2f}" + ("  OVER CAP" if d["spent"] > d["cap"] else ""))
    out.append(f"  total: ${total:.4f} of $10.00")
    out.append("")
    out.append("Runs cut short or skipped")
    cut = [t for t in traces if t["outcome"] != "answered"]
    have = {t["run_id"] for t in traces}
    for t in cut:
        out.append(f"  cut short: {t['run_id']} outcome={t['outcome']} ({t['error']})")
    planned = [run_id(*r) for r in PILOT + PROOF]
    showcase = [t for t in traces if t["stage"] == "showcase"]
    if showcase:
        planned += [run_id(a, showcase[0]["n_matters"], 1) for a in ("sql", "tools")]
    skipped = [r for r in planned if r not in have]
    for r in skipped:
        out.append(f"  skipped: {r} (no trace; the sweep stopped or the run could not start)")
    if not cut and not skipped:
        out.append("  none")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["run", "index", "report", "rescore"])
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--env-file")
    ap.add_argument("--only", choices=["sql", "tools"], help="with run: only this arm's runs")
    ap.add_argument("--results", default=str(RESULTS))
    args = ap.parse_args(argv)
    results = Path(args.results)
    if args.report or args.command == "report":
        print(report(results))
        return 0
    if args.command == "index":
        rows = build_index(results)
        print(f"indexed {len(rows)} runs")
        return 0
    if args.command == "rescore":
        print(f"rescored {rescore(results)} traces")
        return 0
    if args.command == "run":
        if not args.env_file:
            ap.error("run needs --env-file")
        return cmd_run(args)
    ap.error("give a command or --report")


if __name__ == "__main__":
    sys.exit(main())
