"""Workspace: the one object the UI talks to.

    ws = Workspace()
    ws.add_files([("orders.csv", bytes), ("targets.xlsx", bytes)])
    answer = ws.ask("total revenue by month")

ask() flow
    1. LLM plans SQL from the schema (never the data) and recent history.
    2. If the plan is a clarification, return it without running anything.
    3. Run the SQL in DuckDB. On failure, feed the error back to the LLM and
       retry (self-healing), up to MAX_ATTEMPTS total.
    4. LLM narrates the result in plain English.
    5. Record the turn so follow-up questions have context.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import duckdb
import pandas as pd

from .engine import Engine, SQLGuardError
from .llm import LLM, LLMError, SQLPlan, Turn
from .loader import LoadedTable, load_bytes
from .profiler import JoinKey, TableProfile, clean_table, detect_join_keys, profile_table, schema_text

MAX_ATTEMPTS = 3


@dataclass
class Attempt:
    sql: str
    error: str


@dataclass
class Answer:
    question: str
    title: str = ""
    narrative: str = ""
    explanation: str = ""
    sql: str | None = None
    df: pd.DataFrame | None = None
    chart_hint: str = "table"
    clarification: str | None = None
    error: str | None = None
    attempts: list[Attempt] = field(default_factory=list)   # failed tries before success
    truncated: bool = False
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None and self.clarification is None and self.df is not None

    @property
    def healed(self) -> bool:
        return self.ok and len(self.attempts) > 0


class Workspace:
    def __init__(self, llm: LLM | None = None) -> None:
        self.engine = Engine()
        self.tables: list[LoadedTable] = []
        self.profiles: list[TableProfile] = []
        self.joins: list[JoinKey] = []
        self.history: list[Turn] = []
        self._llm = llm
        self._suggestions: list[str] | None = None
        self._schema_cache: str | None = None
        self._cache: dict[tuple, Answer] = {}

    # ------------------------------------------------------------ LLM (lazy)
    @property
    def llm(self) -> LLM:
        if self._llm is None:
            self._llm = LLM()
        return self._llm

    # ------------------------------------------------------------ data
    def add_files(self, files: list[tuple[str, bytes]]) -> list[LoadedTable]:
        taken = {t.name for t in self.tables}
        added: list[LoadedTable] = []
        for filename, data in files:
            for t in load_bytes(filename, data, taken):
                t.df, warnings = clean_table(t.df)
                self.engine.register(t.name, t.df)
                self.tables.append(t)
                self.profiles.append(profile_table(t, warnings))
                added.append(t)
        self._refresh()
        return added

    def remove_table(self, name: str) -> None:
        self.engine.unregister(name)
        self.tables = [t for t in self.tables if t.name != name]
        self.profiles = [p for p in self.profiles if p.name != name]
        self._refresh()

    def clear(self) -> None:
        self.engine.clear()
        self.tables, self.profiles, self.history = [], [], []
        self._refresh()

    def _refresh(self) -> None:
        self.joins = detect_join_keys(self.tables)
        self._schema_cache = None
        self._suggestions = None
        self._cache.clear()

    @property
    def has_data(self) -> bool:
        return bool(self.tables)

    @property
    def schema(self) -> str:
        if self._schema_cache is None:
            self._schema_cache = schema_text(self.profiles, self.joins)
        return self._schema_cache

    # ------------------------------------------------------------ questions
    def suggestions(self) -> list[str]:
        if not self.has_data:
            return []
        if self._suggestions is None:
            try:
                self._suggestions = self.llm.suggest_questions(self.schema)
            except LLMError:
                self._suggestions = []
        return self._suggestions

    def _cache_key(self, question: str) -> tuple:
        last_sql = self.history[-1].sql if self.history else None
        return (question.strip().lower(), self.schema, last_sql)

    def ask(self, question: str) -> Answer:
        t0 = time.perf_counter()
        ans = Answer(question=question)
        if not self.has_data:
            ans.error = "Upload at least one CSV or Excel file first."
            return ans

        # Same question on the same data (and same conversational context) needs no model call.
        key = self._cache_key(question)
        cached = self._cache.get(key)
        if cached is not None and cached.ok:
            hit = Answer(**{**cached.__dict__, "elapsed_ms": 0.0})
            self.history.append(Turn(question=question, sql=hit.sql, answer=hit.narrative))
            return hit

        try:
            plan = self.llm.plan_sql(question, self.schema, self.history)
        except LLMError as e:
            ans.error = str(e)
            return ans

        ans.title, ans.explanation, ans.chart_hint = plan.title, plan.explanation, plan.chart_hint
        if plan.sql is None:
            ans.clarification = plan.clarification or "Could you rephrase the question? I could not map it to the data."
            ans.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            return ans

        result = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                result = self.engine.run(plan.sql)
                break
            except (SQLGuardError, duckdb.Error) as e:
                err = str(e).splitlines()[0] if str(e) else type(e).__name__
                ans.attempts.append(Attempt(sql=plan.sql, error=err))
                if attempt == MAX_ATTEMPTS - 1:
                    break
                try:
                    plan = self.llm.repair_sql(question, self.schema, plan.sql, str(e))
                except LLMError as le:
                    ans.error = str(le)
                    return ans
                if plan.sql is None:
                    ans.clarification = plan.clarification or "I could not build a valid query for that."
                    return ans
                ans.title, ans.explanation, ans.chart_hint = plan.title or ans.title, plan.explanation, plan.chart_hint

        if result is None:
            last = ans.attempts[-1] if ans.attempts else None
            ans.sql = last.sql if last else plan.sql
            ans.error = f"The query kept failing after {MAX_ATTEMPTS} attempts. Last error: {last.error if last else 'unknown'}"
            ans.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            return ans

        ans.sql, ans.df, ans.truncated = result.sql, result.df, result.truncated
        try:
            ans.narrative = self.llm.narrate(question, ans.explanation, ans.df, ans.truncated)
        except LLMError as e:
            ans.narrative = f"(Could not generate a summary: {e})"

        self.history.append(Turn(question=question, sql=ans.sql, answer=ans.narrative))
        ans.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        if len(self._cache) > 200:
            self._cache.clear()
        self._cache[key] = ans
        return ans
