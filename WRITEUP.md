# One tool per system, or one SQL tool?

## TL;DR

Two terms first. **Tokens read** is every input token the model processed across all of a run's calls, including
cached re-reads. **Peak context** is the largest single prompt the model saw in a run. Cost and peak context are
the numbers to trust most, because tokens read overstates the gap once caching is counted.

The numbers, generated from `results/index.json`:

<!-- tldr:start -->

- On the base task at 120 matters, the SQL agent cost $0.018 to $0.027 per run and its peak context was 2,972 to 5,198 tokens. The tools agent cost $0.63 with a peak context of 204,495 tokens (one seed; seed 12 was stopped twice by the budget cap, not by the model). The trimmed-tools agent cost $0.51 to $0.60 with a peak context of 146,461 to 146,754 tokens.
- Paired tools/sql cost ratios: 12x to 15x at 40 matters (two seeds) and 24x at 120 matters (1 pair). Tokens read ratios: 28x to 32x and 51x. Phase 1 (one seed, no cache isolation) had 54x for cost and 110x for tokens read at 120 matters.
- Held under trimming: trimming records lowered peak context and cost, more at 40 matters than at 120, but the trimmed agent still cost 9.2x to 29x the SQL agent. At 120 it was also slower than plain tools.
- Accuracy did not separate the arms on Sonnet 5.5 at these sizes: F1 was 1.00 in 20 of 20 answered phase 2 runs (trimmed tools ran only on the base task). No run missed a matter or added a wrong one.
- The arithmetic variant did not trip the tools agent when it answered (F1 1.00 at 40 matters, $0.61). At 120 matters it stopped with outcome max_tokens after $1.68, with no answer, while the SQL agent answered with F1 1.00 for $0.019. The deadlines-in-text variant did not trip either agent (F1 1.00 in 6 runs); at 40 matters the SQL agent then cost $0.053 to $0.060 per run (base task: $0.018 to $0.019) and the tools agent $0.20 to $0.24.
- Haiku 4.5 is where accuracy did separate the arms. Its SQL agent scored F1 1.00, 1.00, 1.00 (cost $0.018 to $0.038); its tools agent scored F1 0.50, 1.00, 0.94 at 40 matters (cost $0.16 to $0.17). At 120 matters its tools run submitted an empty list (F1 0.00) without hitting its 200,000-token window. There was no Haiku SQL run at 120.
- Where SQL was worse: it makes far more upstream API calls behind its one tool (143 to 144 against 45 at 120 matters). Under a slower, limited upstream (500 ms a call, 10 at once) the modeled tools/sql wall-time ratio at 120 matters is 2.1x. With ten times the mail pages it is 0.64x. Only the SQL server's load grows in that case, because it pulls all mail while the tools agents filtered mail by date. That is the missing predicate pushdown caveat, priced.
- Wall time did not drop 10x in the recorded runs: tools/sql was 2.3x to 2.6x at 40 matters and 3.3x at 120 matters.
- Sample sizes are small: 43 runs in total, 22 on Sonnet in phase 2, at most two seeds per Sonnet base cell and one at 120 matters in the variants. Read the ranges as a first look, not as statistics.

<!-- tldr:end -->

What held and what did not:

- Held: one SQL tool over everything cost far less money and needed far less context than one tool per system. The gap grew with the number of matters. It survived fresh data, fresh seeds, no cache reuse between runs, and trimmed records.
- Did not hold: wall time did not drop 10x. Waiting on the model hides most of the difference.
- Not tested: whether hand-done aggregation causes errors. On Sonnet 5.5 every answered run scored a perfect F1, in the base task and both harder variants. Accuracy never separated the arms at these sizes on that model.
- Where SQL was worse: it makes many more upstream calls behind its one tool, it can be the slower agent when mail history is long and the upstream is slow, and it costs more when the answer hides in free text.
- Accuracy did separate the arms on Haiku 4.5, the weaker model, and only there. That is one model and a handful of runs.

## The question

Every arm gets the same question, word for word:

