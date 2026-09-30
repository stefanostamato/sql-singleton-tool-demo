"""Phase 2 sweep: the robustness run plan under two capped pots, resumable, with a report.

    python -m experiment.sweep2 run --env-file path/to/anthropic.env
    python -m experiment.sweep2 run --only-pot p2-base --env-file path/to/anthropic.env
    python -m experiment.sweep2 plan
    python -m experiment.sweep2 report

Pots (added to results/ledger.json if missing, never changed if present): p2-base $3.00, p2-variants
$3.50. Every run is a separate `experiment.run` process, so each pot's cap is enforced by the runner's
own budget guard and by a check here before a run starts.

Plan, cheapest first inside each group (sql, then tools-lean, then tools):

  p2-base, Sonnet 5.5     base/v2, seeds 11 and 12, N = 40 and 120, arms sql, tools-lean, tools
  p2-variants, Sonnet 5.5 math/v2 seed 11 N = 40 (sql, tools)
                          textdeadlines/v2 N = 40 seeds 11, 12, 13 (sql, tools)
  p2-variants, Haiku 4.5  base/v2 N = 40 seeds 11, 12, 13 (sql, tools); then tools N = 120 seed 11, once
  p2-variants, Sonnet 5.5 math/v2 N = 120 seed 11 (sql, tools), only if the tools arm scored F1 1.00
                          at math N = 40. Seed 12 is skipped by budget (one seed at N = 120). Last,
                          because it is the most expensive group.

A run that ends in an error is retried once. A second error for the same run stops it ("cut").
Exit code 0 always means the sweep finished its plan; read `report` for what was cut or skipped.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from experiment.ledger import Ledger
from experiment.run import MODEL_TAGS
from experiment.sweep import build_index

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
SONNET, HAIKU = "claude-sonnet-5-5", "claude-haiku-4-5"
POT_CAPS = {"p2-base": 3.00, "p2-variants": 3.50}
MIN_START_USD = 0.05  # do not start a run when the pot has less than this left
ARM_ORDER = ("sql", "tools-lean", "tools")
# outcomes that count as a finished run (an outcome is a result: a Haiku overflow is expected)
FINISHED_OUTCOMES = {"answered", "context_overflow", "max_tokens", "refusal", "turn_limit"}


@dataclass(frozen=True)
class Planned:
    group: str
    pot: str
    model: str
    variant: str
    arm: str
    n: int
    seed: int
    rule: str | None = None  # name of a decision rule that must pass first
    skip: str | None = None  # a standing decision to skip this run (reason shown in the report)

    @property
    def run_id(self) -> str:
        return f"{self.variant}-{self.arm}-n{self.n}-s{self.seed}-{MODEL_TAGS[self.model]}"


SKIP_BUDGET = "skipped: budget (one seed at N = 120)"


def _runs(group, pot, model, variant, arms, sizes, seeds, rule=None, skip_seeds=()):
    return [
        Planned(group, pot, model, variant, arm, n, seed, rule, SKIP_BUDGET if seed in skip_seeds else None)
        for arm in arms
        for n in sizes
        for seed in seeds
    ]


def plan() -> list[Planned]:
    return (
        _runs("base, Sonnet", "p2-base", SONNET, "base", ARM_ORDER, (40, 120), (11, 12))
        + _runs("math N=40, Sonnet", "p2-variants", SONNET, "math", ("sql", "tools"), (40,), (11,))
        + _runs("textdeadlines N=40, Sonnet", "p2-variants", SONNET, "textdeadlines", ("sql", "tools"), (40,), (11, 12, 13))
        + _runs("base N=40, Haiku", "p2-variants", HAIKU, "base", ("sql", "tools"), (40,), (11, 12, 13))
        + _runs("base tools N=120, Haiku", "p2-variants", HAIKU, "base", ("tools",), (120,), (11,))
        + _runs("math N=120, Sonnet", "p2-variants", SONNET, "math", ("sql", "tools"), (120,), (11, 12), rule="math120", skip_seeds=(12,))
    )


# ---------- state ----------

def trace_of(results: Path, run_id: str) -> dict | None:
    p = results / "traces" / f"{run_id}.json"
    return json.loads(p.read_text()) if p.exists() else None


def attempts(ledger: Ledger, run_id: str) -> int:
    return sum(1 for r in ledger.data["runs"] if r["run_id"] == run_id)


def rule_verdict(rule: str | None, results: Path) -> str | None:
    """None when the rule passes, else why the run is skipped by rule."""
    if rule is None:
        return None
    if rule == "math120":
        t = trace_of(results, f"math-tools-n40-s11-{MODEL_TAGS[SONNET]}")
        if t is None:
            return "rule: the math N=40 tools run has not finished, so the N=120 rule cannot be decided"
        f1 = (t.get("score") or {}).get("f1")
        if t["outcome"] == "answered" and f1 == 1.0:
            return None
        return f"rule: the tools arm scored F1 {f1 if f1 is not None else 'n/a'} (outcome {t['outcome']}) at math N=40, so N=120 is skipped"
    raise ValueError(rule)


def status(item: Planned, results: Path, ledger: Ledger) -> tuple[str, str]:
    """(state, detail) with state one of done, cut, skipped, pending."""
    t = trace_of(results, item.run_id)
    if t is not None:
        if t["outcome"] in FINISHED_OUTCOMES:
            f1 = (t.get("score") or {}).get("f1")
            return "done", f"{t['outcome']}, F1 {f1 if f1 is not None else 'n/a'}, ${t['totals']['cost_usd']:.4f}"
        if t["outcome"] == "budget_stop":
            return "cut", f"budget_stop: {t['error']}"
        if attempts(ledger, item.run_id) >= 2:
            return "cut", f"error twice: {t['error']}"
        return "pending", f"retry after error: {t['error']}"
    if item.skip:
        return "skipped", item.skip
    why = rule_verdict(item.rule, results)
    if why:
        return "skipped", why
    return "pending", ""


# ---------- running ----------

def run_one(item: Planned, env_file: str, results: Path) -> None:
    cmd = [
        sys.executable, "-m", "experiment.run", "--arm", item.arm, "--variant", item.variant, "--profile", "v2",
        "--n", str(item.n), "--rep", "1", "--seed", str(item.seed), "--model", item.model, "--effort", "medium",
        "--latency", "0.15", "--stage", item.pot, "--pot", item.pot, "--out", str(results),
        "--env-file", env_file, "--ledger", str(results / "ledger.json"), "--force",
    ]
    print(f"[sweep2] {item.run_id} pot={item.pot}", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=False)
    build_index(results)


def cmd_run(args, executor=run_one) -> int:
    results = Path(args.results)
    ledger = Ledger(results / "ledger.json")
    for pot, cap in POT_CAPS.items():
        ledger.ensure_pot(pot, cap)
    for item in plan():
        if args.only_pot and item.pot != args.only_pot:
            continue
        ledger = Ledger(results / "ledger.json")
        state, detail = status(item, results, ledger)
        if state != "pending":
            print(f"[sweep2] {state} {item.run_id}: {detail}", flush=True)
            continue
        left = ledger.cap(item.pot) - ledger.spent(item.pot)
        if left < MIN_START_USD:
            print(f"[sweep2] cut {item.run_id}: pot {item.pot} has ${left:.4f} left (below ${MIN_START_USD})", flush=True)
            continue
        executor(item, args.env_file, results)
    return 0


# ---------- report ----------

def report(results: Path) -> str:
    ledger = Ledger(results / "ledger.json")
    out = []
    rows = {"done": [], "cut": [], "skipped-by-rule": [], "pending": []}
    for item in plan():
        state, detail = status(item, results, ledger)
        if state == "pending" and not detail and ledger.cap(item.pot) - ledger.spent(item.pot) < MIN_START_USD \
                and item.pot in ledger.data["pots"]:
            state, detail = "cut", f"pot {item.pot} has less than ${MIN_START_USD} left"
        rows["skipped-by-rule" if state == "skipped" else state].append((item, detail))
    for label in ("done", "cut", "skipped-by-rule", "pending"):
        out.append(f"{label} ({len(rows[label])})")
        for item, detail in rows[label]:
            out.append(f"  {item.run_id} [{item.pot}, {item.group}]" + (f": {detail}" if detail else ""))
        if not rows[label]:
            out.append("  none")
        out.append("")
    out.append("Spend per pot")
    for pot, d in ledger.data["pots"].items():
        mark = "  OVER CAP" if d["spent"] > d["cap"] else ""
        out.append(f"  {pot}: ${d['spent']:.4f} of ${d['cap']:.2f}{mark}")
    p2 = sum(ledger.data["pots"].get(p, {"spent": 0})["spent"] for p in POT_CAPS)
    out.append(f"  phase 2 total: ${p2:.4f} of ${sum(POT_CAPS.values()):.2f}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["run", "plan", "report", "index"])
    ap.add_argument("--env-file")
    ap.add_argument("--only-pot", choices=sorted(POT_CAPS))
    ap.add_argument("--results", default=str(RESULTS))
    args = ap.parse_args(argv)
    results = Path(args.results)
    if args.command == "plan":
        for i in plan():
            print(f"{i.run_id}\t{i.pot}\t{i.group}" + (f"\t(rule {i.rule})" if i.rule else ""))
        return 0
    if args.command == "report":
        print(report(results))
        return 0
    if args.command == "index":
        print(f"indexed {len(build_index(results))} runs")
        return 0
    if not args.env_file:
        ap.error("run needs --env-file")
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
