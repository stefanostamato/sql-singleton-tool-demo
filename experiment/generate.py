"""Seeded generator for the fake systems of Harbor & Vale LLP.

`generate(n_matters, seed)` returns a `Dataset` holding Clio-like matters, CourtListener-like docket
entries, Microsoft Graph-like emails and Clio-like time entries, plus planted traps. Everything is
deterministic for a given (n_matters, seed). All addresses use `.example` domains.
"""

from __future__ import annotations

import html
import math
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

TODAY = date(2026, 9, 15)
WINDOW_START = date(2026, 9, 1)  # activity window: 2026-09-01 .. 2026-09-15
DEADLINE_END = date(2026, 10, 6)  # deadline window: 2026-09-15 .. 2026-10-06
FIRM = "Harbor & Vale LLP"
FIRM_DOMAIN = "harborvale.example"

ATTORNEY_NAMES = [
    "Dana Whitfield",
    "Marcus Oyelaran",
    "Priya Raman",
    "Tomás Ibarra",
    "Elena Kowalczyk",
    "James Thornbury",
]
RATES = [425.0, 550.0, 495.0, 395.0, 610.0, 575.0]

TRAP_TYPES = [
    "deadline_just_outside_window",
    "opposing_counsel_email_only",
    "non_billable_time_only",
    "client_email_just_outside_window",
    "closed_with_deadline",
    "non_litigation_with_deadline",
]
# By the at-risk rule these matters ARE at risk (a sloppy reader wrongly calls them healthy).
DECEPTIVE_TRAPS = {"opposing_counsel_email_only", "non_billable_time_only", "client_email_just_outside_window"}

PRACTICE_AREAS = ["Litigation", "Corporate", "Employment", "Intellectual Property", "Real Estate"]

