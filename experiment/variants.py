"""Generator profiles and task variants, applied on top of the phase 1 data.

`apply(ds, profile, variant)` edits a freshly generated v1 dataset in place. It never touches the v1
random stream: every choice here comes from its own seeded generators, so the phase 1 data stays
byte-identical and `base`/`v2` and `math`/`v2` share the same boundary cases for a given (N, seed).

- profile v2: boundary cases at every N >= 10 (dates exactly on the edge of a rule window).
- variant math: rule 4 becomes an arithmetic rule; totals are planted just under, at and just over
  each threshold, from many small decimal entries.
- variant textdeadlines: docket entries lose their deadline fields; deadlines live only in the entry
  text, and later entries continue or vacate an earlier deadline (the latest order wins).

Structured metadata that is not exposed through any API lives on the dataset: `tags` (matter id ->
planted trap types) and `effective_deadlines` (textdeadlines: resolved deadline dates per matter).
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from experiment.generate import DEADLINE_END, TODAY, WINDOW_START, Dataset, _rand_date

BOUNDARY_TRAPS = [
    "boundary_deadline_today",
    "boundary_deadline_last_day",
    "boundary_email_last_day",
    "boundary_billable_first_day",
]
MATH_TRAPS = [
    "hours_just_under", "hours_at_threshold", "hours_just_over",
    "unbilled_just_under", "unbilled_at_threshold", "unbilled_just_over",
]
TEXT_TRAPS = ["deadline_continued_out", "deadline_continued_in", "deadline_vacated"]
VARIANT_TRAPS = {"base": [], "math": MATH_TRAPS, "textdeadlines": TEXT_TRAPS}

# Scenarios that pass rules 1 to 3 of the question (open litigation, in-window deadline, no client email in
# the window). Boundary and variant traps are planted on them, in this order of preference.
AT_RISK_CLASS = [
    "at_risk", "opposing_counsel_email_only", "non_billable_time_only", "client_email_just_outside_window",
]
RATES = [395.0, 425.0, 495.0, 550.0, 575.0, 610.0]
HOURS_TARGET_TENTHS = {"hours_just_under": 14, "hours_at_threshold": 15, "hours_just_over": 16}
UNBILLED_TARGET = {"unbilled_just_under": 3950, "unbilled_at_threshold": 4000, "unbilled_just_over": 4050}
LATE_DECOY = date(2026, 10, 7)


def long_date(d: date) -> str:
    """'October 2, 2026' (no zero padding)."""
    return f"{d:%B} {d.day}, {d.year}"


def _d(text: str) -> date:
    return date.fromisoformat(text[:10])


def _past(rng) -> date:
    return _rand_date(rng, TODAY - timedelta(days=30), TODAY - timedelta(days=1))


def _after(rng) -> date:
    return _rand_date(rng, DEADLINE_END + timedelta(days=2), TODAY + timedelta(days=60))


def _in_window(day: date) -> bool:
    return TODAY <= day <= DEADLINE_END


def apply(ds: Dataset, profile: str, variant: str) -> None:
    ds.profile, ds.variant = profile, variant
    if profile == "v2":
        _boundaries(ds, random.Random(f"{ds.seed}-{ds.n_matters}-boundaries"))
    if variant == "math":
        _math(ds, random.Random(f"{ds.seed}-{ds.n_matters}-math"))
    elif variant == "textdeadlines":
        _textdeadlines(ds, random.Random(f"{ds.seed}-{ds.n_matters}-textdeadlines"))
    ds.emails.sort(key=lambda e: (e["receivedDateTime"], e["id"]))


# ---------- shared helpers ----------

def _tag(ds: Dataset, mid: int, name: str) -> None:
    ds.tags.setdefault(mid, []).append(name)


def _matter(ds: Dataset, mid: int) -> dict:
    return next(m for m in ds.matters if m["id"] == mid)


def _pool(ds: Dataset, rng: random.Random) -> list[int]:
    """Matters that pass rules 1 to 3 and carry no tag yet, best candidates first."""
    out: list[int] = []
    for scen in AT_RISK_CLASS:
        ids = sorted(m for m, s in ds.scenarios.items() if s == scen and m not in ds.tags)
        rng.shuffle(ids)
        out += ids
    return out


def _reindex(entries: list[dict]) -> None:
    """Sort a matter's docket by filing date and renumber, keeping ids."""
    entries.sort(key=lambda e: (e["date_filed"], e["entry_number"]))
    for i, e in enumerate(entries, start=1):
        e["entry_number"] = i
        e["document_number"] = str(i)
        e["absolute_url"] = f"/docket/{e['docket_id']}/{i}/"


