"""Clean tables, infer types, summarise schemas, and detect join keys.

Why this exists
- The LLM only ever sees the output of this module (never the data), so the
  quality of the schema summary directly determines the quality of the SQL.
- Real files store numbers as "$1,200" and dates as text. If we do not fix
  that, SUM() and date_trunc() fail and the model gets blamed.
- Cross-file questions only work if the model knows which columns link the
  tables, so join-key detection is surfaced both to the user and the prompt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .loader import LoadedTable

CONVERSION_THRESHOLD = 0.90   # fraction of non-null values that must parse
SAMPLE_ROWS = 3
MAX_TEXT_EXAMPLES = 4

_CURRENCY_RE = re.compile(r"^\s*[-+]?[$€£₹]?\s*[-+]?[\d,]*\.?\d+\s*%?\s*$")
_DATE_HINT_RE = re.compile(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}\s+[A-Za-z]{3}|[A-Za-z]{3}\s+\d{1,2}")


@dataclass
class ColumnProfile:
    name: str
    kind: str                      # "number" | "date" | "text" | "boolean"
    dtype: str
    null_count: int
    distinct_count: int
    min: str | None = None
    max: str | None = None
    examples: list[str] = field(default_factory=list)


@dataclass
class TableProfile:
    name: str
    display_name: str
    rows: int
    columns: list[ColumnProfile]
    sample: list[dict]
    warnings: list[str] = field(default_factory=list)


@dataclass
class JoinKey:
    column: str
    tables: list[str]
    overlap: float                 # fraction of the smaller table's keys present in the larger


# ---------------------------------------------------------------- cleaning

def _is_texty(s: pd.Series) -> bool:
    return pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)


def _try_numeric(s: pd.Series) -> pd.Series | None:
    non_null = s.dropna().astype(str)
    if non_null.empty:
        return None
    looks = non_null.map(lambda v: bool(_CURRENCY_RE.match(v)))
    if looks.mean() < CONVERSION_THRESHOLD:
        return None
    cleaned = s.astype("string").str.replace(r"[$€£₹,%\s]", "", regex=True)
    out = pd.to_numeric(cleaned, errors="coerce")
    if out.notna().sum() / max(len(non_null), 1) < CONVERSION_THRESHOLD:
        return None
    return out


def _try_datetime(s: pd.Series) -> pd.Series | None:
    non_null = s.dropna().astype(str)
    if non_null.empty:
        return None
    hint = non_null.head(50).map(lambda v: bool(_DATE_HINT_RE.search(v)))
    if hint.mean() < 0.5:
        return None
    out = pd.to_datetime(s, errors="coerce", format="mixed")
    if out.notna().sum() / len(non_null) < CONVERSION_THRESHOLD:
        return None
    return out


def clean_table(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Convert text columns that are really numbers or dates. Returns (df, warnings)."""
    df = df.copy()
    warnings: list[str] = []
    for col in df.columns:
        s = df[col]
        if not _is_texty(s):
            continue
        num = _try_numeric(s)
        if num is not None:
            coerced = int(s.notna().sum() - num.notna().sum())
            df[col] = num
            msg = f"'{col}' converted from text to number"
            if coerced:
                msg += f" ({coerced} unparseable values became null)"
            warnings.append(msg)
            continue
        dt = _try_datetime(s)
        if dt is not None:
            coerced = int(s.notna().sum() - dt.notna().sum())
            df[col] = dt
            msg = f"'{col}' converted from text to date"
            if coerced:
                msg += f" ({coerced} unparseable values became null)"
            warnings.append(msg)
    return df, warnings


# ---------------------------------------------------------------- profiling

def _kind(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date"
    if pd.api.types.is_numeric_dtype(s):
        return "number"
    return "text"


def _fmt(v) -> str:
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat() if v == v.normalize() else v.isoformat(sep=" ")
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) < 1e15 else f"{v:.3g}"
    return str(v)


def _sample_rows(df: pd.DataFrame, n: int = SAMPLE_ROWS) -> list[dict]:
    rows = []
    for _, r in df.head(n).iterrows():
        rows.append({k: (None if pd.isna(v) else _fmt(v)) for k, v in r.items()})
    return rows


def profile_table(table: LoadedTable, warnings: list[str] | None = None) -> TableProfile:
    df = table.df
    cols: list[ColumnProfile] = []
    for col in df.columns:
        s = df[col]
        kind = _kind(s)
        cp = ColumnProfile(
            name=col, kind=kind, dtype=str(s.dtype),
            null_count=int(s.isna().sum()), distinct_count=int(s.nunique(dropna=True)),
        )
        non_null = s.dropna()
        if kind in ("number", "date") and not non_null.empty:
            cp.min, cp.max = _fmt(non_null.min()), _fmt(non_null.max())
        elif kind == "text" and not non_null.empty:
            cp.examples = [str(v) for v in non_null.value_counts().head(MAX_TEXT_EXAMPLES).index]
        cols.append(cp)
    warn = list(warnings or [])
    if table.column_renames:
        shown = ", ".join(f"'{a}' → '{b}'" for a, b in list(table.column_renames.items())[:5])
        warn.append(f"Columns renamed to SQL-safe names: {shown}")
    return TableProfile(
        name=table.name, display_name=table.display_name, rows=len(df),
        columns=cols, sample=_sample_rows(df), warnings=warn,
    )


def detect_join_keys(tables: list[LoadedTable]) -> list[JoinKey]:
    """Columns that share a name across tables and whose values actually overlap."""
    by_col: dict[str, list[LoadedTable]] = {}
    for t in tables:
        for col in t.df.columns:
            by_col.setdefault(col, []).append(t)
    keys: list[JoinKey] = []
    for col, ts in by_col.items():
        if len(ts) < 2:
            continue
        sets = [set(t.df[col].dropna().astype(str)) for t in ts]
        sets = [s for s in sets if s]
        if len(sets) < 2:
            continue
        smallest = min(sets, key=len)
        union_others = set().union(*[s for s in sets if s is not smallest])
        overlap = len(smallest & union_others) / len(smallest)
        if overlap >= 0.5:
            keys.append(JoinKey(column=col, tables=[t.name for t in ts], overlap=round(overlap, 2)))
    return sorted(keys, key=lambda k: -k.overlap)


# ---------------------------------------------------------------- prompt text

def schema_text(profiles: list[TableProfile], joins: list[JoinKey]) -> str:
    """Compact schema description for the LLM prompt. Roughly 60-120 tokens per table."""
    lines: list[str] = []
    for p in profiles:
        lines.append(f"TABLE {p.name}  ({p.rows:,} rows)")
        for c in p.columns:
            detail = ""
            if c.kind in ("number", "date") and c.min is not None:
                detail = f" range {c.min} to {c.max}"
            elif c.examples:
                detail = " e.g. " + ", ".join(repr(e) for e in c.examples)
            nulls = f", {c.null_count} nulls" if c.null_count else ""
            lines.append(f"  - {c.name}: {c.kind}{detail}{nulls}")
        if p.sample:
            lines.append("  sample rows: " + " | ".join(
                ", ".join(f"{k}={v}" for k, v in row.items()) for row in p.sample[:2]
            ))
        lines.append("")
    if joins:
        lines.append("JOIN KEYS (columns shared across tables):")
        for j in joins:
            lines.append(f"  - {j.column}: {' = '.join(f'{t}.{j.column}' for t in j.tables)}")
    return "\n".join(lines).strip()
