"""Generate a small, realistic, linked sample dataset for demos and tests.

Files produced in sample_data/:
  customers.csv         200 customers with segment and region
  products.csv          40 products with category and prices
  orders.csv            2,400 orders linking customers and products
  regional_targets.xlsx two sheets: Targets (region x month) and Headcount

The data is deterministic (fixed seed) so the eval suite has stable answers.
A few deliberate imperfections are included to exercise the profiler:
  - shipping_cost is stored as text with a currency symbol ("$12.50")
  - some discount values are missing
  - order_date is an ISO string, not a native date
"""
from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

SEED = 42
OUT = Path(__file__).resolve().parent.parent / "sample_data"

REGIONS = ["North", "South", "East", "West"]
SEGMENTS = ["Consumer", "Corporate", "Small Business"]
CITIES = {
    "North": ["Seattle", "Portland", "Minneapolis"],
    "South": ["Austin", "Houston", "Miami"],
    "East": ["New York", "Boston", "Philadelphia"],
    "West": ["Los Angeles", "San Francisco", "Denver"],
}
CATEGORIES = {
    "Electronics": ["Laptop", "Monitor", "Keyboard", "Headphones", "Webcam"],
    "Furniture": ["Desk", "Office Chair", "Bookshelf", "Filing Cabinet"],
    "Office Supplies": ["Printer Paper", "Stapler", "Notebook", "Pen Set", "Binder"],
    "Software": ["Antivirus", "Office Suite", "Design Tool", "CRM License"],
}
FIRST = ["Ava", "Liam", "Noah", "Emma", "Mia", "Ethan", "Zoe", "Lucas", "Aria", "Leo",
         "Nora", "Owen", "Ivy", "Kai", "Maya", "Eli", "Ruby", "Max", "Lily", "Finn"]
LAST = ["Patel", "Garcia", "Chen", "Okafor", "Novak", "Silva", "Kim", "Rossi",
        "Müller", "Haddad", "Nguyen", "Brown", "Singh", "Dubois", "Tanaka"]


def make_customers(rng: random.Random) -> pd.DataFrame:
    rows = []
    for i in range(1, 201):
        region = rng.choice(REGIONS)
        rows.append({
            "customer_id": f"C{i:04d}",
            "customer_name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
            "segment": rng.choices(SEGMENTS, weights=[5, 3, 2])[0],
            "region": region,
            "city": rng.choice(CITIES[region]),
            "signup_date": (pd.Timestamp("2022-01-01") + pd.Timedelta(days=rng.randint(0, 700))).date().isoformat(),
        })
    return pd.DataFrame(rows)


def make_products(rng: random.Random) -> pd.DataFrame:
    rows = []
    pid = 1
    price_ranges = {
        "Electronics": (80, 1500),
        "Furniture": (60, 900),
        "Office Supplies": (3, 40),
        "Software": (50, 600),
    }
    for category, names in CATEGORIES.items():
        for name in names:
            for variant in ("Standard", "Pro"):
                lo, hi = price_ranges[category]
                list_price = round(rng.uniform(lo, hi), 2)
                rows.append({
                    "product_id": f"P{pid:03d}",
                    "product_name": f"{name} {variant}",
                    "category": category,
                    "unit_cost": round(list_price * rng.uniform(0.45, 0.7), 2),
                    "list_price": list_price,
                })
                pid += 1
    return pd.DataFrame(rows)


def make_orders(rng: random.Random, customers: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    rows = []
    start = pd.Timestamp("2024-01-01")
    n_days = 546  # through 2025-06-30
    for i in range(1, 2401):
        cust = customers.iloc[rng.randrange(len(customers))]
        prod = products.iloc[rng.randrange(len(products))]
        # Seasonality: more orders late in the year, gentle upward trend.
        day = int(min(n_days - 1, abs(rng.gauss(n_days * 0.6, n_days * 0.3))))
        order_date = start + pd.Timedelta(days=day)
        qty = rng.choices([1, 2, 3, 4, 5, 10], weights=[40, 25, 15, 8, 7, 5])[0]
        discount = rng.choice([0, 0, 0, 0.05, 0.1, 0.15, 0.2, None])
        unit_price = prod["list_price"]
        revenue = round(qty * unit_price * (1 - (discount or 0)), 2)
        ship = round(rng.uniform(4, 45), 2)
        rows.append({
            "order_id": f"O{i:05d}",
            "order_date": order_date.date().isoformat(),
            "customer_id": cust["customer_id"],
            "product_id": prod["product_id"],
            "quantity": qty,
            "unit_price": unit_price,
            "discount": discount,
            "revenue": revenue,
            "shipping_cost": f"${ship:,.2f}",
            "status": rng.choices(["Delivered", "Shipped", "Returned", "Cancelled"], weights=[80, 10, 6, 4])[0],
        })
    return pd.DataFrame(rows).sort_values("order_date").reset_index(drop=True)


def make_targets(rng: random.Random) -> tuple[pd.DataFrame, pd.DataFrame]:
    months = pd.period_range("2024-01", "2025-06", freq="M")
    rows = []
    # Targets sit near the actual run-rate (about 34K per region-month on average)
    # and grow slowly, so early months miss and later months beat the target.
    for region in REGIONS:
        base = rng.uniform(22_000, 34_000)
        for m in months:
            growth = 1 + 0.015 * (m.ordinal - months[0].ordinal)
            rows.append({
                "region": region,
                "month": m.to_timestamp().date().isoformat(),
                "target_revenue": round(base * growth * rng.uniform(0.9, 1.1), 2),
            })
    targets = pd.DataFrame(rows)
    headcount = pd.DataFrame({
        "region": REGIONS,
        "sales_reps": [rng.randint(4, 12) for _ in REGIONS],
        "regional_manager": [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in REGIONS],
    })
    return targets, headcount


def main() -> None:
    rng = random.Random(SEED)
    OUT.mkdir(exist_ok=True)
    customers = make_customers(rng)
    products = make_products(rng)
    orders = make_orders(rng, customers, products)
    targets, headcount = make_targets(rng)

    customers.to_csv(OUT / "customers.csv", index=False)
    products.to_csv(OUT / "products.csv", index=False)
    orders.to_csv(OUT / "orders.csv", index=False)
    with pd.ExcelWriter(OUT / "regional_targets.xlsx") as xw:
        targets.to_excel(xw, sheet_name="Targets", index=False)
        headcount.to_excel(xw, sheet_name="Headcount", index=False)

    print(f"customers {len(customers)} | products {len(products)} | orders {len(orders)} | targets {len(targets)}")
    print(f"total revenue: {orders['revenue'].sum():,.2f}")


if __name__ == "__main__":
    main()
