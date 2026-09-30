"""Agent runner: one agent answers the at-risk question with one arm's MCP tools and writes a trace.

    python -m experiment.run --arm sql --n 5 --rep 1 --model claude-haiku-4-5 --stage dev --pot dev \
        --out runs --env-file path/to/anthropic.env

The trace format is documented in docs/trace-format.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from experiment.envfile import load_env_file
from experiment.generate import TODAY, generate
from experiment.ledger import DEFAULT_PATH, Ledger
from experiment.prices import PRICES, SUPPORTS_EFFORT, cost_usd
from experiment.questions import QUESTIONS, new_run_tag, system_prompt
from experiment.truth import matter_kinds, write_truth

ROOT = Path(__file__).resolve().parent.parent

QUESTION = QUESTIONS["base"]
NUDGE = "Please submit your final answer with the submit_answer tool."

SUBMIT_TOOL = {
    "name": "submit_answer",
    "description": "Submit the final answer: the at-risk matters grouped by responsible attorney. Call exactly once.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "at_risk": {
                "type": "array",
                "description": "One entry per responsible attorney who has at least one at-risk matter.",
                "items": {
                    "type": "object",
                    "properties": {
                        "attorney": {"type": "string", "description": "Attorney full name."},
                        "matters": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Display numbers such as HV-2026-0012.",
                        },
                    },
                    "required": ["attorney", "matters"],
                    "additionalProperties": False,
                },
            },
            "notes": {"type": "string", "description": "Short notes on how you got the answer."},
        },
        "required": ["at_risk", "notes"],
        "additionalProperties": False,
    },
}

STAGES = ("dev", "pilot", "proof", "showcase", "p2-base", "p2-variants")
POTS = ("dev", "proof", "showcase", "p2-base", "p2-variants")
ARMS = ("tools", "tools-lean", "sql")
MODEL_TAGS = {"claude-sonnet-5-5": "sonnet", "claude-haiku-4-5": "haiku"}
CHARS_PER_TOKEN = 3.5
MAX_TOKENS = 16000
TOOL_READ_TIMEOUT = timedelta(seconds=60)
RETRY_WAITS_S = (2, 4, 8)
TERMINAL_STOPS = {
    "refusal": "refusal",
    "model_context_window_exceeded": "context_overflow",
    "max_tokens": "max_tokens",
}


def make_run_id(args) -> str:
    """Phase 1 ids for the original data and question; phase 2 ids carry variant, seed and model tag."""
    if (args.profile, args.variant) == ("v1", "base") and args.arm in ("tools", "sql"):
        return f"{args.arm}-n{args.n}-r{args.rep}"
    return f"{args.variant}-{args.arm}-n{args.n}-s{args.seed}-{MODEL_TAGS[args.model]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_attorney(name) -> str:
    """Accent-stripped, case-folded, single-spaced: 'Tomás  Ibarra' matches 'tomas ibarra'."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", str(name)) if not unicodedata.combining(c))
    return " ".join(plain.casefold().split())


def norm_matter(number) -> str:
    return str(number).strip().upper()


def errors_by_trap(false_positives: list[str], false_negatives: list[str], kinds: dict[str, str]) -> dict:
    """Group errors by what the matter is (a trap type, "healthy" or "at_risk_plain"). A matter number that
    does not exist in the data is filed under "unknown". Only kinds with at least one error appear."""
    out: dict[str, dict[str, list[str]]] = {}
    for key, items in (('false_positives', false_positives), ('false_negatives', false_negatives)):
        for matter in items:
            entry = out.setdefault(kinds.get(matter, 'unknown'), {'false_positives': [], 'false_negatives': []})
            entry[key].append(matter)
    return out


def score_answer(answer: dict | None, expected: dict, kinds: dict[str, str] | None = None) -> dict | None:
    """Score a submitted answer against the ground truth (contract: `score` block). None if unanswered.
    Attorney names and matter numbers are normalized on both sides before comparing. With `kinds`
    (display number -> trap type) the score also carries `errors_by_trap`."""
    if answer is None:
        return None
    want = {norm_matter(m) for g in expected["at_risk"] for m in g["matters"]}
    got_list = [norm_matter(m) for g in answer.get("at_risk", []) for m in g.get("matters", [])]
    got = set(got_list)
    tp = len(want & got)
    precision = tp / len(got) if got else 0.0
    recall = tp / len(want) if want else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    submitted: dict[str, set] = {}
    for g in answer.get("at_risk", []):
        ms = {norm_matter(m) for m in g.get("matters", [])}
        if ms:
            submitted.setdefault(norm_attorney(g.get("attorney", "")), set()).update(ms)
    truth = {}
    for g in expected["at_risk"]:
        truth.setdefault(norm_attorney(g["attorney"]), set()).update(norm_matter(m) for m in g["matters"])
    score = {
        "expected_count": len(want),
        "submitted_count": len(got),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "grouping_exact": truth == submitted,
        "false_positives": sorted(got - want),
        "false_negatives": sorted(want - got),
    }
    if kinds is not None:
        score["errors_by_trap"] = errors_by_trap(score["false_positives"], score["false_negatives"], kinds)
    return score


