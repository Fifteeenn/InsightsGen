
"""Fast tests with no network: loader, profiler, engine guard, chart rules."""
from __future__ import annotations

import io

import duckdb
import pandas as pd
import pytest

from core.charts import choose_chart, chart_payload
from core.engine import Engine, SQLGuardError, validate_sql
from core.loader import load_bytes, load_many, sanitize_identifier
from core.profiler import clean_table, detect_join_keys, profile_table, schema_text
from golden import DATA, SAMPLE_FILES


# ---------------------------------------------------------------- loader

def test_sanitize_identifier():
    assert sanitize_identifier("Sales Q1 (final).csv") == "sales_q1_final_csv"
    assert sanitize_identifier("2024 data") == "table_2024_data"
    assert sanitize_identifier("###") == "table"


def test_csv_columns_are_sql_safe():
    csv = b"Order ID,Total $,Ship Date\n1,10,2024-01-01\n"
    (t,) = load_bytes("My Orders.csv", csv)
    assert t.name == "my_orders"
    assert list(t.df.columns) == ["order_id", "total", "ship_date"]
    assert t.column_renames["Order ID"] == "order_id"


def test_excel_every_sheet_becomes_a_table():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        pd.DataFrame({"a": [1, 2]}).to_excel(xw, sheet_name="First", index=False)
        pd.DataFrame({"b": [3]}).to_excel(xw, sheet_name="Second Sheet", index=False)
        pd.DataFrame().to_excel(xw, sheet_name="Empty", index=False)
    tables = load_bytes("book.xlsx", buf.getvalue())
    assert [t.name for t in tables] == ["book_first", "book_second_sheet"]
    assert tables[1].sheet == "Second Sheet"


def test_duplicate_table_names_get_suffixes():
    tables = load_many([("a.csv", b"x\n1\n"), ("a.csv", b"x\n2\n")])
    assert [t.name for t in tables] == ["a", "a_2"]


def test_latin1_csv_loads():
    data = "name,city\nJosé,Zürich\n".encode("latin-1")
    (t,) = load_bytes("people.csv", data)
    assert t.df.loc[0, "city"] == "Zürich"


def test_unsupported_extension():
    from core.loader import UnsupportedFileError
    with pytest.raises(UnsupportedFileError):
        load_bytes("doc.pdf", b"%PDF")


# ---------------------------------------------------------------- profiler

def test_currency_and_dates_are_converted():
    # One bad value in eleven is under the 10% tolerance, so the column still converts.
    amounts = ["$1,200.50", "$3.00"] + [f"${i}.00" for i in range(8)] + ["n/a"]
    df = pd.DataFrame({"amount": amounts, "when": [f"2024-01-{d:02d}" for d in range(1, 12)], "note": list("abcdefghijk")})
    out, warnings = clean_table(df)
    assert out["amount"].tolist()[:2] == [1200.5, 3.0] and pd.isna(out["amount"].iloc[-1])
    assert pd.api.types.is_datetime64_any_dtype(out["when"])
    assert out["note"].dtype == object or pd.api.types.is_string_dtype(out["note"])
    assert any("amount" in w and "1 unparseable" in w for w in warnings)


def test_ids_are_not_converted():
    df = pd.DataFrame({"customer_id": ["C0001", "C0002"], "zip": ["02134", "90210"]})
    out, _ = clean_table(df)
    assert out["customer_id"].tolist() == ["C0001", "C0002"]


def test_join_keys_detected_on_sample_data():
    tables = load_many([(f, (DATA / f).read_bytes()) for f in SAMPLE_FILES])
    joins = {j.column: set(j.tables) for j in detect_join_keys(tables)}
    assert joins["customer_id"] == {"orders", "customers"}
    assert joins["product_id"] == {"orders", "products"}
    assert "region" in joins


def test_schema_text_is_compact_and_complete():
    tables = load_many([(f, (DATA / f).read_bytes()) for f in SAMPLE_FILES])
    profiles = []
    for t in tables:
        t.df, w = clean_table(t.df)
        profiles.append(profile_table(t, w))
    text = schema_text(profiles, detect_join_keys(tables))
    assert "TABLE orders" in text and "order_date: date" in text and "shipping_cost: number" in text
    assert "JOIN KEYS" in text
    assert len(text) < 6000   # roughly 1,500 tokens for five tables


# ---------------------------------------------------------------- engine guard

