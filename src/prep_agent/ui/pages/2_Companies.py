"""Companies — master view as card grid."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from prep_agent.calendar.store import CalendarStore
from prep_agent.companies.aggregate import aggregate_companies
from prep_agent.ui.helpers import get_settings, get_trace_store, require_auth
from prep_agent.ui.style import apply_style, pill

st.set_page_config(page_title="Companies · prep-agent", layout="wide")
apply_style()
require_auth()
st.markdown("# Companies")
st.caption(
    "Every company you've researched or interviewed with — joined across prep docs, "
    "traces, and calendar events. Email integration: hook ready, sync not built yet."
)

settings = get_settings()
trace_store = get_trace_store()
calendar_store = CalendarStore(db_path=settings.trace_db_path)

companies = aggregate_companies(
    prep_dir=settings.output_dir,
    trace_store=trace_store,
    calendar_store=calendar_store,
)

if not companies:
    st.info(
        "No companies yet. Generate a prep doc on the **prep-agent** page or "
        "run `prep-agent research <name>`."
    )
    st.stop()

# --- Card grid (3 cards per row) ---
for row_start in range(0, len(companies), 3):
    cols = st.columns(3)
    for offset, c in enumerate(companies[row_start : row_start + 3]):
        with cols[offset].container(border=True):
            last = c.last_seen_at.strftime("%b %d, %H:%M") if c.last_seen_at else "—"
            error_count = sum(1 for t in c.research_traces if t.status == "error")
            ok_count = sum(1 for t in c.research_traces if t.status == "ok")
            pills = []
            if c.prep_files:
                pills.append(pill(f"{len(c.prep_files)} prep", "ok"))
            if ok_count:
                pills.append(pill(f"{ok_count} ok", "ok"))
            if error_count:
                pills.append(pill(f"{error_count} err", "err"))
            if c.calendar_events:
                pills.append(pill(f"{len(c.calendar_events)} cal", "muted"))

            st.markdown(f"### {c.name}")
            st.markdown(" ".join(pills) if pills else "", unsafe_allow_html=True)
            st.markdown(
                f"<div style='font-size:0.82rem; color:#8B93A7; margin-top:0.5rem'>"
                f"Last activity: {last}<br>"
                f"<span class='mono'>{c.total_tokens:,} tokens · ${c.total_cost_usd:.4f}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

st.divider()

# --- Drill-in ---
st.markdown("### Details")
selected_slug = st.selectbox(
    "Company",
    options=[c.slug for c in companies],
    format_func=lambda s: next(c.name for c in companies if c.slug == s),
    label_visibility="collapsed",
)
selected = next(c for c in companies if c.slug == selected_slug)

col_left, col_right = st.columns([1, 1])

with col_left, st.container(border=True):
    st.markdown(f"### {selected.name}")
    if selected.last_seen_at:
        st.caption(f"Last seen: {selected.last_seen_at:%Y-%m-%d %H:%M}")
    st.markdown(
        f"<span class='mono'>{selected.total_tokens:,} tok · "
        f"${selected.total_cost_usd:.4f}</span>",
        unsafe_allow_html=True,
    )

    st.markdown("**Prep documents**")
    if not selected.prep_files:
        st.caption("(none)")
    for p in selected.prep_files:
        st.markdown(
            f"<div style='font-size:0.85rem'>"
            f"<code>{p.path.name}</code> · "
            f"<span class='mono'>{p.size_bytes:,} b</span> · "
            f"<span style='color:#8B93A7'>{p.date:%Y-%m-%d %H:%M}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("**Research traces**")
    if not selected.research_traces:
        st.caption("(none)")
    for t in selected.research_traces:
        when = datetime.fromtimestamp(t.started_at).strftime("%Y-%m-%d %H:%M")
        kind = {"ok": "ok", "error": "err"}.get(t.status, "muted")
        st.markdown(
            f"<div style='font-size:0.85rem'>"
            f"<code>{t.trace_id}</code> {pill(t.status, kind)} · "
            f"<span style='color:#8B93A7'>{when}</span> · "
            f"<span class='mono'>{t.total_tokens:,} tok · ${t.total_cost_usd:.4f}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

with col_right, st.container(border=True):
    st.markdown("**Calendar events**")
    if not selected.calendar_events:
        st.caption(
            "(none yet — run `prep-agent calendar sync` after OAuth setup)"
        )
    for e in selected.calendar_events:
        when = datetime.fromtimestamp(e.processed_at).strftime("%Y-%m-%d %H:%M")
        st.markdown(
            f"<div style='font-size:0.85rem; margin-bottom:0.5rem'>"
            f"<b>{e.summary[:60]}</b><br>"
            f"<span style='color:#8B93A7'>conf {e.confidence:.2f} · processed {when}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("**Email hits**")
    st.caption(
        "Gmail integration not built yet. The data model carries an "
        "`email_hits` field; a Gmail sync would populate it the same way "
        "the calendar sync populates calendar_events."
    )

# --- Prep doc preview ---
if selected.prep_files:
    st.divider()
    latest = selected.prep_files[0]
    st.markdown(f"### Latest prep · `{latest.path.name}`")
    content = latest.path.read_text(encoding="utf-8")
    tab_render, tab_raw = st.tabs(["Rendered", "Markdown source"])
    with tab_render:
        st.markdown(content)
    with tab_raw:
        st.code(content, language="markdown")