CLIENT_PREFIX = [
    "Northwind", "Cobalt", "Redwood", "Summit", "Lakeshore", "Ironbridge", "Alder", "Kestrel", "Meridian",
    "Bluefin", "Granite", "Sable", "Harlow", "Pinecrest", "Vantage", "Orchard", "Tidewater", "Copperfield",
    "Brightwater", "Falcon", "Juniper", "Lantern", "Marlowe", "Nimbus", "Onyx", "Quarry", "Ridgeway",
    "Stonegate", "Thistle", "Umber", "Wexford", "Yarrow", "Zephyr", "Ashford", "Birchwood", "Crescent",
    "Driftwood", "Emberly", "Foxglove", "Glenmoor",
]
CLIENT_SUFFIX = [
    "Logistics", "Foods", "Holdings", "Biotech", "Media", "Dental Group", "Energy", "Robotics", "Apparel",
    "Freight", "Analytics", "Hospitality",
]
OPP_FIRM_A = [
    "Whitmore", "Pryce", "Langford", "Ashby", "Corbin", "Dalton", "Fairbanks", "Garrity", "Holloway", "Kimball",
    "Lockhart", "Mercer", "Nash", "Overton", "Prescott", "Quimby", "Radcliffe", "Sterling", "Tolliver", "Ulrich",
]
OPP_FIRM_B = [
    "Barlow", "Castellan", "Devereux", "Eastman", "Fenwick", "Galloway", "Hargrove", "Irvine", "Jessup",
    "Kensington", "Lund", "Montague", "Norcross", "Okafor", "Penhale", "Rourke", "Sutton", "Trevino", "Vance",
    "Wexler",
]
FIRST_NAMES = [
    "Alex", "Bianca", "Carlos", "Deepa", "Evan", "Farah", "Gavin", "Hana", "Isaac", "Joanna", "Kofi", "Lena",
    "Mateo", "Nadia", "Owen", "Petra", "Quinn", "Rosa", "Samir", "Tessa", "Umar", "Vera", "Wes", "Ximena",
    "Yusuf", "Zoe", "Aisha", "Brendan", "Camille", "Dmitri",
]
LAST_NAMES = [
    "Abbott", "Banerjee", "Castillo", "Duarte", "Eriksen", "Fontaine", "Gupta", "Hoffman", "Ivanov", "Jimenez",
    "Khan", "Lindqvist", "Moreau", "Novak", "Okonkwo", "Petrov", "Quesada", "Rasmussen", "Sato", "Tanaka",
    "Ueda", "Vasquez", "Walsh", "Xu", "Yamamoto", "Zielinski", "Bellamy", "Cho", "Dietrich", "Esposito",
]
TITLES = [
    "General Counsel", "Chief Financial Officer", "VP Operations", "Controller", "Head of Compliance",
    "Managing Director", "Director of HR", "Chief Executive Officer",
]
COURTS = [
    ("U.S. District Court, Southern District of New York", "1"),
    ("U.S. District Court, Northern District of Illinois", "1"),
    ("U.S. District Court, Western District of Washington", "2"),
    ("Superior Court of California, County of Alameda", "3"),
    ("Circuit Court of Cook County, Illinois", "1"),
    ("U.S. District Court, District of Massachusetts", "1"),
]
JUDGES = ["Hon. R. Alvarez", "Hon. M. Chen", "Hon. T. Brennan", "Hon. S. Okoye", "Hon. L. Fitzgerald"]
DEADLINE_TYPES = [
    "Response to motion to compel due",
    "Opposition to motion for summary judgment due",
    "Expert disclosure deadline",
    "Joint pretrial statement due",
    "Answer to amended complaint due",
    "Motion in limine deadline",
    "Mediation statement due",
    "Reply brief due",
    "Deposition of corporate representative",
    "Close of fact discovery",
]
PLAIN_ENTRIES = [
    "NOTICE of Appearance filed by counsel for Defendant. Certificate of service attached.",
    "ORDER setting Initial Scheduling Conference. Parties shall submit a joint status report seven days before the conference.",
    "STIPULATION and [PROPOSED] ORDER regarding electronically stored information and a protective order for confidential materials.",
    "MINUTE ENTRY for proceedings held before the presiding judge. Status conference held; counsel for both sides present.",
    "CERTIFICATE OF SERVICE re Plaintiff's First Set of Requests for Production. Served by email on all counsel of record.",
    "NOTICE of Deposition of a corporate designee, to be taken remotely. Court reporter has been retained.",
    "ORDER granting in part the parties' joint request to modify the case schedule. All other dates remain in effect.",
    "LETTER from counsel re discovery dispute and request for an informal conference with the court.",
    "MOTION for Leave to File Excess Pages in connection with dispositive motions. Opposition, if any, is due per local rules.",
    "REPLY in support of motion to compel, with declaration of counsel and exhibits A through D.",
]
MATTER_DESC = {
    "Litigation": [
        "{c} v. {o}: commercial contract dispute over unpaid invoices and breach of warranty.",
        "{c} defense of a wage and hour class action filed against the company.",
        "{c} v. {o}: trade secret misappropriation and unfair competition claims.",
        "{c} defense of a product liability suit arising from a recalled component.",
        "{c} v. {o}: landlord-tenant dispute over a commercial lease guaranty.",
    ],
    "Corporate": [
        "{c}: Series B financing, stock purchase agreement and disclosure schedules.",
        "{c}: acquisition of a regional competitor, asset purchase and diligence.",
        "{c}: annual corporate maintenance, board minutes and bylaws update.",
    ],
    "Employment": [
        "{c}: executive employment agreements and restrictive covenant review.",
        "{c}: internal investigation and remediation of a harassment complaint.",
    ],
    "Intellectual Property": [
        "{c}: trademark portfolio clearance and registration in three classes.",
        "{c}: patent prosecution for a control-systems invention.",
    ],
    "Real Estate": [
        "{c}: purchase and financing of a distribution warehouse.",
        "{c}: ground lease negotiation for a new headquarters site.",
    ],
}
CUSTOM_FIELDS = [
    ("Referral Source", ["Existing client", "Bar association referral", "Website inquiry", "Partner network"]),
    ("Conflict Check", ["Cleared", "Cleared with waiver"]),
    ("Fee Arrangement", ["Hourly", "Hourly with cap", "Blended rate"]),
    ("Retainer Held", ["$5,000", "$10,000", "$25,000", "None"]),
    ("Insurance Carrier Notified", ["Yes", "No", "Not applicable"]),
]
ACTIVITIES = [
    (7001, "Legal research"), (7002, "Drafting"), (7003, "Client call"), (7004, "Court appearance"),
    (7005, "Document review"), (7006, "Correspondence"), (7007, "Deposition preparation"),
]
TIME_NOTES = [
    "Reviewed opposing production",
    "Drafted response brief",
    "Client call re open items",
    "Hearing preparation",
    "Legal research on standard of review",
    "Emails with opposing counsel re scheduling",
    "Contract redline review",
    "Internal strategy meeting",
]
EMAIL_TOPICS = [
    "Discovery schedule", "Draft stipulation", "Settlement discussion", "Deposition scheduling",
    "Document production", "Status update", "Engagement terms", "Hearing logistics", "Exhibit list",
    "Invoice question", "Next steps",
]
CLIENT_SENTENCES = [
    "Thank you for the update. I reviewed the attached draft with our team and we have a few comments.",
    "Could you confirm the timing of the next filing so that I can brief our executives ahead of time?",
    "We gathered the additional documents you requested and will send them over by the end of the week.",
    "Please let me know if there is anything else you need from us before the deadline.",
    "I have looped in our finance lead who can answer questions about the invoices in dispute.",
    "We are comfortable with the approach you outlined, subject to a quick call to align on risk.",
    "Our insurance carrier has asked for a short summary of the case; can you help prepare one?",
]
ATTORNEY_SENTENCES = [
    "Following up on our call, I have attached the latest draft and a short summary of open issues.",
    "The court's scheduling order sets the next deadline, and I want to make sure we are on track.",
    "I recommend we respond to the request narrowly and preserve our objections; details below.",
    "Please review the enclosed and send me your comments by Thursday so we can finalize.",
    "I will circulate a proposed timeline and budget estimate for the next phase later this week.",
    "We received the other side's production and have begun a first-pass review for key documents.",
]
OPPOSING_SENTENCES = [
    "We propose the following dates for depositions and ask that you confirm availability of your witnesses.",
    "Attached is our supplemental production. We reserve all rights and objections as previously stated.",
    "Please advise whether your client will stipulate to a short extension of the briefing schedule.",
    "We are available for a meet and confer on the discovery dispute any afternoon this week.",
    "Enclosed is a draft protective order for your review; we expect it to be uncontroversial.",
]
NOISE = [
    ("Firm newsletter: September CLE calendar and new hires", "newsletter@harborvale.example",
     "This month's continuing legal education sessions, welcome notes for two new associates, and a reminder about the annual retreat."),
    ("Reminder: timesheets due Friday", "accounting@harborvale.example",
     "Please submit all time entries for the current period by end of day Friday so that invoices can go out on schedule."),
    ("Office closed for elevator maintenance Saturday", "facilities@harborvale.example",
     "The building will be closed on Saturday for scheduled elevator maintenance. Remote access is unaffected."),
    ("Lunch and learn: e-discovery tooling", "training@harborvale.example",
     "Join us Wednesday at noon for a walkthrough of the firm's new e-discovery review platform. Lunch provided."),
    ("Weekly legal news digest", "digest@legalupdates.example",
     "Top stories this week: appellate rulings on arbitration clauses, new state privacy statutes, and court rule changes."),
]


