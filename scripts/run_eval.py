"""Run the golden-question eval and print a results table (also written to tests/eval_results.md).

Usage: python scripts/run_eval.py [--model openai/gpt-oss-120b]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from core.llm import LLM  # noqa: E402
from core.pipeline import Workspace  # noqa: E402
from golden import DATA, SAMPLE_FILES, check, expectations  # noqa: E402

model = None
if "--model" in sys.argv:
    model = sys.argv[sys.argv.index("--model") + 1]

golden = json.loads((ROOT / "tests" / "golden_questions.json").read_text())
truth = expectations()
ws = Workspace(llm=LLM(model=model) if model else None)
ws.add_files([(f, (DATA / f).read_bytes()) for f in SAMPLE_FILES])

rows = []
for case in golden:
    ws.history.clear()
    t0 = time.perf_counter()
    a = ws.ask(case["q"])
    secs = time.perf_counter() - t0
    if a.error:
        ok, detail = False, f"error: {a.error[:80]}"
    elif a.clarification:
        ok, detail = False, f"asked: {a.clarification[:80]}"
    else:
        ok, detail = check(a.df, truth[case["expect"]])
    rows.append((case["id"], case["q"], ok, a.healed, secs, detail if not ok else ""))
    print(f"{'PASS' if ok else 'FAIL'}  {case['id']:<22} {secs:4.1f}s {'(healed)' if a.healed else '':9} {detail if not ok else ''}")

passed = sum(1 for r in rows if r[2])
healed = sum(1 for r in rows if r[3])
print(f"\n{passed}/{len(rows)} passed · {healed} self-healed · model {ws.llm.model}")

md = [f"# Eval results\n", f"Model: `{ws.llm.model}` · {passed}/{len(rows)} passed · {healed} self-healed\n",
      "| # | Question | Result | Time | Note |", "|---|---|---|---|---|"]
for i, (cid, q, ok, h, secs, detail) in enumerate(rows, 1):
    md.append(f"| {i} | {q} | {'✅' if ok else '❌'}{' 🔧' if h else ''} | {secs:.1f}s | {detail} |")
(ROOT / "tests" / "eval_results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
