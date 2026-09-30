"""Phase 2 plumbing: lean records, variant schemas, run ids, cache-isolation prefix, errors by trap."""

import asyncio
import json
import re
import sys
from types import SimpleNamespace

import pytest

from experiment import run as runner
from experiment.fake_apis import FakeApis, to_json
from experiment.generate import generate
from experiment.lean import DOCKET_COLUMNS, DOCKET_DEADLINE_COLUMNS, EMAIL_COLUMNS, MATTER_COLUMNS, TIME_COLUMNS
from experiment.questions import QUESTIONS, new_run_tag, system_prompt
from experiment.server_sql import Store, schema_text
from experiment.server_tools import build_server
from experiment.truth import matter_kinds, truth, truth_path
from tests.test_variants import independent  # noqa: F401  (imported to keep the oracle in one place)


def run_async(coro):
    return asyncio.run(coro)


async def fetch_all(apis: FakeApis, ds):
    """Page through every source the way the SQL loader does."""
    async def paged(fetch, key):
        out, page = [], 1
        while True:
            r = await fetch(page)
            out += r["data"] if "data" in r else r["value"]
            if not key(r):
                return out
            page += 1

    matters = await paged(lambda p: apis.list_matters(page=p), lambda r: r["meta"]["paging"]["next"])
    mail = await paged(lambda p: apis.search_mail(page=p), lambda r: r.get("@odata.nextLink"))
    times = await paged(lambda p: apis.list_time_entries(page=p), lambda r: r["meta"]["paging"]["next"])
    dockets = {m["matter_id"] if "matter_id" in m else m["id"]: (await apis.list_docket_entries(m["matter_id"] if "matter_id" in m else m["id"]))["results"] for m in matters}
    return matters, dockets, mail, times


@pytest.mark.parametrize("variant", ["base", "math", "textdeadlines"])
def test_lean_records_hold_exactly_the_sql_columns(variant):
    ds = generate(20, 11, "v2", variant)
    matters, dockets, mail, times = run_async(fetch_all(FakeApis(ds, 0, lean=True), ds))
    assert all(set(m) == set(MATTER_COLUMNS) | {"client_contacts"} for m in matters)
    assert all(set(c) == {"name", "email"} for m in matters for c in m["client_contacts"])
    docket_cols = set(DOCKET_COLUMNS) | (set() if variant == "textdeadlines" else set(DOCKET_DEADLINE_COLUMNS))
    entries = [e for es in dockets.values() for e in es]
    assert entries and all(set(e) == docket_cols for e in entries)
    assert all(set(e) == set(EMAIL_COLUMNS) | {"participants"} for e in mail)
    assert all(set(p) == {"email", "role"} for e in mail for p in e["participants"])
    assert all(set(t) == set(TIME_COLUMNS) for t in times)


@pytest.mark.parametrize("variant", ["base", "textdeadlines"])
def test_lean_values_equal_the_sql_tables(variant):
    ds = generate(20, 11, "v2", variant)
    apis = FakeApis(ds, 0, lean=True)
    matters, dockets, mail, times = run_async(fetch_all(apis, ds))

    async def load():
        store = Store(FakeApis(ds, 0))
        await store.ensure_loaded()
        return store

    store = run_async(load())

    def table(name, cols):
        return store.con.execute(f"select {', '.join(cols)} from {name} order by 1, 2").fetchall()

    def rows(records, cols):
        return sorted((tuple(r[c] for c in cols) for r in records), key=lambda t: (str(t[0]), str(t[1])))

    def norm(rs):
        return sorted((tuple(str(v) for v in r) for r in rs), key=lambda t: (t[0], t[1]))

    assert norm(rows(matters, MATTER_COLUMNS)) == norm(table("matters", MATTER_COLUMNS))
    docket_cols = DOCKET_COLUMNS + ([] if variant == "textdeadlines" else DOCKET_DEADLINE_COLUMNS)
    assert norm(rows([e for es in dockets.values() for e in es], docket_cols)) == norm(table("docket_entries", docket_cols))
    assert norm(rows(times, TIME_COLUMNS)) == norm(table("time_entries", TIME_COLUMNS))
    got = store.con.execute("select message_id, email, role from email_participants order by 1, 2, 3").fetchall()
    assert sorted((e["message_id"], p["email"], p["role"]) for e in mail for p in e["participants"]) == sorted(got)
    emails = store.con.execute("select message_id, received_date, from_email, body_preview from emails").fetchall()
    assert sorted((e["message_id"], e["received_date"], e["from_email"], e["body_preview"]) for e in mail) == sorted(
        (m, str(d), f, b) for m, d, f, b in emails
    )


