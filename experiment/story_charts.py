"""Charts for STORY.md, drawn from results/index.json.

Run with: uv run --with matplotlib python -m experiment.story_charts
(matplotlib is not a project dependency; it is pulled in just for this script.)
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "img"

COLORS = {"tools": "#2f6fdb", "tools-lean": "#1baf7a", "sql": "#e8622c"}
NAMES = {"tools": "Tool per system", "tools-lean": "Trimmed tools", "sql": "SQL singleton"}


def load() -> list[dict]:
    rows = json.loads((ROOT / "results" / "index.json").read_text())
    for r in rows:
        r.setdefault("variant", "base")
    return rows


def style(ax, title, xlabel, ylabel):
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, which="major", axis="y", alpha=0.3)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def scatter_and_median(ax, rows, key, arm):
    pts = [(r["n_matters"], r[key]) for r in rows if r["arm"] == arm and r["outcome"] == "answered"]
    if not pts:
        return
    xs, ys = zip(*pts)
    ax.scatter(xs, ys, color=COLORS[arm], s=28, alpha=0.75, zorder=3)
    by_n = defaultdict(list)
    for x, y in pts:
        by_n[x].append(y)
    ns = sorted(by_n)
    ax.plot(ns, [median(by_n[n]) for n in ns], color=COLORS[arm], lw=2, label=NAMES[arm], zorder=2)


def chart_cost_and_context(rows):
    sonnet = [r for r in rows if r["variant"] == "base" and "sonnet" in r["model"]]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, key, title, ylabel in (
        (axes[0], "cost_usd", "What one question costs", "US dollars per run"),
        (axes[1], "context_peak_tokens", "How much the model must hold in mind", "peak prompt size, tokens"),
    ):
        for arm in ("tools", "tools-lean", "sql"):
            scatter_and_median(ax, sonnet, key, arm)
        ax.set_xscale("log", base=2)
        ax.set_yscale("log")
        ax.set_xticks([5, 10, 20, 40, 120])
        ax.set_xticklabels(["5", "10", "20", "40", "120"])
        style(ax, title, "matters in the firm (N)", ylabel)
    axes[0].legend(frameon=False, loc="upper left")
    fig.suptitle("Base task, Claude Sonnet 5.5, both phases. Dots are runs, lines join medians. Log scales.",
                 fontsize=9, color="#555", x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(OUT / "cost-and-context.png", dpi=160)
    plt.close(fig)


def chart_haiku(rows):
    haiku = [r for r in rows if r["variant"] == "base" and "haiku" in r["model"]]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    labels, vals, cols = [], [], []
    for r in sorted(haiku, key=lambda r: (r["arm"] != "sql", r["n_matters"], r["seed"])):
        labels.append(f"{NAMES[r['arm']]}\nN={r['n_matters']}, seed {r['seed']}")
        vals.append(r["f1"] or 0.0)
        cols.append(COLORS[r["arm"]])
    ax.bar(range(len(vals)), vals, color=cols)
    ax.set_xticks(range(len(vals)))
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylim(0, 1.05)
    style(ax, "The weaker model (Haiku 4.5): accuracy per run", "", "F1 score (1.0 = perfect)")
    for i, v in enumerate(vals):
        ax.text(i, v + 0.02, f"{v:.2f}", ha="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "haiku-accuracy.png", dpi=160)
    plt.close(fig)


def chart_ratio(rows):
    """Paired tools/sql cost ratio per N on Sonnet, base task, cache-isolated phase 2 runs plus phase 1."""
    sonnet = [r for r in rows if r["variant"] == "base" and "sonnet" in r["model"] and r["outcome"] == "answered"]
    by = defaultdict(dict)
    for r in sonnet:
        by[(r["n_matters"], r.get("seed"), r["rep"])][r["arm"]] = r["cost_usd"]
    pts = defaultdict(list)
    for (n, _s, _rep), arms in by.items():
        if "tools" in arms and "sql" in arms:
            pts[n].append(arms["tools"] / arms["sql"])
    ns = sorted(pts)
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.plot(ns, [median(pts[n]) for n in ns], color="#333", lw=2, marker="o")
    for n in ns:
        for v in pts[n]:
            ax.scatter([n], [v], color="#999", s=18, zorder=3)
    ax.set_xscale("log", base=2)
    ax.set_xticks(ns)
    ax.set_xticklabels([str(n) for n in ns])
    style(ax, "How many times cheaper the SQL agent was", "matters in the firm (N)", "cost ratio, tools / SQL")
    ax.axhline(10, color="#e8622c", ls="--", lw=1)
    ax.text(ns[0], 10.6, "the 10x we predicted", color="#e8622c", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "cost-ratio.png", dpi=160)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = load()
    chart_cost_and_context(rows)
    chart_haiku(rows)
    chart_ratio(rows)
    print(f"wrote {sorted(p.name for p in OUT.glob('*.png'))}")


if __name__ == "__main__":
    main()