@dataclass
class Dataset:
    n_matters: int
    seed: int
    today: date
    attorneys: list[dict]
    matters: list[dict]
    dockets: dict[int, list[dict]]  # matter_id -> docket entries (litigation only)
    emails: list[dict]
    time_entries: list[dict]
    scenarios: dict[int, str] = field(default_factory=dict)  # matter_id -> scenario name
    email_owner: dict[str, int | None] = field(default_factory=dict)  # message id -> matter id (None = noise)
    profile: str = "v1"
    variant: str = "base"
    # Structured generator metadata, never exposed through the fake APIs:
    tags: dict[int, list[str]] = field(default_factory=dict)  # matter_id -> planted boundary / variant trap types
    effective_deadlines: dict[int, list[date]] = field(default_factory=dict)  # textdeadlines: resolved deadlines


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _ascii(text: str) -> str:
    return text.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")


def _rand_date(rng: random.Random, lo: date, hi: date) -> date:
    return lo + timedelta(days=rng.randint(0, (hi - lo).days))


def _plan_scenarios(n: int, rng: random.Random) -> list[str]:
    """Return one scenario name per matter (shuffled). See module docs for the mix."""
    if n < 10:
        traps = ["deadline_just_outside_window"]
        clean_at_risk = 1
    else:
        t = max(6, int(0.25 * n + 0.5))
        traps = [TRAP_TYPES[i % 6] for i in range(t)]
        target = max(1, int(0.25 * n + 0.5))
        clean_at_risk = max(1, target - sum(1 for x in traps if x in DECEPTIVE_TRAPS))
    scen = ["at_risk"] * clean_at_risk + traps
    healthy = ["healthy_lit_email", "healthy_lit_time", "healthy_lit_both", "healthy_nonlit"]
    i = 0
    while len(scen) < n:
        scen.append(healthy[i % 4])
        i += 1
    scen = scen[:n]
    rng.shuffle(scen)
    return scen


