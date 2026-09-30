"""Phase 2 sweep logic with a fake executor: plan order, decision rules, resume, caps, report. No API."""

import json
from argparse import Namespace

from experiment import sweep2
from experiment.ledger import Ledger

TOTAL_KEYS = (
    "turns", "tool_calls", "api_calls", "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
    "output_tokens", "context_peak_tokens", "result_bytes", "wall_ms", "model_ms", "tools_ms",
)


def trace(item, outcome="answered", f1=1.0, cost=0.1, error=None):
    return {
        "run_id": item.run_id, "arm": item.arm, "variant": item.variant, "profile": "v2", "seed": item.seed,
        "n_matters": item.n, "rep": 1, "stage": item.pot, "pot": item.pot, "model": item.model, "outcome": outcome,
        "error": error, "started_at": "2026-09-30T00:00:00Z",
        "totals": {k: 1 for k in TOTAL_KEYS} | {"cost_usd": cost},
        "score": {"precision": f1, "recall": f1, "f1": f1, "grouping_exact": True} if outcome == "answered" else None,
    }


class Fake:
    """Stands in for the runner: writes a trace and books the spend in the ledger.

    `script` maps a run id to a list of (outcome, f1, error), one entry per attempt (the last repeats)."""

    def __init__(self, script=None, cost=0.1):
        self.script, self.cost, self.ran = script or {}, cost, []

    def __call__(self, item, env_file, results):
        self.ran.append(item.run_id)
        attempts = self.script.get(item.run_id, [("answered", 1.0, None)])
        outcome, f1, err = attempts[min(self.ran.count(item.run_id), len(attempts)) - 1]
        ledger = Ledger(results / "ledger.json")
        ledger.add(item.pot, item.run_id, item.model, self.cost)
        ledger.finish(item.pot, item.run_id, item.model)
        (results / "traces").mkdir(parents=True, exist_ok=True)
        (results / "traces" / f"{item.run_id}.json").write_text(json.dumps(trace(item, outcome, f1, self.cost, err)))


def run(tmp_path, fake, only_pot=None):
    return sweep2.cmd_run(Namespace(results=str(tmp_path), env_file="e", only_pot=only_pot), executor=fake)


def test_plan_matches_the_phase_doc_and_is_cheapest_first():
    items = sweep2.plan()
    assert len(items) == 12 + 2 + 6 + 6 + 1 + 4
    base = [i for i in items if i.pot == "p2-base"]
    assert [i.arm for i in base] == ["sql"] * 4 + ["tools-lean"] * 4 + ["tools"] * 4
    assert {(i.n, i.seed) for i in base} == {(40, 11), (40, 12), (120, 11), (120, 12)}
    assert all(i.model == sweep2.SONNET and i.variant == "base" for i in base)
    ids = [i.run_id for i in items]
    assert len(set(ids)) == len(ids)
    assert "math-tools-n40-s11-sonnet" in ids and "textdeadlines-sql-n40-s13-sonnet" in ids
    assert "base-tools-n120-s11-haiku" in ids and "math-sql-n120-s12-sonnet" in ids
    haiku = [i for i in items if i.model == sweep2.HAIKU]
    assert [i.arm for i in haiku] == ["sql"] * 3 + ["tools"] * 3 + ["tools"]
    text = [i for i in items if i.variant == "textdeadlines"]
    assert [i.arm for i in text] == ["sql"] * 3 + ["tools"] * 3
    assert [i.rule for i in items if i.n == 120 and i.variant == "math"] == ["math120"] * 4
    assert {i.pot for i in items} == {"p2-base", "p2-variants"}


