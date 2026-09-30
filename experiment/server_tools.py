"""MCP server for the "tools" arm: one tool per system, each returning the raw API JSON as text.

    python -m experiment.server_tools --n 40 --seed 7 --latency 0.15 [--profile v2] [--variant math] [--lean]

Upstream API calls made by each invocation are returned out-of-band in the result's `_meta`
(`{"api_calls": [...]}`), so the model never sees them.
"""

from __future__ import annotations

import argparse
import inspect
import re

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from experiment.fake_apis import FakeApis, record, to_json
from experiment.generate import generate


LEAN_TEXT = {
    "matters_list": (
        r"Returns matter records with the client.*?billing settings\.",
        "Records are trimmed to a flat object: matter_id, display_number, description, status, practice_area, "
        "responsible_attorney, responsible_attorney_email, client_id, client_name, open_date, case_number, and "
        "client_contacts (a list of {name, email}).",
    ),
    "docket_entries": (
        r"Returns every entry filed on the matter's case:.*?deadline_type\.",
        "Returns every entry filed on the matter's case. Records are trimmed to: entry_id, matter_id, case_number, "
        "entry_number, date_filed, description{deadline}",
    ),
    "mail_search": (
        r"Returns messages newest first with.*?received time and flags\.",
        "Returns messages newest first. Records are trimmed to: message_id, conversation_id, subject, received_at, "
        "received_date, from_email, from_name, body_preview (the first 255 characters of the body) and participants "
        "(a list of {email, role}, role being from, to or cc).",
    ),
    "time_entries": (
        r"Each entry has the date.*?already billed\.",
        "Records are trimmed to: entry_id, matter_id, date, hours, non_billable, billed, rate, total, note and user_name.",
    ),
}
TEXT_DEADLINES_DOCKET = (
    r"Entries that set a court deadline also carry deadline_date.*?deadline_type\.",
    "Court deadlines are not stored as fields: they are stated in the entry description, and later entries can "
    "continue or vacate an earlier deadline.",
)


def describe(fn, lean: bool, variant: str) -> str:
    """The tool description: the docstring, adjusted for the lean arm and the text-deadlines variant."""
    text = inspect.getdoc(fn)
    if not lean and variant != "textdeadlines":
        return text
    text = " ".join(text.split())
    if variant == "textdeadlines" and fn.__name__ == "docket_entries" and not lean:
        text, hits = re.subn(TEXT_DEADLINES_DOCKET[0], TEXT_DEADLINES_DOCKET[1], text)
        assert hits == 1, fn.__name__
    if lean:
        pattern, new = LEAN_TEXT[fn.__name__]
        note = TEXT_DEADLINES_DOCKET[1] if variant == "textdeadlines" else "(null unless the entry sets a court deadline)"
        new = new.replace("{deadline}", f". {note}" if variant == "textdeadlines" else f", deadline_date and deadline_type {note}.")
        text, hits = re.subn(pattern, lambda _: new, text)
        assert hits == 1, fn.__name__
        if fn.__name__ == "docket_entries":  # trimmed matter records have no `id`, they carry matter_id
            text, hits = re.subn(r"\(the id field, for example 10001\)", "(the matter_id field of each record, for example 10001)", text)
            assert hits == 1
    return text


def build_server(n: int, seed: int = 7, latency: float = 0.15, profile: str = "v1", variant: str = "base",
                 lean: bool = False) -> FastMCP:
    apis = FakeApis(generate(n, seed, profile, variant), latency_s=latency, lean=lean)
    mcp = FastMCP("harbor-vale-systems")
    tool = lambda fn: mcp.tool(description=describe(fn, lean, variant))(fn)  # noqa: E731

    def result(text: str, rec) -> CallToolResult:
        return CallToolResult(content=[TextContent(type="text", text=text)], _meta={"api_calls": rec.calls})

    @tool
    async def matters_list(status: str | None = None, practice_area: str | None = None, page: int = 1) -> CallToolResult:
        """List matters from the firm's practice management system (Clio Manage API, GET /api/v4/matters).
        Returns matter records with the client and its contacts, the responsible and originating attorney,
        practice area, status, open and close dates, court and case number, custom fields and billing
        settings. Optional filters: status (Open, Pending or Closed) and practice_area (Litigation,
        Corporate, Employment, Intellectual Property or Real Estate). Results are paginated at 25 records
        per page; pass page=2, 3, ... until meta.paging.next is null. meta.records is the total number of
        matching matters. Dates are YYYY-MM-DD."""
        with record() as rec:
            data = await apis.list_matters(status=status, practice_area=practice_area, page=page)
        return result(to_json(data), rec)

    @tool
    async def docket_entries(matter_id: int) -> CallToolResult:
        """List court docket entries for one matter (CourtListener docket-entries API,
        GET /api/rest/v4/docket-entries). Takes the numeric matter id from matters_list (the id field, for
        example 10001). Returns every entry filed on the matter's case: entry number, filing date
        (YYYY-MM-DD), description, document number and attachments. Entries that set a court deadline also
        carry deadline_date (YYYY-MM-DD) and deadline_type. Only litigation matters have a docket; other
        matters return an empty list. All entries come back in one response (no pagination)."""
        with record() as rec:
            data = await apis.list_docket_entries(matter_id)
        return result(to_json(data), rec)

    @tool
    async def mail_search(
        participants: list[str] | None = None,
        after: str | None = None,
        before: str | None = None,
        page: int = 1,
    ) -> CallToolResult:
        """Search the firm's mailbox (Microsoft Graph, GET /v1.0/me/messages). Returns messages newest
        first with subject, body, sender, to and cc recipients, received time and flags. participants is a
        list of email addresses; a message matches if any listed address appears in from, to or cc. after
        and before filter on the received date, both inclusive, in YYYY-MM-DD form. Omit all filters to
        list every message. Results are paginated at 50 messages per page; while the response has an
        @odata.nextLink, call again with the next page number."""
        with record() as rec:
            data = await apis.search_mail(participants=participants, after=after, before=before, page=page)
        return result(to_json(data), rec)

    @tool
    async def time_entries(matter_id: int | None = None, after: str | None = None, page: int = 1) -> CallToolResult:
        """List time entries from the billing system (Clio Manage activities API, GET /api/v4/activities).
        Each entry has the date (YYYY-MM-DD), hours, hourly rate, total, note, the user who recorded it, the
        matter it belongs to, and whether it is non_billable or already billed. Optional filters: matter_id
        (numeric matter id from matters_list) and after (YYYY-MM-DD, inclusive: only entries dated on or
        after this day). Results are paginated at 100 entries per page; pass page=2, 3, ... until
        meta.paging.next is null."""
        with record() as rec:
            data = await apis.list_time_entries(matter_id=matter_id, after=after, page=page)
        return result(to_json(data), rec)

    return mcp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--latency", type=float, default=0.15)
    ap.add_argument("--profile", default="v1", choices=["v1", "v2"])
    ap.add_argument("--variant", default="base", choices=["base", "math", "textdeadlines"])
    ap.add_argument("--lean", action="store_true", help="trim every record to the SQL table columns")
    args = ap.parse_args()
    build_server(args.n, args.seed, args.latency, args.profile, args.variant, args.lean).run(transport="stdio")


if __name__ == "__main__":
    main()
