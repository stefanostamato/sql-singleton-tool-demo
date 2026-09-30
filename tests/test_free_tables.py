"""The free analyses (misreadings, latency model, bytes) and the guarantee that phase 1 scores stand."""

import asyncio
import json
from pathlib import Path

import pytest

from experiment import bytes_table, latency_model, misreadings
from experiment.generate import generate
from experiment.run import score_answer
from experiment.truth import at_risk_matters, matter_kinds, truth

RESULTS = Path(__file__).resolve().parent.parent / "results"


def test_rescoring_phase_1_traces_changes_no_f1():
    traces = sorted((RESULTS / "traces").glob("*.json"))
    assert len(traces) >= 14
    for p in traces:
        t = json.loads(p.read_text())
        if t.get("variant", "base") != "base" or t.get("profile", "v1") != "v1":
            continue
        ds = generate(t["n_matters"], t["seed"])
        new = score_answer(t["answer"], truth(ds), matter_kinds(ds))
        old = t["score"]
        for key in ("expected_count", "submitted_count", "precision", "recall", "f1", "grouping_exact",
                    "false_positives", "false_negatives"):
            assert new[key] == old[key], (p.name, key)
        assert new["errors_by_trap"] == {}


# ---------- misreadings ----------

def test_each_misreading_changes_the_answer_for_a_reason():
    ds = generate(120, 7)
    right = {m["display_number"] for m in at_risk_matters(ds)}
    for label, rules in misreadings.MISREADINGS:
        wrong = {m["display_number"] for m in at_risk_matters(ds, rules)}
        assert wrong != right, label
    # the direction of each mistake
    by = dict(misreadings.MISREADINGS)
    def got(label):
        return {m["display_number"] for m in at_risk_matters(ds, by[label])}
    assert got("Counts non-billable time") < right  # more activity, fewer at-risk
    assert got("Skips the status check") > right  # fewer filters, more at-risk
    assert got("Skips the docket check") > right
    assert got("Ignores the 10-06 boundary (uses < instead of <=)") < right


def test_misreading_table_has_every_requested_dataset():
    data = misreadings.rows()
    assert [(d["profile"], d["n"]) for d in data if d["seed"] in (7, 11)] == [
        ("v1", 10), ("v1", 20), ("v1", 40), ("v1", 120), ("v2", 40), ("v2", 120)
    ]
    assert len(data[0]["cells"]) == 6
    assert "F1" not in misreadings.markdown(data) and "|" in misreadings.markdown(data)


def test_boundary_misreading_only_bites_on_v2_data_at_small_n():
    v1 = {d["n"]: d for d in misreadings.rows([("v1", 7, 40)])}
    v2 = {d["n"]: d for d in misreadings.rows([("v2", 11, 40)])}
    label_last = [c for c in v1[40]["cells"] if c[0].startswith("Ignores the 10-06")][0]
    assert label_last[1] == 1.0  # no v1 matter at N=40 sits on 10-06
    assert [c for c in v2[40]["cells"] if c[0].startswith("Ignores the 10-06")][0][1] < 1.0


# ---------- latency model ----------

def call(source, start, dur=150):
    return {"source": source, "started_ms": start, "duration_ms": dur}


def test_parallel_calls_run_ten_at_a_time():
    calls = [call("docket", 1 + i % 3) for i in range(25)]
    assert latency_model.modeled_span(calls) == 3 * 500
    assert latency_model.modeled_span(calls[:10]) == 500
    assert latency_model.modeled_span(calls[:11]) == 1000
    assert latency_model.modeled_span([]) == 0


def test_slot_limit_pools_calls_across_parallel_tool_calls():
    tool_calls = [{"duration_ms": 150, "api_calls": [call("docket", 1)]} for _ in range(35)]
    assert latency_model.modeled_turn_ms(tool_calls) == 4 * 500  # ceil(35 / 10), not 500
    trace = {"run_id": "r", "arm": "tools", "turns": [{"model_ms": 0, "tools_ms": 150, "tool_calls": tool_calls}]}
    assert latency_model.model_trace(trace)["modeled_tools_ms"] == 2000


def test_page_loops_stay_sequential_and_mail_scales():
    pages = [call("mail", 0), call("mail", 152), call("mail", 304)]
    assert latency_model.modeled_span(pages) == 1500
    assert latency_model.modeled_span(pages, mail_factor=10) == 15000
    load = pages + [call("billing", 0), call("billing", 152), call("matters", 1)] + [call("docket", 460 + i % 4) for i in range(30)]
    # the docket calls wait for every list to finish, then go 10 at a time
    assert latency_model.modeled_span(load) == 1500 + 3 * 500
    assert latency_model.modeled_span(load, mail_factor=10) == 15000 + 3 * 500


def test_model_trace_keeps_model_time_and_overhead():
    trace = {
        "run_id": "r", "arm": "sql",
        "turns": [
            {"model_ms": 2000, "tools_ms": 400, "tool_calls": [
                {"duration_ms": 400, "api_calls": [call("mail", 0), call("mail", 152)]},
                {"duration_ms": 3, "api_calls": []},
            ]},
            {"model_ms": 1000, "tools_ms": 5, "tool_calls": [{"duration_ms": 5, "api_calls": []}]},
        ],
    }
    m = latency_model.model_trace(trace)
    assert m["recorded_tools_ms"] == 405 and m["model_ms"] == 3000
    overhead = 400 - 302
    assert m["modeled_tools_ms"] == 1000 + overhead + 5
    assert m["modeled_wall_ms"] == 3000 + m["modeled_tools_ms"]
    assert m["modeled_tools_ms_mail_x10"] == 10000 + overhead + 5
    assert "modeled_tools_ms_mail_x10" not in latency_model.model_trace(trace | {"arm": "tools"})


def test_latency_model_runs_over_every_recorded_trace():
    data = latency_model.rows(RESULTS)
    assert len(data) >= 14
    for r in data:
        assert r["modeled_tools_ms"] >= r["recorded_tools_ms"] > 0 or r["recorded_tools_ms"] == 0
        assert ("modeled_tools_ms_mail_x10" in r) == (r["arm"] == "sql")


# ---------- bytes ----------

def test_raw_bytes_match_the_recorded_sql_load_and_lean_is_smaller():
    trace = json.loads((RESULTS / "traces" / "sql-n40-r1.json").read_text())
    loaded = sum(a["bytes"] for t in trace["turns"] for c in t["tool_calls"] for a in c["api_calls"])
    raw = asyncio.run(bytes_table.load_bytes(40, lean=False))
    lean = asyncio.run(bytes_table.load_bytes(40, lean=True))
    assert sum(raw.values()) == loaded
    assert all(lean[s] < raw[s] for s in bytes_table.SOURCES)
    assert bytes_table.sql_result_bytes(40) < 1000
    assert "SQL arm" in bytes_table.markdown(bytes_table.rows((40,)))
