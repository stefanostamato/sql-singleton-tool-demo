"""Ground truth for the at-risk question, computed in plain Python from the generated objects.

`at_risk_matters(ds, rules)` applies the stated rule (the default `Rules`). Passing a `Rules` with one
field changed gives the answer of a reader who misreads that one rule (see misreadings.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from experiment.generate import DEADLINE_END, TODAY, TRAP_TYPES, WINDOW_START, Dataset, generate
from experiment.variants import BOUNDARY_TRAPS, VARIANT_TRAPS

ACTIVITY_LO, ACTIVITY_HI = WINDOW_START, TODAY
DEADLINE_LO, DEADLINE_HI = TODAY, DEADLINE_END
HOURS_LIMIT_TENTHS = 15  # math variant: window hours must total less than 1.5 ...
UNBILLED_LIMIT = Decimal(4000)  # ... or unbilled time before the window must total more than $4,000


@dataclass(frozen=True)
class Rules:
    """The stated rule, with switches for the one-mistake readings."""

    any_tagged_email: bool = False  # count any email tagged with the matter, whoever is on it
    count_non_billable: bool = False  # non-billable time counts as activity
    activity_start: date = ACTIVITY_LO  # start of the activity window
    check_status: bool = True
    check_docket: bool = True
    deadline_end_inclusive: bool = True


def _d(text: str) -> date:
    return date.fromisoformat(text[:10])


def _deadlines(ds: Dataset, matter_id: int) -> list[date]:
    """Deadlines in effect on a matter. In `textdeadlines` they come from generator metadata that no API
    exposes (the resolved result of continuing and vacating orders); otherwise from the docket fields."""
    if ds.variant == "textdeadlines":
        return ds.effective_deadlines.get(matter_id, [])
    return [_d(en["deadline_date"]) for en in ds.dockets.get(matter_id, []) if "deadline_date" in en]


def _math_rule4(ds: Dataset, matter_id: int) -> bool:
    """True when the math variant's rule 4 holds: few billable hours in the window, or a lot of unbilled
    time before it. Sums use exact tenths of an hour and Decimal dollars."""
    tenths, unbilled = 0, Decimal(0)
    for t in ds.time_entries:
        if t["matter"]["id"] != matter_id or t["non_billable"]:
            continue
        day = _d(t["date"])
        if ACTIVITY_LO <= day <= ACTIVITY_HI:
            tenths += round(t["quantity_in_hours"] * 10)
        elif day < ACTIVITY_LO and not t["billed"]:
            unbilled += Decimal(str(t["total"]))
    return tenths < HOURS_LIMIT_TENTHS or unbilled > UNBILLED_LIMIT


def at_risk_matters(ds: Dataset, rules: Rules = Rules()) -> list[dict]:
    """Matters that satisfy the at-risk rule, as matter records."""
    contact_emails: dict[int, set[str]] = {
        m["id"]: {c["email"].lower() for c in m["client"]["contacts"]} for m in ds.matters
    }
    window_emails = []
    for e in ds.emails:
        if rules.activity_start <= _d(e["receivedDateTime"]) <= ACTIVITY_HI:
            addrs = {e["from"]["emailAddress"]["address"].lower()}
            for field in ("toRecipients", "ccRecipients"):
                addrs |= {r["emailAddress"]["address"].lower() for r in e[field]}
            window_emails.append((e["id"], addrs))
    tagged = {mid for eid, _ in window_emails if (mid := ds.email_owner[eid]) is not None}
    active = {
        t["matter"]["id"]
        for t in ds.time_entries
        if rules.activity_start <= _d(t["date"]) <= ACTIVITY_HI and (rules.count_non_billable or not t["non_billable"])
    }
    hi = DEADLINE_HI if rules.deadline_end_inclusive else DEADLINE_HI - timedelta(days=1)
    out = []
    for m in ds.matters:
        if rules.check_status and m["status"] != "Open":
            continue
        if m["practice_area"]["name"] != "Litigation":
            continue
        if rules.check_docket and not any(DEADLINE_LO <= d <= hi for d in _deadlines(ds, m["id"])):
            continue
        if rules.any_tagged_email:
            if m["id"] in tagged:
                continue
        elif any(contact_emails[m["id"]] & addrs for _, addrs in window_emails):
            continue
        if ds.variant == "math":
            if not _math_rule4(ds, m["id"]):
                continue
        elif m["id"] in active:
            continue
        out.append(m)
    return out


def trap_types(ds: Dataset) -> list[str]:
    """Every trap type this dataset can hold, in a stable order."""
    out = list(TRAP_TYPES)
    if ds.profile == "v2":
        out += BOUNDARY_TRAPS
    return out + VARIANT_TRAPS[ds.variant]


def matter_kinds(ds: Dataset) -> dict[str, str]:
    """display number -> what the matter is: a planted trap type (boundary and variant tags win over the
    phase 1 scenario), 'healthy', or 'at_risk_plain' (an at-risk matter with no trap)."""
    out = {}
    for m in ds.matters:
        mid = m["id"]
        scen = ds.scenarios[mid]
        tags = ds.tags.get(mid, [])
        if tags:
            out[m["display_number"]] = tags[0]
        elif scen in TRAP_TYPES:
            out[m["display_number"]] = scen
        elif scen.startswith("healthy"):
            out[m["display_number"]] = "healthy"
        else:
            out[m["display_number"]] = "at_risk_plain"
    return out


def truth(ds: Dataset) -> dict:
    by_attorney: dict[str, list[str]] = {}
    for m in at_risk_matters(ds):
        by_attorney.setdefault(m["responsible_attorney"]["name"], []).append(m["display_number"])
    traps = {t: 0 for t in trap_types(ds)}
    for mid, scen in ds.scenarios.items():
        for kind in {scen, *ds.tags.get(mid, [])}:
            if kind in traps:
                traps[kind] += 1
    out = {"n_matters": ds.n_matters, "seed": ds.seed, "today": ds.today.isoformat()}
    if (ds.profile, ds.variant) != ("v1", "base"):
        out |= {"variant": ds.variant, "profile": ds.profile}
    out["at_risk"] = [{"attorney": a, "matters": sorted(ms)} for a, ms in sorted(by_attorney.items())]
    out["traps"] = traps
    return out


def truth_path(directory: str | Path, n: int, seed: int, profile: str = "v1", variant: str = "base") -> Path:
    """Phase 1 keeps `n<N>.json`; phase 2 runs use `<variant>-<profile>-s<seed>-n<N>.json`."""
    name = f"n{n}.json" if (profile, variant) == ("v1", "base") else f"{variant}-{profile}-s{seed}-n{n}.json"
    return Path(directory) / name


def write_truth(n: int, seed: int, directory: str | Path, profile: str = "v1", variant: str = "base") -> Path:
    path = truth_path(directory, n, seed, profile, variant)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(truth(generate(n, seed, profile, variant)), indent=2, ensure_ascii=False) + "\n")
    return path
