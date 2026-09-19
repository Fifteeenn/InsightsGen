"""InsightsGen: ask questions about your CSV / Excel files in plain English.

This file is the thin UI layer. All logic lives in core/ (see core/pipeline.py).
"""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from core.charts import build_figure, choose_chart
from core.pipeline import Answer, Workspace

ROOT = Path(__file__).resolve().parent
SAMPLE_DIR = ROOT / "sample_data"
SAMPLE_FILES = ["orders.csv", "customers.csv", "products.csv", "regional_targets.xlsx"]

# Streamlit Cloud stores secrets separately from .env; bridge them into the env.
try:
    for key in ("GROQ_API_KEY", "GROQ_MODEL"):
        if key in st.secrets and st.secrets[key]:
            os.environ.setdefault(key, str(st.secrets[key]))
except Exception:
    pass

st.set_page_config(page_title="InsightsGen", page_icon="📊", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.6rem; padding-bottom: 5rem; max-width: 1100px; }
      .ig-title { font-size: 1.7rem; font-weight: 700; margin-bottom: 0; }
      .ig-sub { color: #52514e; margin-top: 0.1rem; margin-bottom: 1rem; }
      .ig-kpi-label { font-size: 0.8rem; color: #52514e; text-transform: uppercase; letter-spacing: .04em; }
      .ig-kpi-value { font-size: 1.9rem; font-weight: 700; line-height: 1.15; }
      .ig-pill { display:inline-block; padding: 2px 8px; border-radius: 999px; font-size: .75rem;
                 background: #eef4fc; color: #1c5cab; margin-right: 6px; }
      .ig-pill-warn { background: #fff4e5; color: #8a4b00; }
      .ig-empty { border: 1px dashed #c3c2b7; border-radius: 12px; padding: 2rem; text-align: center; color: #52514e; }
      div[data-testid="stChatMessage"] { padding-top: .5rem; padding-bottom: .5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- state
def _state() -> None:
    ss = st.session_state
    ss.setdefault("ws", Workspace())
    ss.setdefault("messages", [])          # list[Answer]
    ss.setdefault("loaded_keys", set())    # (name, size) of files already added
    ss.setdefault("pending", None)         # question queued by a suggestion button


def _is_dark() -> bool:
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


_state()
ws: Workspace = st.session_state.ws


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown('<div class="ig-title">📊 InsightsGen</div>', unsafe_allow_html=True)
    st.markdown('<div class="ig-sub">Upload data. Ask in plain English. Get exact answers.</div>', unsafe_allow_html=True)

    uploads = st.file_uploader(
        "Add CSV or Excel files", type=["csv", "tsv", "xlsx", "xlsm", "xls"],
        accept_multiple_files=True, label_visibility="collapsed",
    )
    new_files = []
    for f in uploads or []:
        key = (f.name, f.size)
        if key not in st.session_state.loaded_keys:
            new_files.append((f.name, f.getvalue()))
            st.session_state.loaded_keys.add(key)
    if new_files:
        try:
            with st.spinner("Loading and profiling..."):
                ws.add_files(new_files)
        except Exception as e:
            st.error(f"Could not load a file: {e}")

    c1, c2 = st.columns(2)
    if c1.button("Load sample data", width="stretch", help="Orders, customers, products and an Excel of regional targets"):
        files = [(n, (SAMPLE_DIR / n).read_bytes()) for n in SAMPLE_FILES]
        keys = {(n, len(b)) for n, b in files}
        files = [(n, b) for n, b in files if (n, len(b)) not in st.session_state.loaded_keys]
        if files:
            with st.spinner("Loading and profiling..."):
                ws.add_files(files)
            st.session_state.loaded_keys |= keys
            st.rerun()
    if c2.button("Clear all", width="stretch", disabled=not ws.has_data):
        ws.clear()
        st.session_state.messages = []
        st.session_state.loaded_keys = set()
        st.session_state.pending = None
        st.rerun()

    if ws.has_data:
        st.markdown(f"**{len(ws.tables)} table{'s' if len(ws.tables) != 1 else ''} loaded**")
        for p in ws.profiles:
            with st.expander(f"{p.display_name}  ·  {p.rows:,} rows", expanded=False):
                st.caption(f"SQL name: `{p.name}`")
                for c in p.columns:
                    detail = ""
                    if c.kind in ("number", "date") and c.min is not None:
                        detail = f" · {c.min} → {c.max}"
                    elif c.examples:
                        detail = " · e.g. " + ", ".join(c.examples[:2])
                    nulls = f" · {c.null_count} nulls" if c.null_count else ""
                    st.markdown(f"<span class='ig-pill'>{c.kind}</span>`{c.name}`{detail}{nulls}", unsafe_allow_html=True)
                for w in p.warnings:
                    st.markdown(f"<span class='ig-pill ig-pill-warn'>cleaned</span>{w}", unsafe_allow_html=True)
                if st.button("Remove", key=f"rm_{p.name}"):
                    ws.remove_table(p.name)
                    st.rerun()
        if ws.joins:
            st.markdown("**Detected relationships**")
            for j in ws.joins:
                st.markdown(f"🔗 `{j.column}` links " + " · ".join(f"`{t}`" for t in j.tables))
        elif len(ws.tables) > 1:
            st.caption("No shared columns found between tables. Cross-file questions may need explicit column names.")

    st.divider()
    st.caption(f"Model: `{os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b')}` via Groq · engine: DuckDB")
    st.caption("Your data never leaves this app. The model only sees column names, types and 3 sample rows.")


# ---------------------------------------------------------------- rendering
def render_kpis(kpis: list[tuple[str, str]]) -> None:
    cols = st.columns(min(len(kpis), 4))
    for i, (label, value) in enumerate(kpis[:8]):
        with cols[i % len(cols)]:
            st.markdown(
                f"<div class='ig-kpi-label'>{label}</div><div class='ig-kpi-value'>{value}</div>",
                unsafe_allow_html=True,
            )


def render_answer(a: Answer) -> None:
    if a.clarification:
        st.info(f"**Quick check:** {a.clarification}")
        return
    if a.error:
        st.error(a.error)
        if a.attempts:
            with st.expander("What was tried"):
                for i, at in enumerate(a.attempts, 1):
                    st.markdown(f"**Attempt {i}** — {at.error}")
                    st.code(at.sql, language="sql")
        return

    if a.title:
        st.markdown(f"**{a.title}**")
    st.markdown(a.narrative.replace("$", "\\$"))   # keep "$1,200" from being read as LaTeX

    spec = choose_chart(a.df, a.chart_hint)
    if spec.kind == "kpi":
        render_kpis(spec.kpis)
    else:
        fig = build_figure(a.df, spec, dark=_is_dark())
        if fig is not None:
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    badges = []
    if a.healed:
        badges.append(f"self-corrected after {len(a.attempts)} failed attempt{'s' if len(a.attempts) > 1 else ''}")
    if a.truncated:
        badges.append("result capped at 1,000 rows")
    label = "How I computed this" + (f"  ·  {' · '.join(badges)}" if badges else "")
    with st.expander(label, expanded=False):
        if a.explanation:
            st.caption(a.explanation)
        st.code(a.sql or "", language="sql")
        st.dataframe(a.df, width="stretch", hide_index=True, height=min(400, 40 + 35 * max(len(a.df), 1)))
        st.download_button(
            "Download result as CSV", a.df.to_csv(index=False).encode("utf-8"),
            file_name="insightsgen_result.csv", mime="text/csv", key=f"dl_{id(a)}",
        )
        if a.attempts:
            st.markdown("**Earlier attempts that failed:**")
            for i, at in enumerate(a.attempts, 1):
                st.markdown(f"Attempt {i}: `{at.error}`")
                st.code(at.sql, language="sql")
        st.caption(f"{len(a.df):,} row{'s' if len(a.df) != 1 else ''} · {a.elapsed_ms:,.0f} ms end to end")


# ---------------------------------------------------------------- main
if not ws.has_data:
    st.markdown('<div class="ig-title">Ask your data anything</div>', unsafe_allow_html=True)
    st.markdown('<div class="ig-sub">Upload one or more CSV or Excel files in the sidebar, or load the sample dataset to try it.</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="ig-empty">
          <p><b>How it works</b></p>
          <p>Your files become tables in an in-memory analytics database.<br>
          An open-weight model writes a SQL query from your question, the database computes the exact answer,<br>
          and every answer shows the query it ran so you can verify it.</p>
          <p>Files with shared columns are linked automatically, so you can ask questions across them.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    if not st.session_state.messages:
        st.markdown('<div class="ig-title">What would you like to know?</div>', unsafe_allow_html=True)
        st.markdown('<div class="ig-sub">Try one of these, or type your own question below.</div>', unsafe_allow_html=True)
    suggestions = ws.suggestions()
    if suggestions:
        with st.container():
            cols = st.columns(len(suggestions[:5]))
            for i, q in enumerate(suggestions[:5]):
                if cols[i].button(q, key=f"sug_{i}", width="stretch"):
                    st.session_state.pending = q
                    st.rerun()

    for a in st.session_state.messages:
        with st.chat_message("user"):
            st.markdown(a.question)
        with st.chat_message("assistant"):
            render_answer(a)

question = st.chat_input("Ask a question about your data..." if ws.has_data else "Upload data first", disabled=not ws.has_data)
if st.session_state.pending and ws.has_data:
    question, st.session_state.pending = st.session_state.pending, None

if question and ws.has_data:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Writing the query and computing the answer..."):
            answer = ws.ask(question)
        render_answer(answer)
    st.session_state.messages.append(answer)
