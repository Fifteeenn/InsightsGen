"""Golden-question eval: the full pipeline (Groq + DuckDB) against pandas ground truth.

Skipped automatically when GROQ_API_KEY is not set, so unit tests stay offline.
Run:  pytest tests/test_eval.py -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from core.pipeline import Workspace
from golden import DATA, SAMPLE_FILES, check, expectations

load_dotenv()
GOLDEN = json.loads((Path(__file__).parent / "golden_questions.json").read_text())

pytestmark = pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API_KEY", "").startswith("your_"),
    reason="GROQ_API_KEY not set",
)


@pytest.fixture(scope="module")
def ws() -> Workspace:
    w = Workspace()
    w.add_files([(f, (DATA / f).read_bytes()) for f in SAMPLE_FILES])
    return w


@pytest.fixture(scope="module")
def truth() -> dict:
    return expectations()


@pytest.mark.parametrize("case", GOLDEN, ids=[c["id"] for c in GOLDEN])
def test_golden_question(ws: Workspace, truth: dict, case: dict):
    ws.history.clear()                      # each golden question stands alone
    a = ws.ask(case["q"])
    assert a.error is None, f"pipeline error: {a.error}\nattempts: {[x.error for x in a.attempts]}"
    assert a.clarification is None, f"unexpected clarification: {a.clarification}"
    ok, detail = check(a.df, truth[case["expect"]])
    assert ok, f"{detail}\nSQL: {a.sql}"