> Which active litigation matters are at risk of being neglected? A matter is at risk only if all of these are true:
> 1. Its status is Open and its practice area is Litigation.
> 2. It has a court deadline from 2026-09-15 to 2026-10-06, inclusive.
> 3. No email dated 2026-09-01 to 2026-09-15, inclusive, was sent to or from any of the client's contacts. Emails with opposing counsel or anyone else don't count.
> 4. No billable time was recorded on it dated 2026-09-01 to 2026-09-15, inclusive. Non-billable entries don't count.
>
> List the at-risk matters by display number (like HV-2026-0012), grouped by responsible attorney, and submit them with the submit_answer tool.

Legal is a good test because the answer needs four systems at once: the matter list, court dockets, email and billing. A missed matter here is a missed deadline, so wrong answers cost real money and trust. The data is fake (a made-up firm, Harbor & Vale LLP) and the correct answer is computed in plain Python, so every run is scored exactly. The data includes planted traps: matters that look at risk but are not, and matters that look fine but are at risk.

## The agents

- **Tools agent.** It sees one tool per system (matters, docket, mail, billing). It pages through each API and joins the results itself.
- **Trimmed-tools agent** (`tools-lean`, added in phase 2). The same four tools with the same filters and pagination, but each record is cut down to the columns the SQL tables hold. This is the best case for per-system tools.
- **SQL agent.** It sees two tools: `describe_schema` and `sql_query`. The server loads the four systems into one database and the agent writes queries.
- All arms use the same system prompt, the same data and the same 150 ms of simulated delay per API call. The phase 1 runs and most phase 2 runs use Sonnet 5.5 at medium effort. Phase 2 also repeats the base task on Haiku 4.5.

## Fairness choices

- Parallel tool calls are allowed for every arm.
- Prompt caching is on for every arm.
- The search tools can filter, so the tools agent does not have to list everything.
- List tools are paginated, as real APIs are.
- Real products allow field selection (for example Clio's `fields` parameter and Microsoft Graph's `$select`). The trimmed-tools arm stands in for that. The plain tools arm returns full records.
- Disclosed: the schema the SQL agent reads is hand-written, not discovered from the systems.
- Disclosed: email records carry a 255-character body preview in every arm, as Graph's `bodyPreview` does. Anything past 255 characters is invisible to all arms.
- Disclosed: in phase 2 each run's system prompt starts with a random run id, so runs do not share a cached conversation. The tool list is rendered before the system prompt, so it can still be cached across runs. It is small and the same kind for every arm.

## Results, phase 1

Phase 1 is one seed (7), one run per cell at most sizes and three at 20 matters, no cache isolation between runs. Cells are medians over answered runs. Every number in the tables is generated from `results/index.json`.

<!-- tables:start -->

#### Scaling by N (median of answered runs)

| N | Arm | Runs answered | Not answered | Cost $ | Peak context | Tokens read | Output tokens | Turns | Tool calls | API calls | Wall s | F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 5 | tools | 1 | none | 0.036 | 12,569 | 25,787 | 736 | 3 | 6 | 5 | 7.7 | 1.00 |
| 5 | sql | 1 | none | 0.008 | 2,421 | 5,694 | 549 | 3 | 3 | 8 | 6.4 | 1.00 |
| 10 | tools | 1 | none | 0.060 | 18,534 | 34,309 | 1,090 | 3 | 9 | 8 | 13.9 | 1.00 |
| 10 | sql | 1 | none | 0.014 | 2,511 | 5,784 | 705 | 3 | 3 | 13 | 7.7 | 1.00 |
| 20 | tools | 3 | none | 0.114 | 39,030 | 73,313 | 1,606 | 3 | 10 | 9 | 12.7 | 1.00 |
| 20 | sql | 3 | none | 0.009 | 2,492 | 5,765 | 687 | 3 | 3 | 25 | 7.2 | 1.00 |
| 40 | tools | 1 | none | 0.291 | 91,676 | 230,967 | 3,916 | 4 | 37 | 36 | 26.7 | 1.00 |
| 40 | sql | 1 | none | 0.011 | 2,609 | 5,882 | 817 | 3 | 3 | 49 | 8.4 | 1.00 |
| 120 | tools | 1 | none | 0.714 | 218,856 | 668,490 | 8,235 | 5 | 47 | 46 | 51.5 | 1.00 |
| 120 | sql | 1 | none | 0.013 | 2,982 | 6,255 | 970 | 3 | 3 | 144 | 9.9 | 1.00 |

#### Ratio tools / sql by N (ratio of medians)