# Per-scenario activity constraints.
#   client_win / bill_win: "forbid" | "force" | "free"   (client email / billable time inside 09-01..09-15)
#   opp_win: number of opposing-counsel emails forced inside the window
#   nonbill_win: number of non-billable time entries forced inside the window
#   quiet: no email and no time entry of any kind inside the window
#   client_on_0831: force a client email on 2026-08-31
CONSTRAINTS = {
    "at_risk": dict(client_win="forbid", bill_win="forbid"),
    "opposing_counsel_email_only": dict(client_win="forbid", bill_win="forbid", opp_win=2),
    "non_billable_time_only": dict(client_win="forbid", bill_win="forbid", nonbill_win=2),
    "deadline_just_outside_window": dict(client_win="forbid", bill_win="forbid"),
    "client_email_just_outside_window": dict(client_win="forbid", bill_win="forbid", client_on_0831=True),
    "closed_with_deadline": dict(client_win="forbid", bill_win="forbid", quiet=True),
    "non_litigation_with_deadline": dict(client_win="forbid", bill_win="forbid", quiet=True),
    "healthy_lit_email": dict(client_win="force", bill_win="forbid"),
    "healthy_lit_time": dict(client_win="forbid", bill_win="force"),
    "healthy_lit_both": dict(client_win="force", bill_win="force"),
    "healthy_nonlit": dict(client_win="force", bill_win="force"),
}
LITIGATION_SCENARIOS = set(CONSTRAINTS) - {"non_litigation_with_deadline", "healthy_nonlit"}


PROFILES = ("v1", "v2")
VARIANTS = ("base", "math", "textdeadlines")


