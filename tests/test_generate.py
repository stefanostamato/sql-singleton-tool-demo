import json
from datetime import date

import duckdb
import pytest

from experiment.generate import DECEPTIVE_TRAPS, TODAY, TRAP_TYPES, generate
from experiment.truth import at_risk_matters, truth

SIZES = [10, 20, 40, 60, 80, 100, 120]


def dump(ds):
    return json.dumps([ds.matters, ds.dockets, ds.emails, ds.time_entries], sort_keys=True, default=str)


def test_same_seed_identical():
    assert dump(generate(40, 7)) == dump(generate(40, 7))
    assert dump(generate(40, 7)) != dump(generate(40, 8))


@pytest.mark.parametrize("n", SIZES)
def test_every_trap_type_present(n):
    t = truth(generate(n))
    assert set(t["traps"]) == set(TRAP_TYPES)
    assert all(v >= 1 for v in t["traps"].values()), t["traps"]


def test_small_n_has_at_risk_and_trap():
    t = truth(generate(5))
    assert sum(len(a["matters"]) for a in t["at_risk"]) >= 1
    assert sum(t["traps"].values()) >= 1


@pytest.mark.parametrize("n", [20, 40, 80, 120])
def test_about_a_quarter_at_risk(n):
    ds = generate(n)
    share = len(at_risk_matters(ds)) / n
    assert 0.2 <= share <= 0.35, share


def test_shapes_and_constraints():
    ds = generate(60)
    assert len(ds.attorneys) == 6
    assert len({m["client"]["id"] for m in ds.matters}) == 60  # one client per matter
    for m in ds.matters:
        assert 1 <= len(m["client"]["contacts"]) <= 3
        assert m["display_number"].startswith("HV-2026-")
    for entries in ds.dockets.values():
        assert 3 <= len(entries) <= 8
        for e in entries:
            assert date.fromisoformat(e["date_filed"]) <= TODAY
            if "deadline_date" in e:
                assert date(2026, 8, 16) <= date.fromisoformat(e["deadline_date"]) <= date(2026, 11, 14)
    for e in ds.emails:
        assert date.fromisoformat(e["receivedDateTime"][:10]) <= TODAY
        addrs = [e["from"]["emailAddress"]["address"]]
        addrs += [r["emailAddress"]["address"] for r in e["toRecipients"] + e["ccRecipients"]]
        assert all(a.endswith(".example") for a in addrs)
    noise = [e for e in ds.emails if ds.email_owner[e["id"]] is None]
    assert len(noise) == 60
    for t in ds.time_entries:
        assert date.fromisoformat(t["date"]) <= TODAY


def test_each_trap_is_a_trap_for_exactly_its_reason():
    ds = generate(80)
    at_risk = {m["display_number"] for m in at_risk_matters(ds)}
    by_id = {m["id"]: m for m in ds.matters}
    for mid, scen in ds.scenarios.items():
        m = by_id[mid]
        flagged = m["display_number"] in at_risk
        if scen in TRAP_TYPES:
            # deceptive traps look healthy but the rule flags them; the others look at risk but are not
            assert flagged == (scen in DECEPTIVE_TRAPS), scen
        if scen == "deadline_just_outside_window":
            fut = [e["deadline_date"] for e in ds.dockets[mid] if e.get("deadline_date", "") >= "2026-09-15"]
            assert fut == ["2026-10-07"]
        if scen == "closed_with_deadline":
            assert m["status"] == "Closed"
            assert any("2026-09-15" <= e.get("deadline_date", "") <= "2026-10-06" for e in ds.dockets[mid])
        if scen == "non_litigation_with_deadline":
            assert m["practice_area"]["name"] == "Corporate" and mid not in ds.dockets
            assert "2026-09-15" <= m["statute_of_limitations"] <= "2026-10-06"
        if scen == "client_email_just_outside_window":
            emails = {c["email"] for c in m["client"]["contacts"]}
            dates = [
                e["receivedDateTime"][:10]
                for e in ds.emails
                if emails & ({e["from"]["emailAddress"]["address"]}
                             | {r["emailAddress"]["address"] for r in e["toRecipients"] + e["ccRecipients"]})
            ]
            assert max(dates) == "2026-08-31"
        if scen == "non_billable_time_only":
            inwin = [t for t in ds.time_entries if t["matter"]["id"] == mid and "2026-09-01" <= t["date"] <= "2026-09-15"]
            assert inwin and all(t["non_billable"] for t in inwin)
        if scen == "opposing_counsel_email_only":
            emails = {c["email"] for c in m["client"]["contacts"]}
            inwin = [
                e for e in ds.emails
                if ds.email_owner[e["id"]] == mid and "2026-09-01" <= e["receivedDateTime"][:10] <= "2026-09-15"
            ]
            assert len(inwin) >= 1
            for e in inwin:
                assert not emails & ({e["from"]["emailAddress"]["address"]} | {r["emailAddress"]["address"] for r in e["toRecipients"] + e["ccRecipients"]})


def duckdb_oracle(ds) -> list[dict]:
    """Independent implementation of the at-risk rule in SQL."""
    con = duckdb.connect()
    con.execute("create table m(id int, display varchar, status varchar, area varchar, attorney varchar)")
    con.execute("create table contact(mid int, email varchar)")
    con.execute("create table dk(mid int, dl date)")
    con.execute("create table addr(email varchar, d date)")
    con.execute("create table te(mid int, d date, nb boolean, q double)")
    for m in ds.matters:
        con.execute("insert into m values (?,?,?,?,?)", [m["id"], m["display_number"], m["status"], m["practice_area"]["name"], m["responsible_attorney"]["name"]])
        for c in m["client"]["contacts"]:
            con.execute("insert into contact values (?,?)", [m["id"], c["email"]])
    for mid, entries in ds.dockets.items():
        for e in entries:
            if "deadline_date" in e:
                con.execute("insert into dk values (?,?)", [mid, e["deadline_date"]])
    for e in ds.emails:
        d = e["receivedDateTime"][:10]
        people = [e["from"]["emailAddress"]["address"]] + [r["emailAddress"]["address"] for r in e["toRecipients"]] + [r["emailAddress"]["address"] for r in e["ccRecipients"]]
        for p in people:
            con.execute("insert into addr values (?,?)", [p, d])
    for t in ds.time_entries:
        con.execute("insert into te values (?,?,?,?)", [t["matter"]["id"], t["date"], t["non_billable"], t["quantity_in_hours"]])
    rows = con.execute(
        """
        select attorney, display from m
        where status = 'Open' and area = 'Litigation'
          and exists (select 1 from dk where dk.mid = m.id and dl between date '2026-09-15' and date '2026-10-06')
          and not exists (select 1 from contact c join addr a on a.email = c.email
                          where c.mid = m.id and a.d between date '2026-09-01' and date '2026-09-15')
          and not exists (select 1 from te where te.mid = m.id and d between date '2026-09-01' and date '2026-09-15'
                          and not nb and q > 0)
        order by attorney, display
        """
    ).fetchall()
    out: dict[str, list[str]] = {}
    for a, d in rows:
        out.setdefault(a, []).append(d)
    return [{"attorney": a, "matters": ms} for a, ms in out.items()]


@pytest.mark.parametrize("n", [5, 10, 20, 40, 80, 120])
def test_oracle_matches_duckdb(n):
    ds = generate(n)
    expected = duckdb_oracle(ds)
    assert truth(ds)["at_risk"] == expected
    assert expected, "at least one at-risk matter"
