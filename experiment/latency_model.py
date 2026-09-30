"""Recompute each run's tool time under a more realistic latency model. Free, no API.

    python -m experiment.latency_model [--results results]

The recorded runs used 150 ms of fake latency per upstream API call. Real APIs are slower and rate
limited. This model keeps the recorded call structure (which calls waited for which) and changes only
the cost of a call:

- each upstream call takes 500 ms;
- at most 10 calls run at once in a turn, all of the turn's tool calls pooled together;
- for the SQL arm, a second scenario also multiplies the mail pages by 10 (a year of history instead
  of about two months).

A call depends on another when it started after that one ended in the recording (a page loop, or the
docket fetches that need the matter list). Time a tool spent beyond its upstream calls (loading the
tables, running a query) is kept as recorded. Model time is unchanged. Tools inside one turn run in
parallel, as in the recording.
"""

from __future__ import annotations

import argparse
import heapq
import json
from pathlib import Path

PER_CALL_MS = 500
SLOTS = 10
MAIL_FACTOR = 10
TOLERANCE_MS = 2  # calls started in parallel differ by a millisecond or two


def modeled_finishes(groups: list[list[dict]], per_call_ms: int = PER_CALL_MS, slots: int = SLOTS, mail_factor: int = 1) -> list[int]:
    """Finish time (ms) of each group of upstream calls, all groups sharing one pool of slots.

    A group is one tool invocation's api_calls. Dependencies (page loops, docket fetches waiting for the
    lists) only exist inside a group; the slot limit applies to every call of the turn pooled together."""
    flat = [(g, c) for g, calls in enumerate(groups) for c in calls]
    finishes = [0] * len(groups)
    if not flat:
        return finishes
    order = sorted(range(len(flat)), key=lambda i: flat[i][1]["started_ms"])
    end = [c["started_ms"] + c["duration_ms"] for _, c in flat]
    src = [c["source"] for _, c in flat]

    def depends(j: int, i: int) -> bool:
        """Call i waited for call j: same tool invocation, it started after j ended, in the same page loop,
        or (docket fetches) after the lists they need."""
        if j == i or flat[j][0] != flat[i][0]:
            return False
        if end[j] > flat[i][1]["started_ms"] + TOLERANCE_MS or flat[j][1]["started_ms"] >= flat[i][1]["started_ms"]:
            return False
        return src[j] == src[i] or (src[i] == "docket" and src[j] != "docket")

    def copies(i: int) -> int:
        return mail_factor if src[i] == "mail" else 1

    free = [0] * slots
    heapq.heapify(free)
    finish: dict[tuple[int, int], int] = {}
    for i in order:
        ready = max((finish[(j, copies(j) - 1)] for j in order if depends(j, i)), default=0)
        for k in range(copies(i)):  # copy k+1 is the next page in the chain
            start = max(ready, heapq.heappop(free))
            ready = start + per_call_ms
            heapq.heappush(free, ready)
            finish[(i, k)] = ready
            finishes[flat[i][0]] = max(finishes[flat[i][0]], ready)
    return finishes


def modeled_span(api_calls: list[dict], per_call_ms: int = PER_CALL_MS, slots: int = SLOTS, mail_factor: int = 1) -> int:
    """Time to run one tool invocation's upstream calls under the model, in ms."""
    return modeled_finishes([api_calls], per_call_ms, slots, mail_factor)[0]


def recorded_span(api_calls: list[dict]) -> int:
    return max((c["started_ms"] + c["duration_ms"] for c in api_calls), default=0)


def modeled_turn_ms(tool_calls: list[dict], mail_factor: int = 1) -> int:
    """One turn's tool time: its tool calls run in parallel and share the 10 slots. Each call's modeled
    upstream time is kept, plus whatever the call spent beyond its upstream calls."""
    finishes = modeled_finishes([c["api_calls"] for c in tool_calls], mail_factor=mail_factor)
    out = 0
    for call, fin in zip(tool_calls, finishes):
        if not call["api_calls"]:
            out = max(out, call["duration_ms"])
        else:
            out = max(out, fin + max(0, call["duration_ms"] - recorded_span(call["api_calls"])))
    return out


def model_trace(trace: dict) -> dict:
    turns = trace["turns"]
    recorded = sum(t["tools_ms"] for t in turns)
    model_ms = sum(t["model_ms"] for t in turns)

    def tools(mail_factor: int) -> int:
        return sum(modeled_turn_ms(t["tool_calls"], mail_factor) for t in turns)

    out = {
        "run_id": trace["run_id"], "arm": trace["arm"], "recorded_tools_ms": recorded, "model_ms": model_ms,
        "modeled_tools_ms": tools(1),
    }
    out["modeled_wall_ms"] = model_ms + out["modeled_tools_ms"]
    if trace["arm"] == "sql":
        out["modeled_tools_ms_mail_x10"] = tools(MAIL_FACTOR)
        out["modeled_wall_ms_mail_x10"] = model_ms + out["modeled_tools_ms_mail_x10"]
    return out


def load_traces(results: Path) -> list[dict]:
    traces = [json.loads(p.read_text()) for p in sorted((results / "traces").glob("*.json"))]
    return sorted(traces, key=lambda t: (t["started_at"], t["run_id"]))


def rows(results: Path) -> list[dict]:
    return [model_trace(t) for t in load_traces(results) if t["turns"]]


def markdown(data: list[dict]) -> str:
    head = ["Run", "Recorded tools s", "Modeled tools s", "Modeled wall s", "Modeled tools s, mail x10", "Modeled wall s, mail x10"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    s = lambda ms: f"{ms / 1000:.1f}"  # noqa: E731
    for r in data:
        lines.append("| " + " | ".join([
            r["run_id"], s(r["recorded_tools_ms"]), s(r["modeled_tools_ms"]), s(r["modeled_wall_ms"]),
            s(r["modeled_tools_ms_mail_x10"]) if "modeled_tools_ms_mail_x10" in r else "n/a",
            s(r["modeled_wall_ms_mail_x10"]) if "modeled_wall_ms_mail_x10" in r else "n/a",
        ]) + " |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(Path(__file__).resolve().parent.parent / "results"))
    args = ap.parse_args()
    print(markdown(rows(Path(args.results))))


if __name__ == "__main__":
    main()