def usage_dict(u) -> dict:
    return {
        "input_tokens": u.input_tokens or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        "output_tokens": u.output_tokens or 0,
    }


def result_text(result) -> str:
    return "".join(c.text for c in result.content if getattr(c, "type", "") == "text")


async def call_tool(session: ClientSession, tool_use, run_t0: float) -> dict:
    """Call one MCP tool and return the trace record plus the text handed back to the model."""
    started = time.perf_counter()
    try:
        res = await session.call_tool(tool_use.name, dict(tool_use.input), read_timeout_seconds=TOOL_READ_TIMEOUT)
        text, is_error = result_text(res), bool(res.isError)
        meta = res.meta or {}
        api_calls, load_ms = meta.get("api_calls", []), meta.get("load_ms")
    except Exception as exc:  # protocol-level failure: let the model see it and carry on
        text, is_error, api_calls, load_ms = f"Tool call failed: {exc}", True, [], None
    duration_ms = round((time.perf_counter() - started) * 1000)
    size = len(text.encode("utf-8"))
    record = {
            "id": tool_use.id,
            "name": tool_use.name,
            "input": dict(tool_use.input),
            "is_error": is_error,
            "duration_ms": duration_ms,
            "result_bytes": size,
            "result_tokens_est": round(size / CHARS_PER_TOKEN),
            "preview": text[:1500],
            "api_calls": api_calls,
    }
    if load_ms is not None:
        record["load_ms"] = load_ms
    return {"text": text, "record": record}


async def create_with_retries(client, sleep=asyncio.sleep, **kwargs):
    """messages.create with our own retries (the SDK's are off): up to 3 retries on 429, 5xx and connection
    errors, waiting 2, 4, 8 s. Returns (response, retries, wait_ms, model_ms) where model_ms excludes the waits."""
    retries, waited = 0, 0.0
    started = time.perf_counter()
    while True:
        try:
            response = await client.messages.create(**kwargs)
            break
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as exc:
            if retries >= len(RETRY_WAITS_S):
                raise
            wait = RETRY_WAITS_S[retries]
            print(f"retry {retries + 1} after {type(exc).__name__}, waiting {wait} s", file=sys.stderr)
            retries += 1
            waited += wait
            await sleep(wait)
    model_ms = round((time.perf_counter() - started - waited) * 1000)
    return response, retries, round(waited * 1000), max(model_ms, 0)


async def run(args: argparse.Namespace) -> dict:
    load_env_file(args.env_file)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set (use the environment or --env-file)")
    if args.model not in PRICES:
        raise SystemExit(f"no prices for model {args.model}; add it to experiment/prices.py")

    run_id = make_run_id(args)
    trace_path = Path(args.out) / "traces" / f"{run_id}.json"
    if trace_path.exists() and not args.force:
        raise SystemExit(f"{trace_path} exists; pass --force to overwrite it")
    ledger = Ledger(args.ledger, args.cap)
    module = "server_sql" if args.arm == "sql" else "server_tools"
    server_args = [
        "-m", f"experiment.{module}", "--n", str(args.n), "--seed", str(args.seed), "--latency", str(args.latency),
        "--profile", args.profile, "--variant", args.variant,
    ]
    if args.arm == "tools-lean":
        server_args.append("--lean")
    server = StdioServerParameters(command=sys.executable, args=server_args, cwd=str(ROOT))
    trace: dict = {
        "schema_version": 1,
        "run_id": run_id,
        "arm": args.arm,
        "variant": args.variant,
        "profile": args.profile,
        "n_matters": args.n,
        "rep": args.rep,
        "stage": args.stage,
        "pot": args.pot,
        "model": args.model,
        "seed": args.seed,
        "today": TODAY.isoformat(),
        "effort": args.effort if args.model in SUPPORTS_EFFORT else None,
        "latency_s": args.latency,
        "started_at": now_iso(),
        "finished_at": None,
        "outcome": None,
        "error": None,
        "question": QUESTIONS[args.variant],
        "system_prompt": system_prompt(new_run_tag()),
        "tools": [],
        "turns": [],
        "answer": None,
        "totals": None,
        "score": None,
    }
    t0 = time.perf_counter()
    spent = 0.0
    try:
        log_dir = Path(args.out) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / f"{run_id}.server.log", "w") as server_log:
            async with stdio_client(server, errlog=server_log) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    mcp_tools = (await session.list_tools()).tools
                    tool_defs = [
                        {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema} for t in mcp_tools
                    ] + [SUBMIT_TOOL]
                    trace["tools"] = [{"name": t["name"], "description": t["description"]} for t in tool_defs]
                    spent = await agent_loop(args, trace, session, tool_defs, ledger, run_id, t0)
    except Exception as exc:  # any failure still produces a trace
        while isinstance(exc, BaseExceptionGroup) and exc.exceptions:  # anyio wraps errors in task groups
            exc = exc.exceptions[0]
        trace["outcome"], trace["error"] = "error", f"{type(exc).__name__}: {exc}"
    finish(args, trace, ledger, run_id, t0)
    return trace


