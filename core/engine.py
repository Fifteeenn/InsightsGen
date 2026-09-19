"""DuckDB wrapper: register DataFrames as tables, run SQL, enforce read-only.

Why DuckDB
- Exact analytical SQL (group by, joins, window functions, date_trunc) over
  pandas DataFrames with zero setup. Tens of millions of rows fit in memory.
- Cross-file questions become joins between registered tables.
- Read-only safety is enforced in three layers:
    1. connection config disables external file access (no read_csv('/etc/..'))
    2. a text guard rejects anything that is not a single SELECT/WITH
    3. results are capped at MAX_ROWS so a runaway query cannot exhaust memory
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import duckdb
import pandas as pd

MAX_ROWS = 1000

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|ATTACH|DETACH|COPY|PRAGMA|INSTALL|LOAD|"
    r"EXPORT|IMPORT|CALL|TRUNCATE|GRANT|REVOKE|VACUUM|CHECKPOINT|FORCE)\b",
    re.IGNORECASE,
)
_FORBIDDEN_FUNCS = re.compile(
    r"\b(read_csv|read_csv_auto|read_parquet|read_json|read_json_auto|read_text|read_blob|"
    r"glob|getenv|sniff_csv|read_xlsx|st_read|parquet_scan|json_scan)\s*\(",
    re.IGNORECASE,
)


class SQLGuardError(ValueError):
    """Raised when SQL is rejected before execution."""


@dataclass
class QueryResult:
    sql: str
    df: pd.DataFrame
    truncated: bool
    elapsed_ms: float

    @property
    def row_count(self) -> int:
        return len(self.df)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql.strip()


def _strip_strings(sql: str) -> str:
    """Blank out string literals so keywords inside quotes do not trip the guard."""
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def validate_sql(sql: str) -> str:
    """Return a cleaned single SELECT statement or raise SQLGuardError."""
    if not sql or not sql.strip():
        raise SQLGuardError("Empty SQL.")
    cleaned = _strip_comments(sql).rstrip(";").strip()
    if ";" in _strip_strings(cleaned):
        raise SQLGuardError("Only a single statement is allowed.")
    head = cleaned.lstrip("(").split(None, 1)[0].upper() if cleaned else ""
    if head not in ("SELECT", "WITH"):
        raise SQLGuardError(f"Only SELECT queries are allowed (got '{head}').")
    bare = _strip_strings(cleaned)
    m = _FORBIDDEN.search(bare)
    if m:
        raise SQLGuardError(f"Statement contains forbidden keyword '{m.group(1).upper()}'.")
    m = _FORBIDDEN_FUNCS.search(bare)
    if m:
        raise SQLGuardError(f"Function '{m.group(1)}' is not allowed.")
    return cleaned


class Engine:
    def __init__(self) -> None:
        self.con = duckdb.connect(
            database=":memory:",
            config={"enable_external_access": "false"},
        )
        self._tables: dict[str, pd.DataFrame] = {}

    # ---------------------------------------------------------- tables
    def register(self, name: str, df: pd.DataFrame) -> None:
        self.con.register(name, df)
        self._tables[name] = df

    def unregister(self, name: str) -> None:
        if name in self._tables:
            self.con.unregister(name)
            del self._tables[name]

    def clear(self) -> None:
        for name in list(self._tables):
            self.unregister(name)

    @property
    def tables(self) -> dict[str, pd.DataFrame]:
        return dict(self._tables)

    # ---------------------------------------------------------- queries
    def run(self, sql: str, max_rows: int = MAX_ROWS) -> QueryResult:
        cleaned = validate_sql(sql)
        t0 = time.perf_counter()
        rel = self.con.sql(cleaned)
        df = rel.limit(max_rows + 1).df() if rel is not None else pd.DataFrame()
        elapsed = (time.perf_counter() - t0) * 1000
        truncated = len(df) > max_rows
        if truncated:
            df = df.head(max_rows)
        return QueryResult(sql=cleaned, df=df, truncated=truncated, elapsed_ms=round(elapsed, 1))

    def close(self) -> None:
        self.con.close()
