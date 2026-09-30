"""Generated tables and sentences for the phase 2 part of WRITEUP.md. Everything here reads results/.

Called by experiment.writeup_tables; no API calls.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from experiment import bytes_table, latency_model, misreadings, sweep2
from experiment.ledger import Ledger

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
SONNET, HAIKU = sweep2.SONNET, sweep2.HAIKU
ARMS = ("sql", "tools-lean", "tools")
ARM_NAMES = {"sql": "sql", "tools-lean": "tools-lean", "tools": "tools"}


# ---------- helpers ----------

def sig2(x: float) -> str:
    """Two significant figures, no exponent: 0.62, 4.5, 2.0, 13, 110."""
    if x == 0:
        return "0"
    if x >= 100:
        return f"{round(x, 2 - len(str(int(x)))):,.0f}"
    if x >= 10:
        return f"{x:.0f}"
    return f"{x:.1f}" if x >= 1 else f"{x:.2f}"


def ratio_str(x: float | None) -> str:
    return "n/a" if x is None else sig2(x) + "x"


def tokens_read(r: dict) -> int:
    return r["input_tokens"] + r["cache_creation_input_tokens"] + r["cache_read_input_tokens"]


def table(head: list[str], body: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(c) + " |" for c in body]
    return "\n".join(out)


def span(vals: list[float], f: str) -> str:
    if not vals:
        return "n/a"
    lo, hi = min(vals), max(vals)
    return f.format(lo) if f.format(lo) == f.format(hi) else f"{f.format(lo)} to {f.format(hi)}"


def base_rows(rows: list[dict], model: str = SONNET) -> list[dict]:
    return [r for r in rows if r["stage"] == "p2-base" and r["variant"] == "base" and r["model"] == model]


def answered(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["outcome"] == "answered"]


def pick(rows, arm, n, seed=None):
    return [r for r in rows if r["arm"] == arm and r["n_matters"] == n and (seed is None or r["seed"] == seed)]


def phase1(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["profile"] == "v1" and r["variant"] == "base"]


def pair_ratios(rows, num_arm, den_arm, n, fn) -> list[float]:
    """Ratio num/den for each seed where both runs were answered."""
    out = []
    for seed in sorted({r["seed"] for r in rows if r["n_matters"] == n}):
        a = answered(pick(rows, num_arm, n, seed))
        b = answered(pick(rows, den_arm, n, seed))
        if a and b and fn(b[0]):
            out.append(fn(a[0]) / fn(b[0]))
    return out


METRICS = [
    ("Cost $", lambda r: r["cost_usd"], "{:.3f}"),
    ("Peak context", lambda r: r["context_peak_tokens"], "{:,.0f}"),
    ("Tokens read", tokens_read, "{:,.0f}"),
    ("Wall s", lambda r: r["wall_ms"] / 1000, "{:.1f}"),
    ("F1", lambda r: r["f1"], "{:.2f}"),
]
RATIO_METRICS = [("Tokens read", tokens_read), ("Cost", lambda r: r["cost_usd"]), ("Wall time", lambda r: r["wall_ms"])]


# ---------- base ranges ----------

def base_ranges_table(rows) -> str:
    b = base_rows(rows)
    head = ["N", "Arm", "Runs answered"] + [m[0] for m in METRICS]
    body = []
    for n in (40, 120):
        for arm in ARMS:
            a = answered(pick(b, arm, n))
            if not a:
                continue
            body.append([str(n), arm, str(len(a))] + [span([fn(r) for r in a], f) for _, fn, f in METRICS])
    return table(head, body)


PAIRS = [("tools", "sql"), ("tools-lean", "sql"), ("tools", "tools-lean")]


def ratio_span(vals: list[float]) -> str:
    lo, hi = sig2(min(vals)), sig2(max(vals))
    return f"{lo}x" if lo == hi else f"{lo}x to {hi}x"


def paired_ratio_table(rows) -> str:
    b = base_rows(rows)
    head = ["N", "Pair (first / second)", "Seeds"] + [f"{m[0]} ratio" for m in RATIO_METRICS]
    body = []
    for n in (40, 120):
        for num, den in PAIRS:
            cols = []
            for _, fn in RATIO_METRICS:
                rs = pair_ratios(b, num, den, n, fn)
                cols.append("n/a" if not rs else ratio_span(rs))
            count = len(pair_ratios(b, num, den, n, tokens_read))
            body.append([str(n), f"{num} / {den}", str(count)] + cols)
    return table(head, body)


def phase1_pair_table(rows) -> str:
    p1 = phase1(rows)
    head = ["N", "Pair (first / second)", "Run pair"] + [f"{m[0]} ratio" for m in RATIO_METRICS]
    body = []
    for n in (40, 120):
        t = [r for r in answered(pick(p1, "tools", n)) if r["stage"] in ("proof", "showcase")]
        s = [r for r in answered(pick(p1, "sql", n)) if r["stage"] in ("proof", "showcase")]
        if not t or not s:
            continue
        cols = [ratio_str(fn(t[0]) / fn(s[0])) for _, fn in RATIO_METRICS]
        body.append([str(n), "tools / sql", f"{t[0]['run_id']}, {s[0]['run_id']} (seed 7)"] + cols)
    return table(head, body)


# ---------- three arms ----------

THREE = [
    ("Cost $", lambda r: r["cost_usd"], "{:.3f}"),
    ("Peak context", lambda r: r["context_peak_tokens"], "{:,.0f}"),
    ("Tokens read", tokens_read, "{:,.0f}"),
    ("Output tokens", lambda r: r["output_tokens"], "{:,.0f}"),
    ("Turns", lambda r: r["turns"], "{:,.1f}"),
    ("Tool calls", lambda r: r["tool_calls"], "{:,.1f}"),
    ("API calls", lambda r: r["api_calls"], "{:,.1f}"),
    ("Wall s", lambda r: r["wall_ms"] / 1000, "{:.1f}"),
    ("F1", lambda r: r["f1"], "{:.2f}"),
]


def three_arm_table(rows) -> str:
    b = base_rows(rows)
    head = ["N", "Arm", "Runs answered"] + [m[0] for m in THREE]
    body = []
    for n in (40, 120):
        for arm in ARMS:
            a = answered(pick(b, arm, n))
            if not a:
                continue
            body.append([str(n), arm, str(len(a))] + [f.format(statistics.mean(fn(r) for r in a)) for _, fn, f in THREE])
    return table(head, body)


# ---------- variants ----------

def load_trace(run_id: str, results: Path = RESULTS) -> dict | None:
    p = results / "traces" / f"{run_id}.json"
    return json.loads(p.read_text()) if p.exists() else None


def errors_text(run_id: str, results: Path = RESULTS) -> str:
    t = load_trace(run_id, results)
    score = (t or {}).get("score")
    if score is None:
        return "n/a (no answer)"
    ebt = score.get("errors_by_trap") or {}
    if not ebt:
        return "none"
    parts = []
    for trap, e in sorted(ebt.items()):
        if e.get("false_positives"):
            parts.append(f"{trap}: {len(e['false_positives'])} false positives")
        if e.get("false_negatives"):
            parts.append(f"{trap}: {len(e['false_negatives'])} false negatives")
    return "; ".join(parts)


def variants_table(rows) -> str:
    v = [r for r in rows if r["stage"] == "p2-variants" and r["variant"] in ("math", "textdeadlines") and r["model"] == SONNET]
    head = ["Variant", "N", "Seed", "Arm", "Outcome", "F1", "Cost $", "Tokens read", "Turns", "Errors by trap"]
    body = []
    for r in sorted(v, key=lambda r: (r["variant"], r["n_matters"], r["seed"], r["arm"] != "sql")):
        body.append([
            r["variant"], str(r["n_matters"]), str(r["seed"]), r["arm"], r["outcome"],
            "n/a" if r["f1"] is None else f"{r['f1']:.2f}", f"{r['cost_usd']:.3f}", f"{tokens_read(r):,}",
            str(r["turns"]), errors_text(r["run_id"]),
        ])
    return table(head, body)


# ---------- Haiku ----------

def haiku_table(rows) -> str:
    h = [r for r in rows if r["model"] == HAIKU]
    head = ["Run", "Outcome", "F1", "Cost $", "Peak context", "Turns", "Errors by trap"]
    body = []
    for r in sorted(h, key=lambda r: (r["n_matters"], r["arm"] != "sql", r["seed"])):
        body.append([
            r["run_id"], r["outcome"], "n/a" if r["f1"] is None else f"{r['f1']:.2f}", f"{r['cost_usd']:.3f}",
            f"{r['context_peak_tokens']:,}", str(r["turns"]), errors_text(r["run_id"]),
        ])
    return table(head, body)


def haiku_facts(rows) -> dict:
    h = [r for r in rows if r["model"] == HAIKU]
    over = [r for r in h if r["outcome"] == "context_overflow"]
    first = {}
    for r in h:
        if r["arm"] == "sql":
            t = load_trace(r["run_id"])
            if t and t["turns"]:
                first[r["run_id"]] = t["turns"][0]
    return {"runs": len(h), "overflow": [r["run_id"] for r in over], "first_turn": first}


# ---------- latency ----------

def latency_table(rows) -> str:
    ids = [r["run_id"] for r in base_rows(rows) if r["n_matters"] in (40, 120) and r["outcome"] == "answered"]
    ids += [r["run_id"] for r in phase1(rows) if r["stage"] in ("proof", "showcase") and r["n_matters"] in (40, 120)
            and r["outcome"] == "answered"]
    data = []
    for i in ids:
        t = load_trace(i)
        if t:
            m = latency_model.model_trace(t)
            m["wall_ms"] = t["totals"]["wall_ms"]
            m["n"] = t["n_matters"]
            data.append(m)
    head = ["Run", "N", "Recorded wall s", "Recorded tools s", "Modeled tools s", "Modeled wall s", "Modeled wall s, SQL mail x10"]
    body = []
    s = lambda ms: f"{ms / 1000:.1f}"  # noqa: E731
    for m in sorted(data, key=lambda m: (m["n"], m["run_id"])):
        x10 = m.get("modeled_wall_ms_mail_x10")
        body.append([m["run_id"], str(m["n"]), s(m["wall_ms"]), s(m["recorded_tools_ms"]), s(m["modeled_tools_ms"]),
                     s(m["modeled_wall_ms"]), "n/a" if x10 is None else s(x10)])
    return table(head, body)


def latency_ratio(rows, n: int, key: str) -> float | None:
    """Median modeled wall ratio tools / sql over the p2-base seeds at this N."""
    b = base_rows(rows)
    out = []
    for seed in sorted({r["seed"] for r in b}):
        t, s = answered(pick(b, "tools", n, seed)), answered(pick(b, "sql", n, seed))
        if not t or not s:
            continue
        mt, ms = latency_model.model_trace(load_trace(t[0]["run_id"])), latency_model.model_trace(load_trace(s[0]["run_id"]))
        num = mt["modeled_wall_ms"]
        den = ms["modeled_wall_ms_mail_x10"] if key == "x10" else ms["modeled_wall_ms"]
        out.append(num / den)
    return statistics.median(out) if out else None


# ---------- cut and skipped ----------

def cut_and_skipped_table(results: Path = RESULTS) -> str:
    ledger = Ledger(results / "ledger.json")
    body = []
    for p in sorted((results / "traces" / "cut").glob("*.json")):
        t = json.loads(p.read_text())
        body.append([t["run_id"], "cut (first attempt)", t["error"].replace("budget_stop: ", "budget_stop: ", 1) if t["outcome"] == "budget_stop" else t["outcome"],
                     f"${t['totals']['cost_usd']:.3f}"])
    for item in sweep2.plan():
        state, detail = sweep2.status(item, results, ledger)
        if state in ("skipped", "cut", "pending"):
            t = load_trace(item.run_id, results)
            spent = t["totals"]["cost_usd"] if t and t["outcome"] == "budget_stop" else 0.0
            body.append([item.run_id, state, detail.replace("budget_stop: budget_stop:", "budget_stop:") or "not run", f"${spent:.3f}"])
    return table(["Run", "State", "Why", "Spend on the cut attempt"], body)


def spend_table(results: Path = RESULTS) -> str:
    ledger = Ledger(results / "ledger.json")
    body = [[pot, f"${ledger.spent(pot):.2f}", f"${ledger.cap(pot):.2f}"] for pot in sweep2.POT_CAPS]
    body.append(["Phase 2 total", f"${sum(ledger.spent(p) for p in sweep2.POT_CAPS):.2f}", f"${sum(ledger.cap(p) for p in sweep2.POT_CAPS):.2f}"])
    return table(["Pot", "Spent", "Cap"], body)


def wasted_usd(results: Path = RESULTS) -> float:
    total = sum(json.loads(p.read_text())["totals"]["cost_usd"] for p in (results / "traces" / "cut").glob("*.json"))
    for p in (results / "traces").glob("*.json"):
        t = json.loads(p.read_text())
        if t["outcome"] == "budget_stop":
            total += t["totals"]["cost_usd"]
    return total


# ---------- generated sentences ----------

NUMBER_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four"}


def haiku_cache_sentence(rows) -> str:
    """Which Haiku SQL runs cached later turns, from the traces."""
    sql = sorted([r for r in rows if r["model"] == HAIKU and r["arm"] == "sql"], key=lambda r: r["seed"])
    cached, never = [], []
    for r in sql:
        t = load_trace(r["run_id"])
        used = any(x["usage"].get("cache_creation_input_tokens", 0) > 0 for x in t["turns"])
        (cached if used else never).append(r)
    if not never:
        return f"All {len(sql)} Haiku SQL runs cached later turns."
    seeds = ", ".join(f"seed {r['seed']}" for r in never)
    return (f"{NUMBER_WORDS[len(cached)]} of {NUMBER_WORDS[len(sql)].lower()} Haiku SQL runs did cache later turns, once the "
            f"conversation passed that length; only {seeds} never cached.")


def haiku_notes(rows) -> str:
    facts = haiku_facts(rows)
    h = [r for r in rows if r["model"] == HAIKU]
    peak = max(r["context_peak_tokens"] for r in h)
    firsts = [t["context_tokens"] for t in facts["first_turn"].values()]
    lines = [
        f"- The largest peak context in any Haiku run was {peak:,} tokens. "
        + ("Runs that overflowed the 200,000-token window: " + ", ".join(facts["overflow"]) + "."
           if facts["overflow"] else "No Haiku run reached its 200,000-token window, so there was no overflow to record."),
        f"- Haiku's SQL runs opened with a prompt of {min(firsts):,} to {max(firsts):,} tokens. Haiku 4.5 needs at least 4,096 "
        "tokens in a prompt before it will cache it (Anthropic's documented minimum), so the opening prompt could not be cached. "
        + haiku_cache_sentence(rows),
    ]
    for r in h:
        t = load_trace(r["run_id"])
        sc = (t or {}).get("score")
        if sc and sc["submitted_count"] == 0 and sc["expected_count"]:
            lines.append(f"- {r['run_id']} submitted an empty list: 0 of {sc['expected_count']} at-risk matters found, "
                         f"{sc['false_positives'] if isinstance(sc['false_positives'], int) else len(sc['false_positives'])} false positives.")
    return "\n".join(lines)


def variant_notes(rows) -> str:
    lines = []
    for r in rows:
        if r["model"] == SONNET and r["variant"] in ("math", "textdeadlines") and r["outcome"] != "answered":
            t = load_trace(r["run_id"])
            last = t["turns"][-1]
            lines.append(
                f"- {r['run_id']} ended with outcome {r['outcome']} and no answer. Its last model call had a context of "
                f"{last['context_tokens']:,} tokens and wrote {last['usage']['output_tokens']:,} output tokens (this harness's per-reply cap) "
                f"and cost ${last['cost_usd']:.2f}, out of ${r['cost_usd']:.2f} for the run."
            )
            if last["stop_reason"] == "max_tokens" and not (last.get("text") or "").strip() and not last["tool_calls"]:
                lines[-1] += (f" Its last reply used the harness's {last['usage']['output_tokens']:,}-token output cap with no "
                              "visible text and no tool call, so the tokens likely went to internal reasoning (deduced).")
    lines.append(textdeadlines_note(rows))
    return "\n".join(lines)


def textdeadlines_note(rows) -> str:
    """SQL agent's cost with deadlines in free text, and how it compares with the tools agent (N=40)."""
    td = [r for r in rows if r["variant"] == "textdeadlines" and r["model"] == SONNET and r["outcome"] == "answered"]
    sql = {r["seed"]: r["cost_usd"] for r in td if r["arm"] == "sql"}
    tools = {r["seed"]: r["cost_usd"] for r in td if r["arm"] == "tools"}
    base = [r["cost_usd"] for r in answered(pick(base_rows(rows), "sql", 40))]
    r_ = [tools[s] / sql[s] for s in sorted(sql) if s in tools]
    return (f"- SQL agent, deadlines in free text, 40 matters: its own cost roughly triples when deadlines hide in free text "
            f"(base task {span(base, '${:.3f}')} per run, deadlines in text {span(list(sql.values()), '${:.3f}')}), though it stays "
            f"about {span(r_, '{:.1f}x')} cheaper than the tools agent ({len(r_)} paired seeds).")


