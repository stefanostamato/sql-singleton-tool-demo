import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import duckdb
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from experiment.generate import generate
from experiment import server_sql
from experiment.fake_apis import FakeApis
from experiment.server_sql import Store, answer_query, check_single_readonly, literal
from experiment.truth import truth

ROOT = Path(__file__).resolve().parent.parent

REFERENCE_QUERY = """
select m.display_number, m.responsible_attorney
from matters m
where m.status = 'Open' and m.practice_area = 'Litigation'
  and exists (select 1 from docket_entries d where d.matter_id = m.matter_id
              and d.deadline_date between date '2026-09-15' and date '2026-10-06')
  and not exists (select 1 from client_contacts c
                  join email_participants p on p.email = c.email
                  join emails e on e.message_id = p.message_id
                  where c.matter_id = m.matter_id
                    and e.received_date between date '2026-09-01' and date '2026-09-15')
  and not exists (select 1 from time_entries t
                  where t.matter_id = m.matter_id and t.date between date '2026-09-01' and date '2026-09-15'
                    and not t.non_billable and t.hours > 0)
order by 2, 1
"""


@asynccontextmanager
async def session(module: str, n: int, latency: float = 0.0):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", f"experiment.{module}", "--n", str(n), "--seed", "7", "--latency", str(latency)],
        cwd=str(ROOT),
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            yield s


def text(result) -> str:
    return result.content[0].text


def api_calls(result) -> list[dict]:
    return result.meta["api_calls"]


def parse_rows(out: str) -> list[list[str]]:
    lines = out.splitlines()
    return [[c.strip() for c in ln.split("|")] for ln in lines[1:-1]]


def refused(sql: str) -> bool:
    stmt, problem = check_single_readonly(sql)
    return stmt is None and bool(problem)


def test_statement_guard_uses_the_parser():
    assert refused("select 1; select 2")
    assert refused("drop table matters")
    assert refused("-- select\ndelete from matters")
    assert refused("")
    assert refused("explain select 1")
    # quote tricks that fooled the old regex guard: the quotes hide a second statement from a text scan
    assert refused("select 1 as \"'\"; create table pwn as select 1; select 2 as \"'\"")
    assert refused("select $$'$$; drop table emails; select $$'$$")
    for ok in ("select 1;", "with x as (select 1) select * from x", "describe matters", "show tables", "select ';'",
               "select 1 -- trailing comment", "/* c */ select ';--'"):
        assert not refused(ok), ok


def test_load_literals_escape_quotes():
    assert literal("O'Brien; drop table t") == "'O''Brien; drop table t'"
    assert [literal(v) for v in (None, True, 3, 1.5)] == ["NULL", "true", "3", "1.5"]


async def loaded_store(n: int = 5) -> Store:
    store = Store(FakeApis(generate(n, 7), latency_s=0.0))
    await store.ensure_loaded()
    return store


async def test_lockdown_blocks_files_and_config_changes():
    store = await loaded_store()
    text_, err, _ = await answer_query(store, "select * from read_text('/etc/hostname')")
    assert err and "disabled by configuration" in text_
    # SET is not a SELECT, so the guard refuses it; the lock refuses it even when it reaches DuckDB
    text_, err, _ = await answer_query(store, "SET enable_external_access=true")
    assert err
    with pytest.raises(duckdb.Error, match="locked"):
        store.con.execute("SET enable_external_access=true")


async def test_timeout_interrupts_slow_query(monkeypatch):
    store = await loaded_store()
    monkeypatch.setattr(server_sql, "QUERY_TIMEOUT_S", 0.5)
    started = time.perf_counter()
    text_, err, _ = await answer_query(store, "select count(*) from range(3000000) a, range(3000000) b")
    assert err and text_ == "query timed out after 0.5 s"
    assert time.perf_counter() - started < 5
    ok, err, _ = await answer_query(store, "select count(*) from matters")  # the store still works
    assert not err and ok.splitlines()[1] == "5"


async def test_both_servers_list_tools():
    async with session("server_tools", 5) as s:
        names = {t.name for t in (await s.list_tools()).tools}
        assert names == {"matters_list", "docket_entries", "mail_search", "time_entries"}
    async with session("server_sql", 5) as s:
        names = {t.name for t in (await s.list_tools()).tools}
        assert names == {"describe_schema", "sql_query"}
        assert "matter_id" in text(await s.call_tool("describe_schema", {}))


