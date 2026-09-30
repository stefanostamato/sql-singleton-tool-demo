"""Measure how many tokens one matter's records take, per source (free count_tokens endpoint).

    python -m experiment.size_payloads [--env-file PATH]
"""

from __future__ import annotations

import argparse
import json

import anthropic

from experiment.envfile import load_env_file
from experiment.generate import generate

MODEL = "claude-sonnet-5-5"


def compact(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def count(client: anthropic.Anthropic, text: str) -> int:
    return client.messages.count_tokens(model=MODEL, messages=[{"role": "user", "content": text}]).input_tokens


def per_matter_records(ds, matter_id: int) -> dict[str, object]:
    matter = next(m for m in ds.matters if m["id"] == matter_id)
    return {
        "matters": matter,
        "docket": ds.dockets.get(matter_id, []),
        "mail": [e for e in ds.emails if ds.email_owner[e["id"]] == matter_id],
        "billing": [t for t in ds.time_entries if t["matter"]["id"] == matter_id],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--sample", type=int, default=5)
    args = ap.parse_args()
    load_env_file(args.env_file)
    client = anthropic.Anthropic()
    baseline = count(client, "x")
    for n in (10, 40):
        ds = generate(n)
        step = max(1, n // args.sample)
        ids = [m["id"] for m in ds.matters][::step][: args.sample]
        sums = {"matters": 0, "docket": 0, "mail": 0, "billing": 0}
        for mid in ids:
            for src, val in per_matter_records(ds, mid).items():
                sums[src] += count(client, compact(val)) - baseline
        # one unrelated noise email is generated per matter: add a sampled noise email's tokens per matter
        noise = [e for e in ds.emails if ds.email_owner[e["id"]] is None][: args.sample]
        sums["mail"] += sum(count(client, compact(e)) - baseline for e in noise)
        k = len(ids)
        print(f"\nN={n} (mean over {k} sampled matters; tokens counted with {MODEL})")
        print(f"{'source':<10}{'tokens/matter':>15}")
        total = 0.0
        for src in ("matters", "docket", "mail", "billing"):
            mean = sums[src] / k
            total += mean
            print(f"{src:<10}{mean:>15.0f}")
        print(f"{'total':<10}{total:>15.0f}")


if __name__ == "__main__":
    main()