| N | Cost $ | Peak context | Tokens read | Output tokens | Turns | Tool calls | API calls | Wall s |
|---|---|---|---|---|---|---|---|---|
| 5 | 4.7x | 5.2x | 4.5x | 1.3x | 1.0x | 2.0x | 0.62x | 1.2x |
| 10 | 4.3x | 7.4x | 5.9x | 1.5x | 1.0x | 3.0x | 0.62x | 1.8x |
| 20 | 12x | 16x | 13x | 2.3x | 1.0x | 3.3x | 0.36x | 1.8x |
| 40 | 27x | 35x | 39x | 4.8x | 1.3x | 12x | 0.73x | 3.2x |
| 120 | 54x | 73x | 110x | 8.5x | 1.7x | 16x | 0.32x | 5.2x |

#### Showcase pair

| Run | Outcome | Cost $ | Peak context | Tokens read | Output tokens | Turns | Tool calls | API calls | Wall s | F1 |
|---|---|---|---|---|---|---|---|---|---|---|
| tools-n120-r1 | answered | 0.714 | 218,856 | 668,490 | 8,235 | 5 | 47 | 46 | 51.5 | 1.00 |
| sql-n120-r1 | answered | 0.013 | 2,982 | 6,255 | 970 | 3 | 3 | 144 | 9.9 | 1.00 |

#### Predictions and verdicts

| # | Prediction | Actual | Verdict |
|---|---|---|---|
| P1 | At 20+ matters, tokens read drop about 10x | tools/sql at N=[20, 40, 120]: 13x, 39x, 110x | held |
| P2 | At 20+ matters, wall time drops about 10x | tools/sql at N=[20, 40, 120]: 1.8x, 3.2x, 5.2x | did not hold |
| P3 | Output tokens drop 2 to 5x | tools/sql at N=[20, 40, 120]: 2.3x, 4.8x, 8.5x | held, larger than predicted |
| P4 | The gap widens as N grows | tokens-read ratio at N=[10, 20, 40, 120]: 5.9x, 13x, 39x, 110x | held |
| P5 | Hand-done aggregation is where errors come from | mean F1 tools 1.00, sql 1.00 | not tested (ceiling) |

<!-- tables:end -->

Plain reading:

- Tokens read grow with the number of matters for the tools agent and stay small and nearly flat for the SQL agent.
- Tool calls and API calls behave differently. The tools agent makes more tool calls. The SQL server makes more upstream API calls behind its one tool, because it loads every matter's data.
- Turns barely change. Every arm finishes in a few turns, since it can call tools in parallel.
- Wall time gap is small at first and grows with size. Waiting on the model dominates, and the SQL agent also pays for loading the data on its first query.
- Dollars follow tokens read but are softened by caching, so the cost ratio is smaller than the tokens-read ratio.

## Predictions versus actuals

These are the predictions the experiment set out to test. The thresholds (10x, 2 to 5x) are the predictions. The verdict column in the table above is computed by fixed rules, on the phase 1 runs.

- P1 (tokens read drop about 10x at 20+ matters): held. The worst ratio clears the bar and the gap is much larger at 120 matters.
- P2 (wall time drops about 10x): did not hold. Waiting on the model, which every arm does for several seconds, hides most of the difference.
- P3 (output tokens drop 2 to 5x): held, larger than predicted at the top end.
- P4 (the gap widens with N): held. The tokens-read ratio rises at every step.
- P5 (hand-done aggregation is where errors come from): not tested (ceiling). Both arms were perfect, so there was nothing for the accuracy question to separate.

## Robustness (phase 2)

A reviewer of phase 1 raised fair objections. This phase answers them.

- Fresh data and seeds. The generator's second profile (`v2`) plants boundary cases at every size from 10 matters up, and the base task now runs on seeds 11 and 12, not just 7.
- No shared cache between runs. See the run id note above. The seed 7 pair from phase 1 is listed separately, labeled "no cache isolation".
- A fairer per-system arm. `tools-lean` returns trimmed records.
- Two harder variants meant to break each side. `math` replaces rule 4 with arithmetic: billable hours in 2026-09-01 to 2026-09-15 total less than 1.5, or unbilled billable time before 2026-09-01 totals more than $4,000, with totals planted just under, at and just over each threshold. `textdeadlines` removes the structured deadline columns, so deadlines exist only in docket entry text, and later entries can continue or vacate an earlier deadline.
- A weaker model. The base task on Haiku 4.5.
- Free checks that cost no API money: what a one-rule misreading scores, timings under a slower upstream, and bytes moved.