def _set_deadline(rng, entry: dict, new: date) -> None:
    old = _d(entry["deadline_date"])
    entry["description"] = entry["description"].replace(old.strftime("%B %d, %Y"), new.strftime("%B %d, %Y"))
    entry["deadline_date"] = new.isoformat()
    if _d(entry["date_filed"]) >= new:
        entry["date_filed"] = (new - timedelta(days=rng.randint(1, 20))).isoformat()


def _window_deadlines(ds: Dataset, mid: int) -> list[dict]:
    return [e for e in ds.dockets.get(mid, []) if "deadline_date" in e and _in_window(_d(e["deadline_date"]))]


def _addresses(email: dict) -> set[str]:
    out = {email["from"]["emailAddress"]["address"].lower()}
    for key in ("toRecipients", "ccRecipients"):
        out |= {r["emailAddress"]["address"].lower() for r in email[key]}
    return out


def _move_email(email: dict, day: date) -> None:
    for key in ("receivedDateTime", "sentDateTime"):
        email[key] = day.isoformat() + email[key][10:]


def _move_time(entry: dict, day: date) -> None:
    entry["date"] = day.isoformat()
    entry["updated_at"] = day.isoformat() + entry["updated_at"][10:]


# ---------- profile v2: boundary cases ----------

def _boundaries(ds: Dataset, rng: random.Random) -> None:
    if ds.n_matters < 10:
        return
    pool = _pool(ds, rng)
    if len(pool) >= 1:
        _only_window_deadline(ds, rng, pool[0], TODAY)
        _tag(ds, pool[0], "boundary_deadline_today")
    if len(pool) >= 2:
        _only_window_deadline(ds, rng, pool[1], DEADLINE_END)
        _tag(ds, pool[1], "boundary_deadline_last_day")
    if len(pool) >= 3:  # second late-deadline decoy: only deadline is the day after the window
        entries = _window_deadlines(ds, pool[2])
        _set_deadline(rng, entries[0], LATE_DECOY)
        for e in entries[1:]:
            _set_deadline(rng, e, _past(rng))
        _reindex(ds.dockets[pool[2]])
        _tag(ds, pool[2], "deadline_just_outside_window")
    healthy_email = sorted(m for m, s in ds.scenarios.items() if s == "healthy_lit_email")
    if healthy_email:
        mid = rng.choice(healthy_email)
        contacts = {c["email"].lower() for c in _matter(ds, mid)["client"]["contacts"]}
        inwin = [
            e for e in ds.emails
            if ds.email_owner[e["id"]] == mid and contacts & _addresses(e) and WINDOW_START <= _d(e["receivedDateTime"]) <= TODAY
        ]
        _move_email(inwin[0], TODAY)
        for e in inwin[1:]:
            _move_email(e, _rand_date(rng, TODAY - timedelta(days=60), WINDOW_START - timedelta(days=2)))
        _tag(ds, mid, "boundary_email_last_day")
    healthy_time = sorted(m for m, s in ds.scenarios.items() if s == "healthy_lit_time")
    if healthy_time:
        mid = rng.choice(healthy_time)
        inwin = [
            t for t in ds.time_entries
            if t["matter"]["id"] == mid and not t["non_billable"] and WINDOW_START <= _d(t["date"]) <= TODAY
        ]
        _move_time(inwin[0], WINDOW_START)
        for t in inwin[1:]:
            _move_time(t, _rand_date(rng, TODAY - timedelta(days=60), WINDOW_START - timedelta(days=2)))
        _tag(ds, mid, "boundary_billable_first_day")