async def agent_loop(args, trace, session, tool_defs, ledger: Ledger, run_id: str, t0: float, client=None) -> float:
    client = client or anthropic.AsyncAnthropic(max_retries=0)
    price = PRICES[args.model]
    extra = {"output_config": {"effort": args.effort}} if args.model in SUPPORTS_EFFORT else {}
    question = trace.get("question", QUESTION)
    system = trace.get("system_prompt") or system_prompt(new_run_tag())
    messages: list[dict] = [{"role": "user", "content": question}]
    prompt_chars = len(system) + len(question) + len(json.dumps(tool_defs))
    last_context = round(prompt_chars / CHARS_PER_TOKEN)
    last_output = 0
    pending_result_tokens = 0
    spent = 0.0
    nudged = False

    for index in range(args.max_turns):
        # conservative: the next prompt is priced at the cache-write rate, and the reply at max_tokens
        est = (
            (last_context + last_output + pending_result_tokens + 500) * price["cache_write_5m"]
            + MAX_TOKENS * price["output"]
        ) / 1e6
        if ledger.spent(args.pot) + est > ledger.cap(args.pot):
            trace["outcome"] = "budget_stop"
            trace["error"] = (
                f"budget_stop: pot {args.pot} spent ${ledger.spent(args.pot):.4f} + estimate ${est:.4f} "
                f"exceeds cap ${ledger.cap(args.pot):.2f}"
            )
            print(trace["error"], file=sys.stderr)
            return spent
        turn_start = time.perf_counter()
        try:
            response, retries, wait_ms, model_ms = await create_with_retries(
                client,
                model=args.model,
                max_tokens=MAX_TOKENS,
                system=system,
                tools=tool_defs,
                messages=messages,
                cache_control={"type": "ephemeral"},
                **extra,
            )
        except anthropic.BadRequestError as exc:
            if "prompt is too long" in str(exc).lower():
                trace["outcome"] = "context_overflow"
                trace["error"] = str(exc)[:500]
                return spent
            raise
        usage = usage_dict(response.usage)
        cost = cost_usd(args.model, usage)
        spent += cost
        ledger.add(args.pot, run_id, args.model, cost)
        last_context = usage["input_tokens"] + usage["cache_creation_input_tokens"] + usage["cache_read_input_tokens"]
        last_output = usage["output_tokens"]
        pending_result_tokens = 0
        text = "".join(b.text for b in response.content if b.type == "text")[:2000]
        turn = {
            "index": index,
            "started_ms": round((turn_start - t0) * 1000),
            "model_ms": model_ms,
            "retries": retries,
            "retry_wait_ms": wait_ms,
            "tools_ms": 0,
            "usage": usage,
            "context_tokens": last_context,
            "cost_usd": round(cost, 6),
            "stop_reason": response.stop_reason,
            "text": text,
            "tool_calls": [],
        }
        trace["turns"].append(turn)

        if response.stop_reason in TERMINAL_STOPS:
            trace["outcome"] = TERMINAL_STOPS[response.stop_reason]
            if response.stop_reason != "refusal":
                trace["error"] = f"stop_reason: {response.stop_reason}"
            return spent
        messages.append({"role": "assistant", "content": response.content})
        uses = [b for b in response.content if b.type == "tool_use"]

        if response.stop_reason == "tool_use" and uses:
            tools_start = time.perf_counter()
            submit = next((u for u in uses if u.name == "submit_answer"), None)
            others = [u for u in uses if u.name != "submit_answer"]
            done = await asyncio.gather(*(call_tool(session, u, t0) for u in others))
            turn["tools_ms"] = round((time.perf_counter() - tools_start) * 1000)
            results = []
            for u, d in zip(others, done):
                turn["tool_calls"].append(d["record"])
                pending_result_tokens += d["record"]["result_tokens_est"]
                block = {"type": "tool_result", "tool_use_id": u.id, "content": d["text"]}
                if d["record"]["is_error"]:
                    block["is_error"] = True
                results.append(block)
            if submit is not None:
                trace["answer"] = dict(submit.input)
                turn["tool_calls"].append(
                    {
                        "id": submit.id, "name": "submit_answer", "input": dict(submit.input), "is_error": False,
                        "duration_ms": 0, "result_bytes": len("Answer recorded."), "result_tokens_est": 5,
                        "preview": "Answer recorded.", "api_calls": [],
                    }
                )
                trace["outcome"] = "answered"
                return spent
            messages.append({"role": "user", "content": results})
        elif response.stop_reason == "end_turn":
            if nudged:
                trace["outcome"], trace["error"] = "error", "no answer submitted"
                return spent
            nudged = True
            messages.append({"role": "user", "content": NUDGE})
        else:
            trace["outcome"], trace["error"] = "error", f"unexpected stop_reason: {response.stop_reason}"
            return spent
    trace["outcome"] = "turn_limit"
    return spent