Ranges below are min to max across seeds 11 and 12. Runs are single attempts, so the ranges show run-to-run spread, not a confidence interval.

<!-- robust:start -->

#### Base task on new data, ranges across seeds 11 and 12 (Sonnet 5.5)

| N | Arm | Runs answered | Cost $ | Peak context | Tokens read | Wall s | F1 |
|---|---|---|---|---|---|---|---|
| 40 | sql | 2 | 0.018 to 0.019 | 3,456 to 3,465 | 6,765 to 6,768 | 9.1 to 9.4 | 1.00 |
| 40 | tools-lean | 2 | 0.168 to 0.187 | 49,876 to 53,495 | 90,589 to 146,014 | 22.3 to 23.4 | 1.00 |
| 40 | tools | 2 | 0.233 to 0.280 | 73,189 to 86,937 | 190,868 to 216,992 | 21.3 to 23.3 | 1.00 |
| 120 | sql | 2 | 0.018 to 0.027 | 2,972 to 5,198 | 6,275 to 8,497 | 9.6 to 13.4 | 1.00 |
| 120 | tools-lean | 2 | 0.513 to 0.597 | 146,461 to 146,754 | 369,751 to 743,722 | 56.6 to 65.0 | 1.00 |
| 120 | tools | 1 | 0.630 | 204,495 | 435,243 | 44.4 | 1.00 |

#### Paired ratios per seed, min to max across seeds

| N | Pair (first / second) | Seeds | Tokens read ratio | Cost ratio | Wall time ratio |
|---|---|---|---|---|---|
| 40 | tools / sql | 2 | 28x to 32x | 12x to 15x | 2.3x to 2.6x |
| 40 | tools-lean / sql | 2 | 13x to 22x | 9.2x to 9.8x | 2.5x |
| 40 | tools / tools-lean | 2 | 1.3x to 2.4x | 1.2x to 1.7x | 0.91x to 1.0x |
| 120 | tools / sql | 1 | 51x | 24x | 3.3x |
| 120 | tools-lean / sql | 2 | 59x to 88x | 22x to 29x | 4.8x to 5.9x |
| 120 | tools / tools-lean | 1 | 0.59x | 1.1x | 0.68x |

#### Phase 1 pair for comparison (seed 7, no cache isolation)

| N | Pair (first / second) | Run pair | Tokens read ratio | Cost ratio | Wall time ratio |
|---|---|---|---|---|---|
| 40 | tools / sql | tools-n40-r1, sql-n40-r1 (seed 7) | 39x | 27x | 3.2x |
| 120 | tools / sql | tools-n120-r1, sql-n120-r1 (seed 7) | 110x | 54x | 5.2x |

#### Three arms, mean of the two seeds

| N | Arm | Runs answered | Cost $ | Peak context | Tokens read | Output tokens | Turns | Tool calls | API calls | Wall s | F1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 40 | sql | 2 | 0.019 | 3,460 | 6,766 | 936 | 3.0 | 3.0 | 49.0 | 9.2 | 1.00 |
| 40 | tools-lean | 2 | 0.178 | 51,686 | 118,302 | 3,508 | 4.5 | 37.5 | 36.5 | 22.8 | 1.00 |
| 40 | tools | 2 | 0.257 | 80,063 | 203,930 | 3,156 | 4.0 | 27.5 | 26.5 | 22.3 | 1.00 |
| 120 | sql | 2 | 0.022 | 4,085 | 7,386 | 1,124 | 3.0 | 3.0 | 143.5 | 11.5 | 1.00 |
| 120 | tools-lean | 2 | 0.555 | 146,608 | 556,736 | 10,664 | 8.5 | 103.0 | 102.0 | 60.8 | 1.00 |
| 120 | tools | 1 | 0.630 | 204,495 | 435,243 | 7,281 | 4.0 | 46.0 | 45.0 | 44.4 | 1.00 |

#### Harder variants (Sonnet 5.5)

