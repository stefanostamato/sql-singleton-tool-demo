"""Generated TL;DR bullets for WRITEUP.md, so every number in them comes from results/.

Called by experiment.writeup_tables; no API calls.
"""

from __future__ import annotations

import statistics

from experiment import robustness_tables as rt
from experiment.robustness_tables import HAIKU, SONNET, answered, base_rows, pick, ratio_span, ratio_str, sig2, span, tokens_read


def usd(x: float) -> str:
    return f"${x:.3f}" if x < 0.1 else f"${x:.2f}"


def usd_span(vals: list[float]) -> str:
    lo, hi = min(vals), max(vals)
    return usd(lo) if usd(lo) == usd(hi) else f"{usd(lo)} to {usd(hi)}"


def ctx_span(vals: list[float]) -> str:
    lo, hi = min(vals), max(vals)
    return f"{lo:,.0f}" if lo == hi else f"{lo:,.0f} to {hi:,.0f}"


def sonnet_answered(rows: list[dict]) -> list[dict]:
    """Every answered Sonnet run in phase 2, all variants."""
    return [r for r in rows if r["model"] == SONNET and r["profile"] == "v2" and r["outcome"] == "answered"]


def bullets(rows: list[dict]) -> list[str]:
    b = base_rows(rows)
    a = lambda arm, n: answered(pick(b, arm, n))  # noqa: E731
    out = []

    # 1. cost and peak context first
    s120, t120, l120 = a("sql", 120), a("tools", 120), a("tools-lean", 120)
    out.append(
        f"On the base task at 120 matters, the SQL agent cost {usd_span([r['cost_usd'] for r in s120])} per run and its "
        f"peak context was {ctx_span([r['context_peak_tokens'] for r in s120])} tokens. The tools agent cost "
        f"{usd_span([r['cost_usd'] for r in t120])} with a peak context of {ctx_span([r['context_peak_tokens'] for r in t120])} "
        f"tokens (one seed; seed 12 was stopped twice by the budget cap, not by the model). The trimmed-tools agent cost {usd_span([r['cost_usd'] for r in l120])} "
        f"with a peak context of {ctx_span([r['context_peak_tokens'] for r in l120])} tokens."
    )
    # 2. paired ratios
    rc = rt.pair_ratios(b, "tools", "sql", 40, lambda r: r["cost_usd"])
    rk = rt.pair_ratios(b, "tools", "sql", 40, tokens_read)
    rc1 = rt.pair_ratios(b, "tools", "sql", 120, lambda r: r["cost_usd"])
    rk1 = rt.pair_ratios(b, "tools", "sql", 120, tokens_read)
    p1 = rt.phase1(rows)
    p1t = [r for r in answered(pick(p1, "tools", 120)) if r["stage"] in ("proof", "showcase")]
    p1s = [r for r in answered(pick(p1, "sql", 120)) if r["stage"] in ("proof", "showcase")]
    out.append(
        f"Paired tools/sql cost ratios: {ratio_span(rc)} at 40 matters (two seeds) and {ratio_span(rc1)} at 120 matters "
        f"({len(rc1)} pair). Tokens read ratios: {ratio_span(rk)} and {ratio_span(rk1)}. Phase 1 (one seed, no cache "
        f"isolation) had {ratio_str(p1t[0]['cost_usd'] / p1s[0]['cost_usd'])} for cost and "
        f"{ratio_str(tokens_read(p1t[0]) / tokens_read(p1s[0]))} for tokens read at 120 matters."
    )
    # 3. trimmed tools
    lc40 = rt.pair_ratios(b, "tools-lean", "sql", 40, lambda r: r["cost_usd"])
    lc120 = rt.pair_ratios(b, "tools-lean", "sql", 120, lambda r: r["cost_usd"])
    lw120 = rt.pair_ratios(b, "tools-lean", "sql", 120, lambda r: r["wall_ms"])
    lo, hi = min(lc40 + lc120), max(lc40 + lc120)
    out.append(
        "Held under trimming: trimming records lowered peak context and cost, more at 40 matters than at 120, but the "
        f"trimmed agent still cost {ratio_str(lo)} to {ratio_str(hi)} the SQL agent. At 120 it was also slower than plain tools."
    )
    # 4. accuracy
    sa = sonnet_answered(rows)
    perfect = [r for r in sa if r["f1"] == 1.0]
    out.append(
        f"Accuracy did not separate the arms on Sonnet 5.5 at these sizes: F1 was 1.00 in {len(perfect)} of {len(sa)} answered "
        f"phase 2 runs (trimmed tools ran only on the base task). No run missed a matter or added a wrong one."
        if len(perfect) == len(sa) else
        f"On Sonnet 5.5, F1 was 1.00 in {len(perfect)} of {len(sa)} answered phase 2 runs."
    )
    # 5. variants
    m = {(r["arm"], r["n_matters"]): r for r in rows if r["variant"] == "math" and r["model"] == SONNET}
    td = [r for r in rows if r["variant"] == "textdeadlines"]
    td_sql = [r["cost_usd"] for r in td if r["arm"] == "sql"]
    td_tools = [r["cost_usd"] for r in td if r["arm"] == "tools"]
    base40_sql = [r["cost_usd"] for r in a("sql", 40)]
    mt120 = m.get(("tools", 120))
    out.append(
        f"The arithmetic variant did not trip the tools agent when it answered (F1 {m[('tools', 40)]['f1']:.2f} at 40 matters, "
        f"{usd(m[('tools', 40)]['cost_usd'])}). At 120 matters it stopped with outcome {mt120['outcome']} after "
        f"{usd(mt120['cost_usd'])}, with no answer, while the SQL agent answered with F1 {m[('sql', 120)]['f1']:.2f} for "
        f"{usd(m[('sql', 120)]['cost_usd'])}. The deadlines-in-text variant did not trip either agent (F1 "
        f"{span([r['f1'] for r in td], '{:.2f}')} in {len(td)} runs); at 40 matters the SQL agent then "
        f"cost {usd_span(td_sql)} per run (base task: {usd_span(base40_sql)}) and the tools agent {usd_span(td_tools)}."
    )
    # 6. Haiku
    h = [r for r in rows if r["model"] == HAIKU]
    hs = sorted([r for r in h if r["arm"] == "sql"], key=lambda r: r["seed"])
    ht = sorted([r for r in h if r["arm"] == "tools" and r["n_matters"] == 40], key=lambda r: r["seed"])
    h120 = [r for r in h if r["n_matters"] == 120]
    ov = [r for r in h if r["outcome"] == "context_overflow"]
    h120txt = ""
    if h120:
        r = h120[0]
        assert r["outcome"] == "answered" and r["f1"] == 0.0 and not ov
        h120txt = (
            f" At 120 matters its tools run submitted an empty list (F1 {r['f1']:.2f}) without hitting its 200,000-token "
            "window. There was no Haiku SQL run at 120."
        )
    out.append(
        f"Haiku 4.5 is where accuracy did separate the arms. Its SQL agent scored F1 {', '.join(f'{r['f1']:.2f}' for r in hs)} "
        f"(cost {usd_span([r['cost_usd'] for r in hs])}); its tools agent scored F1 {', '.join(f'{r['f1']:.2f}' for r in ht)} "
        f"at 40 matters (cost {usd_span([r['cost_usd'] for r in ht])}).{h120txt}"
    )
    # 7. where SQL was worse
    x10 = rt.latency_ratio(rows, 120, "x10")
    x1 = rt.latency_ratio(rows, 120, "x1")
    sql_api = [r["api_calls"] for r in s120]
    tools_api = [r["api_calls"] for r in t120]
    out.append(
        f"Where SQL was worse: it makes far more upstream API calls behind its one tool ({ctx_span(sql_api)} against "
        f"{ctx_span(tools_api)} at 120 matters). Under a slower, limited upstream (500 ms a call, 10 at once) the modeled "
        f"tools/sql wall-time ratio at 120 matters is {sig2(x1)}x. With ten times the mail pages it is {sig2(x10)}x. Only the SQL "
        "server's load grows in that case, because it pulls all mail while the tools agents filtered mail by date. That is "
        "the missing predicate pushdown caveat, priced."
    )
    # 8. wall time
    w40 = rt.pair_ratios(b, "tools", "sql", 40, lambda r: r["wall_ms"])
    w120 = rt.pair_ratios(b, "tools", "sql", 120, lambda r: r["wall_ms"])
    out.append(
        f"Wall time did not drop 10x in the recorded runs: tools/sql was {ratio_span(w40)} at 40 matters and "
        f"{ratio_span(w120)} at 120 matters."
    )
    # 9. sample size
    sonnet_n = len([r for r in rows if r["model"] == SONNET and r["profile"] == "v2"])
    out.append(
        f"Sample sizes are small: {len(rows)} runs in total, {sonnet_n} on Sonnet in phase 2, at most two seeds per Sonnet base cell "
        f"and one at 120 matters in the variants. Read the ranges as a first look, not as statistics."
    )
    return out


def build_block(rows: list[dict]) -> str:
    return "\n".join(f"- {b}" for b in bullets(rows))
