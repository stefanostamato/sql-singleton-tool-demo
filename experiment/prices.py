"""Per-model prices in US dollars per million tokens.

Sources:
- Base input and output prices, and the Sonnet 5.5 cache read price: the Claude API pricing table as
  cached in the claude-api reference docs, dated 2026-09-25.
- Cache multipliers: claude-api docs, file `shared/prompt-caching.md`, section "Economics" (read
  2026-09-29): cache reads cost about 0.1x the input price (0.05x on Claude Opus 5.5, which is $0.20
  per million), and cache writes cost 1.25x the input price for the 5-minute TTL (2x for 1 hour). This
  runner only uses the default 5-minute TTL. Haiku 4.5: read 0.1 x 1.00 = 0.10, write 1.25 x 1.00 = 1.25.
  Sonnet 5.5: write 1.25 x 2.00 = 2.50.
- Haiku 4.5 needs at least 4096 prompt tokens before anything is cached (shared/prompt-caching.md).
"""

from __future__ import annotations

PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_write_5m": 2.50, "cache_read": 0.20},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_write_5m": 1.25, "cache_read": 0.10},
}

# Models that take output_config={"effort": ...}. Haiku 4.5 has no effort parameter.
SUPPORTS_EFFORT = {"claude-sonnet-5-5"}


def cost_usd(model: str, usage: dict) -> float:
    p = PRICES[model]
    return (
        usage.get("input_tokens", 0) * p["input"]
        + usage.get("cache_creation_input_tokens", 0) * p["cache_write_5m"]
        + usage.get("cache_read_input_tokens", 0) * p["cache_read"]
        + usage.get("output_tokens", 0) * p["output"]
    ) / 1_000_000