def cut_notes(results: Path = RESULTS) -> str:
    ledger = Ledger(results / "ledger.json")
    return "\n".join([
        f"- Spend on attempts that were cut by a pot cap before answering: ${wasted_usd(results):.2f}.",
        f"- The pots started at ${sweep2.POT_CAPS['p2-base']:.2f} (p2-base) and ${sweep2.POT_CAPS['p2-variants']:.2f} (p2-variants). "
        f"They were raised to ${ledger.cap('p2-base'):.2f} and ${ledger.cap('p2-variants'):.2f} after the first attempts were cut. "
        f"No pot went over its cap. Together the pots spent ${sum(ledger.spent(p) for p in sweep2.POT_CAPS):.2f}, "
        f"above the ${sum(sweep2.POT_CAPS.values()):.2f} first planned for phase 2, because of the top-up.",
    ])


# ---------- bytes reading ----------

def bytes_note() -> str:
    data = bytes_table.rows()
    shares = [100 * sum(d["lean"].values()) / sum(d["raw"].values()) for d in data]
    return (f"- Reading: even trimmed, a full pull is {span(shares, '{:.1f}')}% of raw, while the SQL agent saw under 1 KB of rows. "
            "The SQL server still pulled the full raw data upstream.")


# ---------- assemble ----------

def build_block(rows: list[dict]) -> str:
    parts = [
        "#### Base task on new data, ranges across seeds 11 and 12 (Sonnet 5.5)", base_ranges_table(rows),
        "#### Paired ratios per seed, min to max across seeds", paired_ratio_table(rows),
        "#### Phase 1 pair for comparison (seed 7, no cache isolation)", phase1_pair_table(rows),
        "#### Three arms, mean of the two seeds", three_arm_table(rows),
        "#### Harder variants (Sonnet 5.5)", variants_table(rows), variant_notes(rows),
        "#### Haiku 4.5, base task", haiku_table(rows), haiku_notes(rows),
        "#### One-rule misreadings, F1 (+false positives / -false negatives), free from the oracle", misreadings.markdown(),
        "#### Timings under a slower, limited upstream (500 ms per call, 10 at once)", latency_table(rows),
        "#### Bytes, phase 1 data (seed 7): a full pull of all four systems, raw vs trimmed, vs SQL rows shown to the model", bytes_table.markdown(), bytes_note(),
        "#### Cut and skipped runs", cut_and_skipped_table(), cut_notes(),
        "#### Spend", spend_table(),
    ]
    return "\n\n".join(parts)