def _only_window_deadline(ds: Dataset, rng: random.Random, mid: int, day: date) -> None:
    entries = _window_deadlines(ds, mid)
    _set_deadline(rng, entries[0], day)
    for e in entries[1:]:
        _set_deadline(rng, e, _after(rng))
    _reindex(ds.dockets[mid])


# ---------- variant math ----------

FIRST_UNBILLED = TODAY - timedelta(days=60)


class _Ids:
    def __init__(self, ds: Dataset, rng: random.Random) -> None:
        self.rng = rng
        self.next = max(t["id"] for t in ds.time_entries) + 1

    def take(self) -> int:
        self.next += 1
        return self.next - 1

    def hexid(self, n: int) -> str:
        return "".join(self.rng.choice("0123456789abcdef") for _ in range(n))


def _split_tenths(rng: random.Random, total: int) -> list[int]:
    parts, left = [], total
    while left > 0:
        p = min(left, rng.choice([1, 2, 2, 3, 3, 4, 5, 7]))
        parts.append(p)
        left -= p
    return parts


_COMBOS = [(r, h) for r in RATES for h in range(1, 8)]


def _half_dollars(rate: float, tenths: int) -> int:
    return int(rate) * tenths // 5  # rate * tenths / 10 dollars, in units of $0.50


def _fit_dollars(rng: random.Random, target: int) -> list[tuple[float, int]]:
    """(rate, tenths) pairs of 0.1 to 0.7 hours whose totals sum to exactly `target` dollars."""
    goal = target * 2
    for _ in range(2000):
        left, picked = goal, []
        while left > rng.randint(300, 900):
            r, h = rng.choice(_COMBOS)
            v = _half_dollars(r, h)
            if v <= left:
                picked.append((r, h))
                left -= v
        tail = _solve_shuffled(rng, left)
        if tail is not None:
            rng.shuffle(picked)
            return picked + tail
    raise RuntimeError(f"cannot fit {target}")


def _solve_shuffled(rng: random.Random, remaining: int) -> list[tuple[float, int]] | None:
    order = _COMBOS[:]
    rng.shuffle(order)

    def go(left: int, depth: int):
        if left == 0:
            return []
        if depth == 0:
            return None
        for r, h in order:
            v = _half_dollars(r, h)
            if v <= left:
                rest = go(left - v, depth - 1)
                if rest is not None:
                    return [(r, h)] + rest
        return None

    return go(remaining, 3)


def _fill_dollars(rng: random.Random, low: int, high: int) -> list[tuple[float, int]]:
    """Random small entries totalling somewhere between `low` and `high` dollars."""
    goal, picked, total = rng.randint(low, high), [], 0.0
    while total < goal:
        r, h = rng.choice(_COMBOS)
        picked.append((r, h))
        total += r * h / 10
    return picked


def _entry(ds: Dataset, ids: _Ids, matter: dict, rate: float, tenths: int, day: date, billed: bool) -> dict:
    from experiment.generate import ACTIVITIES, TIME_NOTES

    rng = ids.rng
    user = next(a for a in ds.attorneys if a["rate"] == rate)
    hours = tenths / 10
    act = rng.choice(ACTIVITIES)
    return {
        "id": ids.take(),
        "etag": f'"{ids.hexid(8)}"',
        "type": "TimeEntry",
        "date": day.isoformat(),
        "quantity_in_hours": hours,
        "rounded_quantity_in_hours": hours,
        "price": rate,
        "total": round(rate * hours, 2),
        "note": rng.choice(TIME_NOTES),
        "non_billable": False,
        "billed": billed,
        "matter": {"id": matter["id"], "display_number": matter["display_number"]},
        "user": {"id": user["id"], "name": user["name"]},
        "activity_description": {"name": act[1]},
        "updated_at": f"{day.isoformat()}T{rng.randint(15, 23)}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z",
    }


