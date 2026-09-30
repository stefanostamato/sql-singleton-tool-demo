"""MCP server for the "sql" arm: one SQL tool over everything, backed by in-memory DuckDB.

    python -m experiment.server_sql --n 40 --seed 7 --latency 0.15

On the first `sql_query` the server pulls every record through the same fake APIs the other arm uses
(matter pages, docket entries per matter, all mail pages, all time-entry pages), flattens them into
tables, and keeps them for the life of the process. Upstream calls made by an invocation come back
out-of-band in the result's `_meta` (`{"api_calls": [...]}`).
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import datetime

import duckdb
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from experiment.fake_apis import FakeApis, record
from experiment.generate import generate

MAX_ROWS = 200
QUERY_TIMEOUT_S = 20
INSERT_CHUNK = 1000

# DuckDB is locked down from the start: no file or network access, no extension loading, and the
# configuration cannot be changed afterwards, so a query cannot turn any of that back on.
LOCKDOWN = {
    "enable_external_access": False,
    "lock_configuration": True,
    "temp_directory": "",
    "autoinstall_known_extensions": False,
    "autoload_known_extensions": False,
}


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(":memory:", config=LOCKDOWN)


_PARSER = connect()

SCHEMA_TEXT = """Tables (DuckDB SQL). Dates are DATE values, compare with e.g. date '2026-09-15'.

matters(matter_id, display_number, description, status, practice_area, responsible_attorney,
        responsible_attorney_email, client_id, client_name, open_date DATE, case_number)
  One row per matter. status is Open, Pending or Closed. practice_area is Litigation, Corporate,
  Employment, Intellectual Property or Real Estate. case_number is set for litigation matters only.
  display_number looks like HV-2026-0012.
client_contacts(client_id, matter_id, name, email)
  The client's contact people for a matter. Join on matter_id (or client_id).
docket_entries(entry_id, matter_id, case_number, entry_number, date_filed DATE, description,
               deadline_date DATE, deadline_type)
  Court docket entries, litigation matters only. deadline_date and deadline_type are NULL unless the
  entry sets a court deadline. Join on matter_id.
emails(message_id, conversation_id, subject, received_at TIMESTAMP, received_date DATE, from_email,
       from_name, body_preview)
  One row per email in the firm mailbox. Subjects of matter emails contain the display number in
  brackets, for example [HV-2026-0012]; some emails belong to no matter. Emails are not linked to
  matters directly: link them through email_participants and client_contacts.email.
email_participants(message_id, email, role)
  One row per address on an email. role is 'from', 'to' or 'cc'. Join on message_id.
time_entries(entry_id, matter_id, date DATE, hours DOUBLE, non_billable BOOLEAN, billed BOOLEAN,
             rate DOUBLE, total DOUBLE, note, user_name)
  Time recorded against matters. Join on matter_id.

Join keys: matter_id links matters, client_contacts, docket_entries and time_entries.
message_id links emails and email_participants. client_contacts.email matches email_participants.email."""

DDL = """
create table matters(matter_id bigint, display_number varchar, description varchar, status varchar,
  practice_area varchar, responsible_attorney varchar, responsible_attorney_email varchar,
  client_id bigint, client_name varchar, open_date date, case_number varchar);
create table client_contacts(client_id bigint, matter_id bigint, name varchar, email varchar);
create table docket_entries(entry_id bigint, matter_id bigint, case_number varchar, entry_number integer,
  date_filed date, description varchar, deadline_date date, deadline_type varchar);
create table emails(message_id varchar, conversation_id varchar, subject varchar, received_at timestamp,
  received_date date, from_email varchar, from_name varchar, body_preview varchar);
create table email_participants(message_id varchar, email varchar, role varchar);
create table time_entries(entry_id bigint, matter_id bigint, date date, hours double, non_billable boolean,
  billed boolean, rate double, total double, note varchar, user_name varchar);