| Variant | N | Seed | Arm | Outcome | F1 | Cost $ | Tokens read | Turns | Errors by trap |
|---|---|---|---|---|---|---|---|---|---|
| math | 40 | 11 | sql | answered | 1.00 | 0.022 | 7,029 | 3 | none |
| math | 40 | 11 | tools | answered | 1.00 | 0.606 | 529,124 | 8 | none |
| math | 120 | 11 | sql | answered | 1.00 | 0.019 | 6,500 | 3 | none |
| math | 120 | 11 | tools | max_tokens | n/a | 1.676 | 1,157,228 | 8 | n/a (no answer) |
| textdeadlines | 40 | 11 | sql | answered | 1.00 | 0.058 | 42,099 | 5 | none |
| textdeadlines | 40 | 11 | tools | answered | 1.00 | 0.234 | 212,699 | 5 | none |
| textdeadlines | 40 | 12 | sql | answered | 1.00 | 0.060 | 43,511 | 5 | none |
| textdeadlines | 40 | 12 | tools | answered | 1.00 | 0.202 | 138,231 | 4 | none |
| textdeadlines | 40 | 13 | sql | answered | 1.00 | 0.053 | 30,510 | 4 | none |
| textdeadlines | 40 | 13 | tools | answered | 1.00 | 0.242 | 196,276 | 4 | none |

- math-tools-n120-s11-sonnet ended with outcome max_tokens and no answer. Its last model call had a context of 524,307 tokens and wrote 16,000 output tokens (this harness's per-reply cap) and cost $1.00, out of $1.68 for the run. Its last reply used the harness's 16,000-token output cap with no visible text and no tool call, so the tokens likely went to internal reasoning (deduced).
- SQL agent, deadlines in free text, 40 matters: its own cost roughly triples when deadlines hide in free text (base task $0.018 to $0.019 per run, deadlines in text $0.053 to $0.060), though it stays about 3.4x to 4.6x cheaper than the tools agent (3 paired seeds).

#### Haiku 4.5, base task

| Run | Outcome | F1 | Cost $ | Peak context | Turns | Errors by trap |
|---|---|---|---|---|---|---|
| base-sql-n40-s11-haiku | answered | 1.00 | 0.037 | 8,522 | 9 | none |
| base-sql-n40-s12-haiku | answered | 1.00 | 0.038 | 7,385 | 10 | none |
| base-sql-n40-s13-haiku | answered | 1.00 | 0.018 | 3,386 | 4 | none |
| base-tools-n40-s11-haiku | answered | 0.50 | 0.163 | 75,279 | 8 | at_risk_plain: 1 false negatives; boundary_deadline_last_day: 1 false negatives; client_email_just_outside_window: 1 false negatives; non_billable_time_only: 1 false negatives; opposing_counsel_email_only: 2 false negatives |
| base-tools-n40-s12-haiku | answered | 1.00 | 0.172 | 63,615 | 11 | none |
| base-tools-n40-s13-haiku | answered | 0.94 | 0.166 | 75,012 | 7 | at_risk_plain: 1 false negatives |
| base-tools-n120-s11-haiku | answered | 0.00 | 0.376 | 161,889 | 18 | at_risk_plain: 12 false negatives; boundary_deadline_last_day: 1 false negatives; boundary_deadline_today: 1 false negatives; client_email_just_outside_window: 5 false negatives; non_billable_time_only: 5 false negatives; opposing_counsel_email_only: 5 false negatives |

- The largest peak context in any Haiku run was 161,889 tokens. No Haiku run reached its 200,000-token window, so there was no overflow to record.
- Haiku's SQL runs opened with a prompt of 1,252 to 1,255 tokens. Haiku 4.5 needs at least 4,096 tokens in a prompt before it will cache it (Anthropic's documented minimum), so the opening prompt could not be cached. Two of three Haiku SQL runs did cache later turns, once the conversation passed that length; only seed 13 never cached.
- base-tools-n120-s11-haiku submitted an empty list: 0 of 29 at-risk matters found, 0 false positives.

#### One-rule misreadings, F1 (+false positives / -false negatives), free from the oracle

