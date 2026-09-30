"""Sweep logic, no API calls."""

import csv
import json
from argparse import Namespace
from pathlib import Path

from experiment import sweep
from experiment.ledger import Ledger


def make_trace(rid, arm, n, rep, started, outcome="answered", cost=0.1, stage="proof", f1=1.0):
    return {
        "run_id": rid, "arm": arm, "n_matters": n, "rep": rep, "stage": stage, "pot": "proof", "model": "m",
        "outcome": outcome, "error": None if outcome == "answered" else "x", "started_at": started,
        "totals": {k: 1 for k in sweep.TOTAL_FIELDS} | {"cost_usd": cost},
        "score": {"precision": 1.0, "recall": 1.0, "f1": f1, "grouping_exact": True} if outcome == "answered" else None,
    }


def write(results: Path, t):
    (results / "traces").mkdir(parents=True, exist_ok=True)
    (results / "traces" / f"{t['run_id']}.json").write_text(json.dumps(t))


def test_is_done_skips_all_but_error(tmp_path):
    write(tmp_path, make_trace("sql-n5-r1", "sql", 5, 1, "2026-01-01T00:00:00Z"))
    write(tmp_path, make_trace("tools-n5-r1", "tools", 5, 1, "2026-01-01T00:01:00Z", outcome="error"))
    write(tmp_path, make_trace("sql-n20-r1", "sql", 20, 1, "2026-01-01T00:02:00Z", outcome="budget_stop"))
    assert sweep.is_done(tmp_path, "sql-n5-r1")
    assert not sweep.is_done(tmp_path, "tools-n5-r1")
    assert sweep.is_done(tmp_path, "sql-n20-r1")
    assert not sweep.is_done(tmp_path, "sql-n40-r1")


def test_run_stage_only_runs_missing(tmp_path):
    write(tmp_path, make_trace("sql-n5-r1", "sql", 5, 1, "2026-01-01T00:00:00Z"))
    called = []
    sweep.run_stage([("sql", 5, 1), ("tools", 5, 1)], "proof", "proof", "e", tmp_path, lambda *a: called.append(a[:3]))
    assert called == [("tools", 5, 1)]


def test_projection_math():
    total, rows = sweep.project_proof(0.10, 0.02)
    by = {(a, n, r): c for a, n, r, c in rows}
    assert abs(by[("tools", 5, 1)] - 0.025) < 1e-12
    assert abs(by[("tools", 40, 1)] - 1.6) < 1e-12
    assert by[("sql", 5, 1)] == 0.02  # never below the N=10 cost
    assert abs(by[("sql", 40, 1)] - 0.08) < 1e-12
    assert abs(total - 3.045) < 1e-9


def test_exit_3_when_projection_over_cap(tmp_path):
    write(tmp_path, make_trace("sql-n10-r1", "sql", 10, 1, "2026-01-01T00:00:00Z", cost=0.05, stage="pilot"))
    write(tmp_path, make_trace("tools-n10-r1", "tools", 10, 1, "2026-01-01T00:01:00Z", cost=0.30, stage="pilot"))
    Ledger(tmp_path / "ledger.json").add("proof", "x", "m", 0.35)
    called = []
    rc = sweep.cmd_run(Namespace(results=str(tmp_path), env_file="e"), executor=lambda *a: called.append(a))
    assert rc == sweep.EXIT_CHECKPOINT
    assert called == []  # nothing ran after the checkpoint


def test_continues_when_projection_fits(tmp_path):
    write(tmp_path, make_trace("sql-n10-r1", "sql", 10, 1, "2026-01-01T00:00:00Z", cost=0.01, stage="pilot"))
    write(tmp_path, make_trace("tools-n10-r1", "tools", 10, 1, "2026-01-01T00:01:00Z", cost=0.02, stage="pilot"))
    Ledger(tmp_path / "ledger.json").add("proof", "x", "m", 0.03)
    called = []
    sweep.cmd_run(Namespace(results=str(tmp_path), env_file="e"), executor=lambda *a: called.append(a[:3]))
    assert called[0] == ("sql", 5, 1) and len(called) >= 10


def test_fit_nonnegative_and_exact():
    a, b = sweep.fit_ab([(5, 0.05 * 5 + 0.002 * 25), (20, 0.05 * 20 + 0.002 * 400), (40, 0.05 * 40 + 0.002 * 1600)])
    assert abs(a - 0.05) < 1e-9 and abs(b - 0.002) < 1e-9
    a, b = sweep.fit_ab([(10, 1.0), (20, 1.5), (40, 2.0)])  # concave: unconstrained fit has b < 0
    assert b == 0 and a > 0
    a, b = sweep.fit_ab([(10, 0.1), (20, 0.4), (40, 1.6)])  # pure quadratic
    assert a >= 0 and b >= 0 and abs(b - 0.001) < 1e-9


def test_pick_showcase_n():
    n, _ = sweep.pick_showcase_n(0.0, 0.0004, 0.5)  # N=120 costs 5.76+0.5, too big; N=100 costs 4.0+0.5
    assert n == 100
    assert sweep.pick_showcase_n(0.0, 0.0001, 0.5)[0] == 120
    assert sweep.pick_showcase_n(0.0, 0.01, 0.5)[0] is None


def test_build_index(tmp_path):
    write(tmp_path, make_trace("tools-n5-r1", "tools", 5, 1, "2026-01-01T00:05:00Z", cost=0.2, f1=0.8))
    write(tmp_path, make_trace("sql-n5-r1", "sql", 5, 1, "2026-01-01T00:01:00Z", cost=0.1))
    write(tmp_path, make_trace("sql-n20-r1", "sql", 20, 1, "2026-01-01T00:09:00Z", outcome="budget_stop"))
    rows = sweep.build_index(tmp_path)
    assert [r["run_id"] for r in rows] == ["sql-n5-r1", "tools-n5-r1", "sql-n20-r1"]
    assert list(rows[0].keys()) == sweep.INDEX_FIELDS
    assert rows[1]["f1"] == 0.8 and rows[1]["cost_usd"] == 0.2
    assert rows[2]["f1"] is None and rows[2]["outcome"] == "budget_stop"
    assert json.loads((tmp_path / "index.json").read_text()) == rows
    csv_rows = list(csv.DictReader(open(tmp_path / "results.csv")))
    assert len(csv_rows) == 3 and csv_rows[2]["f1"] == "" and csv_rows[0]["stage"] == "proof"


def test_run_stage_only_filters_by_arm(tmp_path):
    called = []
    runs = [("sql", 5, 1), ("tools", 5, 1), ("sql", 20, 1)]
    sweep.run_stage(runs, "proof", "proof", "e", tmp_path, lambda *a: called.append(a[:3]), only="sql")
    assert called == [("sql", 5, 1), ("sql", 20, 1)]