@pytest.mark.parametrize("sql", [
    "DROP TABLE orders",
    "SELECT 1; DROP TABLE orders",
    "CREATE TABLE x AS SELECT 1",
    "INSERT INTO orders VALUES (1)",
    "SELECT * FROM read_csv('C:/secret.csv')",
    "SELECT * FROM read_parquet('x.parquet')",
    "COPY orders TO 'out.csv'",
    "PRAGMA database_list",
    "",
])
def test_guard_blocks_unsafe_sql(sql):
    with pytest.raises(SQLGuardError):
        validate_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select count(*) from orders",
    "WITH t AS (SELECT 1 AS x) SELECT * FROM t",
    "SELECT * FROM orders WHERE status = 'DROP TABLE'",
    "SELECT * FROM orders -- comment with DELETE\n",
    "  (SELECT 1)  ;",
])
def test_guard_allows_safe_sql(sql):
    assert validate_sql(sql)


def test_engine_runs_and_caps_rows():
    e = Engine()
    e.register("t", pd.DataFrame({"x": range(5000)}))
    r = e.run("SELECT * FROM t ORDER BY x")
    assert r.row_count == 1000 and r.truncated
    assert r.df["x"].iloc[0] == 0   # ordering preserved through the cap


def test_engine_external_access_disabled(tmp_path):
    e = Engine()
    (tmp_path / "s.csv").write_text("a\n1\n")
    with pytest.raises((SQLGuardError, duckdb.Error)):
        e.con.execute(f"SELECT * FROM '{(tmp_path / 's.csv').as_posix()}'")


# ---------------------------------------------------------------- chart rules

def test_single_row_is_kpi():
    df = pd.DataFrame({"total_revenue": [2449852.14], "orders": [2400]})
    spec = choose_chart(df)
    assert spec.kind == "kpi"
    assert spec.kpis == [("Total Revenue", "2,449,852.14"), ("Orders", "2,400")]


def test_date_plus_measure_is_line():
    df = pd.DataFrame({"month": pd.date_range("2024-01-01", periods=6, freq="MS"), "revenue": [1, 2, 3, 4, 5, 6]})
    assert choose_chart(df).kind == "line"


def test_text_month_is_line():
    df = pd.DataFrame({"month": ["2024-01", "2024-02", "2024-03"], "revenue": [1, 2, 3]})
    spec = choose_chart(df)
    assert spec.kind == "line" and spec.x == "month"


def test_category_plus_measure_is_bar_sorted():
    df = pd.DataFrame({"segment": ["A", "B", "C"], "revenue": [5, 9, 1]})
    spec = choose_chart(df)
    assert spec.kind == "bar" and not spec.horizontal
    payload = chart_payload(df, spec)
    assert [r["segment"] for r in payload["data"]] == ["B", "A", "C"]


def test_two_categories_is_grouped_bar_and_pivots():
    df = pd.DataFrame({"region": ["E", "E", "W", "W"], "segment": ["x", "y", "x", "y"], "revenue": [1, 2, 3, 4]})
    spec = choose_chart(df)
    assert spec.kind == "bar" and spec.color == "segment"
    payload = chart_payload(df, spec)
    assert {s["key"] for s in payload["series"]} == {"x", "y"}
    assert payload["data"][0] == {"region": "E", "x": 1, "y": 2}


def test_id_and_name_columns_use_name_not_grouping():
    df = pd.DataFrame({"product_id": ["P1", "P2", "P3"], "product_name": ["A", "B", "C"], "revenue": [3, 2, 1]})
    spec = choose_chart(df)
    assert spec.kind == "bar" and spec.x == "product_name" and spec.color is None


def test_many_rows_of_records_is_table():
    df = pd.DataFrame({"order_id": [f"O{i}" for i in range(60)], "revenue": range(60)})
    assert choose_chart(df).kind == "table"


def test_payload_is_json_safe():
    import json
    df = pd.DataFrame({"name": ["A"] * 9 + ["B"], "v": range(10)})
    json.dumps(chart_payload(df, choose_chart(df)))
    df2 = pd.DataFrame({"a_very_long_category_name_indeed": ["Alpha Beta Gamma Delta"] * 1, "v": [1]})
    assert isinstance(choose_chart(pd.concat([df2] * 6, ignore_index=True).assign(v=range(6))).horizontal, bool)
