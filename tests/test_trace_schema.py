"""Trace contract (docs/trace-format.md): validate real traces in runs/traces and scripted runs."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from experiment import run as runner
from experiment.generate import generate
from experiment.ledger import Ledger
from experiment.prices import cost_usd
from experiment.truth import truth

ROOT = Path(__file__).resolve().parent.parent
OUTCOMES = {"answered", "budget_stop", "turn_limit", "context_overflow", "refusal", "error"}
USAGE = {"input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"}
TOTALS = {
    "turns", "tool_calls", "api_calls", "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
    "output_tokens", "context_peak_tokens", "result_bytes", "cost_usd", "wall_ms", "model_ms", "tools_ms",
}
API_CALL = {"source", "endpoint", "params", "started_ms", "duration_ms", "bytes"}
SCORE = {
    "expected_count", "submitted_count", "precision", "recall", "f1", "grouping_exact", "false_positives",
    "false_negatives", "errors_by_trap",
}


def validate_trace(t: dict) -> None:
    assert t["schema_version"] == 1
    for key in ("run_id", "arm", "stage", "pot", "model", "today", "started_at", "finished_at", "question", "system_prompt"):
        assert isinstance(t[key], str) and t[key], key
    variant, profile = t.get("variant", "base"), t.get("profile", "v1")
    if (variant, profile) == ("base", "v1"):
        assert t["run_id"] == f"{t['arm']}-n{t['n_matters']}-r{t['rep']}"
    else:
        tag = {"claude-sonnet-5-5": "sonnet", "claude-haiku-4-5": "haiku"}[t["model"]]
        assert t["run_id"] == f"{variant}-{t['arm']}-n{t['n_matters']}-s{t['seed']}-{tag}"
    assert variant in ("base", "math", "textdeadlines") and profile in ("v1", "v2")
    assert re.match(r"^Run [0-9a-f]{16}\. ", t["system_prompt"])
    assert t["arm"] in ("tools", "tools-lean", "sql")
    assert t["stage"] in ("dev", "pilot", "proof", "showcase", "p2-base", "p2-variants")
    assert t["pot"] in ("dev", "proof", "showcase", "p2-base", "p2-variants")
    assert isinstance(t["n_matters"], int) and isinstance(t["rep"], int) and isinstance(t["seed"], int)
    assert t["outcome"] in OUTCOMES
    assert (t["error"] is None) or isinstance(t["error"], str)
    if t["outcome"] == "error":
        assert t["error"]
    assert t["tools"] and all(set(x) == {"name", "description"} for x in t["tools"])
    assert any(x["name"] == "submit_answer" for x in t["tools"])
    tool_names = {x["name"] for x in t["tools"]}
    for i, turn in enumerate(t["turns"]):
        assert turn["index"] == i
        for key in ("started_ms", "model_ms", "tools_ms"):
            assert isinstance(turn[key], int) and turn[key] >= 0
        assert set(turn["usage"]) >= USAGE
        assert turn["context_tokens"] == sum(turn["usage"][k] for k in USAGE - {"output_tokens"})
        assert turn["cost_usd"] >= 0 and isinstance(turn["stop_reason"], str)
        assert len(turn["text"]) <= 2000
        for c in turn["tool_calls"]:
            assert c["name"] in tool_names
            assert isinstance(c["input"], dict) and isinstance(c["is_error"], bool)
            assert c["result_tokens_est"] == pytest.approx(c["result_bytes"] / 3.5, abs=1)
            assert len(c["preview"]) <= 1500
            for a in c["api_calls"]:
                assert set(a) == API_CALL and a["source"] in ("matters", "docket", "mail", "billing")
            if c["name"] == "submit_answer":
                assert c["api_calls"] == []
    tot = t["totals"]
    assert set(tot) >= TOTALS
    assert tot["turns"] == len(t["turns"])
    assert tot["tool_calls"] == sum(len(x["tool_calls"]) for x in t["turns"])
    assert tot["api_calls"] == sum(len(c["api_calls"]) for x in t["turns"] for c in x["tool_calls"])
    assert tot["output_tokens"] == sum(x["usage"]["output_tokens"] for x in t["turns"])
    assert tot["cost_usd"] == pytest.approx(sum(x["cost_usd"] for x in t["turns"]), abs=1e-5)
    if t["answer"] is not None:
        assert set(t["answer"]) == {"at_risk", "notes"}
        assert t["score"] is not None and set(t["score"]) == SCORE
    else:
        assert t["score"] is None


def real_traces():
    return sorted((ROOT / "runs" / "traces").glob("*.json"))


@pytest.mark.skipif(not real_traces(), reason="no runs/traces yet (runs/ is gitignored)")
@pytest.mark.parametrize("path", real_traces(), ids=lambda p: p.name)
def test_real_traces_validate(path):
    validate_trace(json.loads(path.read_text()))


# ---- scripted runs (no network): a fake model drives the real runner and MCP servers -----------------------


def block(**kw):
    return SimpleNamespace(**kw)


def tool_use(i, name, **inp):
    return block(type="tool_use", id=f"toolu_{i}", name=name, input=inp)


def reply(content, stop="tool_use", inp=1000, out=50):
    usage = SimpleNamespace(input_tokens=inp, output_tokens=out, cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(content=content, stop_reason=stop, usage=usage)


class FakeClient:
    """Stands in for anthropic.AsyncAnthropic; `script` is a list of replies or exceptions."""

    script: list = []
    calls: list = []

    def __init__(self, *a, **k):
        self.messages = self

    async def create(self, **kwargs):
        FakeClient.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        item = FakeClient.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def scripted(monkeypatch, tmp_path, script, arm="sql", n=10, extra=(), env_key=True):
    FakeClient.script, FakeClient.calls = list(script), []
    monkeypatch.setattr(runner.anthropic, "AsyncAnthropic", FakeClient)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real" if env_key else "")
    argv = [
        "--arm", arm, "--n", str(n), "--rep", "1", "--model", "claude-haiku-4-5", "--stage", "dev", "--pot", "dev",
        "--out", str(tmp_path / "out"), "--latency", "0", "--ledger", str(tmp_path / "ledger.json"), *extra,
    ]
    import asyncio

    return asyncio.run(runner.run(runner.parse_args(argv)))


def expected_answer(n):
    return {"at_risk": truth(generate(n))["at_risk"], "notes": "scripted"}


def test_scripted_run_answered_and_scored(monkeypatch, tmp_path):
    ans = expected_answer(10)
    script = [
        reply([block(type="text", text="Loading."), tool_use(1, "sql_query", sql="select count(*) from matters")]),
        reply([tool_use(2, "submit_answer", **ans)]),
    ]
    t = scripted(monkeypatch, tmp_path, script)
    validate_trace(t)
    on_disk = json.loads((tmp_path / "out" / "traces" / "sql-n10-r1.json").read_text())
    validate_trace(on_disk)
    assert on_disk["outcome"] == "answered" and on_disk["score"]["f1"] == 1.0 and on_disk["score"]["grouping_exact"]
    first = on_disk["turns"][0]["tool_calls"][0]
    assert first["preview"].startswith("count_star()") or "count" in first["preview"]
    assert {a["source"] for a in first["api_calls"]} == {"matters", "docket", "mail", "billing"}
    assert on_disk["turns"][0]["text"] == "Loading."
    assert (tmp_path / "out" / "truth" / "n10.json").exists()
    # the API request: automatic caching, strict submit tool, no thinking/fallbacks/effort for Haiku
    req = FakeClient.calls[0]
    assert req["cache_control"] == {"type": "ephemeral"} and req["max_tokens"] == 16000
    assert "thinking" not in req and "output_config" not in req and "fallbacks" not in req
    assert next(x for x in req["tools"] if x["name"] == "submit_answer")["strict"] is True
    # ledger reflects both turns
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    expect = 2 * cost_usd("claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 50})
    assert ledger["pots"]["dev"]["spent"] == pytest.approx(expect)
    assert ledger["runs"][0]["run_id"] == "sql-n10-r1" and ledger["runs"][0]["finished_at"]


def test_scripted_wrong_answer_scored(monkeypatch, tmp_path):
    ans = {"at_risk": [{"attorney": "Nobody", "matters": ["HV-2026-0999"]}], "notes": ""}
    t = scripted(monkeypatch, tmp_path, [reply([tool_use(1, "submit_answer", **ans)])])
    validate_trace(t)
    assert t["score"]["recall"] == 0.0 and t["score"]["false_positives"] == ["HV-2026-0999"]
    assert t["score"]["false_negatives"]


def test_scripted_tools_arm_parallel_calls_have_own_api_calls(monkeypatch, tmp_path):
    script = [
        reply([tool_use(1, "matters_list", page=1), tool_use(2, "mail_search", page=1), tool_use(3, "time_entries")]),
        reply([tool_use(4, "submit_answer", at_risk=[], notes="none")]),
    ]
    t = scripted(monkeypatch, tmp_path, script, arm="tools", n=10)
    validate_trace(t)
    calls = t["turns"][0]["tool_calls"]
    assert [len(c["api_calls"]) for c in calls] == [1, 1, 1]
    assert [c["api_calls"][0]["source"] for c in calls] == ["matters", "mail", "billing"]
    assert calls[0]["result_bytes"] == calls[0]["api_calls"][0]["bytes"]


def test_scripted_nudge_then_error(monkeypatch, tmp_path):
    script = [reply([block(type="text", text="done")], stop="end_turn")] * 2
    t = scripted(monkeypatch, tmp_path, script)
    validate_trace(t)
    assert t["outcome"] == "error" and t["error"] == "no answer submitted" and len(t["turns"]) == 2
    assert FakeClient.calls[1]["messages"][-1] == {"role": "user", "content": runner.NUDGE}


def test_scripted_nudge_then_answer(monkeypatch, tmp_path):
    script = [reply([block(type="text", text="done")], stop="end_turn"), reply([tool_use(1, "submit_answer", at_risk=[], notes="")])]
    t = scripted(monkeypatch, tmp_path, script)
    validate_trace(t)
    assert t["outcome"] == "answered" and len(t["turns"]) == 2


def test_scripted_refusal_overflow_turn_limit_and_crash(monkeypatch, tmp_path):
    t = scripted(monkeypatch, tmp_path / "a", [reply([], stop="refusal")])
    validate_trace(t)
    assert t["outcome"] == "refusal"

    import anthropic
    import httpx

    resp = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    overflow = anthropic.BadRequestError("prompt is too long: 250000 tokens > 200000 maximum", response=resp, body=None)
    t = scripted(monkeypatch, tmp_path / "b", [overflow])
    validate_trace(t)
    assert t["outcome"] == "context_overflow"

    loop = [reply([tool_use(i, "describe_schema")]) for i in range(3)]
    t = scripted(monkeypatch, tmp_path / "c", loop, extra=("--max-turns", "3"))
    validate_trace(t)
    assert t["outcome"] == "turn_limit" and len(t["turns"]) == 3

    t = scripted(monkeypatch, tmp_path / "d", [RuntimeError("boom")])
    validate_trace(t)
    assert t["outcome"] == "error" and "boom" in t["error"]


def test_scripted_budget_stop_before_and_mid_run(monkeypatch, tmp_path):
    t = scripted(monkeypatch, tmp_path / "a", [], extra=("--cap", "0.001"))
    validate_trace(t)
    assert t["outcome"] == "budget_stop" and t["turns"] == [] and "budget_stop" in t["error"]
    assert FakeClient.calls == []  # no paid call was made

    # cap allows the first call only (estimate about $0.082): the second turn's estimate pushes past it
    script = [reply([tool_use(1, "describe_schema")], inp=5000), reply([tool_use(2, "submit_answer", at_risk=[], notes="")])]
    t = scripted(monkeypatch, tmp_path / "b", script, extra=("--cap", "0.09"))
    validate_trace(t)
    assert t["outcome"] == "budget_stop" and len(t["turns"]) == 1


def test_ledger_atomic_and_cap_override(tmp_path):
    lg = Ledger(tmp_path / "l.json", cap_override=0.5)
    assert lg.cap("dev") == 0.5 and json.loads((tmp_path / "l.json").read_text())["pots"]["dev"]["cap"] == 1.0
    lg.add("dev", "r1", "claude-haiku-4-5", 0.1)
    lg.add("dev", "r1", "claude-haiku-4-5", 0.2)
    again = Ledger(tmp_path / "l.json")
    assert again.spent("dev") == pytest.approx(0.3) and len(again.data["runs"]) == 1
    assert not list(tmp_path.glob(".ledger-*"))


def test_scripted_phase2_run_variant_lean_and_ids(monkeypatch, tmp_path):
    from experiment.truth import matter_kinds

    ds = generate(10, 11, "v2", "math")
    ans = {"at_risk": truth(ds)["at_risk"], "notes": "scripted"}
    script = [
        reply([tool_use(1, "matters_list", page=1)]),
        reply([tool_use(2, "submit_answer", **ans)]),
    ]
    extra = ("--variant", "math", "--profile", "v2", "--seed", "11")
    t = scripted(monkeypatch, tmp_path / "a", script, arm="tools-lean", n=10, extra=extra)
    validate_trace(t)
    assert t["run_id"] == "math-tools-lean-n10-s11-haiku" and t["variant"] == "math" and t["profile"] == "v2"
    assert t["score"]["f1"] == 1.0 and t["score"]["errors_by_trap"] == {}
    assert "total less than 1.5" in t["question"]
    assert (tmp_path / "a" / "out" / "truth" / "math-v2-s11-n10.json").exists()
    first = t["turns"][0]["tool_calls"][0]
    assert "matter_id" in first["preview"] and "responsible_attorney" in first["preview"] and '"etag"' not in first["preview"]
    assert all("trimmed" in x["description"] for x in t["tools"] if x["name"] != "submit_answer")
    assert FakeClient.calls[0]["system"] == t["system_prompt"]
    # a second run of the same thing gets a different system prompt (no shared cache prefix)
    script = [reply([tool_use(3, "submit_answer", **ans)])]
    t2 = scripted(monkeypatch, tmp_path / "b", script, arm="tools-lean", n=10, extra=extra)
    assert t2["system_prompt"] != t["system_prompt"]
    # wrong answer files its errors by trap type
    wrong = {"at_risk": [{"attorney": "A", "matters": [ans["at_risk"][0]["matters"][0]] + [d for d, k in matter_kinds(ds).items() if k == "healthy"][:1]}], "notes": ""}
    t3 = scripted(monkeypatch, tmp_path / "c", [reply([tool_use(4, "submit_answer", **wrong)])], arm="sql", n=10, extra=extra)
    validate_trace(t3)
    assert set(t3["score"]["errors_by_trap"]) >= {"healthy"}
