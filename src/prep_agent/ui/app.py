"""Streamlit home page — your interview prep dashboard."""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime

import streamlit as st

from prep_agent.calendar.auth import load_credentials
from prep_agent.calendar.client import GoogleCalendarClient
from prep_agent.calendar.extract import looks_like_interview
from prep_agent.calendar.store import CalendarStore
from prep_agent.companies.aggregate import aggregate_companies
from prep_agent.obs.context import trace_context
from prep_agent.pipeline import _queries_for
from prep_agent.ui.helpers import get_pipeline, get_settings, get_trace_store, require_auth
from prep_agent.ui.style import apply_style, chip

st.set_page_config(page_title="prep-agent", layout="wide")
apply_style()
require_auth()

settings = get_settings()
pipeline = get_pipeline()
trace_store = get_trace_store()
calendar_store = CalendarStore(db_path=settings.trace_db_path)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _human_when(dt: datetime) -> str:
    delta = dt - datetime.now(dt.tzinfo) if dt.tzinfo else dt - datetime.now()
    days = delta.days
    if days < 0:
        return dt.strftime("%a %b %d · %H:%M")
    if days == 0:
        return f"today · {dt.strftime('%H:%M')}"
    if days == 1:
        return f"tomorrow · {dt.strftime('%H:%M')}"
    if days < 7:
        return f"in {days} days · {dt.strftime('%a %H:%M')}"
    return dt.strftime("%a %b %d · %H:%M")


# --- Hero ---
st.markdown('<div class="hero-eyebrow">PREP AGENT</div>', unsafe_allow_html=True)
st.markdown("# Good luck out there.")
st.markdown(
    '<div class="hero-sub">Company-tailored interview prep in 30 seconds — '
    "powered by your own playbook.</div>",
    unsafe_allow_html=True,
)

# --- Quick-action chip row ---
st.markdown(
    '<div class="chip-row">'
    + chip("Playbook", "/Playbook", "📝")
    + chip("Past preps", "/Past_preps", "📚")
    + chip("Companies", "/Companies", "🏢")
    + chip("Stats", "/Stats", "📊")
    + "</div>",
    unsafe_allow_html=True,
)


# --- Deep link: ?company=foo opens the latest saved prep for that company ---
qp_company = st.query_params.get("company", "").strip()
if qp_company:
    target_slug = _slug(qp_company)
    matches = sorted(
        settings.output_dir.glob(f"{target_slug}-*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if matches:
        latest = matches[0]
        st.success(f"Showing latest prep for **{qp_company}** — `{latest.name}`")
        tab_render, tab_raw = st.tabs(["Your prep doc", "Markdown source"])
        content = latest.read_text(encoding="utf-8")
        with tab_render:
            st.markdown(content)
        with tab_raw:
            st.code(content, language="markdown")
        st.stop()
    else:
        st.info(
            f"No saved prep for **{qp_company}** yet. "
            "Generate one below — or check the URL slug."
        )


# --- Generate form ---
with st.container(border=True):
    col_input, col_button = st.columns([5, 1])
    with col_input:
        company = st.text_input(
            "Company",
            placeholder="Type a company name (e.g. Chalk, ScaleOps, Anthropic, Vercel)",
            label_visibility="collapsed",
        )
    with col_button:
        generate = st.button("Generate", type="primary", use_container_width=True)


async def _run_with_status(
    company: str, status: st.delta_generator.DeltaGenerator
) -> tuple[str, str]:
    async with trace_context(
        pipeline.trace_store, label=company, kind="research"
    ) as trace_id:
        status.update(label=f"🔍 Searching the web for {company}...", state="running")
        results = await pipeline._search.search_many(_queries_for(company))

        status.update(label=f"📖 Reading {len(results)} sources...")
        signals = await pipeline._extract.extract(company, results)

        status.update(label="🧠 Matching with your playbook...")
        chunks = pipeline._retrieve.retrieve(signals)

        status.update(label="✍️ Writing your prep doc...")
        prep = await pipeline._synth.synthesize(signals, playbook_chunks=chunks)

        status.update(label="✓ Done.", state="complete")
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
            ][:3]
        except Exception:
            upcoming = []

        if upcoming:
            st.markdown("### 📅 Upcoming interviews")
            cols = st.columns(min(len(upcoming), 3) or 1)
            for i, ev in enumerate(upcoming):
                with cols[i % len(cols)].container(border=True):
                    st.markdown(
                        f'<div class="company-card-title">{ev.summary[:55]}</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<div style='color:#A78BFA; font-size:0.86rem; "
                        f"font-weight:500'>{_human_when(ev.start)}</div>",
                        unsafe_allow_html=True,
                    )
                    ext_attendees = [a.email for a in ev.attendees if not a.is_self]
                    if ext_attendees:
                        st.markdown(
                            f"<div class='company-card-meta'>"
                            f"With: {', '.join(ext_attendees[:2])}"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

    # Recent prep docs as click-to-open cards
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
                with cols[offset]:
                    last = c.last_seen_at.strftime("%b %d") if c.last_seen_at else "—"
                    latest_name = c.prep_files[0].path.name if c.prep_files else ""
                    n_preps = len(c.prep_files)
                    preps_label = f"{n_preps} prep doc{'s' if n_preps != 1 else ''}"
                    st.markdown(
                        f'<a class="card-link" href="/?company={c.slug}" target="_self">'
                        f'<div data-testid="stVerticalBlockBorderWrapper" '
                        f'style="background:linear-gradient(180deg,#131826,#0F1320);'
                        f'border:1px solid #1F2A3F;border-radius:14px;'
                        f'padding:1.2rem 1.3rem;cursor:pointer;">'
                        f'<div class="company-card-title">{c.name}</div>'
                        f'<div style="font-size:0.78rem;color:#A78BFA;font-weight:600;'
                        f'letter-spacing:0.04em;text-transform:uppercase">'
                        f'{preps_label}</div>'
                        f'<div class="company-card-meta">Last prepped {last}<br>'
                        f'<code style="font-size:0.72rem;opacity:0.7">{latest_name}</code>'
                        f'</div>'
                        f'</div></a>',
                        unsafe_allow_html=True,
                    )
    elif creds is None or not creds.valid:
        # First-time experience
        st.info(
            "👋 Type a company name above to generate your first prep doc. "
            "It takes about 30 seconds and is free with Gemini."
        )

# --- Sidebar: friendly stats ---
with st.sidebar:
    companies_all = aggregate_companies(
        prep_dir=settings.output_dir,
        trace_store=trace_store,
        calendar_store=calendar_store,
    )
    total_preps = sum(len(c.prep_files) for c in companies_all)
    st.markdown(
        f"<div style='font-size:0.95rem; padding:0.5rem 0; color:#CBD5E1'>"
        f"<b style='color:#E2E8F0'>{len(companies_all)}</b> companies · "
        f"<b style='color:#E2E8F0'>{total_preps}</b> prep doc"
        f"{'s' if total_preps != 1 else ''}"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.divider()
    st.markdown("### 💡 Tips")
    st.caption(
        "• `?company=scaleops` deep-links to a saved prep.\n\n"
        "• **Playbook** holds your drill sheet + AMC deep dive + Hebrew prep.\n\n"
        "• Past preps live under **Past preps**."
    )
    st.divider()
    st.caption(f"Provider: **{settings.llm_provider}** · `{settings.synthesize_model}`")
