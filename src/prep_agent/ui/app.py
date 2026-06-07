"""Streamlit home page — your interview prep dashboard."""
from __future__ import annotations

import asyncio
import re
from datetime import date

import streamlit as st

from prep_agent.calendar.auth import load_credentials
from prep_agent.calendar.client import GoogleCalendarClient
from prep_agent.calendar.extract import looks_like_interview
from prep_agent.calendar.store import CalendarStore
from prep_agent.companies.aggregate import aggregate_companies
from prep_agent.obs.context import trace_context
from prep_agent.pipeline import _queries_for
from prep_agent.ui.helpers import get_pipeline, get_settings, get_trace_store, require_auth
from prep_agent.ui.style import apply_style

st.set_page_config(page_title="prep-agent", layout="wide")
apply_style()
require_auth()

settings = get_settings()
pipeline = get_pipeline()
trace_store = get_trace_store()
calendar_store = CalendarStore(db_path=settings.trace_db_path)


# --- Hero ---
st.markdown("# Good luck out there.")
st.caption("Generate company-tailored interview prep in 30 seconds.")

# --- Generate form (always at the top, prominent) ---
with st.container(border=True):
    col_input, col_button = st.columns([5, 1])
    with col_input:
        company = st.text_input(
            "Company",
            placeholder="Type a company name and press Generate (e.g. Chalk, Anthropic, Vercel)",
            label_visibility="collapsed",
        )
    with col_button:
        generate = st.button("Generate", type="primary", use_container_width=True)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


async def _run_with_status(
    company: str, status: st.delta_generator.DeltaGenerator
) -> tuple[str, str]:
    async with trace_context(
        pipeline.trace_store, label=company, kind="research"
    ) as trace_id:
        status.update(label=f"Searching the web for {company}...", state="running")
        results = await pipeline._search.search_many(_queries_for(company))

        status.update(label=f"Reading {len(results)} sources...")
        signals = await pipeline._extract.extract(company, results)

        status.update(label="Matching with your playbook...")
        chunks = pipeline._retrieve.retrieve(signals)

        status.update(label="Writing your prep doc...")
        prep = await pipeline._synth.synthesize(signals, playbook_chunks=chunks)

        status.update(label="Done.", state="complete")
        return prep.raw_markdown, trace_id


if generate and company:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    with st.status("Starting...", expanded=True) as status:
        try:
            markdown, trace_id = asyncio.run(_run_with_status(company, status))
        except Exception as e:
            status.update(label=f"Failed: {e}", state="error")
            st.exception(e)
            st.stop()

    out_path = settings.output_dir / f"{_slug(company)}-{date.today().isoformat()}.md"
    out_path.write_text(markdown, encoding="utf-8")

    st.success(f"Saved as `{out_path.name}`")
    tab_render, tab_raw = st.tabs(["Your prep doc", "Markdown source"])
    with tab_render:
        st.markdown(markdown)
    with tab_raw:
        st.code(markdown, language="markdown")
elif generate and not company:
    st.warning("Type a company name first.")
else:
    # --- Default view: upcoming interviews + recent preps ---

    # Upcoming interviews from Calendar
    creds = None
    try:
        creds = load_credentials(settings.google_token_path)
    except Exception:
        creds = None

    if creds and creds.valid:
        try:
            calendar_client = GoogleCalendarClient(credentials=creds)
            upcoming = [
                e for e in calendar_client.list_events(
                    calendar_id=settings.google_calendar_id, days_ahead=14
                )
                if looks_like_interview(e)
            ][:5]
        except Exception:
            upcoming = []

        if upcoming:
            st.markdown("### 📅 Your upcoming interviews")
            cols = st.columns(min(len(upcoming), 3) or 1)
            for i, ev in enumerate(upcoming):
                with cols[i % len(cols)].container(border=True):
                    st.markdown(f"**{ev.summary[:55]}**")
                    st.markdown(
                        f"<div style='color:#8B93A7; font-size:0.85rem'>"
                        f"{ev.start.strftime('%a %b %d · %H:%M')}"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                    ext_attendees = [a.email for a in ev.attendees if not a.is_self]
                    if ext_attendees:
                        st.caption("With: " + ", ".join(ext_attendees[:2]))

    # Recent prep docs as cards
    companies = aggregate_companies(
        prep_dir=settings.output_dir,
        trace_store=trace_store,
        calendar_store=calendar_store,
    )
    recent_with_prep = [c for c in companies if c.prep_files][:6]

    if recent_with_prep:
        st.markdown("### Recently prepped")
        for row_start in range(0, len(recent_with_prep), 3):
            cols = st.columns(3)
            for offset, c in enumerate(recent_with_prep[row_start : row_start + 3]):
                with cols[offset].container(border=True):
                    last = c.last_seen_at.strftime("%b %d") if c.last_seen_at else "—"
                    st.markdown(f"#### {c.name}")
                    st.caption(f"Last prepped {last}")
                    if c.prep_files:
                        latest = c.prep_files[0]
                        st.markdown(
                            f"<div style='font-size:0.78rem; color:#8B93A7'>"
                            f"📄 <code>{latest.path.name}</code>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
    elif creds is None or not creds.valid:
        # First-time experience
        st.info(
            "👋 Type a company name above to generate your first prep doc. "
            "It takes about 30 seconds and is free with Gemini."
        )

# --- Sidebar: friendly stats only ---
with st.sidebar:
    companies_all = aggregate_companies(
        prep_dir=settings.output_dir,
        trace_store=trace_store,
        calendar_store=calendar_store,
    )
    total_preps = sum(len(c.prep_files) for c in companies_all)
    st.markdown(
        f"<div style='font-size:0.95rem; padding:0.5rem 0'>"
        f"<b>{len(companies_all)}</b> companies · "
        f"<b>{total_preps}</b> prep doc{'s' if total_preps != 1 else ''}"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.divider()
    st.caption("Tip: drop a company name above any time — it'll show up under **Past preps** when done.")
    st.divider()
    st.caption(f"Provider: **{settings.llm_provider}** · `{settings.synthesize_model}`")
