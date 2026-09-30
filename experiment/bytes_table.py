"""Bytes moved: raw per-system payloads vs the same records trimmed vs what the SQL arm returned. Free.

    python -m experiment.bytes_table

For each N (base data, profile v1, seed 7): page through the four fake systems the way the SQL server's
loader does, once with raw records and once with records trimmed to the SQL columns, and add up the
bytes of every response. Next to them: the bytes the SQL arm's own `sql_query` calls returned in the
recorded run at that size. Tokens are estimated as bytes / 3.5, the same rule the traces use.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from experiment.fake_apis import FakeApis, record
from experiment.generate import generate

CHARS_PER_TOKEN = 3.5
SOURCES = ("matters", "docket", "mail", "billing")
SIZES = (40, 120)
RESULTS = Path(__file__).resolve().parent.parent / "results"


async def load_bytes(n: int, lean: bool, seed: int = 7) -> dict[str, int]:
    """Bytes returned by every upstream response the SQL loader fetches, per source."""
    apis = FakeApis(generate(n, seed), latency_s=0.0, lean=lean)
    totals = {s: 0 for s in SOURCES}
    with record() as rec:
        matters, page = [], 1
        while True:
            r = await apis.list_matters(page=page)
            matters += r["data"]
            if not r["meta"]["paging"]["next"]:
                break
            page += 1
        page = 1
        while True:
            r = await apis.search_mail(page=page)
            if not r.get("@odata.nextLink"):
                break
            page += 1
        page = 1
        while True:
            r = await apis.list_time_entries(page=page)
            if not r["meta"]["paging"]["next"]:
                break
            page += 1
        for m in matters:
            await apis.list_docket_entries(m["matter_id"] if lean else m["id"])
    for c in rec.calls:
        totals[c["source"]] += c["bytes"]
    return totals


def sql_result_bytes(n: int, results: Path = RESULTS) -> int | None:
    """Bytes the SQL arm's sql_query calls returned to the model in the recorded phase 1 run at this N."""
    path = results / "traces" / f"sql-n{n}-r1.json"
    if not path.exists():
        return None
    trace = json.loads(path.read_text())
    return sum(c["result_bytes"] for t in trace["turns"] for c in t["tool_calls"] if c["name"] == "sql_query")


def rows(sizes=SIZES, results: Path = RESULTS) -> list[dict]:
    out = []
    for n in sizes:
        raw = asyncio.run(load_bytes(n, lean=False))
        lean = asyncio.run(load_bytes(n, lean=True))
        out.append({"n": n, "raw": raw, "lean": lean, "sql_result": sql_result_bytes(n, results)})
    return out


def markdown(data: list[dict] | None = None) -> str:
    data = data or rows()
    head = ["N", "What", "Bytes", "Est. tokens", "Share of raw"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for d in data:
        raw_total, lean_total = sum(d["raw"].values()), sum(d["lean"].values())
        entries = [(f"Raw, all four systems ({s})", d["raw"][s], raw_total) for s in SOURCES]
        entries.append(("Raw, all four systems (total)", raw_total, raw_total))
        entries += [(f"Trimmed, all four systems ({s})", d["lean"][s], raw_total) for s in SOURCES]
        entries.append(("Trimmed, all four systems (total)", lean_total, raw_total))
        if d["sql_result"] is not None:
            entries.append(("SQL arm, rows returned to the model", d["sql_result"], raw_total))
        for label, b, base in entries:
            lines.append(f"| {d['n']} | {label} | {b:,} | {round(b / CHARS_PER_TOKEN):,} | {100 * b / base:.1f}% |")
    return "\n".join(lines)


def main() -> None:
    print(markdown())


if __name__ == "__main__":
    main()