async def test_sql_reference_query_equals_oracle():
    for n in (10, 20):
        expected = truth(generate(n))["at_risk"]
        async with session("server_sql", n) as s:
            res = await s.call_tool("sql_query", {"sql": REFERENCE_QUERY})
        assert not res.isError, text(res)
        grouped: dict[str, list[str]] = {}
        for display, attorney in parse_rows(text(res)):
            grouped.setdefault(attorney, []).append(display)
        assert [{"attorney": a, "matters": ms} for a, ms in grouped.items()] == expected


async def test_sql_load_api_calls_and_cache():
    n = 10
    async with session("server_sql", n) as s:
        first = await s.call_tool("sql_query", {"sql": "select count(*) from matters"})
        second = await s.call_tool("sql_query", {"sql": "select count(*) from emails"})
    calls = api_calls(first)
    by_source = {}
    for c in calls:
        by_source.setdefault(c["source"], []).append(c)
        assert set(c) == {"source", "endpoint", "params", "started_ms", "duration_ms", "bytes"}
    assert set(by_source) == {"matters", "docket", "mail", "billing"}
    assert len(by_source["docket"]) == n  # fan-out: one call per matter
    assert api_calls(second) == []  # loaded once per session
    assert first.meta["load_ms"] > 0 and second.meta["load_ms"] == 0
    assert text(first).splitlines()[1] == str(n)


async def test_sql_errors_and_limits():
    async with session("server_sql", 10) as s:
        bad = await s.call_tool("sql_query", {"sql": "select nope from matters"})
        assert bad.isError and "nope" in text(bad)
        for stmt in ("drop table matters", "select 1; select 2", "select $$'$$; drop table emails; select $$'$$",
                     "select * from read_text('/etc/hostname')"):
            r = await s.call_tool("sql_query", {"sql": stmt})
            assert r.isError
        big = await s.call_tool("sql_query", {"sql": "select * from emails, matters"})
        assert not big.isError
        lines = text(big).splitlines()
        assert lines[-1].endswith("rows, showing first 200)")
        assert len(lines) == 202  # header + 200 rows + count line
        small = await s.call_tool("sql_query", {"sql": "select display_number from matters order by 1 limit 2"})
        assert text(small).splitlines() == ["display_number", "HV-2026-0001", "HV-2026-0002", "(2 rows)"]


async def test_tools_server_returns_generated_records_and_calls():
    n = 40
    ds = generate(n)
    async with session("server_tools", n) as s:
        p1 = json.loads(text(await s.call_tool("matters_list", {})))
        p2r = await s.call_tool("matters_list", {"page": 2})
        p2 = json.loads(text(p2r))
        assert p1["data"] == ds.matters[:25] and p2["data"] == ds.matters[25:]
        assert p1["meta"]["records"] == n and p1["meta"]["paging"]["next"] and p2["meta"]["paging"]["next"] is None
        assert api_calls(p2r)[0]["params"] == {"page": 2, "page_size": 25}

        lit = next(m for m in ds.matters if m["id"] in ds.dockets)
        d = json.loads(text(await s.call_tool("docket_entries", {"matter_id": lit["id"]})))
        assert d["results"] == ds.dockets[lit["id"]] and d["count"] == len(ds.dockets[lit["id"]])

        who = lit["client"]["contacts"][0]["email"]
        mail = json.loads(text(await s.call_tool("mail_search", {"participants": [who]})))
        expect = [e for e in ds.emails if who in json.dumps(e)]
        assert {e["id"] for e in mail["value"]} == {e["id"] for e in expect}
        dated = json.loads(text(await s.call_tool("mail_search", {"after": "2026-09-01", "before": "2026-09-15"})))
        assert all("2026-09-01" <= e["receivedDateTime"][:10] <= "2026-09-15" for e in dated["value"])

        te = json.loads(text(await s.call_tool("time_entries", {"matter_id": lit["id"]})))
        assert te["data"] == sorted(
            [t for t in ds.time_entries if t["matter"]["id"] == lit["id"]], key=lambda t: (t["date"], t["id"]), reverse=True
        )


async def test_api_calls_attributed_per_invocation_under_concurrency():
    async with session("server_tools", 40, latency=0.05) as s:
        r1, r2, r3 = await asyncio.gather(
            s.call_tool("matters_list", {"page": 1}),
            s.call_tool("matters_list", {"page": 2}),
            s.call_tool("mail_search", {"page": 1}),
        )
    assert [len(api_calls(r)) for r in (r1, r2, r3)] == [1, 1, 1]
    assert api_calls(r1)[0]["params"]["page"] == 1 and api_calls(r2)[0]["params"]["page"] == 2
    assert api_calls(r3)[0]["source"] == "mail"
    assert all(api_calls(r)[0]["duration_ms"] >= 45 for r in (r1, r2, r3))
