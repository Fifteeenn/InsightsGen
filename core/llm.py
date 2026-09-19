"""Groq-hosted open-weight LLM calls. Three jobs, three prompts.

1. plan_sql       question + schema (+ history)  -> {sql, chart_hint, explanation, clarification, title}
2. repair_sql     failed sql + DuckDB error      -> corrected plan (the self-healing loop)
3. narrate        question + sql + result rows   -> 1-3 plain-English sentences
plus suggest_questions(schema) for the cold-start experience.

The model never receives raw data. It receives the schema summary (column
names, types, ranges, a couple of sample rows) and, for narration, the result
of the query it wrote, which is at most a few dozen rows.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import pandas as pd
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

# Open-weight models served by Groq (Sept 2026). gpt-oss-120b is Apache-2.0 licensed
# and the strongest at SQL; qwen/qwen3.8-27b is a good cheaper fallback.
DEFAULT_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODEL = "qwen/qwen3.8-27b"
CHART_HINTS = {"line", "bar", "kpi", "table", "scatter"}
HISTORY_TURNS = 4
NARRATE_MAX_ROWS = 25


class LLMError(RuntimeError):
    pass


@dataclass
class SQLPlan:
    sql: str | None
    chart_hint: str = "table"
    explanation: str = ""
    clarification: str | None = None
    title: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class Turn:
    question: str
    sql: str | None
    answer: str


SQL_SYSTEM = """You are a senior data analyst who writes DuckDB SQL to answer questions about tables the user uploaded.

{schema}

Respond with ONLY a JSON object with exactly these keys:
  "sql": a single DuckDB SELECT statement, or null if you must ask for clarification
  "chart_hint": one of "line" (trend over time), "bar" (compare categories), "kpi" (a single number), "table" (a list of records), "scatter" (two numeric measures)
  "explanation": one sentence stating what the query computes and any assumption you made
  "clarification": null, or ONE short question if the request is genuinely ambiguous
  "title": a 3-6 word title for the result

Rules:
- Use only the tables and columns listed above. Column and table names are case-sensitive and already SQL-safe.
- Combine tables using the JOIN KEYS listed. Prefer JOIN ... USING (key) when the key name matches.
- For trends over time use date_trunc('month', date_col) (or 'week'/'day'/'year' if asked) and ORDER BY that date ascending.
- For "top N" use ORDER BY metric DESC LIMIT N. For comparisons return one row per category.
- Give every aggregate a readable snake_case alias (total_revenue, avg_order_value, order_count).
- Round money values with ROUND(x, 2). Use COUNT(*) for counts and COUNT(DISTINCT ...) for unique counts.
- Return only the columns needed. Add LIMIT 200 unless the user asks for everything.
- Text comparisons: match the exact casing seen in the examples; if unsure use ILIKE.
- Only ask for clarification when a term could map to several columns or tables and no sensible default exists. If a reasonable default exists, use it and state it in "explanation".
- If the question cannot be answered from these tables at all, set sql to null and explain why in "clarification".
- Never modify data. Never reference files. Output JSON only, no markdown fences."""

REPAIR_USER = """The SQL you wrote failed. Fix it and return the same JSON object.

Question: {question}

Failed SQL:
{sql}

DuckDB error:
{error}

Common causes: a column that does not exist in that table (check the schema), a type mismatch (cast with ::DATE or ::DOUBLE), a missing GROUP BY column, or a non-DuckDB function. Return JSON only."""

NARRATE_SYSTEM = """You explain query results to a business user in plain English.
Write 1-3 short sentences that directly answer the question using ONLY the numbers in the result.
Lead with the answer. Mention the most important figures with units or currency formatting where obvious (e.g. 2,449,852.14).
If the result has many rows, summarise the top items and the overall pattern rather than listing everything.
If the result is empty, say that no rows matched and suggest what to check.
Do not mention SQL, tables, or columns by their technical names. No markdown, no bullet points."""

SUGGEST_SYSTEM = """You are a data analyst looking at a new dataset for the first time.

{schema}