def finish(args, trace: dict, ledger: Ledger, run_id: str, t0: float) -> None:
    trace["finished_at"] = now_iso()
    turns = trace["turns"]
    calls = [c for t in turns for c in t["tool_calls"]]
    sums = lambda key: sum(t["usage"][key] for t in turns)  # noqa: E731
    trace["totals"] = {
        "turns": len(turns),
        "tool_calls": len(calls),
        "api_calls": sum(len(c["api_calls"]) for c in calls),
        "input_tokens": sums("input_tokens"),
        "cache_creation_input_tokens": sums("cache_creation_input_tokens"),
        "cache_read_input_tokens": sums("cache_read_input_tokens"),
        "output_tokens": sums("output_tokens"),
        "context_peak_tokens": max((t["context_tokens"] for t in turns), default=0),
        "result_bytes": sum(c["result_bytes"] for c in calls),
        "cost_usd": round(sum(t["cost_usd"] for t in turns), 6),
        "wall_ms": round((time.perf_counter() - t0) * 1000),
        "model_ms": sum(t["model_ms"] for t in turns),
        "tools_ms": sum(t["tools_ms"] for t in turns),
    }
    out = Path(args.out)
    truth_file = write_truth(args.n, args.seed, out / "truth", args.profile, args.variant)
    kinds = matter_kinds(generate(args.n, args.seed, args.profile, args.variant))
    trace["score"] = score_answer(trace["answer"], json.loads(truth_file.read_text()), kinds)
    (out / "traces").mkdir(parents=True, exist_ok=True)
    (out / "traces" / f"{run_id}.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False) + "\n")
    ledger.finish(args.pot, run_id, args.model)


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", choices=ARMS, required=True)
    ap.add_argument("--variant", choices=["base", "math", "textdeadlines"], default="base")
    ap.add_argument("--profile", choices=["v1", "v2"], default="v1")
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--rep", type=int, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--stage", choices=STAGES, required=True)
    ap.add_argument("--pot", choices=POTS, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--latency", type=float, default=0.15)
    ap.add_argument("--env-file")
    ap.add_argument("--ledger", default=str(DEFAULT_PATH))
    ap.add_argument("--force", action="store_true", help="overwrite an existing trace for this run")
    ap.add_argument("--cap", type=float, help="override the pot's cap in USD (testing)")
    return ap.parse_args(argv)


def main() -> None:
    logging.getLogger().setLevel(logging.WARNING)
    trace = asyncio.run(run(parse_args()))
    t = trace["totals"]
    print(
        f"{trace['run_id']} outcome={trace['outcome']} turns={t['turns']} tool_calls={t['tool_calls']} "
        f"cost=${t['cost_usd']:.4f} score={trace['score'] and trace['score']['f1']}"
    )
    if trace["error"]:
        print(f"note: {trace['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()