def generate(n_matters: int, seed: int = 7, profile: str = "v1", variant: str = "base") -> Dataset:
    """Generate the fake systems. profile "v1" with variant "base" is the phase 1 data, byte for byte.
    Profile "v2" adds boundary cases (every N >= 10); a variant reshapes the data for a harder question."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}")
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    ds = _generate_v1(n_matters, seed)
    if profile != "v1" or variant != "base":
        from experiment import variants

        variants.apply(ds, profile, variant)
    return ds


def _generate_v1(n_matters: int, seed: int) -> Dataset:
    rng = random.Random(f"{seed}-{n_matters}")
    attorneys = []
    for i, name in enumerate(ATTORNEY_NAMES):
        parts = _ascii(name).lower().split()
        attorneys.append(
            {
                "id": 1001 + i,
                "name": name,
                "email": f"{parts[0]}.{parts[1]}@{FIRM_DOMAIN}",
                "rate": RATES[i],
            }
        )

    scenarios = _plan_scenarios(n_matters, rng)
    names = rng.sample([f"{p} {s}" for p in CLIENT_PREFIX for s in CLIENT_SUFFIX], n_matters)
    opp_names = rng.sample([f"{a} {b} LLP" for a in OPP_FIRM_A for b in OPP_FIRM_B], n_matters)

    ids = {"contact": 30001, "docket_entry": 500001, "time": 900001, "person": 60001}
    matters: list[dict] = []
    dockets: dict[int, list[dict]] = {}
    emails: list[dict] = []
    times: list[dict] = []
    scen_by_matter: dict[int, str] = {}
    email_owner: dict[str, int | None] = {}

    def nid(kind: str) -> int:
        ids[kind] += 1
        return ids[kind] - 1

    def hexid(length: int) -> str:
        return "".join(rng.choice("0123456789abcdef") for _ in range(length))

    for i in range(n_matters):
        scen = scenarios[i]
        matter_id = 10001 + i
        display = f"HV-2026-{i + 1:04d}"
        scen_by_matter[matter_id] = scen
        lit = scen in LITIGATION_SCENARIOS
        if lit:
            area = "Litigation"
        elif scen == "non_litigation_with_deadline":
            area = "Corporate"
        else:
            area = rng.choice(PRACTICE_AREAS[1:])
        status = "Closed" if scen == "closed_with_deadline" else (
            "Pending" if scen == "healthy_nonlit" and rng.random() < 0.3 else "Open"
        )

        resp = rng.choice(attorneys)
        orig = rng.choice(attorneys)
        cname = names[i]
        cslug = _slug(cname)
        cdomain = f"{cslug}.example"
        contacts = []
        used = set()
        for _ in range(rng.randint(1, 3)):
            while True:
                fn, ln = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
                if (fn, ln) not in used:
                    used.add((fn, ln))
                    break
            contacts.append(
                {
                    "id": nid("contact"),
                    "name": f"{fn} {ln}",
                    "title": rng.choice(TITLES),
                    "email": f"{fn.lower()}.{ln.lower()}@{cdomain}",
                    "phone": f"+1-555-{rng.randint(100, 999):03d}-{rng.randint(0, 9999):04d}",
                }
            )
        client_id = 20001 + i

        opp_lawyers = []
        opp_firm = opp_domain = None
        if lit:
            opp_firm = opp_names[i]
            opp_domain = f"{_slug(opp_firm)}.example"
            for _ in range(rng.randint(1, 2)):
                while True:
                    fn, ln = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
                    if (fn, ln) not in used:
                        used.add((fn, ln))
                        break
                opp_lawyers.append({"name": f"{fn} {ln}", "email": f"{fn.lower()}.{ln.lower()}@{opp_domain}"})

        open_date = _rand_date(rng, date(2024, 10, 1), date(2026, 6, 30))
        close_date = _rand_date(rng, date(2026, 7, 1), date(2026, 8, 20)) if status == "Closed" else None
        created = datetime(open_date.year, open_date.month, open_date.day, 14, 5, 12)
        updated = datetime(2026, 9, rng.randint(1, 14), rng.randint(8, 18), rng.randint(0, 59), 3)
        court = case_number = None
        if lit:
            court_name, div = rng.choice(COURTS)
            case_number = f"{div}:26-cv-{rng.randint(100, 9999):05d}"
            court = {"name": court_name, "case_number": case_number}
        if scen == "non_litigation_with_deadline":
            sol = _rand_date(rng, TODAY, DEADLINE_END)
        else:
            sol = _rand_date(rng, date(2026, 11, 1), date(2028, 6, 30))

        desc_tpl = rng.choice(MATTER_DESC[area])
        cf_pick = rng.sample(CUSTOM_FIELDS, 2)
        matter = {
            "id": matter_id,
            "etag": f'"{hexid(12)}"',
            "display_number": display,
            "description": desc_tpl.format(c=cname, o=opp_firm.replace(" LLP", "") if opp_firm else "counterparty"),
            "status": status,
            "location": rng.choice(["Chicago, IL", "New York, NY", "Seattle, WA", "Boston, MA"]),
            "client": {
                "id": client_id,
                "name": cname,
                "type": "Company",
                "primary_email_address": contacts[0]["email"],
                "contacts": contacts,
            },
            "practice_area": {"id": 400 + PRACTICE_AREAS.index(area), "name": area},
            "responsible_attorney": {"id": resp["id"], "name": resp["name"], "email": resp["email"]},
            "originating_attorney": {"id": orig["id"], "name": orig["name"], "email": orig["email"]},
            "open_date": open_date.isoformat(),
            "close_date": close_date.isoformat() if close_date else None,
            "billable": True,
            "billing_method": rng.choice(["hourly", "hourly", "flat", "contingency"]),
            "statute_of_limitations": sol.isoformat(),
            "court": court,
            "custom_field_values": [
                {"field_name": nm, "value": rng.choice(vals)}
                for k, (nm, vals) in enumerate(cf_pick)
            ],
            "created_at": created.isoformat() + "Z",
            "updated_at": updated.isoformat() + "Z",
        }
        matters.append(matter)

        # ---- docket entries -------------------------------------------------------------
        if lit:
            dockets[matter_id] = _docket(rng, ids, matter, scen, opp_firm)

        # ---- activity (emails and time) ---------------------------------------------------
        _activity(rng, hexid, nid, emails, times, email_owner, matter, scen, lit, resp, orig, contacts,
                  opp_lawyers, attorneys)

        # ---- one unrelated noise email per matter ---------------------------------------
        subj, sender, text = rng.choice(NOISE)
        nd = _rand_date(rng, TODAY - timedelta(days=60), TODAY)
        recips = rng.sample(attorneys, 3)
        msg = _email_record(
            rng, hexid, subj, text, [f"<p>{html.escape(text)}</p>", "<p>Regards,<br>Harbor &amp; Vale Administration</p>"],
            (sender.split("@")[0].title() + " Desk", sender), [(a["name"], a["email"]) for a in recips], [],
            datetime(nd.year, nd.month, nd.day, rng.randint(7, 19), rng.randint(0, 59), rng.randint(0, 59)),
            f"AAQkAGE{hexid(10)}", False, "low",
        )
        emails.append(msg)
        email_owner[msg["id"]] = None

    emails.sort(key=lambda e: (e["receivedDateTime"], e["id"]))
    return Dataset(
        n_matters=n_matters, seed=seed, today=TODAY, attorneys=attorneys, matters=matters, dockets=dockets,
        emails=emails, time_entries=times, scenarios=scen_by_matter, email_owner=email_owner,
    )


def _docket(rng, ids, matter, scen, opp_firm) -> list[dict]:
    """Docket entries for one litigation matter, honouring the scenario's deadline rules."""
    win_lo, win_hi = TODAY, DEADLINE_END
    past = lambda: _rand_date(rng, TODAY - timedelta(days=30), TODAY - timedelta(days=1))  # noqa: E731
    after = lambda: _rand_date(rng, DEADLINE_END + timedelta(days=2), TODAY + timedelta(days=60))  # noqa: E731
    deadlines: list[date] = []
    if scen == "deadline_just_outside_window":
        deadlines.append(date(2026, 10, 7))
        if rng.random() < 0.5:
            deadlines.append(past())
    else:
        for _ in range(1 if rng.random() < 0.75 else 2):
            deadlines.append(_rand_date(rng, win_lo, win_hi))
        for _ in range(rng.randint(0, 2)):
            deadlines.append(past() if rng.random() < 0.5 else after())
    k = max(rng.choice([3, 3, 4, 4, 5, 5, 6, 7, 8]), len(deadlines))
    specs = []
    for d in deadlines:
        filed = _rand_date(rng, TODAY - timedelta(days=120), min(TODAY, d - timedelta(days=1)))
        specs.append((filed, d))
    for _ in range(k - len(deadlines)):
        specs.append((_rand_date(rng, TODAY - timedelta(days=120), TODAY), None))
    specs.sort(key=lambda s: s[0])
    docket_id = 7000000 + matter["id"]
    plaintiff = matter["client"]["name"]
    out = []
    for n, (filed, d) in enumerate(specs, start=1):
        eid = ids["docket_entry"]
        ids["docket_entry"] += 1
        if d:
            dtype = rng.choice(DEADLINE_TYPES)
            text = (
                f"{dtype.split(' due')[0].split(' deadline')[0].upper()} filed by counsel for "
                f"{rng.choice([plaintiff, opp_firm.replace(' LLP', '')])}. Per the court's order, the "
                f"corresponding deadline is set for {d.strftime('%B %d, %Y')}."
            )
        else:
            dtype = None
            text = rng.choice(PLAIN_ENTRIES)
        doc_no = str(n)
        entry = {
            "id": eid,
            "docket_id": docket_id,
            "court": "".join(w[0] for w in matter["court"]["name"].split() if w[0].isupper()),
            "case_number": matter["court"]["case_number"],
            "entry_number": n,
            "date_filed": filed.isoformat(),
            "description": text,
            "document_number": doc_no,
            "absolute_url": f"/docket/{docket_id}/{doc_no}/",
            "attachments": [
                {"attachment_number": a + 1, "description": rng.choice(["Exhibit A", "Declaration", "Proposed Order", "Memorandum"])}
                for a in range(rng.choice([0, 0, 0, 1]))
            ],
            "recap_documents": [
                {"id": eid * 10, "is_available": False, "page_count": rng.randint(1, 40)}
            ],
        }
        if d:
            entry["deadline_date"] = d.isoformat()
            entry["deadline_type"] = dtype
        out.append(entry)
    return out


