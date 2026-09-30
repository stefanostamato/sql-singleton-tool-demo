"""Verdict rules and marker rewriting for the writeup tables."""

from experiment import writeup_tables as w

BASE = {
    "stage": "proof", "model": "m", "outcome": "answered", "turns": 1, "tool_calls": 1, "api_calls": 1,
    "input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 100,
    "wall_ms": 1000, "cost_usd": 0.1, "f1": 1.0, "rep": 1, "context_peak_tokens": 100,
}


def row(arm, n, tokens, out=100, wall=1000, f1=1.0, outcome="answered"):
    return BASE | {
        "run_id": f"{arm}-n{n}-r1", "arm": arm, "n_matters": n, "input_tokens": tokens, "output_tokens": out,
        "wall_ms": wall, "f1": f1, "outcome": outcome,
    }


def verdict(rows):
    return {pid: v for pid, _, _, v in w.verdicts(rows)}


def test_verdict_bands_and_growth():
    rows = [
        row("sql", 10, 1000), row("tools", 10, 2000),
        row("sql", 20, 1000), row("tools", 20, 8000, out=300, wall=9000, f1=0.8),
        row("sql", 40, 1000), row("tools", 40, 20000, out=300, wall=20000, f1=0.8),
    ]
    v = verdict(rows)
    assert v["P1"] == "held"  # worst ratio is 8x
    assert v["P2"] == "held"
    assert v["P3"] == "held"  # 3x
    assert v["P4"] == "held"  # 2, 8, 20
    assert v["P5"] == "held"


def test_verdict_partly_and_not():
    rows = [
        row("sql", 10, 1000), row("tools", 10, 5000),
        row("sql", 20, 1000), row("tools", 20, 4000, out=100, f1=1.0),
        row("sql", 40, 1000), row("tools", 40, 2000, out=100, f1=1.0),
    ]
    v = verdict(rows)
    assert v["P1"] == "did not hold"  # worst is 2x
    assert v["P3"] == "did not hold"
    assert v["P4"] == "did not hold"  # 5, 4, 2
    assert v["P5"] == "not tested (ceiling)"  # both arms perfect
    rows[3] = row("tools", 20, 5000, out=160)
    assert verdict(rows)["P1"] == "did not hold"
    rows = [row("sql", 20, 1000), row("tools", 20, 5000, out=170)]
    assert verdict(rows)["P1"] == "partly held" and verdict(rows)["P3"] == "partly held"


def test_p3_larger_than_predicted_and_unanswered_ignored():
    rows = [row("sql", 20, 1000), row("tools", 20, 9000, out=900), row("tools", 40, 1, outcome="budget_stop")]
    assert verdict(rows)["P3"] == "held, larger than predicted"
    assert "1 budget_stop" in w.scaling_table(rows)


def test_rewrite_is_idempotent():
    text = f"a\n{w.START}\nold\n{w.END}\nb\n"
    once = w.rewrite(text, "block")
    assert "old" not in once and w.rewrite(once, "block") == once
