# Trace format (schema_version 1)

Every agent run writes one JSON trace. The web app reads only these files plus `results/index.json`
and `results/truth/n<N>.json`. Times are milliseconds from the start of the run. Money is US
dollars. Token counts come from the API's `usage` object unless the field name ends in `_est`.

## Run trace: `results/traces/<run_id>.json`

```jsonc
{
  "schema_version": 1,
  "run_id": "tools-n40-r1",          // <arm>-n<N>-r<rep>
  "arm": "tools",                     // "tools" (one tool per system) | "sql" (one SQL tool)
  "n_matters": 40,
  "rep": 1,
  "stage": "proof",                   // "dev" | "pilot" | "proof" | "showcase"
  "pot": "proof",                     // "dev" | "proof" | "showcase"
  "model": "claude-sonnet-5-5",
  "seed": 7,
  "today": "2026-09-15",
  "started_at": "2026-09-29T15:15:00Z",
  "finished_at": "2026-09-29T15:17:12Z",
  "outcome": "answered",              // "answered" | "budget_stop" | "turn_limit"
                                      // | "context_overflow" | "max_tokens" | "refusal" | "error"
  "error": null,                      // message when outcome is "error"
  "question": "Which active litigation matters ...",
  "system_prompt": "You are an assistant at Harbor & Vale LLP ...",
  "tools": [ { "name": "matters_list", "description": "..." } ],
  "turns": [
    {
      "index": 0,
      "started_ms": 0,
      "model_ms": 2300,               // time waiting on the model for this turn
      "retries": 0,                   // optional: model-call retries this turn (429, 5xx, connection errors)
      "retry_wait_ms": 0,             // optional: time spent waiting between those retries, not in model_ms
      "tools_ms": 450,                // time running this turn's tool calls (in parallel)
      "usage": {
        "input_tokens": 1200,
        "cache_creation_input_tokens": 3100,
        "cache_read_input_tokens": 0,
        "output_tokens": 310
      },
      "context_tokens": 4300,         // sum of the three input counts: what the model read
      "cost_usd": 0.0141,
      "stop_reason": "tool_use",
      "text": "I'll start by listing open matters.",   // visible text, max 2000 chars
      "tool_calls": [
        {
          "id": "toolu_01...",
          "name": "matters_list",
          "input": { "status": "Open", "page": 1 },
          "is_error": false,
          "duration_ms": 160,
          "result_bytes": 48211,
          "result_tokens_est": 13775,  // result_bytes / 3.5
          "preview": "{\"data\":[{\"id\":10001, ...",  // first 1500 chars of the result
          "load_ms": 140,             // optional, sql arm only: time building the DuckDB tables in this call
          "api_calls": [
            {
              "source": "matters",    // "matters" | "docket" | "mail" | "billing"
              "endpoint": "GET /api/v4/matters",
              "params": { "status": "Open", "page": 1, "page_size": 25 },
              "started_ms": 1,        // from the start of this tool call
              "duration_ms": 151,
              "bytes": 48211
            }
          ]
        }
      ]
    }
  ],
  "answer": {                         // input of the submit_answer call, or null
    "at_risk": [ { "attorney": "Dana Whitfield", "matters": ["HV-2026-0012"] } ],
    "notes": "..."
  },
  "totals": {
    "turns": 12,
    "tool_calls": 81,
    "api_calls": 83,
    "input_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "output_tokens": 0,
    "context_peak_tokens": 0,
    "result_bytes": 0,
    "cost_usd": 0.0,
    "wall_ms": 0,
    "model_ms": 0,
    "tools_ms": 0
  },
  "score": {                          // null until scored
    "expected_count": 9,
    "submitted_count": 10,
    "precision": 0.9,
    "recall": 1.0,
    "f1": 0.947,
    "grouping_exact": false,
    "false_positives": ["HV-2026-0031"],
    "false_negatives": []
  }
}
```

The `submit_answer` call appears in `tool_calls` like any other call, with an empty `api_calls`.

Fields added by the runner (extra to the schema above; nothing was renamed or removed):

- `effort`: the `output_config.effort` value sent with each request (`"medium"`), or `null` for
  models that take no effort parameter (Haiku 4.5).
- `latency_s`: the simulated upstream API latency per call, in seconds (`0.15` by default).
- `tools` also lists the local `submit_answer` tool, since the model sees it.
- `score` is `null` unless the model submitted an answer, so runs that ended in `budget_stop`,
  `turn_limit`, `context_overflow`, `refusal` or `error` before answering are unscored.
- `error` also carries the reason for `budget_stop` (pot, spend, estimate and cap), `context_overflow`
  and `max_tokens`. `context_overflow` covers both a "prompt is too long" rejection and the stop reason
  `model_context_window_exceeded`; `max_tokens` means a reply hit the 16,000-token output limit.
- `retries` and `retry_wait_ms` on a turn are optional; older traces lack them. The runner turns the
  SDK's own retries off and retries up to 3 times itself on 429, 5xx and connection errors, waiting 2,
  4 and 8 s. Those waits count in `wall_ms` but not in `model_ms`.
