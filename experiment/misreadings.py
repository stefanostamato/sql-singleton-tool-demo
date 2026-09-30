"""How wrong is an agent that misreads exactly one rule? Free, no API: computed from the oracle.

    python -m experiment.misreadings

For each dataset, apply the stated rule with one mistake and score the result against the correct
answer. The cells show F1 and the count of false positives and false negatives.
"""

from __future__ import annotations

from datetime import date

from experiment.generate import generate
from experiment.truth import Rules, at_risk_matters

MISREADINGS: list[tuple[str, Rules]] = [
    ("Counts any email tagged with the matter, whoever is on it", Rules(any_tagged_email=True)),
    ("Counts non-billable time", Rules(count_non_billable=True)),
    ("Starts the activity window a day early (2026-08-31)", Rules(activity_start=date(2026, 8, 31))),
    ("Skips the status check", Rules(check_status=False)),
    ("Skips the docket check", Rules(check_docket=False)),
    ("Ignores the 10-06 boundary (uses < instead of <=)", Rules(deadline_end_inclusive=False)),
]
# (profile, seed, N): base/v1 is the phase 1 data; base/v2 uses the phase 2 seeds.
DATASETS = [("v1", 7, 10), ("v1", 7, 20), ("v1", 7, 40), ("v1", 7, 120), ("v2", 11, 40), ("v2", 11, 120), ("v2", 12, 40), ("v2", 12, 120)]


def f1_counts(got: set[str], want: set[str]) -> tuple[float, int, int]:
    tp = len(got & want)
    precision = tp / len(got) if got else 0.0
    recall = tp / len(want) if want else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return f1, len(got - want), len(want - got)


def rows(datasets=DATASETS) -> list[dict]:
    out = []
    for profile, seed, n in datasets:
        ds = generate(n, seed, profile, "base")
        want = {m["display_number"] for m in at_risk_matters(ds)}
        cells = []
        for label, rules in MISREADINGS:
            got = {m["display_number"] for m in at_risk_matters(ds, rules)}
            cells.append((label, *f1_counts(got, want)))
        out.append({"profile": profile, "seed": seed, "n": n, "correct_count": len(want), "cells": cells})
    return out


def markdown(data: list[dict] | None = None) -> str:
    data = data or rows()
    head = ["Misreading"] + [f"base/{d['profile']} N={d['n']}" + (f" s{d['seed']}" if d["profile"] == "v2" else "") for d in data]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines.append("| Correct answers (matters) | " + " | ".join(str(d["correct_count"]) for d in data) + " |")
    for i, (label, _) in enumerate(MISREADINGS):
        cells = []
        for d in data:
            _, f1, fp, fn = d["cells"][i]
            cells.append(f"{f1:.2f} (+{fp}/-{fn})")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    print(markdown())


if __name__ == "__main__":
    main()