"""

# textdeadlines: the docket keeps no deadline columns, only the full text of each entry.
TEXT_DOCKET_SCHEMA = """docket_entries(entry_id, matter_id, case_number, entry_number, date_filed DATE, description)
  Court docket entries, litigation matters only. Join on matter_id. Court deadlines are not stored as
  columns: they are stated in the description text, and later entries can continue or vacate an earlier
  deadline."""
BASE_DOCKET_SCHEMA = SCHEMA_TEXT[SCHEMA_TEXT.index("docket_entries(") : SCHEMA_TEXT.index("emails(")]
TEXT_DDL_OLD = """create table docket_entries(entry_id bigint, matter_id bigint, case_number varchar, entry_number integer,
  date_filed date, description varchar, deadline_date date, deadline_type varchar);"""
TEXT_DDL_NEW = """create table docket_entries(entry_id bigint, matter_id bigint, case_number varchar, entry_number integer,
  date_filed date, description varchar);"""
assert BASE_DOCKET_SCHEMA and TEXT_DDL_OLD in DDL


def schema_text(variant: str = "base") -> str:
    if variant == "textdeadlines":
        return SCHEMA_TEXT.replace(BASE_DOCKET_SCHEMA, TEXT_DOCKET_SCHEMA + "\n")
    return SCHEMA_TEXT


def ddl(variant: str = "base") -> str:
    return DDL.replace(TEXT_DDL_OLD, TEXT_DDL_NEW) if variant == "textdeadlines" else DDL


def check_single_readonly(sql: str):
    """Parse `sql` with DuckDB. Return (statement, None) when it is exactly one SELECT-type statement
    (SELECT, WITH, VALUES, DESCRIBE, SHOW and SUMMARIZE all parse as SELECT), else (None, error message)."""
    try:
        stmts = _PARSER.extract_statements(sql)
    except duckdb.Error as exc:
        return None, f"SQL error: {exc}"
    if not stmts:
        return None, "Empty query."
    if len(stmts) > 1:
        return None, "Only one statement is allowed per call."
    if stmts[0].type != duckdb.StatementType.SELECT:
        return None, "Only a single SELECT, WITH, DESCRIBE or SHOW statement is allowed."
    return stmts[0], None


def format_rows(cols: list[str], rows: list[tuple]) -> str:
    def cell(v) -> str:
        return "NULL" if v is None else str(v).replace("\n", " ").replace("|", "/")

    total = len(rows)
    shown = rows[:MAX_ROWS]
    lines = [" | ".join(cols)] + [" | ".join(cell(v) for v in r) for r in shown]
    lines.append(f"({total} rows)" if total <= MAX_ROWS else f"({total} rows, showing first {MAX_ROWS})")
    return "\n".join(lines)


def literal(v) -> str:
    """A SQL literal for a Python value. Strings and datetimes become quoted strings that the INSERT
    casts to the column type."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, datetime):
        v = v.isoformat(sep=" ")
    return "'" + str(v).replace("'", "''") + "'"


class Store:
    """The DuckDB tables, loaded lazily through FakeApis exactly once per process."""

    def __init__(self, apis: FakeApis) -> None:
        self.apis = apis
        self.con = connect()
        self.load_ms = 0  # time spent building the tables, excluding API waits
        self._lock = asyncio.Lock()
        self.loaded = False

    async def ensure_loaded(self) -> None:
        async with self._lock:
            if self.loaded:
                return
            matters, emails, times = await asyncio.gather(self._matters(), self._mail(), self._time())
            dockets = await self._dockets(matters)
            started = time.perf_counter()
            self._flatten(matters, dockets, emails, times)
            self.load_ms = round((time.perf_counter() - started) * 1000)
            self.loaded = True

    async def _paged(self, fetch, key_next):
        out, page = [], 1
        while True:
            resp = await fetch(page)
            out.extend(resp["data"] if "data" in resp else resp["value"])
            if not key_next(resp):
                return out
            page += 1

    async def _matters(self):
        return await self._paged(lambda p: self.apis.list_matters(page=p), lambda r: r["meta"]["paging"]["next"])

    async def _mail(self):
        return await self._paged(lambda p: self.apis.search_mail(page=p), lambda r: r.get("@odata.nextLink"))

    async def _time(self):
        return await self._paged(lambda p: self.apis.list_time_entries(page=p), lambda r: r["meta"]["paging"]["next"])

    async def _dockets(self, matters):
        async def one(m):
            return m["id"], (await self.apis.list_docket_entries(m["id"]))["results"]

        return dict(await asyncio.gather(*(one(m) for m in matters)))

    def _insert(self, table: str, ncols: int, rows: list[tuple]) -> None:
        """Bulk load with multi-row INSERT statements built from escaped literals. DuckDB's executemany
        runs one statement per row (about 4 s for the N=120 data), and binding parameters from Python is
        nearly as slow; literals are about 100x faster and need neither pandas nor pyarrow."""
        for i in range(0, len(rows), INSERT_CHUNK):
            values = ",".join("(" + ",".join(literal(v) for v in row) + ")" for row in rows[i : i + INSERT_CHUNK])
            self.con.execute(f"insert into {table} values {values}")

    def _flatten(self, matters, dockets, emails, times) -> None:
        con = self.con
        text_deadlines = self.apis.ds.variant == "textdeadlines"
        con.execute(ddl(self.apis.ds.variant))
        self._insert("matters", 11, [
                (m["id"], m["display_number"], m["description"], m["status"], m["practice_area"]["name"],
                 m["responsible_attorney"]["name"], m["responsible_attorney"]["email"], m["client"]["id"],
                 m["client"]["name"], m["open_date"], (m.get("court") or {}).get("case_number"))
                for m in matters
            ],
        )
        self._insert("client_contacts", 4, [(m["client"]["id"], m["id"], c["name"], c["email"]) for m in matters for c in m["client"]["contacts"]],
        )
        self._insert("docket_entries", 6 if text_deadlines else 8, [
                (e["id"], mid, e["case_number"], e["entry_number"], e["date_filed"], e["description"])
                + (() if text_deadlines else (e.get("deadline_date"), e.get("deadline_type")))
                for mid, entries in dockets.items()
                for e in entries
            ],
        )
        self._insert("emails", 8, [
                (e["id"], e["conversationId"], e["subject"],
                 datetime.fromisoformat(e["receivedDateTime"].removesuffix("Z")), e["receivedDateTime"][:10],
                 e["from"]["emailAddress"]["address"], e["from"]["emailAddress"]["name"], e["bodyPreview"])
                for e in emails
            ],
        )
        parts = []
        for e in emails:
            parts.append((e["id"], e["from"]["emailAddress"]["address"], "from"))
            parts += [(e["id"], r["emailAddress"]["address"], "to") for r in e["toRecipients"]]
            parts += [(e["id"], r["emailAddress"]["address"], "cc") for r in e["ccRecipients"]]
        self._insert("email_participants", 3, parts)
        self._insert("time_entries", 10, [
                (t["id"], t["matter"]["id"], t["date"], t["quantity_in_hours"], t["non_billable"], t["billed"],
                 t["price"], t["total"], t["note"], t["user"]["name"])
                for t in times
            ],
        )

    def run(self, statement, cursor: duckdb.DuckDBPyConnection | None = None) -> str:
        cur = (cursor or self.con.cursor()).execute(statement)
        cols = [d[0] for d in cur.description]
        return format_rows(cols, cur.fetchall())


