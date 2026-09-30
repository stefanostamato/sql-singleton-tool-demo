"""Profiles and variants: boundary cases, planted thresholds, text deadlines, and oracles checked
against independent DuckDB (and, for text deadlines, independent text parsing)."""

import re
from datetime import date
from decimal import Decimal

import duckdb
import pytest

from experiment.generate import TODAY, TRAP_TYPES, generate
from experiment.truth import at_risk_matters, matter_kinds, truth
from experiment.variants import BOUNDARY_TRAPS, MATH_TRAPS, TEXT_TRAPS

SIZES = [10, 40, 120]
DATE_RE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")
CONTINUE_RE = re.compile(r"deadline set in entry (\d+) is continued to ([A-Z][a-z]+ \d{1,2}, \d{4})")
VACATE_RE = re.compile(r"deadline set in entry (\d+) is vacated")


def parse_long(text: str) -> str:
    from datetime import datetime

    return datetime.strptime(text, "%B %d, %Y").date().isoformat()


def deadlines_from_text(entries: list[dict]) -> list[str]:
    """Independent resolver: read only the docket entries as an API client sees them."""
    current: dict[int, str | None] = {}
    for e in sorted(entries, key=lambda e: e["entry_number"]):
        assert "deadline_date" not in e and "deadline_type" not in e
        text = e["description"]
        m = CONTINUE_RE.search(text)
        if m:
            current[int(m.group(1))] = parse_long(m.group(2))
            continue
        m = VACATE_RE.search(text)
        if m:
            current[int(m.group(1))] = None
            continue
        m = DATE_RE.search(text)
        if m:
            current[e["entry_number"]] = parse_long(m.group(1))
    return [d for d in current.values() if d]


def independent(ds) -> list[dict]:
    """Rules 1 to 4 for this dataset's variant, in SQL over tables built here (not the servers' loader)."""
    con = duckdb.connect()
    con.execute("create table m(id int, display varchar, status varchar, area varchar, attorney varchar)")
    con.execute("create table contact(mid int, email varchar)")
    con.execute("create table dk(mid int, dl date)")
    con.execute("create table addr(email varchar, d date)")
    con.execute("create table te(mid int, d date, nb boolean, billed boolean, tenths int, cents bigint)")
    for m in ds.matters:
        con.execute("insert into m values (?,?,?,?,?)", [m["id"], m["display_number"], m["status"], m["practice_area"]["name"], m["responsible_attorney"]["name"]])
        for c in m["client"]["contacts"]:
            con.execute("insert into contact values (?,?)", [m["id"], c["email"]])
    for mid, entries in ds.dockets.items():
        if ds.variant == "textdeadlines":
            for d in deadlines_from_text(entries):
                con.execute("insert into dk values (?,?)", [mid, d])
        else:
            for e in entries:
                if "deadline_date" in e:
                    con.execute("insert into dk values (?,?)", [mid, e["deadline_date"]])
    for e in ds.emails:
        d = e["receivedDateTime"][:10]
        people = [e["from"]["emailAddress"]["address"]] + [r["emailAddress"]["address"] for r in e["toRecipients"]] + [r["emailAddress"]["address"] for r in e["ccRecipients"]]
        for p in people:
            con.execute("insert into addr values (?,?)", [p, d])
    for t in ds.time_entries:
        con.execute("insert into te values (?,?,?,?,?,?)", [
            t["matter"]["id"], t["date"], t["non_billable"], t["billed"],
            round(t["quantity_in_hours"] * 10), round(t["total"] * 100),
        ])
    if ds.variant == "math":
        rule4 = """
          and ((select coalesce(sum(tenths), 0) from te where te.mid = m.id and not nb
                and d between date '2026-09-01' and date '2026-09-15') < 15
            or (select coalesce(sum(cents), 0) from te where te.mid = m.id and not nb and not billed
                and d < date '2026-09-01') > 400000)"""
    else:
        rule4 = """
          and not exists (select 1 from te where te.mid = m.id and d between date '2026-09-01' and date '2026-09-15'
                          and not nb)"""
    rows = con.execute(
        f"""
        select attorney, display from m
        where status = 'Open' and area = 'Litigation'
          and exists (select 1 from dk where dk.mid = m.id and dl between date '2026-09-15' and date '2026-10-06')
          and not exists (select 1 from contact c join addr a on a.email = c.email
                          where c.mid = m.id and a.d between date '2026-09-01' and date '2026-09-15')
          {rule4}
        order by attorney, display
        """
    ).fetchall()
    out: dict[str, list[str]] = {}
    for a, d in rows:
        out.setdefault(a, []).append(d)
    return [{"attorney": a, "matters": ms} for a, ms in out.items()]


