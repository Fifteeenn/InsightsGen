"""Decide whether a result deserves a chart, which kind, and build it.

The decision is rule-based on the SHAPE of the result, not on the model's
opinion, so a chart is never broken or misleading. The model's chart_hint is
only consulted where the rules are genuinely ambiguous.

Shape -> form (in priority order)
  1 row                                   -> KPI (hero numbers), no plot
  date column + numeric                   -> line (multi-series if a small category column exists)
  category column + numeric, <= 40 rows   -> bar (grouped if a second small category exists)
  two numerics, no category/date          -> scatter
  anything else                           -> table only

Visual rules (from the data-viz method)
  - one y-axis, never dual axis; too-different scales fall back to the first measure
  - categorical colours in a fixed validated order, never cycled
  - single-series marks use one hue; no legend for a single series
  - thin marks, recessive grid, hover tooltips on
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

MAX_BAR_ROWS = 40
MAX_SERIES = 4
SMALL_CATEGORY = 8           # a text column with <= this many distinct values can colour a chart
SCALE_RATIO_LIMIT = 50       # measures whose maxima differ by more than this do not share an axis

PALETTE_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
PALETTE_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
CHROME = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781", grid="#e1e0d9", axis="#c3c2b7"),
    "dark": dict(surface="#1a1a19", ink="#ffffff", ink2="#c3c2b7", muted="#898781", grid="#2c2c2a", axis="#383835"),
}

_DATE_TEXT_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


@dataclass
class ChartSpec:
    kind: str                            # kpi | line | bar | scatter | table
    x: str | None = None
    y: list[str] = field(default_factory=list)
    color: str | None = None
    horizontal: bool = False
    kpis: list[tuple[str, str]] = field(default_factory=list)   # (label, formatted value)
    reason: str = ""


# ------------------------------------------------------------------ helpers

def humanize(name: str) -> str:
    return re.sub(r"[_\s]+", " ", str(name)).strip().title()


def fmt_number(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if pd.api.types.is_bool(v):
        return str(v)
    if pd.api.types.is_integer(v) or (pd.api.types.is_float(v) and float(v).is_integer() and abs(v) < 1e12):
        return f"{int(v):,}"
    if pd.api.types.is_float(v):
        return f"{float(v):,.2f}"
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    return str(v)


def _is_id_like(name: str) -> bool:
    n = str(name).lower()
    return n == "id" or n.endswith("_id") or n.endswith("id") and len(n) <= 6 or n.endswith("_code") or n.endswith("_key")


def _classify(df: pd.DataFrame) -> tuple[list[str], list[str], list[str]]:
    """Return (date_cols, numeric_cols, text_cols). Text that looks like YYYY-MM counts as date."""
    dates, nums, texts = [], [], []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            dates.append(c)
        elif pd.api.types.is_bool_dtype(s):
            texts.append(c)
        elif pd.api.types.is_numeric_dtype(s):
            nums.append(c)
        else:
            sample = s.dropna().astype(str).head(20)
            if not sample.empty and sample.map(lambda v: bool(_DATE_TEXT_RE.match(v))).all():
                dates.append(c)
            else:
                texts.append(c)
    return dates, nums, texts


def _same_scale(df: pd.DataFrame, cols: list[str]) -> list[str]:
    """Keep only measures that can honestly share one axis with the first one."""
    if len(cols) <= 1:
        return cols
    base = abs(df[cols[0]].abs().max()) or 1.0
    keep = [cols[0]]
    for c in cols[1:]:
        m = abs(df[c].abs().max()) or 1.0
        ratio = max(base, m) / max(min(base, m), 1e-9)
        if ratio <= SCALE_RATIO_LIMIT:
            keep.append(c)
    return keep[:MAX_SERIES]


# ------------------------------------------------------------------ decision

def choose_chart(df: pd.DataFrame, hint: str = "table") -> ChartSpec:
    if df is None or df.empty:
        return ChartSpec(kind="table", reason="empty result")
    n = len(df)
    dates, nums, texts = _classify(df)

    # 1. Single row -> hero numbers
    if n == 1:
        kpis: list[tuple[str, str]] = []
        for c in df.columns:
            kpis.append((humanize(c), fmt_number(df[c].iloc[0])))
        return ChartSpec(kind="kpi", kpis=kpis, reason="single row")

    # 2. Time series
    if dates and nums:
        x = dates[0]
        small_cats = [t for t in texts if df[t].nunique() <= SMALL_CATEGORY]
        rows_per_x = n / max(df[x].nunique(), 1)
        if small_cats and rows_per_x > 1.05:
            color = small_cats[0]
            if df.groupby([x, color]).size().max() == 1:
                return ChartSpec(kind="line", x=x, y=[nums[0]], color=color, reason="date + small category + measure")
        if rows_per_x <= 1.05:
            return ChartSpec(kind="line", x=x, y=_same_scale(df, nums), reason="date + measure(s)")
        return ChartSpec(kind="table", reason="multiple rows per date without a small category")

    # 3. Categories
    if texts and nums and n <= MAX_BAR_ROWS:
        # Highest cardinality first; among ties prefer a human label over an id column.
        texts_by_card = sorted(texts, key=lambda t: (-df[t].nunique(), _is_id_like(t)))
        x = texts_by_card[0]
        # A colour column must actually group rows: both axes smaller than the row count
        # and the pair (x, colour) unique per row (a proper cross-tab, e.g. segment x region).
        others = [t for t in texts_by_card[1:]
                  if df[t].nunique() <= SMALL_CATEGORY and df[t].nunique() < n and df[x].nunique() < n]
        if others and df.groupby([x, others[0]]).size().max() == 1:
            return ChartSpec(kind="bar", x=x, y=[nums[0]], color=others[0],
                             horizontal=False, reason="two categories + measure")
        if df[x].nunique() < n:
            return ChartSpec(kind="table", reason="category repeats without a second grouping column")
        y = _same_scale(df, nums)
        long_labels = bool(df[x].astype(str).str.len().max() > 18)
        return ChartSpec(kind="bar", x=x, y=y, horizontal=bool(n > 8 or (n > 4 and long_labels)),
                         reason="category + measure(s)")

    # 4. Two measures, no category or date
    if len(nums) >= 2 and not texts and not dates and n > 1 and hint in ("scatter", "table"):
        return ChartSpec(kind="scatter", x=nums[0], y=[nums[1]], reason="two measures")

    return ChartSpec(kind="table", reason="no chartable shape")


# ------------------------------------------------------------------ build

def _layout(fig: go.Figure, mode: str, n_series: int, title: str | None = None) -> go.Figure:
    c = CHROME[mode]
    fig.update_layout(
        template="plotly_white" if mode == "light" else "plotly_dark",
        paper_bgcolor=c["surface"], plot_bgcolor=c["surface"],
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', color=c["ink2"], size=13),
        title=dict(text=title, font=dict(color=c["ink"], size=15), x=0, xanchor="left") if title else None,
        margin=dict(l=8, r=8, t=44 if title else 16, b=8),
        height=380,
        showlegend=n_series > 1,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title=None,
                    font=dict(color=c["ink2"])),
        hoverlabel=dict(bgcolor=c["surface"], font=dict(color=c["ink"]), bordercolor=c["axis"]),
        colorway=PALETTE_LIGHT if mode == "light" else PALETTE_DARK,
    )
    fig.update_xaxes(showgrid=False, linecolor=c["axis"], tickfont=dict(color=c["muted"]),
                     title_font=dict(color=c["ink2"]), zeroline=False)
    fig.update_yaxes(gridcolor=c["grid"], gridwidth=1, linecolor=c["surface"], tickfont=dict(color=c["muted"]),
                     title_font=dict(color=c["ink2"]), zeroline=False, separatethousands=True)
    return fig


def build_figure(df: pd.DataFrame, spec: ChartSpec, dark: bool = False, title: str | None = None) -> go.Figure | None:
    mode = "dark" if dark else "light"
    palette = PALETTE_DARK if dark else PALETTE_LIGHT
    labels = {c: humanize(c) for c in df.columns}

    if spec.kind == "line":
        d = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(d[spec.x]):
            d[spec.x] = pd.to_datetime(d[spec.x], errors="coerce")
        d = d.sort_values(spec.x)
        if spec.color:
            fig = px.line(d, x=spec.x, y=spec.y[0], color=spec.color, labels=labels,
                          color_discrete_sequence=palette, markers=len(d) <= 60)
            n_series = d[spec.color].nunique()
        else:
            y_arg = spec.y[0] if len(spec.y) == 1 else spec.y   # a bare string keeps the real axis title
            fig = px.line(d, x=spec.x, y=y_arg, labels=labels, color_discrete_sequence=palette,
                          markers=len(d) <= 60)
            n_series = len(spec.y)
            if n_series > 1:
                fig.update_layout(yaxis_title=None)
                fig.for_each_trace(lambda t: t.update(name=humanize(t.name)))
        fig.update_traces(line=dict(width=2), marker=dict(size=6))
        fig.update_layout(hovermode="x unified")
        return _layout(fig, mode, n_series, title)

    if spec.kind == "bar":
        d = df.copy()
        n_series = 1
        if spec.color:
            fig = px.bar(d, x=spec.x, y=spec.y[0], color=spec.color, barmode="group", labels=labels,
                         color_discrete_sequence=palette)
            n_series = d[spec.color].nunique()
        elif len(spec.y) > 1:
            fig = px.bar(d, x=spec.x, y=spec.y, barmode="group", labels=labels, color_discrete_sequence=palette)
            fig.update_layout(yaxis_title=None)
            fig.for_each_trace(lambda t: t.update(name=humanize(t.name)))
            n_series = len(spec.y)
        else:
            d = d.sort_values(spec.y[0], ascending=spec.horizontal)
            if spec.horizontal:
                fig = px.bar(d, y=spec.x, x=spec.y[0], orientation="h", labels=labels,
                             color_discrete_sequence=palette)
            else:
                fig = px.bar(d, x=spec.x, y=spec.y[0], labels=labels, color_discrete_sequence=palette)
        fig.update_traces(marker_line_width=0)
        fig.update_layout(bargap=0.35, bargroupgap=0.08)
        if spec.horizontal:
            fig.update_xaxes(gridcolor=CHROME[mode]["grid"], showgrid=True, separatethousands=True)
            fig.update_yaxes(showgrid=False, autorange="reversed" if False else None)
            fig.update_layout(height=max(300, 28 * len(d) + 80))
        return _layout(fig, mode, n_series, title)

    if spec.kind == "scatter":
        fig = px.scatter(df, x=spec.x, y=spec.y[0], labels=labels, color_discrete_sequence=palette)
        fig.update_traces(marker=dict(size=8, opacity=0.8))
        return _layout(fig, mode, 1, title)

    return None


# ------------------------------------------------------------------ JSON payload (for the React frontend)

def _json_value(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat() if v == v.normalize() else v.isoformat(sep=" ")
    if pd.api.types.is_integer(v):
        return int(v)
    if pd.api.types.is_float(v):
        return None if pd.isna(v) else float(v)
    if pd.api.types.is_bool(v):
        return bool(v)
    return str(v)


def chart_payload(df: pd.DataFrame, spec: ChartSpec) -> dict:
    """Plot-ready description the frontend can render without any chart logic of its own.

    {
      kind: 'kpi' | 'line' | 'bar' | 'scatter' | 'table',
      x: column name for the axis, series: [{key, name}], data: [rows keyed by x + series keys],
      horizontal: bool, kpis: [{label, value}]
    }
    Multi-series-by-category results are pivoted here so every series is a column.
    """
    out = {"kind": spec.kind, "x": spec.x, "series": [], "data": [], "horizontal": spec.horizontal,
           "kpis": [{"label": l, "value": v} for l, v in spec.kpis], "reason": spec.reason}
    if spec.kind in ("kpi", "table") or df is None or df.empty:
        return out

    d = df.copy()
    if spec.kind == "line" and not pd.api.types.is_datetime64_any_dtype(d[spec.x]):
        d[spec.x] = pd.to_datetime(d[spec.x], errors="coerce")
    if spec.kind == "line":
        d = d.sort_values(spec.x)

    if spec.color:
        pivot = d.pivot_table(index=spec.x, columns=spec.color, values=spec.y[0], aggfunc="first", sort=True)
        pivot = pivot.reset_index()
        keys = [c for c in pivot.columns if c != spec.x]
        out["series"] = [{"key": str(k), "name": str(k)} for k in keys[:8]]
        pivot.columns = [str(c) for c in pivot.columns]
        d = pivot
    else:
        if spec.kind == "bar" and len(spec.y) == 1:
            d = d.sort_values(spec.y[0], ascending=False)
        out["series"] = [{"key": y, "name": humanize(y)} for y in spec.y]

    out["x_label"] = humanize(spec.x) if spec.x else None
    out["data"] = [{k: _json_value(v) for k, v in row.items()} for row in d.to_dict(orient="records")]
    return out