def _plan_time(ds, ids, matter, window_tenths: int, unbilled: list[tuple[float, int]], billed_noise: bool) -> list[dict]:
    rng = ids.rng
    out = []
    for h in _split_tenths(rng, window_tenths):
        out.append(_entry(ds, ids, matter, rng.choice(RATES), h, _rand_date(rng, WINDOW_START, TODAY), False))
    for r, h in unbilled:
        out.append(_entry(ds, ids, matter, r, h, _rand_date(rng, FIRST_UNBILLED, WINDOW_START - timedelta(days=1)), False))
    if billed_noise:
        for r, h in _fill_dollars(rng, 1200, 2200):
            out.append(_entry(ds, ids, matter, r, h, _rand_date(rng, FIRST_UNBILLED, WINDOW_START - timedelta(days=1)), True))
    return out


def _math(ds: Dataset, rng: random.Random) -> None:
    ids = _Ids(ds, rng)
    pool = _pool(ds, rng)
    n_traps = min(len(pool), 6 * max(1, ds.n_matters // 40)) if ds.n_matters >= 10 else 0
    traps = {mid: MATH_TRAPS[i % 6] for i, mid in enumerate(pool[:n_traps])}
    plain = pool[n_traps:]
    healthy_time = sorted(m for m, s in ds.scenarios.items() if s == "healthy_lit_time" and m not in ds.tags)
    targets = list(traps) + plain + healthy_time
    by_matter = {m["id"]: m for m in ds.matters}
    drop = set(targets)
    ds.time_entries[:] = [t for t in ds.time_entries if not (t["matter"]["id"] in drop and not t["non_billable"])]
    new: list[dict] = []
    for mid in targets:
        matter = by_matter[mid]
        trap = traps.get(mid)
        if trap in HOURS_TARGET_TENTHS:
            entries = _plan_time(ds, ids, matter, HOURS_TARGET_TENTHS[trap], _fill_dollars(rng, 800, 2800), False)
        elif trap in UNBILLED_TARGET:
            entries = _plan_time(ds, ids, matter, rng.randint(18, 32), _fit_dollars(rng, UNBILLED_TARGET[trap]), True)
        elif mid in healthy_time:
            entries = _plan_time(ds, ids, matter, rng.randint(18, 40), _fill_dollars(rng, 500, 3000), False)
        else:  # plain at-risk: little or no billable time in the window, unbilled well under the threshold
            window = 0 if rng.random() < 0.5 else rng.randint(3, 12)
            entries = _plan_time(ds, ids, matter, window, _fill_dollars(rng, 500, 3000), False)
        new += entries
        if trap:
            _tag(ds, mid, trap)
    ds.time_entries.extend(new)


# ---------- variant textdeadlines ----------

DEADLINE_SENTENCES = {
    "Response to motion to compel due": "Response to the motion to compel is due by {d}.",
    "Opposition to motion for summary judgment due": "Opposition to the motion for summary judgment is due by {d}.",
    "Expert disclosure deadline": "Expert disclosures must be served by {d}.",
    "Joint pretrial statement due": "The joint pretrial statement is due by {d}.",
    "Answer to amended complaint due": "The answer to the amended complaint is due by {d}.",
    "Motion in limine deadline": "Motions in limine must be filed by {d}.",
    "Mediation statement due": "Mediation statements are due by {d}.",
    "Reply brief due": "The reply brief is due by {d}.",
    "Deposition of corporate representative": "The deposition of the corporate representative must be completed by {d}.",
    "Close of fact discovery": "Fact discovery closes on {d}.",
}
ORDER_HEADS = ["SCHEDULING ORDER.", "MINUTE ORDER.", "ORDER on stipulation."]
CONTINUE_TEXT = [
    "ORDER granting the parties' joint request. The deadline set in entry {k} is continued to {d}.",
    "MINUTE ORDER. On the court's own motion, the deadline set in entry {k} is continued to {d}. All other dates remain in effect.",
]
VACATE_TEXT = [
    "ORDER on motion. The deadline set in entry {k} is vacated.",
    "MINUTE ORDER. The deadline set in entry {k} is vacated; the court will reset it if needed.",
]


def _textdeadlines(ds: Dataset, rng: random.Random) -> None:
    pool = _pool(ds, rng)
    n_traps = min(len(pool), 6 * max(1, ds.n_matters // 40)) if ds.n_matters >= 10 else 0
    traps = {mid: TEXT_TRAPS[i % 3] for i, mid in enumerate(pool[:n_traps])}
    next_id = max(e["id"] for es in ds.dockets.values() for e in es) + 1
    events: dict[int, list[tuple[int, str, date | None]]] = {}  # matter -> (entry index, kind, new date)

    for mid, trap in traps.items():
        entries = _window_deadlines(ds, mid)
        if trap == "deadline_continued_out":
            for e in entries:
                if rng.random() < 0.5:  # continued once inside the window, then out of it
                    events.setdefault(mid, []).append((id(e), "continue", _rand_date(rng, TODAY, DEADLINE_END)))
                events.setdefault(mid, []).append((id(e), "continue", _after(rng)))
        elif trap == "deadline_vacated":
            for e in entries:
                if rng.random() < 0.4:
                    events.setdefault(mid, []).append((id(e), "continue", _rand_date(rng, TODAY, DEADLINE_END)))
                events.setdefault(mid, []).append((id(e), "vacate", None))
        else:  # continued_in: originally outside the window, continued into it
            for i, e in enumerate(entries):
                _set_deadline(rng, e, _after(rng) if rng.random() < 0.6 else _past(rng))
                if i == 0:
                    events.setdefault(mid, []).append((id(e), "continue", _rand_date(rng, TODAY, DEADLINE_END)))
        _tag(ds, mid, trap)

    # noise on other matters: continuations that keep a deadline on the same side of the window
    for mid in sorted(ds.dockets):
        if mid in traps or mid in ds.tags or rng.random() > 0.3:
            continue
        with_dl = [e for e in ds.dockets[mid] if "deadline_date" in e]
        if not with_dl:
            continue
        e = rng.choice(with_dl)
        day = _d(e["deadline_date"])
        if _in_window(day):
            events.setdefault(mid, []).append((id(e), "continue", _rand_date(rng, TODAY, DEADLINE_END)))
        elif day > DEADLINE_END:
            events.setdefault(mid, []).append((id(e), "continue", _rand_date(rng, day, TODAY + timedelta(days=75))))
        else:
            events.setdefault(mid, []).append((id(e), "vacate", None))

    for mid, entries in ds.dockets.items():
        by_obj = {id(e): e for e in entries}
        _reindex(entries)  # numbers are final from here on
        current: dict[int, date | None] = {}
        for e in entries:
            if "deadline_date" in e:
                day = _d(e.pop("deadline_date"))
                dtype = e.pop("deadline_type")
                e["description"] = f"{rng.choice(ORDER_HEADS)} " + DEADLINE_SENTENCES[dtype].format(d=long_date(day))
                current[e["entry_number"]] = day
        last = max(_d(e["date_filed"]) for e in entries)
        template = entries[-1]
        for obj, kind, day in events.get(mid, []):
            ref = by_obj[obj]["entry_number"]
            last = _rand_date(rng, last, TODAY)
            text = (rng.choice(CONTINUE_TEXT).format(k=ref, d=long_date(day)) if kind == "continue"
                    else rng.choice(VACATE_TEXT).format(k=ref))
            number = len(entries) + 1
            entries.append({
                "id": next_id,
                "docket_id": template["docket_id"],
                "court": template["court"],
                "case_number": template["case_number"],
                "entry_number": number,
                "date_filed": last.isoformat(),
                "description": text,
                "document_number": str(number),
                "absolute_url": f"/docket/{template['docket_id']}/{number}/",
                "attachments": [],
                "recap_documents": [{"id": next_id * 10, "is_available": False, "page_count": rng.randint(1, 12)}],
            })
            next_id += 1
            current[ref] = day  # the latest order wins (None = vacated)
        ds.effective_deadlines[mid] = sorted(d for d in current.values() if d is not None)