@pytest.mark.parametrize("variant", ["base", "math", "textdeadlines"])
@pytest.mark.parametrize("n", SIZES)
@pytest.mark.parametrize("seed", [11, 7])
def test_oracle_equals_independent_duckdb(variant, n, seed):
    ds = generate(n, seed, "v2", variant)
    expected = independent(ds)
    assert truth(ds)["at_risk"] == expected
    assert expected


def test_v1_math_and_text_also_consistent():
    for variant in ("math", "textdeadlines"):
        ds = generate(40, 7, "v1", variant)
        assert truth(ds)["at_risk"] == independent(ds)


@pytest.mark.parametrize("n", [10, 20, 40, 120])
@pytest.mark.parametrize("seed", [11, 12, 13])
def test_v2_boundary_cases_present(n, seed):
    ds = generate(n, seed, "v2")
    by_id = {m["id"]: m for m in ds.matters}
    at_risk = {m["display_number"] for m in at_risk_matters(ds)}
    tagged = {t: [mid for mid, ts in ds.tags.items() if t in ts] for t in BOUNDARY_TRAPS + ["deadline_just_outside_window"]}
    for t in BOUNDARY_TRAPS:
        assert len(tagged[t]) == 1, t
    (today,) = tagged["boundary_deadline_today"]
    (last,) = tagged["boundary_deadline_last_day"]
    (email_day,) = tagged["boundary_email_last_day"]
    (bill_day,) = tagged["boundary_billable_first_day"]

    def window_deadlines(mid):
        return [
            e["deadline_date"] for e in ds.dockets[mid] if "deadline_date" in e and "2026-09-15" <= e["deadline_date"] <= "2026-10-06"
        ]

    assert window_deadlines(today) == ["2026-09-15"]
    assert window_deadlines(last) == ["2026-10-06"]
    assert by_id[today]["display_number"] in at_risk and by_id[last]["display_number"] in at_risk
    # healthy by exactly one email dated 09-15
    contacts = {c["email"].lower() for c in by_id[email_day]["client"]["contacts"]}
    dates = []
    for e in ds.emails:
        people = {e["from"]["emailAddress"]["address"].lower()} | {r["emailAddress"]["address"].lower() for r in e["toRecipients"] + e["ccRecipients"]}
        if contacts & people and "2026-09-01" <= e["receivedDateTime"][:10] <= "2026-09-15":
            dates.append(e["receivedDateTime"][:10])
    assert dates == ["2026-09-15"]
    assert by_id[email_day]["display_number"] not in at_risk
    # healthy by exactly one billable entry dated 09-01
    billable = [t["date"] for t in ds.time_entries if t["matter"]["id"] == bill_day and not t["non_billable"]
                and "2026-09-01" <= t["date"] <= "2026-09-15"]
    assert billable == ["2026-09-01"]
    assert by_id[bill_day]["display_number"] not in at_risk
    # the second late-deadline decoy: a 10-07 deadline and nothing in the window
    decoys = tagged["deadline_just_outside_window"]
    assert len(decoys) == 1
    assert window_deadlines(decoys[0]) == []
    assert "2026-10-07" in [e.get("deadline_date") for e in ds.dockets[decoys[0]]]
    assert by_id[decoys[0]]["display_number"] not in at_risk
    # phase 1 trap types all still present, decoy counted
    t = truth(ds)["traps"]
    assert all(t[x] >= 1 for x in TRAP_TYPES) and t["deadline_just_outside_window"] >= 2
    assert all(t[x] == 1 for x in BOUNDARY_TRAPS)


def test_v2_below_10_is_v1():
    a, b = generate(5, 11, "v1"), generate(5, 11, "v2")
    assert a.matters == b.matters and a.emails == b.emails and a.time_entries == b.time_entries and a.dockets == b.dockets


def test_v2_docket_invariants():
    ds = generate(120, 12, "v2", "base")
    for entries in ds.dockets.values():
        assert [e["entry_number"] for e in entries] == list(range(1, len(entries) + 1))
        assert [e["date_filed"] for e in entries] == sorted(e["date_filed"] for e in entries)
        for e in entries:
            if "deadline_date" in e:
                assert e["date_filed"] < e["deadline_date"]
                assert date.fromisoformat(e["date_filed"]) <= TODAY
    for e in ds.emails:
        assert e["receivedDateTime"][:10] <= "2026-09-15"