| Misreading | base/v1 N=10 | base/v1 N=20 | base/v1 N=40 | base/v1 N=120 | base/v2 N=40 s11 | base/v2 N=120 s11 | base/v2 N=40 s12 | base/v2 N=120 s12 |
|---|---|---|---|---|---|---|---|---|
| Correct answers (matters) | 4 | 5 | 10 | 30 | 9 | 29 | 9 | 29 |
| Counts any email tagged with the matter, whoever is on it | 0.40 (+0/-3) | 0.75 (+0/-2) | 0.46 (+0/-7) | 0.57 (+0/-18) | 0.62 (+0/-5) | 0.65 (+0/-15) | 0.71 (+0/-4) | 0.59 (+0/-17) |
| Counts non-billable time | 0.86 (+0/-1) | 0.57 (+0/-3) | 0.75 (+0/-4) | 0.70 (+0/-14) | 0.71 (+0/-4) | 0.74 (+0/-12) | 0.71 (+0/-4) | 0.68 (+0/-14) |
| Starts the activity window a day early (2026-08-31) | 0.67 (+0/-2) | 0.75 (+0/-2) | 0.82 (+0/-3) | 0.87 (+0/-7) | 0.80 (+0/-3) | 0.82 (+0/-9) | 0.80 (+0/-3) | 0.88 (+0/-6) |
| Skips the status check | 0.89 (+1/-0) | 0.91 (+1/-0) | 0.95 (+1/-0) | 0.92 (+5/-0) | 0.95 (+1/-0) | 0.92 (+5/-0) | 0.95 (+1/-0) | 0.92 (+5/-0) |
| Skips the docket check | 0.89 (+1/-0) | 0.91 (+1/-0) | 0.91 (+2/-0) | 0.92 (+5/-0) | 0.86 (+3/-0) | 0.91 (+6/-0) | 0.86 (+3/-0) | 0.91 (+6/-0) |
| Ignores the 10-06 boundary (uses < instead of <=) | 1.00 (+0/-0) | 1.00 (+0/-0) | 1.00 (+0/-0) | 0.97 (+0/-2) | 0.94 (+0/-1) | 0.96 (+0/-2) | 0.88 (+0/-2) | 0.98 (+0/-1) |

#### Timings under a slower, limited upstream (500 ms per call, 10 at once)

| Run | N | Recorded wall s | Recorded tools s | Modeled tools s | Modeled wall s | Modeled wall s, SQL mail x10 |
|---|---|---|---|---|---|---|
| base-sql-n40-s11-sonnet | 40 | 9.4 | 0.8 | 4.1 | 12.0 | 30.0 |
| base-sql-n40-s12-sonnet | 40 | 9.1 | 0.8 | 4.1 | 11.8 | 29.8 |
| base-tools-lean-n40-s11-sonnet | 40 | 23.4 | 0.6 | 3.0 | 25.3 | n/a |
| base-tools-lean-n40-s12-sonnet | 40 | 22.3 | 0.5 | 2.5 | 23.8 | n/a |
| base-tools-n40-s11-sonnet | 40 | 21.3 | 0.5 | 2.0 | 22.4 | n/a |
| base-tools-n40-s12-sonnet | 40 | 23.3 | 0.5 | 2.5 | 24.9 | n/a |
| sql-n40-r1 | 40 | 8.4 | 0.8 | 4.1 | 11.0 | 29.0 |
| tools-n40-r1 | 40 | 26.7 | 0.5 | 2.5 | 27.9 | n/a |
| base-sql-n120-s11-sonnet | 120 | 13.4 | 2.0 | 11.6 | 22.5 | 72.0 |
| base-sql-n120-s12-sonnet | 120 | 9.6 | 2.0 | 11.6 | 18.6 | 68.1 |
| base-tools-lean-n120-s11-sonnet | 120 | 65.0 | 1.4 | 8.1 | 71.0 | n/a |
| base-tools-lean-n120-s12-sonnet | 120 | 56.6 | 1.0 | 7.1 | 62.2 | n/a |
| base-tools-n120-s11-sonnet | 120 | 44.4 | 0.5 | 3.0 | 46.4 | n/a |
| sql-n120-r1 | 120 | 9.9 | 2.1 | 12.1 | 19.3 | 73.3 |
| tools-n120-r1 | 120 | 51.5 | 0.6 | 3.5 | 53.9 | n/a |

