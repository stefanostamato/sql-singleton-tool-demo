"""The question each task variant asks, and the system prompt with its per-run cache-isolation prefix."""

from __future__ import annotations

import secrets

SYSTEM_PROMPT = (
    "You are an assistant at Harbor & Vale LLP with read-only access to the firm's systems through the "
    "tools provided. Today is 2026-09-15. Use the tools to find the answer; do not guess. When you have "
    "the final answer, call submit_answer exactly once."
)

_INTRO = (
    "Which active litigation matters are at risk of being neglected? A matter is at risk only if all of "
    "these are true:\n"
    "1. Its status is Open and its practice area is Litigation.\n"
)
_RULE2 = "2. It has a court deadline from 2026-09-15 to 2026-10-06, inclusive.\n"
_RULE2_TEXT = (
    "2. It has a court deadline in effect from 2026-09-15 to 2026-10-06, inclusive. Later docket entries "
    "can continue or vacate an earlier deadline.\n"
)
_RULE3 = (
    "3. No email dated 2026-09-01 to 2026-09-15, inclusive, was sent to or from any of the client's "
    "contacts. Emails with opposing counsel or anyone else don't count.\n"
)
_RULE4 = (
    "4. No billable time was recorded on it dated 2026-09-01 to 2026-09-15, inclusive. Non-billable "
    "entries don't count.\n"
)
_RULE4_MATH = (
    "4. Its billable hours dated 2026-09-01 to 2026-09-15, inclusive, total less than 1.5, or its billable "
    "time dated before 2026-09-01 that is not yet billed totals more than $4,000.\n"
)
_OUTRO = (
    "List the at-risk matters by display number (like HV-2026-0012), grouped by responsible attorney, "
    "and submit them with the submit_answer tool."
)

QUESTIONS = {
    "base": _INTRO + _RULE2 + _RULE3 + _RULE4 + _OUTRO,
    "math": _INTRO + _RULE2 + _RULE3 + _RULE4_MATH + _OUTRO,
    "textdeadlines": _INTRO + _RULE2_TEXT + _RULE3 + _RULE4 + _OUTRO,
}


def new_run_tag() -> str:
    """16 random hex characters, unique per run."""
    return secrets.token_hex(8)


def system_prompt(run_tag: str) -> str:
    """The system prompt starts with a run-specific tag so no run can reuse another run's cached prefix."""
    return f"Run {run_tag}. {SYSTEM_PROMPT}"