def test_phase_1_truth_unchanged_by_dropping_hours_condition():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "results" / "truth"
    for p in sorted(root.glob("n*.json")):
        stored = json.loads(p.read_text())
        assert truth(generate(stored["n_matters"], stored["seed"])) == stored, p.name
    assert not any(t["quantity_in_hours"] <= 0 for n in (5, 20, 120) for t in generate(n).time_entries)


# ---------- math ----------

def window_tenths(ds, mid):
    return sum(round(t["quantity_in_hours"] * 10) for t in ds.time_entries
               if t["matter"]["id"] == mid and not t["non_billable"] and "2026-09-01" <= t["date"] <= "2026-09-15")


def unbilled(ds, mid):
    return sum((Decimal(str(t["total"])) for t in ds.time_entries
                if t["matter"]["id"] == mid and not t["non_billable"] and not t["billed"] and t["date"] < "2026-09-01"), Decimal(0))


@pytest.mark.parametrize("n", [40, 120])
def test_math_plants_totals_at_the_thresholds(n):
    ds = generate(n, 11, "v2", "math")
    at_risk = {m["display_number"] for m in at_risk_matters(ds)}
    by_id = {m["id"]: m for m in ds.matters}
    seen = set()
    for mid, tags in ds.tags.items():
        for t in tags:
            if t not in MATH_TRAPS:
                continue
            seen.add(t)
            entries = [x for x in ds.time_entries if x["matter"]["id"] == mid and not x["non_billable"]]
            assert len(entries) >= 6, "many small entries"
            assert all(0.1 <= x["quantity_in_hours"] <= 0.7 for x in entries if "2026-09-01" <= x["date"] <= "2026-09-15")
            expect_risk = t in ("hours_just_under", "unbilled_just_over")
            assert (by_id[mid]["display_number"] in at_risk) == expect_risk, t
            if t.startswith("hours"):
                assert window_tenths(ds, mid) == {"hours_just_under": 14, "hours_at_threshold": 15, "hours_just_over": 16}[t]
                assert unbilled(ds, mid) < 4000
            else:
                assert unbilled(ds, mid) == {"unbilled_just_under": 3950, "unbilled_at_threshold": 4000, "unbilled_just_over": 4050}[t]
                assert window_tenths(ds, mid) >= 15
                billed = sum(Decimal(str(x["total"])) for x in entries if x["billed"] and x["date"] < "2026-09-01")
                assert unbilled(ds, mid) + billed > 4000  # counting billed time would be a mistake
    assert seen == set(MATH_TRAPS)


# ---------- text deadlines ----------

@pytest.mark.parametrize("n", [40, 120])
def test_textdeadlines_shape_and_traps(n):
    ds = generate(n, 12, "v2", "textdeadlines")
    for entries in ds.dockets.values():
        for e in entries:
            assert "deadline_date" not in e and "deadline_type" not in e
    at_risk = {m["display_number"] for m in at_risk_matters(ds)}
    by_id = {m["id"]: m for m in ds.matters}
    seen = set()
    for mid, tags in ds.tags.items():
        for t in tags:
            if t not in TEXT_TRAPS:
                continue
            seen.add(t)
            texts = " ".join(e["description"] for e in ds.dockets[mid])
            assert ("is vacated" in texts) if t == "deadline_vacated" else ("is continued to" in texts)
            assert (by_id[mid]["display_number"] in at_risk) == (t == "deadline_continued_in"), t
            assert sorted(deadlines_from_text(ds.dockets[mid])) == [d.isoformat() for d in ds.effective_deadlines[mid]]
    assert seen == set(TEXT_TRAPS)
    sample = next(e["description"] for es in ds.dockets.values() for e in es if "due by" in e["description"] or "must be" in e["description"])
    assert DATE_RE.search(sample) and "  " not in sample and not re.search(r"\b0\d,", sample)


def test_textdeadlines_referenced_entries_exist_and_come_first():
    ds = generate(120, 13, "v2", "textdeadlines")
    for entries in ds.dockets.values():
        for e in entries:
            for rx in (CONTINUE_RE, VACATE_RE):
                m = rx.search(e["description"])
                if m:
                    ref = int(m.group(1))
                    assert ref < e["entry_number"]
                    assert DATE_RE.search(entries[ref - 1]["description"]) and "deadline set in entry" not in entries[ref - 1]["description"]


def test_matter_kinds_cover_every_matter():
    ds = generate(120, 11, "v2", "math")
    kinds = matter_kinds(ds)
    assert set(kinds) == {m["display_number"] for m in ds.matters}
    assert {"healthy", *MATH_TRAPS} <= set(kinds.values())
    assert "at_risk_plain" in set(matter_kinds(generate(40, 7)).values())
