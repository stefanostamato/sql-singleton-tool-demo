"""Regenerate the tables in WRITEUP.md from results/index.json.

    python -m experiment.writeup_tables

Only the text between the tables:start and tables:end markers is replaced.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START, END = "<!-- tables:start -->", "<!-- tables:end -->"


def tokens_read(r: dict) -> int:
    return r["input_tokens"] + r["cache_creation_input_tokens"] + r["cache_read_input_tokens"]


METRICS = [
    ("Cost $", lambda r: r["cost_usd"], "{:,.3f}"),
    ("Peak context", lambda r: r["context_peak_tokens"], "{:,.0f}"),
    ("Tokens read", tokens_read, "{:,.0f}"),
    ("Output tokens", lambda r: r["output_tokens"], "{:,.0f}"),
    ("Turns", lambda r: r["turns"], "{:,.0f}"),
    ("Tool calls", lambda r: r["tool_calls"], "{:,.0f}"),
    ("API calls", lambda r: r["api_calls"], "{:,.0f}"),
    ("Wall s", lambda r: r["wall_ms"] / 1000, "{:,.1f}"),
    ("F1", lambda r: r["f1"], "{:.2f}"),
]


def sig2(x: float) -> str:
    """Two significant figures, no exponent: 0.62, 4.5, 2.0, 13, 110."""
    if x >= 100:
        return f"{round(x, 2 - len(str(int(x)))):,.0f}"
    if x >= 10:
        return f"{x:.0f}"
    return f"{x:.1f}" if x >= 1 else f"{x:.2f}"


def answered(rows, arm, n):
    return [r for r in rows if r["arm"] == arm and r["n_matters"] == n and r["outcome"] == "answered"]


def median_of(rows, fn):
    vals = [fn(r) for r in rows if fn(r) is not None]
    return statistics.median(vals) if vals else None


def fmt(v, f):
    return "n/a" if v is None else f.format(v)


def others(rows, arm, n):
    """Non-answered outcomes as text, e.g. '1 budget_stop'."""
    counts: dict[str, int] = {}
    for r in rows:
        if r["arm"] == arm and r["n_matters"] == n and r["outcome"] != "answered":
            counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    return ", ".join(f"{c} {o}" for o, c in sorted(counts.items())) or "none"


def sizes(rows):
    return sorted({r["n_matters"] for r in rows})


def ratio_at(rows, n, fn):
    t, s = answered(rows, "tools", n), answered(rows, "sql", n)
    if not t or not s:
        return None
    mt, ms = median_of(t, fn), median_of(s, fn)
    return mt / ms if ms else None


def scaling_table(rows):
    head = ["N", "Arm", "Runs answered", "Not answered"] + [m[0] for m in METRICS]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for n in sizes(rows):
        for arm in ("tools", "sql"):
            a = answered(rows, arm, n)
            if not a and others(rows, arm, n) == "none":
                continue
            cells = [str(n), arm, str(len(a)), others(rows, arm, n)]
            cells += [fmt(median_of(a, fn), f) for _, fn, f in METRICS]
            out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def ratio_table(rows):
    cols = [m for m in METRICS if m[0] != "F1"]
    head = ["N"] + [c[0] for c in cols]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for n in sizes(rows):
        rs = [ratio_at(rows, n, fn) for _, fn, _ in cols]
        if all(r is None for r in rs):
            continue
        out.append("| " + " | ".join([str(n)] + ["n/a" if r is None else f"{sig2(r)}x" for r in rs]) + " |")
    return "\n".join(out)


def showcase_table(rows):
    sc = [r for r in rows if r["stage"] == "showcase"]
    head = ["Run", "Outcome"] + [m[0] for m in METRICS]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in sorted(sc, key=lambda r: r["arm"], reverse=True):
        out.append("| " + " | ".join([r["run_id"], r["outcome"]] + [fmt(fn(r), f) for _, fn, f in METRICS]) + " |")
    return "\n".join(out)


def band(ratios, held=7.0, partly=3.0):
    if not ratios:
        return "no data"
    w = min(ratios)
    return "held" if w >= held else "partly held" if w >= partly else "did not hold"


def verdicts(rows):
    big = [n for n in sizes(rows) if n >= 20 and ratio_at(rows, n, tokens_read) is not None]
    r_tok = [ratio_at(rows, n, tokens_read) for n in big]
    r_wall = [ratio_at(rows, n, lambda r: r["wall_ms"]) for n in big]
    r_out = [ratio_at(rows, n, lambda r: r["output_tokens"]) for n in big]
    p3 = "no data"
    if r_out:
        if all(2 <= r <= 5 for r in r_out):
            p3 = "held"
        elif all(r >= 2 for r in r_out) and any(r > 5 for r in r_out):
            p3 = "held, larger than predicted"
        elif any(r >= 1.5 for r in r_out):
            p3 = "partly held"
        else:
            p3 = "did not hold"
    g = [n for n in sizes(rows) if n >= 10 and ratio_at(rows, n, tokens_read) is not None]
    gr = [ratio_at(rows, n, tokens_read) for n in g]
    if len(gr) < 2:
        p4 = "no data"
    elif all(b > a for a, b in zip(gr, gr[1:])):
        p4 = "held"
    elif gr[-1] > gr[0]:
        p4 = "partly held"
    else:
        p4 = "did not hold"
    f_t = [r["f1"] for r in rows if r["arm"] == "tools" and r["outcome"] == "answered" and r["f1"] is not None]
    f_s = [r["f1"] for r in rows if r["arm"] == "sql" and r["outcome"] == "answered" and r["f1"] is not None]
    if not f_t or not f_s:
        p5 = "no data"
    elif min(f_t) == 1.0 and min(f_s) == 1.0:
        p5 = "not tested (ceiling)"
    else:
        p5 = "held" if statistics.mean(f_t) < statistics.mean(f_s) else "did not hold"

    def rng(rs):
        return "n/a" if not rs else ", ".join(f"{sig2(r)}x" for r in rs)

    return [
        ("P1", "At 20+ matters, tokens read drop about 10x", f"tools/sql at N={big}: {rng(r_tok)}", band(r_tok)),
        ("P2", "At 20+ matters, wall time drops about 10x", f"tools/sql at N={big}: {rng(r_wall)}", band(r_wall)),
        ("P3", "Output tokens drop 2 to 5x", f"tools/sql at N={big}: {rng(r_out)}", p3),
        ("P4", "The gap widens as N grows", f"tokens-read ratio at N={g}: {rng(gr)}", p4),
        (
            "P5",
            "Hand-done aggregation is where errors come from",
            "mean F1 tools "
            + ("n/a" if not f_t else f"{statistics.mean(f_t):.2f}")
            + ", sql "
            + ("n/a" if not f_s else f"{statistics.mean(f_s):.2f}"),
            p5,
        ),
    ]


def predictions_table(rows):
    out = ["| # | Prediction | Actual | Verdict |", "|---|---|---|---|"]
    for pid, text, actual, verdict in verdicts(rows):
        out.append(f"| {pid} | {text} | {actual} | {verdict} |")
    return "\n".join(out)


def build_block(rows) -> str:
    rows = [r for r in rows if r["profile"] == "v1" and r["variant"] == "base"]  # phase 1
    parts = [
        "#### Scaling by N (median of answered runs)",
        scaling_table(rows),
        "#### Ratio tools / sql by N (ratio of medians)",
        ratio_table(rows),
        "#### Showcase pair",
        showcase_table(rows),
        "#### Predictions and verdicts",
        predictions_table(rows),
    ]
    return "\n\n".join(parts)


def rewrite(text: str, block: str, name: str = "tables") -> str:
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit(f"WRITEUP.md has no {name} markers")
    return pattern.sub(lambda _: f"{start}\n\n{block}\n\n{end}", text, count=1)


def main() -> int:
    from experiment import robustness_tables, tldr

    rows = json.loads((ROOT / "results" / "index.json").read_text())
    path = ROOT / "WRITEUP.md"
    text = rewrite(path.read_text(), build_block(rows))
    text = rewrite(text, robustness_tables.build_block(rows), "robust")
    text = rewrite(text, tldr.build_block(rows), "tldr")
    path.write_text(text)
    print("WRITEUP.md tables regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