def _email_record(rng, hexid, subject, preview_src, paragraphs, sender, to, cc, when, conv, has_att, importance):
    plain = re.sub(r"<[^>]+>", " ", " ".join(paragraphs))
    plain = html.unescape(re.sub(r"\s+", " ", plain)).strip()
    mid = "AAMkAGE" + hexid(12)
    frm = {"emailAddress": {"name": sender[0], "address": sender[1]}}
    sent = when
    recv = when + timedelta(seconds=rng.randint(1, 9))
    return {
        "id": mid,
        "categories": [],
        "receivedDateTime": recv.isoformat() + "Z",
        "sentDateTime": sent.isoformat() + "Z",
        "hasAttachments": bool(has_att),
        "internetMessageId": f"<{hexid(8)}@mail.harborvale.example>",
        "subject": subject,
        "bodyPreview": plain[:255],
        "importance": importance,
        "parentFolderId": "AQMkAGE" + hexid(6),
        "conversationId": conv,
        "isRead": rng.random() < 0.7,
        "webLink": f"https://outlook.example/owa/?ItemID={mid[:12]}",
        "body": {"contentType": "html", "content": "<html><body>" + "".join(paragraphs) + "</body></html>"},
        "sender": frm,
        "from": frm,
        "toRecipients": [{"emailAddress": {"name": n, "address": a}} for n, a in to],
        "ccRecipients": [{"emailAddress": {"name": n, "address": a}} for n, a in cc],
    }


