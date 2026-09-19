"""Reference answers for the golden questions, computed independently with pandas.

These deliberately do NOT use DuckDB or the LLM: they are the ground truth the
pipeline is measured against. Each expectation is one of
  {"value": float}                              a single number must appear in the result
  {"label": str, "value": float}                a row must contain both the label and the number
  {"rows": [{"label": str, "value": float}]}    every pair must appear in some row
  {"first_label": str}                          the first row must contain this label
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "sample_data"
SAMPLE_FILES = ["orders.csv", "customers.csv", "products.csv", "regional_targets.xlsx"]


def _load() -> dict[str, pd.DataFrame]:
    orders = pd.read_csv(DATA / "orders.csv")
    orders["order_date"] = pd.to_datetime(orders["order_date"])
    orders["shipping_cost"] = orders["shipping_cost"].str.replace(r"[$,]", "", regex=True).astype(float)
    customers = pd.read_csv(DATA / "customers.csv")
    products = pd.read_csv(DATA / "products.csv")
    targets = pd.read_excel(DATA / "regional_targets.xlsx", sheet_name="Targets")
    targets["month"] = pd.to_datetime(targets["month"])
    headcount = pd.read_excel(DATA / "regional_targets.xlsx", sheet_name="Headcount")
    return dict(orders=orders, customers=customers, products=products, targets=targets, headcount=headcount)


def expectations() -> dict[str, dict]:
    d = _load()
    o, c, p, t, h = d["orders"], d["customers"], d["products"], d["targets"], d["headcount"]
    oc = o.merge(c, on="customer_id")
    op = o.merge(p, on="product_id")

    seg = oc.groupby("segment")["revenue"].sum().sort_values(ascending=False)
    reg = oc.groupby("region")["revenue"].sum()
    cat = op.groupby("category")["revenue"].sum()
    prod = op.groupby("product_name")["revenue"].sum().sort_values(ascending=False)
    o24 = o[o["order_date"].dt.year == 2024]
    monthly = o24.groupby(o24["order_date"].dt.month)["revenue"].sum()
    disc = op.groupby("category")["discount"].mean()

    return {
        "total_revenue":       {"value": float(o["revenue"].sum())},
        "order_count":         {"value": float(len(o))},
        "unique_customers":    {"value": float(o["customer_id"].nunique())},
        "avg_order_value":     {"value": float(o["revenue"].mean())},
        "returned_orders":     {"value": float((o["status"] == "Returned").sum())},
        "revenue_2024":        {"value": float(o24["revenue"].sum())},
        "top_segment":         {"first_label": seg.index[0], "value": float(seg.iloc[0])},
        "revenue_by_region":   {"rows": [{"label": k, "value": float(v)} for k, v in reg.items()]},
        "revenue_by_category": {"rows": [{"label": k, "value": float(v)} for k, v in cat.items()]},
        "top_product":         {"first_label": prod.index[0], "value": float(prod.iloc[0])},
        "monthly_2024":        {"rows": [{"label": None, "value": float(v)} for v in monthly.values], "row_count": 12},
        "north_target_2024":   {"value": float(t[(t["region"] == "North") & (t["month"].dt.year == 2024)]["target_revenue"].sum())},
        "most_reps":           {"first_label": h.sort_values("sales_reps", ascending=False)["region"].iloc[0]},
        "avg_discount_by_cat": {"rows": [{"label": k, "value": float(v)} for k, v in disc.items()]},
        "shipping_total":      {"value": float(o["shipping_cost"].sum())},
    }


# ---------------------------------------------------------------- checking

def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.011, abs(b) * 1e-4)


def _numeric_cells(row: pd.Series) -> list[float]:
    out = []
    for v in row:
        if isinstance(v, (int, float)) and not isinstance(v, bool) and pd.notna(v):
            out.append(float(v))
    return out


def _text_cells(row: pd.Series) -> list[str]:
    return [str(v).strip().lower() for v in row if pd.notna(v)]


def check(df: pd.DataFrame, exp: dict) -> tuple[bool, str]:
    """Return (passed, detail)."""
    if df is None or df.empty:
        return False, "empty result"
    if "row_count" in exp and len(df) != exp["row_count"]:
        return False, f"expected {exp['row_count']} rows, got {len(df)}"
    if "first_label" in exp:
        if exp["first_label"].lower() not in _text_cells(df.iloc[0]):
            return False, f"first row {df.iloc[0].tolist()} lacks '{exp['first_label']}'"
        if "value" in exp and not any(_close(x, exp["value"]) for x in _numeric_cells(df.iloc[0])):
            return False, f"first row lacks value {exp['value']:.2f}"
        return True, "ok"
    if "rows" in exp:
        for want in exp["rows"]:
            hit = False
            for _, row in df.iterrows():
                label_ok = want["label"] is None or want["label"].lower() in _text_cells(row)
                if label_ok and any(_close(x, want["value"]) for x in _numeric_cells(row)):
                    hit = True
                    break
            if not hit:
                return False, f"no row with {want['label']} = {want['value']:.4f}"
        return True, "ok"
    if "value" in exp:
        for _, row in df.iterrows():
            if any(_close(x, exp["value"]) for x in _numeric_cells(row)):
                return True, "ok"
        return False, f"value {exp['value']:.2f} not found in {df.head(3).to_dict(orient='records')}"
    return False, "unknown expectation"