Propose 5 analytical questions a business user would want answered from these tables. Requirements:
- Each must be answerable with a SQL query over the tables above.
- Mix types: at least one total or count, one trend over time (only if a date column exists), one comparison across a category, and at least one that combines two tables using a join key (only if join keys exist).
- Plain English, under 14 words each, no technical column names when a plain term exists.
Respond with ONLY a JSON object: {{"questions": ["...", "...", "...", "...", "..."]}}"""


class LLM:
    """Two models on purpose: the planner (SQL) is the strongest model; narration and
    question suggestions go to a smaller model. Groq rate limits are per model, so
    this keeps a burst of questions from stalling on one quota, and the small model
    is plenty for summarising a result table in English."""

    def __init__(self, api_key: str | None = None, model: str | None = None, narrator_model: str | None = None) -> None:
        key = api_key or os.getenv("GROQ_API_KEY")
        if not key or key.startswith("your_"):
            raise LLMError("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")
        self.client = Groq(api_key=key)
        self.model = model or os.getenv("GROQ_MODEL") or DEFAULT_MODEL
        self.narrator_model = narrator_model or os.getenv("GROQ_NARRATOR_MODEL") or FALLBACK_MODEL

    # ------------------------------------------------------------ raw call
    def _chat(self, messages: list[dict], json_mode: bool, temperature: float = 0.0,
              max_tokens: int = 1024, model: str | None = None) -> str:
        model = model or self.model
        kwargs = dict(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if "gpt-oss" in model:
            # Reasoning model: low effort is plenty for SQL and keeps latency down.
            kwargs["reasoning_effort"] = "low"
        try:
            resp = self.client.chat.completions.create(**kwargs)
        except Exception as e:  # groq raises several subclasses; surface one clean message
            raise LLMError(f"Groq request failed: {e}") from e
        return resp.choices[0].message.content or ""

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                return json.loads(m.group(0))
            raise LLMError(f"Model did not return valid JSON: {text[:200]}")

    @staticmethod
    def _to_plan(data: dict) -> SQLPlan:
        sql = data.get("sql")
        if isinstance(sql, str) and not sql.strip():
            sql = None
        hint = str(data.get("chart_hint") or "table").lower()
        if hint not in CHART_HINTS:
            hint = "table"
        clar = data.get("clarification")
        if isinstance(clar, str) and not clar.strip():
            clar = None
        return SQLPlan(
            sql=sql,
            chart_hint=hint,
            explanation=str(data.get("explanation") or ""),
            clarification=clar,
            title=str(data.get("title") or ""),
            raw=data,
        )

    # ------------------------------------------------------------ jobs
    def plan_sql(self, question: str, schema: str, history: list[Turn] | None = None) -> SQLPlan:
        messages = [{"role": "system", "content": SQL_SYSTEM.format(schema=schema)}]
        for t in (history or [])[-HISTORY_TURNS:]:
            messages.append({"role": "user", "content": t.question})
            prior = {"sql": t.sql, "explanation": t.answer[:200]}
            messages.append({"role": "assistant", "content": json.dumps(prior)})
        messages.append({"role": "user", "content": question})
        return self._to_plan(self._parse_json(self._chat(messages, json_mode=True)))

    def repair_sql(self, question: str, schema: str, failed_sql: str, error: str) -> SQLPlan:
        messages = [
            {"role": "system", "content": SQL_SYSTEM.format(schema=schema)},
            {"role": "user", "content": REPAIR_USER.format(question=question, sql=failed_sql, error=error[:600])},
        ]
        return self._to_plan(self._parse_json(self._chat(messages, json_mode=True)))

    @staticmethod
    def _digest(df: pd.DataFrame) -> str:
        """Whole-result summary so the narrator is never fooled by a truncated preview."""
        lines = [f"Total rows: {len(df)}"]
        for col in df.columns:
            s = df[col]
            if pd.api.types.is_numeric_dtype(s):
                lines.append(f"  {col}: min {s.min():,.2f}, max {s.max():,.2f}, mean {s.mean():,.2f}, sum {s.sum():,.2f}")
            elif pd.api.types.is_datetime64_any_dtype(s):
                lines.append(f"  {col}: from {s.min()} to {s.max()}")
            else:
                vals = s.dropna().astype(str).unique()
                shown = ", ".join(vals[:12]) + (", ..." if len(vals) > 12 else "")
                lines.append(f"  {col}: {len(vals)} distinct values ({shown})")
        return "\n".join(lines)

    def narrate(self, question: str, explanation: str, df: pd.DataFrame, truncated: bool = False) -> str:
        preview = df.head(NARRATE_MAX_ROWS)
        body = preview.to_csv(index=False) if not preview.empty else "(empty result)"
        note = ""
        if len(df) > NARRATE_MAX_ROWS:
            note = (f"\n\nOnly the first {NARRATE_MAX_ROWS} of {len(df)} rows are shown above. "
                    f"Use this summary of ALL rows for any claim about totals, counts, or which values exist:\n"
                    + self._digest(df))
        if truncated:
            note += "\n(The result was capped at the row limit.)"
        user = f"Question: {question}\nWhat the query computed: {explanation}\n\nResult (CSV):\n{body}{note}"
        messages = [
            {"role": "system", "content": NARRATE_SYSTEM},
            {"role": "user", "content": user},
        ]
        return self._chat(messages, json_mode=False, temperature=0.2, max_tokens=450, model=self.narrator_model).strip()

    def suggest_questions(self, schema: str) -> list[str]:
        messages = [
            {"role": "system", "content": SUGGEST_SYSTEM.format(schema=schema)},
            {"role": "user", "content": "Suggest questions."},
        ]
        data = self._parse_json(self._chat(messages, json_mode=True, temperature=0.4, model=self.narrator_model))
        qs = data.get("questions") or []
        return [str(q).strip() for q in qs if str(q).strip()][:5]
