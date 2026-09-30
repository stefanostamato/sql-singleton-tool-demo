"""Trimmed records for the tools-lean arm: each record keeps exactly the columns the SQL tables hold.

This is the best case for per-system tools that let the caller pick fields (like Clio `fields` or Graph
`$select`). Two sources hold a child table in SQL, so their records carry it as a nested list:
matters carry `client_contacts` ([{name, email}]) and mail carries `participants` ([{email, role}]).
"""

from __future__ import annotations

from datetime import datetime

MATTER_COLUMNS = [
    "matter_id", "display_number", "description", "status", "practice_area", "responsible_attorney",
    "responsible_attorney_email", "client_id", "client_name", "open_date", "case_number",
]
DOCKET_COLUMNS = ["entry_id", "matter_id", "case_number", "entry_number", "date_filed", "description"]
DOCKET_DEADLINE_COLUMNS = ["deadline_date", "deadline_type"]  # absent in the textdeadlines variant
EMAIL_COLUMNS = [
    "message_id", "conversation_id", "subject", "received_at", "received_date", "from_email", "from_name",
    "body_preview",
]
TIME_COLUMNS = ["entry_id", "matter_id", "date", "hours", "non_billable", "billed", "rate", "total", "note", "user_name"]


def lean_matter(m: dict) -> dict:
    return {
        "matter_id": m["id"],
        "display_number": m["display_number"],
        "description": m["description"],
        "status": m["status"],
        "practice_area": m["practice_area"]["name"],
        "responsible_attorney": m["responsible_attorney"]["name"],
        "responsible_attorney_email": m["responsible_attorney"]["email"],
        "client_id": m["client"]["id"],
        "client_name": m["client"]["name"],
        "open_date": m["open_date"],
        "case_number": (m.get("court") or {}).get("case_number"),
        "client_contacts": [{"name": c["name"], "email": c["email"]} for c in m["client"]["contacts"]],
    }


def lean_docket(e: dict, matter_id: int, deadline_columns: bool = True) -> dict:
    out = {
        "entry_id": e["id"],
        "matter_id": matter_id,
        "case_number": e["case_number"],
        "entry_number": e["entry_number"],
        "date_filed": e["date_filed"],
        "description": e["description"],
    }
    if deadline_columns:
        out["deadline_date"] = e.get("deadline_date")
        out["deadline_type"] = e.get("deadline_type")
    return out


def lean_email(e: dict) -> dict:
    received = e["receivedDateTime"].removesuffix("Z")
    parts = [{"email": e["from"]["emailAddress"]["address"], "role": "from"}]
    parts += [{"email": r["emailAddress"]["address"], "role": "to"} for r in e["toRecipients"]]
    parts += [{"email": r["emailAddress"]["address"], "role": "cc"} for r in e["ccRecipients"]]
    return {
        "message_id": e["id"],
        "conversation_id": e["conversationId"],
        "subject": e["subject"],
        "received_at": datetime.fromisoformat(received).isoformat(),
        "received_date": e["receivedDateTime"][:10],
        "from_email": e["from"]["emailAddress"]["address"],
        "from_name": e["from"]["emailAddress"]["name"],
        "body_preview": e["bodyPreview"],
        "participants": parts,
    }


def lean_time(t: dict) -> dict:
    return {
        "entry_id": t["id"],
        "matter_id": t["matter"]["id"],
        "date": t["date"],
        "hours": t["quantity_in_hours"],
        "non_billable": t["non_billable"],
        "billed": t["billed"],
        "rate": t["price"],
        "total": t["total"],
        "note": t["note"],
        "user_name": t["user"]["name"],
    }