- `load_ms` on a `sql_query` tool call is optional (older traces and the tools arm lack it). The SQL
  server fetches all data on its first query and serves later queries from memory, so only the first
  `sql_query` call has a non-zero `load_ms` and lists the loading `api_calls`. `load_ms` is the time
  spent building DuckDB tables, excluding waits on the fake APIs.
- Tool results returned to the model are the full text. `result_bytes` is the UTF-8 length of that text.

## Run index: `results/index.json`

A JSON array, one object per run, in the order the runs were made. Each object has `run_id`,
`stage`, `arm`, `n_matters`, `rep`, `model`, `outcome`, every field of `totals`, and `precision`,
`recall`, `f1`, `grouping_exact` from `score` (null when unscored). `results/results.csv` holds the
same rows with the same column names.

## Ground truth: `results/truth/n<N>.json`

```jsonc
{
  "n_matters": 40,
  "seed": 7,
  "today": "2026-09-15",
  "at_risk": [ { "attorney": "Dana Whitfield", "matters": ["HV-2026-0012", "HV-2026-0027"] } ],
  "traps": {                          // how many of each planted trap exist at this N
    "deadline_just_outside_window": 3,
    "opposing_counsel_email_only": 4,
    "non_billable_time_only": 3,
    "client_email_just_outside_window": 2,
    "closed_with_deadline": 2,
    "non_litigation_with_deadline": 3
  }
}
```

Attorneys and matters inside `at_risk` are sorted by name and display number.

`at_risk` is what the stated rule gives, computed in plain Python from the generated data. Three of
the planted trap types are matters that look healthy to a careless reader but are at risk by the rule
(`opposing_counsel_email_only`, `non_billable_time_only`, `client_email_just_outside_window`, whose
latest client email is dated 2026-08-31). The other three look at risk but are not
(`deadline_just_outside_window`, `closed_with_deadline`, `non_litigation_with_deadline`). `traps` counts
all six regardless of which way they fall.

## Additions in phase 2 (robustness runs)

All additions are optional for older traces; readers must treat a missing field as the default.

- `variant`: `"base"` (default, the original question) | `"math"` | `"textdeadlines"`.
- `profile`: `"v1"` (default, the original generator) | `"v2"` (v1 plus boundary cases at every
  N >= 10).
- `arm` gains `"tools-lean"`: the same four per-system tools, same filters and pagination, with each
  record trimmed to exactly the columns the SQL tables hold (matters also carry `client_contacts`,
  mail also carries `participants`). Its tool descriptions say the records are trimmed.
- New pots: `"p2-base"`, `"p2-variants"`. New stage values: `"p2-base"`, `"p2-variants"`.
- Run ids for phase 2 runs: `<variant>-<arm>-n<N>-s<seed>-<model tag>`, where the model tag is
  `sonnet` or `haiku`, e.g. `math-tools-n40-s11-sonnet`. Phase 1 ids are unchanged. A run with the
  default variant and profile (`base`, `v1`) and arm `tools` or `sql` keeps the phase 1 id format.
- `system_prompt` starts with `Run <16 hex characters>.`, random per run, recorded as sent. It keeps
  runs from sharing a cached conversation prefix.
- `score.errors_by_trap`: `{ "<trap type or healthy or at_risk_plain>": { "false_positives": [...],
  "false_negatives": [...] } }`, listing only kinds with at least one error. A submitted matter number
  that does not exist in the data is filed under `unknown`. Every trace scored from phase 2 on has the
  key (an empty object when there are no errors); phase 1 traces do not.
- A matter's kind is its planted trap type: a boundary or variant trap type wins over a phase 1 trap
  type; a matter with none is `healthy` or `at_risk_plain`.
- Ground truth for phase 2 runs: `results/truth/<variant>-<profile>-s<seed>-n<N>.json`, same shape
  plus `variant` and `profile`, and `traps` includes any boundary or variant-specific trap types.
  Trap types by profile and variant:
  - v2 adds `boundary_deadline_today`, `boundary_deadline_last_day`, `boundary_email_last_day`,
    `boundary_billable_first_day`, and a second matter of type `deadline_just_outside_window`.
  - math adds `hours_just_under`, `hours_at_threshold`, `hours_just_over`, `unbilled_just_under`,
    `unbilled_at_threshold`, `unbilled_just_over`.
  - textdeadlines adds `deadline_continued_out`, `deadline_continued_in`, `deadline_vacated`.
  A matter can count under a phase 1 trap type and a newer one, so trap counts can overlap.
- `results/index.json` rows and `results/results.csv` gain `variant`, `profile` and `seed` (after
  `arm`; defaults `base`, `v1`, and the run's seed).
- `results/traces/cut/<run_id>.json` holds traces of attempts that ended in `budget_stop` and were later
  rerun. They are kept to document the wasted spend and are not in the index.
