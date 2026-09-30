"""Phase 2 writeup blocks: number formatting and that WRITEUP.md matches what the generators produce."""

import json
from pathlib import Path

from experiment import robustness_tables as rt
from experiment import tldr, writeup_tables

ROOT = Path(__file__).resolve().parent.parent


def test_sig2_gives_two_significant_figures():
    assert rt.sig2(4.53) == "4.5"
    assert rt.sig2(2.0) == "2.0"
    assert rt.sig2(0.6183) == "0.62"
    assert rt.sig2(12.7) == "13"
    assert rt.sig2(106.9) == "110"
    assert rt.sig2(1069) == "1,100"
    assert writeup_tables.sig2(106.9) == "110" and writeup_tables.sig2(0.6183) == "0.62"


def test_writeup_blocks_regenerate_with_no_diff():
    rows = json.loads((ROOT / "results" / "index.json").read_text())
    text = (ROOT / "WRITEUP.md").read_text()
    out = writeup_tables.rewrite(text, writeup_tables.build_block(rows))
    out = writeup_tables.rewrite(out, rt.build_block(rows), "robust")
    out = writeup_tables.rewrite(out, tldr.build_block(rows), "tldr")
    assert out == text


def test_writeup_has_no_em_dashes():
    assert "—" not in (ROOT / "WRITEUP.md").read_text()


def test_errors_by_trap_says_no_answer_when_there_is_no_score():
    from experiment import robustness_tables as rt

    assert rt.errors_text("math-tools-n120-s11-sonnet") == "n/a (no answer)"
    assert "false negatives" in rt.errors_text("base-tools-n40-s11-haiku")