def _activity(rng, hexid, nid, emails, times, email_owner, matter, scen, lit, resp, orig, contacts, opp_lawyers, attorneys):
    cons = CONSTRAINTS[scen]
    quiet = cons.get("quiet", False)
    pre = (TODAY - timedelta(days=60), WINDOW_START - timedelta(days=1))
    win = (WINDOW_START, TODAY)
    full = (TODAY - timedelta(days=60), TODAY)

    def pick(mode_forbid: bool) -> date:
        if quiet or mode_forbid:
            return _rand_date(rng, *pre)
        return _rand_date(rng, *full)

    # ---- email specs: (kind, date)
    especs: list[tuple[str, date]] = []
    if cons["client_win"] == "force":
        especs.append(("client", _rand_date(rng, *win)))
    if cons.get("client_on_0831"):
        especs.append(("client", date(2026, 8, 31)))
    for _ in range(cons.get("opp_win", 0)):
        especs.append(("opposing", _rand_date(rng, *win)))
    if scen == "at_risk" and rng.random() < 0.4:
        especs.append(("opposing", _rand_date(rng, *win)))  # noise: opposing counsel wrote in the window
    total = max(rng.choice([2, 2, 3, 3, 4, 5, 6]), len(especs))
    while len(especs) < total:
        kind = "opposing" if lit and rng.random() < 0.3 else "client"
        forbid = kind == "client" and cons["client_win"] == "forbid"
        especs.append((kind, pick(forbid)))
    if cons["client_win"] == "forbid" and not any(k == "client" and d < WINDOW_START for k, d in especs):
        # the matter was active before the window: add an older client email
        especs.append(("client", _rand_date(rng, pre[0], date(2026, 8, 30))))
    conv_by_topic: dict[str, str] = {}
    topics = rng.sample(EMAIL_TOPICS, 3)
    for kind, d in especs:
        attorney = resp if rng.random() < 0.85 else orig
        topic = rng.choice(topics)
        conv = conv_by_topic.setdefault(topic, f"AAQkAGE{hexid(10)}")
        when = datetime(d.year, d.month, d.day, rng.randint(8, 18), rng.randint(0, 59), rng.randint(0, 59))
        subj = rng.choice(["RE: ", "RE: ", "FW: ", ""]) + f"[{matter['display_number']}] {topic}"
        if kind == "client":
            people = rng.sample(contacts, rng.randint(1, len(contacts)))
            inbound = rng.random() < 0.5
            sents = (CLIENT_SENTENCES if inbound else ATTORNEY_SENTENCES)
            first = people[0]
            if inbound:
                sender = (first["name"], first["email"])
                to = [(attorney["name"], attorney["email"])]
                cc = [(p["name"], p["email"]) for p in people[1:]]
            else:
                sender = (attorney["name"], attorney["email"])
                to = [(p["name"], p["email"]) for p in people]
                cc = [(orig["name"], orig["email"])] if orig is not attorney and rng.random() < 0.4 else []
            greet = first["name"].split()[0] if not inbound else attorney["name"].split()[0]
            signer = first["name"] if inbound else attorney["name"]
        else:
            people = rng.sample(opp_lawyers, rng.randint(1, len(opp_lawyers)))
            inbound = rng.random() < 0.6
            sents = OPPOSING_SENTENCES if inbound else ATTORNEY_SENTENCES
            first = people[0]
            if inbound:
                sender = (first["name"], first["email"])
                to = [(attorney["name"], attorney["email"])]
                cc = [(p["name"], p["email"]) for p in people[1:]]
            else:
                sender = (attorney["name"], attorney["email"])
                to = [(p["name"], p["email"]) for p in people]
                cc = []
            greet = first["name"].split()[0] if not inbound else attorney["name"].split()[0]
            signer = first["name"] if inbound else attorney["name"]
        body = [f"<p>Hi {greet},</p>"]
        for s in rng.sample(sents, min(len(sents), 1)):
            body.append(f"<p>{html.escape(s)}</p>")
        msg = _email_record(rng, hexid, subj, "", body, sender, to, cc, when, conv,
                            rng.random() < 0.3, rng.choice(["normal", "normal", "high"]))
        emails.append(msg)
        email_owner[msg["id"]] = matter["id"]

    # ---- time specs: (date, non_billable)
    tspecs: list[tuple[date, bool]] = []
    if cons["bill_win"] == "force":
        tspecs.append((_rand_date(rng, *win), False))
    for _ in range(cons.get("nonbill_win", 0)):
        tspecs.append((_rand_date(rng, *win), True))
    if scen == "at_risk" and rng.random() < 0.4:
        tspecs.append((_rand_date(rng, *win), True))  # noise: non-billable time in the window
    total = max(rng.choice([3, 4, 4, 5, 5, 6, 7, 8, 10]), len(tspecs))
    while len(tspecs) < total:
        nonbill = rng.random() < 0.12
        forbid = (not nonbill) and cons["bill_win"] == "forbid"
        tspecs.append((pick(forbid), nonbill))
    for d, nonbill in tspecs:
        act = rng.choice(ACTIVITIES)
        user = resp if rng.random() < 0.7 else rng.choice(attorneys)
        qty = round(rng.choice([0.2, 0.3, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.5]) + rng.choice([0, 0, 0.1]), 2)
        rounded = math.ceil(qty * 10 - 1e-9) / 10
        billed = (not nonbill) and d < WINDOW_START and rng.random() < 0.6
        stamp = f"{d.isoformat()}T{rng.randint(15, 23)}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z"
        times.append(
            {
                "id": nid("time"),
                "etag": f'"{hexid(8)}"',
                "type": "TimeEntry",
                "date": d.isoformat(),
                "quantity_in_hours": qty,
                "rounded_quantity_in_hours": rounded,
                "price": user["rate"],
                "total": 0.0 if nonbill else round(user["rate"] * rounded, 2),
                "note": rng.choice(TIME_NOTES),
                "non_billable": nonbill,
                "billed": billed,
                "matter": {"id": matter["id"], "display_number": matter["display_number"]},
                "user": {"id": user["id"], "name": user["name"]},
                "activity_description": {"name": act[1]},
                "updated_at": stamp,
            }
        )