#### Bytes, phase 1 data (seed 7): a full pull of all four systems, raw vs trimmed, vs SQL rows shown to the model

| N | What | Bytes | Est. tokens | Share of raw |
|---|---|---|---|---|
| 40 | Raw, all four systems (matters) | 52,117 | 14,891 | 12.0% |
| 40 | Raw, all four systems (docket) | 77,234 | 22,067 | 17.7% |
| 40 | Raw, all four systems (mail) | 216,503 | 61,858 | 49.8% |
| 40 | Raw, all four systems (billing) | 89,277 | 25,508 | 20.5% |
| 40 | Raw, all four systems (total) | 435,131 | 124,323 | 100.0% |
| 40 | Trimmed, all four systems (matters) | 23,325 | 6,664 | 5.4% |
| 40 | Trimmed, all four systems (docket) | 52,553 | 15,015 | 12.1% |
| 40 | Trimmed, all four systems (mail) | 111,165 | 31,761 | 25.5% |
| 40 | Trimmed, all four systems (billing) | 43,025 | 12,293 | 9.9% |
| 40 | Trimmed, all four systems (total) | 230,068 | 65,734 | 52.9% |
| 40 | SQL arm, rows returned to the model | 351 | 100 | 0.1% |
| 120 | Raw, all four systems (matters) | 156,713 | 44,775 | 11.8% |
| 120 | Raw, all four systems (docket) | 232,778 | 66,508 | 17.5% |
| 120 | Raw, all four systems (mail) | 652,953 | 186,558 | 49.1% |
| 120 | Raw, all four systems (billing) | 286,405 | 81,830 | 21.6% |
| 120 | Raw, all four systems (total) | 1,328,849 | 379,671 | 100.0% |
| 120 | Trimmed, all four systems (matters) | 70,147 | 20,042 | 5.3% |
| 120 | Trimmed, all four systems (docket) | 159,158 | 45,474 | 12.0% |
| 120 | Trimmed, all four systems (mail) | 336,232 | 96,066 | 25.3% |
| 120 | Trimmed, all four systems (billing) | 138,006 | 39,430 | 10.4% |
| 120 | Trimmed, all four systems (total) | 703,543 | 201,012 | 52.9% |
| 120 | SQL arm, rows returned to the model | 951 | 272 | 0.1% |

- Reading: even trimmed, a full pull is 52.9% of raw, while the SQL agent saw under 1 KB of rows. The SQL server still pulled the full raw data upstream.

#### Cut and skipped runs

| Run | State | Why | Spend on the cut attempt |
|---|---|---|---|
| base-tools-n120-s11-sonnet | cut (first attempt) | budget_stop: pot p2-base spent $2.4100 + estimate $0.6057 exceeds cap $3.00 | $0.350 |
| base-tools-n120-s12-sonnet | cut (first attempt) | budget_stop: pot p2-base spent $2.5827 + estimate $0.4820 exceeds cap $3.00 | $0.173 |
| base-tools-n120-s12-sonnet | cut | budget_stop: pot p2-base spent $3.6878 + estimate $0.5909 exceeds cap $4.20 | $0.475 |
| math-sql-n120-s12-sonnet | skipped | skipped: budget (one seed at N = 120) | $0.000 |
| math-tools-n120-s12-sonnet | skipped | skipped: budget (one seed at N = 120) | $0.000 |

- Spend on attempts that were cut by a pot cap before answering: $1.00.
- The pots started at $3.00 (p2-base) and $3.50 (p2-variants). They were raised to $4.20 and $4.40 after the first attempts were cut. No pot went over its cap. Together the pots spent $7.83, above the $6.50 first planned for phase 2, because of the top-up.

#### Spend

| Pot | Spent | Cap |
|---|---|---|
| p2-base | $3.69 | $4.20 |
| p2-variants | $4.14 | $4.40 |
| Phase 2 total | $7.83 | $8.60 |

<!-- robust:end -->

Plain reading of phase 2:

- The gap between the SQL agent and the per-system agents is not an artifact of cache reuse or of seed 7. It shows up on new data and with cache isolation, in every paired ratio above.
- Trimming records shrank the bytes the tools agent had to move, and it lowered peak context and cost. The saving was larger at 40 matters than at 120. At 120 matters the trimmed agent took more turns than the tools agent and read more tokens in total, though each prompt was smaller (this rests on the one seed where both arms answered). The bytes table shows why trimming cannot close the gap: the SQL agent saw under 1 KB of rows, because the joining happens in the database instead of in the model. Trimming only shrinks what the tools agent has to pull through the model, and even trimmed, a full pull is a large share of raw (see the reading under the table).
- On Sonnet 5.5, accuracy did not separate the arms. The misreading table shows the traps are not toothless: a single misread rule drops F1 visibly. The model simply did not misread. So a perfect F1 here says the model is careful at these sizes, not that the task is easy.
- The arithmetic variant did not trip the tools agent at 40 matters. At 120 matters the tools agent never finished: it ran out of output space on its last call. Whether it was working the sums out in text is deduced, not observed.
- The deadlines-in-text variant did not trip either agent. It did make the SQL agent's cost rise, because it now reads free-text descriptions. The numbers are in the note under the variants table.
- Haiku's tools agent was the only agent that lost accuracy. Every mistake was a false negative, an at-risk matter it missed, on both the planted traps and the plain cases. At 120 matters it submitted an empty list, without hitting its context window.
- Under the slower, limited upstream model the SQL agent's advantage in wall time shrinks. With ten times the mail history it reverses at 120 matters (see the timings table). Only the SQL server's load grows in that scenario, because it pulls all mail while the tools agents filtered mail by date. This is the missing predicate pushdown caveat, priced. This is a recalculation of a slower upstream, not a measurement.
- Runs were cut by pot caps. Cost to the experiment is in the cut table. Skipped seeds at 120 matters were a budget decision, so those cells have one seed.

## Accuracy

Every answered Sonnet 5.5 run in this experiment scored a perfect F1 with exact grouping, in phase 1 and phase 2, for every arm and both harder variants. There were no false positives and no false negatives, so the planted traps did not cause any mistakes on that model. The tools agent did the joins by hand and still got them right. Haiku 4.5 did not: see the Haiku table, where its tools agent missed matters and its SQL agent did not. This experiment cannot say what happens at larger sizes, with other question types, or with other models.

## Caveats

- Caching makes re-reading cheap in dollars. Tokens read overstates the gap in cost, which is why cost and peak context lead.
- The SQL server loads whole tables and filters locally. Real products need predicate pushdown, so filters run inside the source APIs. Without it, a real SQL layer over live APIs would pay the API cost the tools agent avoids by filtering.
- The schema the SQL agent must read grows with the number of connectors. Here there are four. Many connectors would make `describe_schema` larger.
- Reads only. Neither agent can change anything.
- Each agent makes one plan up front. No replanning was tested.
- The data is synthetic, and the schema is hand-written.
- Sample sizes are small: see the run counts in the tables. Several cells have a single run.
- Some runs were cut by the budget caps, and some seeds at 120 matters were skipped by decision. See the cut and skipped table.
- The SQL server fetches everything on its first query and answers later queries from memory. Only that first query pays for the upstream API calls.
- The tools agent was free to call bulk endpoints (list all mail, all time entries). Its cost came from the size of the results, not from many turns.
- Wall time includes some server start-up in every arm.
- The SQL arm's first query includes loading the data into DuckDB. `load_ms` in each SQL trace records that, not counting the waits on the fake APIs.
- The smallest size contains only one planted trap type, so accuracy there is on an easier mix.
- The phase 1 SQL runs were rerun after a loader fix found in review. The old runs are in git history.
- The timing model in phase 2 is a recalculation from recorded call structure, not a new measurement.

## How to reproduce

```
cd lab/sql-singleton-tool
uv sync --locked
uv run pytest
uv run python -m experiment.sweep run --env-file path/to/anthropic.env    # phase 1, paid, capped by results/ledger.json
uv run python -m experiment.sweep2 run --env-file path/to/anthropic.env   # phase 2, paid, capped
uv run python -m experiment.sweep2 report
uv run python -m experiment.writeup_tables
```

Both sweeps skip runs that already have a trace, so they can be resumed.

## What's next

- A messy-email and time-zone variant, clients with several matters, and a question in natural wording.
- A code-execution arm, where the agent writes code that calls the tools.
- A government public-records version of the same test.
- A conflict-check question, which needs more joins.
- Many connectors, to measure how schema cost grows.