def test_lean_is_smaller_and_filters_and_pagination_are_unchanged():
    ds = generate(40, 7)
    full, lean = FakeApis(ds, 0), FakeApis(ds, 0, lean=True)

    async def go():
        a = await full.list_matters(status="Open", page=2)
        b = await lean.list_matters(status="Open", page=2)
        assert a["meta"] == b["meta"] and len(a["data"]) == len(b["data"])
        m = await full.search_mail(after="2026-09-10", before="2026-09-12")
        n = await lean.search_mail(after="2026-09-10", before="2026-09-12")
        assert [e["id"] for e in m["value"]] == [e["message_id"] for e in n["value"]]
        t = await full.list_time_entries(matter_id=10003, after="2026-08-01")
        u = await lean.list_time_entries(matter_id=10003, after="2026-08-01")
        assert [x["id"] for x in t["data"]] == [x["entry_id"] for x in u["data"]]
        assert len(to_json(b)) < len(to_json(a)) / 2  # trimmed pages are much smaller

    run_async(go())


def test_lean_tool_descriptions_say_trimmed_and_default_ones_do_not():
    async def descs(lean, variant="base"):
        return {t.name: t.description for t in await build_server(10, 7, 0, "v2", variant, lean).list_tools()}

    lean, full = run_async(descs(True)), run_async(descs(False))
    assert all("trimmed" in d for d in lean.values())
    assert not any("trimmed" in d for d in full.values())
    assert set(lean) == set(full) == {"matters_list", "docket_entries", "mail_search", "time_entries"}
    assert "the matter_id field of each record" in lean["docket_entries"] and "the id field" not in lean["docket_entries"]
    assert "the id field" in full["docket_entries"]
    text = run_async(descs(False, "textdeadlines"))["docket_entries"]
    assert "deadline_date" not in text and "continue or vacate" in text
    assert "deadline_date" not in run_async(descs(True, "textdeadlines"))["docket_entries"]


def test_textdeadlines_sql_schema_has_no_deadline_columns():
    assert "deadline_date" in schema_text("base") and "deadline_date" in schema_text()
    text = schema_text("textdeadlines")
    assert "deadline_date" not in text and "deadline_type" not in text and "description" in text

    async def go():
        store = Store(FakeApis(generate(10, 7, "v2", "textdeadlines"), 0))
        await store.ensure_loaded()
        return [r[0] for r in store.con.execute("describe docket_entries").fetchall()]

    assert run_async(go()) == ["entry_id", "matter_id", "case_number", "entry_number", "date_filed", "description"]


def test_system_prompts_differ_and_start_with_a_run_tag():
    a, b = system_prompt(new_run_tag()), system_prompt(new_run_tag())
    assert a != b
    for p in (a, b):
        assert re.match(r"^Run [0-9a-f]{16}\. You are an assistant", p)


def test_questions_per_variant():
    base, math, text = QUESTIONS["base"], QUESTIONS["math"], QUESTIONS["textdeadlines"]
    assert "total less than 1.5" in math and "more than $4,000" in math and "No billable time" not in math
    assert "2. It has a court deadline in effect from 2026-09-15 to 2026-10-06, inclusive. Later docket entries can continue or vacate an earlier deadline." in text
    assert "in effect" not in base and "1.5" not in base
    for q in (base, math, text):
        assert q.splitlines()[1] == "1. Its status is Open and its practice area is Litigation."
        assert "3. No email dated 2026-09-01 to 2026-09-15" in q


def args_for(**kw):
    base = dict(arm="sql", n=40, rep=1, seed=11, model="claude-sonnet-5-5", variant="base", profile="v1")
    return SimpleNamespace(**(base | kw))


def test_run_ids_and_truth_paths():
    assert runner.make_run_id(args_for(seed=7, n=20, rep=2)) == "sql-n20-r2"
    assert runner.make_run_id(args_for(arm="tools", seed=7)) == "tools-n40-r1"
    assert runner.make_run_id(args_for(variant="math", profile="v2", arm="tools")) == "math-tools-n40-s11-sonnet"
    assert runner.make_run_id(args_for(profile="v2", arm="tools-lean", model="claude-haiku-4-5")) == "base-tools-lean-n40-s11-haiku"
    assert truth_path("t", 40, 7).name == "n40.json"
    assert truth_path("t", 40, 11, "v2", "textdeadlines").name == "textdeadlines-v2-s11-n40.json"


def test_errors_by_trap_files_each_error_under_its_kind():
    ds = generate(40, 11, "v2", "math")
    kinds = matter_kinds(ds)
    t = truth(ds)
    want = [m for g in t["at_risk"] for m in g["matters"]]
    healthy = next(d for d, k in kinds.items() if k == "healthy")
    at_risk_kind = kinds[want[0]]
    answer = {"at_risk": [{"attorney": "X", "matters": want[1:] + [healthy, "HV-2026-9999"]}], "notes": ""}
    s = runner.score_answer(answer, t, kinds)
    assert s["errors_by_trap"] == {
        "healthy": {"false_positives": [healthy], "false_negatives": []},
        "unknown": {"false_positives": ["HV-2026-9999"], "false_negatives": []},
        at_risk_kind: {"false_positives": [], "false_negatives": [want[0]]},
    }
    perfect = runner.score_answer({"at_risk": [{"attorney": "X", "matters": want}], "notes": ""}, t, kinds)
    assert perfect["errors_by_trap"] == {} and perfect["f1"] == 1.0
    assert "errors_by_trap" not in runner.score_answer(answer, t)  # kinds are optional
    assert runner.score_answer(None, t, kinds) is None
