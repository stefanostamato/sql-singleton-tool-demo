"""Four fake HTTP-like APIs over a generated dataset, with simulated latency and per-call recording.

Every method sleeps `latency_s`, then returns a dict shaped like the real service. Each call is also
recorded as an api_call dict on the *current invocation*: a `Recorder` held in a contextvar, so the
MCP servers can report which upstream calls one tool invocation caused (including fan-out tasks).
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlencode

from experiment.generate import Dataset
from experiment.lean import lean_docket, lean_email, lean_matter, lean_time

_current: ContextVar["Recorder | None"] = ContextVar("current_invocation", default=None)


def to_json(obj) -> str:
    """Compact JSON, the exact text tools return and the size that api_calls report."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


class Recorder:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.calls: list[dict] = []


@contextmanager
def record():
    """Attribute every FakeApis call made inside this block (and its tasks) to one invocation."""
    rec = Recorder()
    token = _current.set(rec)
    try:
        yield rec
    finally:
        _current.reset(token)


def _addresses(email: dict) -> set[str]:
    out = {email["from"]["emailAddress"]["address"].lower()}
    for key in ("toRecipients", "ccRecipients"):
        out |= {r["emailAddress"]["address"].lower() for r in email[key]}
    return out


class FakeApis:
    def __init__(self, dataset: Dataset, latency_s: float = 0.15, lean: bool = False) -> None:
        self.ds = dataset
        self.latency_s = latency_s
        self.lean = lean  # trimmed records: exactly the SQL table columns (see lean.py)
        self._emails = sorted(dataset.emails, key=lambda e: (e["receivedDateTime"], e["id"]), reverse=True)
        self._times = sorted(dataset.time_entries, key=lambda t: (t["date"], t["id"]), reverse=True)

    async def _call(self, source: str, endpoint: str, params: dict, build):
        rec = _current.get()
        started = time.perf_counter()
        await asyncio.sleep(self.latency_s)
        response = build()
        duration = time.perf_counter() - started
        if rec is not None:
            rec.calls.append(
                {
                    "source": source,
                    "endpoint": endpoint,
                    "params": params,
                    "started_ms": round((started - rec.t0) * 1000),
                    "duration_ms": round(duration * 1000),
                    "bytes": len(to_json(response).encode("utf-8")),
                }
            )
        return response

    @staticmethod
    def _page(items: list, page: int, page_size: int) -> tuple[list, bool]:
        page = max(1, page)
        lo = (page - 1) * page_size
        return items[lo : lo + page_size], lo + page_size < len(items)

    # --- matters (Clio-like) ------------------------------------------------------------
    async def list_matters(self, status=None, practice_area=None, page=1, page_size=25) -> dict:
        params = {"status": status, "practice_area": practice_area, "page": page, "page_size": page_size}
        params = {k: v for k, v in params.items() if v is not None}

        def build():
            rows = [
                m
                for m in self.ds.matters
                if (status is None or m["status"].lower() == status.lower())
                and (practice_area is None or m["practice_area"]["name"].lower() == practice_area.lower())
            ]
            chunk, more = self._page(rows, page, page_size)
            if self.lean:
                chunk = [lean_matter(m) for m in chunk]
            q = {k: v for k, v in params.items() if k != "page"}
            nxt = "https://app.clio.example/api/v4/matters?" + urlencode({**q, "page": page + 1}) if more else None
            return {"data": chunk, "meta": {"paging": {"next": nxt}, "records": len(rows)}}

        return await self._call("matters", "GET /api/v4/matters", params, build)

    # --- docket (CourtListener-like) -------------------------------------------------------
    async def list_docket_entries(self, matter_id: int) -> dict:
        def build():
            rows = self.ds.dockets.get(int(matter_id), [])
            if self.lean:
                with_deadlines = self.ds.variant != "textdeadlines"
                rows = [lean_docket(e, int(matter_id), with_deadlines) for e in rows]
            return {"count": len(rows), "next": None, "results": rows}

        return await self._call("docket", "GET /api/rest/v4/docket-entries", {"matter_id": matter_id}, build)

    # --- mail (Microsoft Graph-like) -------------------------------------------------------
    async def search_mail(self, participants=None, after=None, before=None, page=1, page_size=50) -> dict:
        params = {"participants": participants, "after": after, "before": before, "page": page, "page_size": page_size}
        params = {k: v for k, v in params.items() if v is not None}
        wanted = {p.lower() for p in participants} if participants else None

        def build():
            rows = [
                e
                for e in self._emails
                if (wanted is None or wanted & _addresses(e))
                and (after is None or e["receivedDateTime"][:10] >= after)
                and (before is None or e["receivedDateTime"][:10] <= before)
            ]
            chunk, more = self._page(rows, page, page_size)
            if self.lean:
                chunk = [lean_email(e) for e in chunk]
            out = {"@odata.context": "https://graph.microsoft.com/v1.0/$metadata#users('me')/messages", "value": chunk}
            if more:
                q = {k: v for k, v in params.items() if k not in ("page", "participants")}
                out["@odata.nextLink"] = "https://graph.microsoft.com/v1.0/me/messages?" + urlencode({**q, "page": page + 1})
            return out

        return await self._call("mail", "GET /v1.0/me/messages", params, build)

    # --- billing (Clio activities-like) -----------------------------------------------------
    async def list_time_entries(self, matter_id=None, after=None, page=1, page_size=100) -> dict:
        params = {"matter_id": matter_id, "after": after, "page": page, "page_size": page_size}
        params = {k: v for k, v in params.items() if v is not None}

        def build():
            rows = [
                t
                for t in self._times
                if (matter_id is None or t["matter"]["id"] == int(matter_id)) and (after is None or t["date"] >= after)
            ]
            chunk, more = self._page(rows, page, page_size)
            if self.lean:
                chunk = [lean_time(t) for t in chunk]
            q = {k: v for k, v in params.items() if k != "page"}
            nxt = "https://app.clio.example/api/v4/activities?" + urlencode({**q, "page": page + 1}) if more else None
            return {"data": chunk, "meta": {"paging": {"next": nxt}, "records": len(rows)}}

        return await self._call("billing", "GET /api/v4/activities", params, build)