def test_run_adds_pots_never_changes_phase_1_and_rule_passes(tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps({
        "pots": {"dev": {"cap": 1.0, "spent": 0.5}, "proof": {"cap": 2.0, "spent": 0.8}}, "runs": [],
    }))
    fake = Fake(cost=0.01)
    assert run(tmp_path, fake) == 0
    after = json.loads((tmp_path / "ledger.json").read_text())["pots"]
    assert after["dev"] == {"cap": 1.0, "spent": 0.5} and after["proof"] == {"cap": 2.0, "spent": 0.8}
    assert after["p2-base"]["cap"] == 3.0 and after["p2-variants"]["cap"] == 3.5
    assert len(fake.ran) == 29  # the rule passed; math N=120 seed 12 is skipped by budget
    assert fake.ran[0].startswith("base-sql-n40-s11")
    # math N=120 comes after everything else
    assert fake.ran.index("math-sql-n120-s11-sonnet") > fake.ran.index("base-tools-n120-s11-haiku")


def test_rule_skips_math_120_when_tools_is_not_perfect(tmp_path):
    fake = Fake({"math-tools-n40-s11-sonnet": [("answered", 0.86, None)]}, cost=0.01)
    run(tmp_path, fake)
    assert not any("math" in r and "n120" in r for r in fake.ran) and len(fake.ran) == 27
    text = sweep2.report(tmp_path)
    assert "skipped-by-rule (4)" in text and "F1 0.86" in text
    fake2 = Fake({"math-tools-n40-s11-sonnet": [("context_overflow", None, None)]}, cost=0.01)
    run(tmp_path / "b", fake2)
    assert not any("math" in r and "n120" in r for r in fake2.ran)


def test_resume_skips_finished_runs_and_retries_one_error(tmp_path):
    rid = "base-sql-n40-s11-sonnet"
    first = Fake({rid: [("error", None, "boom"), ("answered", 1.0, None)]}, cost=0.01)
    run(tmp_path, first, only_pot="p2-base")
    assert first.ran.count(rid) == 1
    again = Fake({rid: [("error", None, "boom"), ("answered", 1.0, None)]}, cost=0.01)
    again.ran = [rid]  # the fake counts attempts by its own history
    run(tmp_path, again, only_pot="p2-base")
    assert again.ran == [rid, rid]  # only the errored run was retried
    third = Fake(cost=0.01)
    run(tmp_path, third, only_pot="p2-base")
    assert third.ran == []


def test_second_error_stops_the_run(tmp_path):
    rid = "base-sql-n40-s11-sonnet"
    fake = Fake({rid: [("error", None, "same reason")]}, cost=0.01)
    for _ in range(3):
        run(tmp_path, fake, only_pot="p2-base")
    assert fake.ran.count(rid) == 2
    assert "error twice: same reason" in sweep2.report(tmp_path)


def test_cap_is_hard(tmp_path):
    fake = Fake(cost=0.5)
    run(tmp_path, fake, only_pot="p2-base")
    spent = Ledger(tmp_path / "ledger.json").spent("p2-base")
    assert spent <= 3.0 and len(fake.ran) == 6  # 3.0 / 0.5; the rest are cut, never started
    text = sweep2.report(tmp_path)
    assert "cut (6)" in text and "less than $0.05 left" in text
    assert "p2-base: $3.0000 of $3.00" in text and "OVER" not in text


def test_budget_stop_is_reported_as_cut_and_context_overflow_as_done(tmp_path):
    fake = Fake({
        "base-tools-n120-s11-haiku": [("context_overflow", None, "prompt is too long")],
        "textdeadlines-tools-n40-s11-sonnet": [("budget_stop", None, "budget_stop: pot p2-variants exceeds cap")],
    }, cost=0.01)
    run(tmp_path, fake, only_pot="p2-variants")
    text = sweep2.report(tmp_path)
    done = text.split("cut (")[0]
    cut = text.split("cut (")[1].split("skipped-by-rule")[0]
    assert "base-tools-n120-s11-haiku" in done and "context_overflow" in done
    assert "textdeadlines-tools-n40-s11-sonnet" in cut and "budget_stop" in cut


def test_math_120_seed_12_is_skipped_by_budget(tmp_path):
    fake = Fake(cost=0.01)
    run(tmp_path, fake)
    assert "math-sql-n120-s12-sonnet" not in fake.ran and "math-tools-n120-s12-sonnet" not in fake.ran
    text = sweep2.report(tmp_path)
    assert "skipped: budget (one seed at N = 120)" in text
