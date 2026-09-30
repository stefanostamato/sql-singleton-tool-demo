"""Runner logic with a fake model client: scoring, retries, outcomes, budget, overwrite guard. No API calls."""

import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from experiment import run as runner
from experiment import sweep
from experiment.generate import generate
from experiment.ledger import Ledger
from experiment.run import score_answer
from experiment.truth import truth

EXPECTED = {"at_risk": [{"attorney": "Tomás Ibarra", "matters": ["HV-2026-0012"]}]}


def answer(attorney, matters):
    return {"at_risk": [{"attorney": attorney, "matters": matters}], "notes": ""}


def test_scoring_ignores_accents_case_spacing_and_matter_case():
    s = score_answer(answer("Tomas  Ibarra", ["hv-2026-0012 "]), EXPECTED)
    assert s["f1"] == 1.0 and s["grouping_exact"] and not s["false_positives"] and not s["false_negatives"]
    s = score_answer(answer("TOMÁS IBARRA", ["HV-2026-0012"]), EXPECTED)
    assert s["grouping_exact"]


def test_scoring_still_catches_real_errors():
    s = score_answer(answer("Dana Whitfield", ["HV-2026-0012"]), EXPECTED)
    assert s["f1"] == 1.0 and not s["grouping_exact"]
    s = score_answer(answer("Tomás Ibarra", ["HV-2026-0099"]), EXPECTED)
    assert s["f1"] == 0.0 and s["false_positives"] == ["HV-2026-0099"] and s["false_negatives"] == ["HV-2026-0012"]
    assert score_answer(None, EXPECTED) is None


def status_error(cls, code):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(code, request=req), body=None)


class FakeMessages:
    def __init__(self, script):
        self.script, self.calls = list(script), 0

    async def create(self, **kwargs):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fake_client(script):
    return SimpleNamespace(messages=FakeMessages(script))


def reply(stop_reason, content=()):
    usage = SimpleNamespace(input_tokens=10, cache_creation_input_tokens=0, cache_read_input_tokens=0, output_tokens=5)
    return SimpleNamespace(content=list(content), stop_reason=stop_reason, usage=usage)


async def test_retries_429_5xx_and_connection_errors_with_backoff():
    waits = []

    async def sleep(s):
        waits.append(s)

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = fake_client([
        status_error(anthropic.RateLimitError, 429),
        status_error(anthropic.InternalServerError, 529),
        anthropic.APIConnectionError(request=req),
        "ok",
    ])
    resp, retries, wait_ms, model_ms = await runner.create_with_retries(client, sleep=sleep)
    assert (resp, retries, wait_ms, waits) == ("ok", 3, 14000, [2, 4, 8])
    assert model_ms < 1000  # the 14 s of waiting is not counted as model time


async def test_retries_give_up_after_three_and_skip_client_errors():
    async def sleep(s):
        pass

    client = fake_client([status_error(anthropic.RateLimitError, 429)] * 4)
    with pytest.raises(anthropic.RateLimitError):
        await runner.create_with_retries(client, sleep=sleep)
    assert client.messages.calls == 4
    client = fake_client([status_error(anthropic.BadRequestError, 400), "ok"])
    with pytest.raises(anthropic.BadRequestError):
        await runner.create_with_retries(client, sleep=sleep)
    assert client.messages.calls == 1


def loop_args():
    return SimpleNamespace(model="claude-sonnet-5-5", effort="medium", pot="proof", max_turns=5)


async def run_loop(tmp_path, script, cap=None):
    trace = {"turns": [], "outcome": None, "error": None, "answer": None}
    ledger = Ledger(tmp_path / "ledger.json", cap)
    client = fake_client(script)
    await runner.agent_loop(loop_args(), trace, None, [], ledger, "sql-n5-r1", 0.0, client=client)
    return trace, client


@pytest.mark.parametrize(
    "stop, outcome",
    [("model_context_window_exceeded", "context_overflow"), ("max_tokens", "max_tokens"), ("refusal", "refusal")],
)
async def test_terminal_stop_reasons_get_their_own_outcome(tmp_path, stop, outcome):
    trace, _ = await run_loop(tmp_path, [reply(stop)])
    assert trace["outcome"] == outcome
    assert trace["turns"][0]["retries"] == 0 and trace["turns"][0]["retry_wait_ms"] == 0


async def test_budget_estimate_reserves_a_full_max_tokens_reply(tmp_path):
    # the old estimate reserved 4000 output tokens (about $0.04); a 16000-token reply can cost $0.16
    trace, client = await run_loop(tmp_path, [reply("end_turn")], cap=0.05)
    assert trace["outcome"] == "budget_stop" and client.messages.calls == 0


async def test_existing_trace_is_not_overwritten_without_force(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "sql-n5-r1.json").write_text("{}")
    argv = ["--arm", "sql", "--n", "5", "--rep", "1", "--model", "claude-sonnet-5-5", "--stage", "dev",
            "--pot", "dev", "--out", str(tmp_path), "--ledger", str(tmp_path / "l.json")]
    with pytest.raises(SystemExit, match="--force"):
        await runner.run(runner.parse_args(argv))
    assert (tmp_path / "traces" / "sql-n5-r1.json").read_text() == "{}"
    assert runner.parse_args(argv + ["--force"]).force


def test_rescore_rewrites_scores_and_index(tmp_path):
    want = truth(generate(5))["at_risk"]
    a = want[0]
    sloppy = {"at_risk": [{"attorney": a["attorney"].upper(), "matters": [m.lower() for m in a["matters"]]}], "notes": ""}
    trace = {
        "run_id": "sql-n5-r1", "arm": "sql", "n_matters": 5, "rep": 1, "stage": "proof", "pot": "proof",
        "model": "m", "seed": 7, "outcome": "answered", "error": None, "started_at": "2026-01-01T00:00:00Z",
        "answer": sloppy, "totals": {k: 1 for k in sweep.TOTAL_FIELDS},
        "score": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "grouping_exact": False},
    }
    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "sql-n5-r1.json").write_text(json.dumps(trace))
    assert sweep.rescore(tmp_path) == 1
    new = json.loads((tmp_path / "traces" / "sql-n5-r1.json").read_text())
    total = sum(len(g["matters"]) for g in want)
    assert new["score"]["precision"] == 1.0 and new["score"]["recall"] == round(len(a["matters"]) / total, 4)
    rows = json.loads((tmp_path / "index.json").read_text())
    assert rows[0]["recall"] == new["score"]["recall"]