async def answer_query(store: Store, sql: str) -> tuple[str, bool, int]:
    """Validate, load on first use, and run `sql` with a timeout. Returns (text, is_error, load_ms)."""
    statement, problem = check_single_readonly(sql)
    if problem:
        return problem, True, 0
    try:
        loaded_before = store.loaded
        await store.ensure_loaded()
        load_ms = 0 if loaded_before else store.load_ms
        cursor = store.con.cursor()
        try:
            text = await asyncio.wait_for(asyncio.to_thread(store.run, statement, cursor), QUERY_TIMEOUT_S)
        except asyncio.TimeoutError:
            cursor.interrupt()
            return f"query timed out after {QUERY_TIMEOUT_S} s", True, load_ms
        return text, False, load_ms
    except duckdb.Error as exc:
        return f"SQL error: {exc}", True, 0


def build_server(n: int, seed: int = 7, latency: float = 0.15, profile: str = "v1", variant: str = "base") -> FastMCP:
    store = Store(FakeApis(generate(n, seed, profile, variant), latency_s=latency))
    schema = schema_text(variant)
    mcp = FastMCP("harbor-vale-sql")

    @mcp.tool()
    async def describe_schema() -> CallToolResult:
        """Describe the tables and columns available to sql_query, with a one-line meaning for each and the
        join keys between tables. Call this first."""
        return CallToolResult(content=[TextContent(type="text", text=schema)], _meta={"api_calls": [], "load_ms": 0})

    @mcp.tool()
    async def sql_query(sql: str) -> CallToolResult:
        """Run one read-only SQL query (DuckDB dialect) over the firm's matters, client contacts, court docket
        entries, emails and time entries. Accepts exactly one statement starting with SELECT, WITH, DESCRIBE
        or SHOW. Returns at most 200 rows as a pipe-separated table with a header line and a final row
        count line. If the query fails, the error message is returned so you can fix the query. The data is
        loaded once per session, on the first query, so later queries are fast. Use describe_schema to see
        the tables."""
        with record() as rec:
            text, err, load_ms = await answer_query(store, sql)
            return CallToolResult(
                content=[TextContent(type="text", text=text)], isError=err,
                _meta={"api_calls": rec.calls, "load_ms": load_ms},
            )

    return mcp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--latency", type=float, default=0.15)
    ap.add_argument("--profile", default="v1", choices=["v1", "v2"])
    ap.add_argument("--variant", default="base", choices=["base", "math", "textdeadlines"])
    args = ap.parse_args()
    build_server(args.n, args.seed, args.latency, args.profile, args.variant).run(transport="stdio")


if __name__ == "__main__":
    main()
