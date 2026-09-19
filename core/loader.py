"""Turn uploaded CSV / Excel files into named pandas DataFrames.

Design notes
- One DataFrame per CSV file, one per Excel sheet. Multi-sheet workbooks are a
  common real-world case that naive loaders miss.
- Table and column names are normalised to snake_case identifiers so the LLM
  can write SQL without worrying about quoting. Original names are kept on the
  LoadedTable for display.
- CSV encoding is guessed by trying the common encodings in order. Real files
  from Excel exports are often latin-1 or utf-8 with a BOM.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

CSV_ENCODINGS = ("utf-8", "utf-8-sig", "latin-1", "cp1252")
EXCEL_EXTENSIONS = {".xlsx", ".xlsm", ".xls"}
CSV_EXTENSIONS = {".csv", ".tsv", ".txt"}


class UnsupportedFileError(ValueError):
    pass


@dataclass
class LoadedTable:
    name: str                       # SQL identifier, e.g. "sales_q1_north"
    source_file: str                # original filename
    sheet: str | None               # Excel sheet name, None for CSV
    df: pd.DataFrame
    column_renames: dict[str, str] = field(default_factory=dict)  # original -> sanitized

    @property
    def display_name(self) -> str:
        return f"{self.source_file} / {self.sheet}" if self.sheet else self.source_file


def sanitize_identifier(raw: str, fallback: str = "table") -> str:
    """Lowercase snake_case identifier safe for unquoted SQL."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(raw)).strip("_").lower()
    s = re.sub(r"_+", "_", s)
    if not s:
        s = fallback
    if s[0].isdigit():
        s = f"{fallback}_{s}"
    return s


def _unique(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    i = 2
    while f"{name}_{i}" in taken:
        i += 1
    return f"{name}_{i}"


def _sanitize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    taken: set[str] = set()
    renames: dict[str, str] = {}
    new_cols = []
    for i, col in enumerate(df.columns):
        original = str(col)
        clean = _unique(sanitize_identifier(original, fallback=f"col{i}"), taken)
        taken.add(clean)
        new_cols.append(clean)
        if clean != original:
            renames[original] = clean
    df = df.copy()
    df.columns = new_cols
    return df, renames


def _read_csv_bytes(data: bytes, filename: str) -> pd.DataFrame:
    sep = "\t" if filename.lower().endswith(".tsv") else None  # None -> sniff
    last_err: Exception | None = None
    for enc in CSV_ENCODINGS:
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc, sep=sep, engine="python")
        except UnicodeDecodeError as e:
            last_err = e
            continue
    raise UnsupportedFileError(f"Could not decode {filename}: {last_err}")


def _drop_empty(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
    # Drop unnamed index columns that Excel/pandas round-trips leave behind.
    unnamed = [c for c in df.columns if str(c).startswith("Unnamed:") and df[c].isna().all()]
    return df.drop(columns=unnamed)


def load_bytes(filename: str, data: bytes, taken_names: set[str] | None = None) -> list[LoadedTable]:
    """Load one uploaded file (as bytes) into one or more tables."""
    taken = taken_names if taken_names is not None else set()
    ext = Path(filename).suffix.lower()
    stem = sanitize_identifier(Path(filename).stem)
    tables: list[LoadedTable] = []

    if ext in CSV_EXTENSIONS:
        df = _drop_empty(_read_csv_bytes(data, filename))
        df, renames = _sanitize_columns(df)
        name = _unique(stem, taken)
        taken.add(name)
        tables.append(LoadedTable(name, filename, None, df, renames))

    elif ext in EXCEL_EXTENSIONS:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
        non_empty = {s: d for s, d in sheets.items() if not d.dropna(how="all").empty}
        for sheet, df in non_empty.items():
            df = _drop_empty(df)
            df, renames = _sanitize_columns(df)
            # Single-sheet workbook keeps the file name; multi-sheet gets file_sheet.
            base = stem if len(non_empty) == 1 else f"{stem}_{sanitize_identifier(sheet)}"
            name = _unique(base, taken)
            taken.add(name)
            tables.append(LoadedTable(name, filename, sheet, df, renames))
        if not tables:
            raise UnsupportedFileError(f"{filename} has no non-empty sheets")
    else:
        raise UnsupportedFileError(f"Unsupported file type: {ext or filename}. Use CSV or Excel.")

    return tables


def load_path(path: str | Path, taken_names: set[str] | None = None) -> list[LoadedTable]:
    p = Path(path)
    return load_bytes(p.name, p.read_bytes(), taken_names)


def load_many(files: list[tuple[str, bytes]]) -> list[LoadedTable]:
    """Load several (filename, bytes) pairs with globally unique table names."""
    taken: set[str] = set()
    out: list[LoadedTable] = []
    for filename, data in files:
        out.extend(load_bytes(filename, data, taken))
    return out
