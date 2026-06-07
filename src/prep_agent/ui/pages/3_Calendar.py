"""Calendar page — show upcoming interview-like events and sync.

Auth is done via CLI (`prep-agent calendar auth`) on first setup. This page
just reads the persisted token and lists events. The Sync button kicks off
the same sync orchestrator the CLI uses.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import streamlit as st

from prep_agent.calendar.auth import GoogleAuthError, load_credentials
from prep_agent.calendar.client import GoogleCalendarClient
from prep_agent.calendar.extract import EventExtractor, looks_like_interview
from prep_agent.calendar.store import CalendarStore
from prep_agent.calendar.sync import SyncReport
from prep_agent.calendar.sync import sync as sync_calendar
from prep_agent.ui.helpers import get_pipeline, get_settings, require_auth
from prep_agent.ui.style import apply_style

st.set_page_config(page_title="Calendar · prep-agent", layout="wide")
apply_style()
require_auth()
st.markdown("# Calendar")
st.caption(
    "Auto-detect interview events on your Google Calendar and generate prep docs for them."
)

settings = get_settings()
pipeline = get_pipeline()

creds = None
try:
    creds = load_credentials(settings.google_token_path)
except Exception as e:
    st.error(f"Failed to load Google credentials: {e}")

if creds is None:
    # Friendly empty state with step-by-step setup
    with st.container(border=True):
        st.markdown("### One-time setup")
        st.markdown(
            "Connect your Google Calendar to surface upcoming interviews automatically. "
            "Read-only — prep-agent never writes to your calendar."
        )
        st.markdown("**Step 1 — Create a Google Cloud project** (~1 minute)")
        st.markdown(
            "Open [console.cloud.google.com](https://console.cloud.google.com) → "
            "top-bar dropdown → **New Project** → name it `prep-agent` → Create."
        )
        st.markdown("**Step 2 — Enable the Calendar API**")
        st.markdown(
            "Open [the Calendar API page](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com), "
            "make sure your project is selected, click **Enable**."
        )
        st.markdown("**Step 3 — Configure consent screen**")
        st.markdown(
            "APIs & Services → OAuth consent screen → **External** → app name `prep-agent`, "
            "your email, Save. Under Test users add your own Gmail."
        )
        st.markdown("**Step 4 — Create OAuth credentials**")
        st.markdown(
            "APIs & Services → Credentials → **Create Credentials → OAuth client ID** → "
            "Application type: **Desktop app** → name `prep-agent-desktop` → Create → Download JSON."
        )
        st.markdown("**Step 5 — Move the file + auth**")
        st.code(
            "mkdir -p ~/.config/prep-agent\n"
            "mv ~/Downloads/client_secret_*.json ~/.config/prep-agent/google_client_secret.json\n"
            "cd ~/Documents/prep-agent && uv run prep-agent calendar auth",
            language="bash",
        )
        st.caption("After auth, refresh this page.")
    st.stop()

if not creds.valid:
    st.warning(
        "Calendar token expired. Run `uv run prep-agent calendar auth` to refresh."
    )
    st.stop()

calendar_client = GoogleCalendarClient(credentials=creds)
calendar_store = CalendarStore(db_path=settings.trace_db_path)

# --- Sidebar: sync controls ---
with st.sidebar:
    st.subheader("Sync")
    days = st.slider("Days ahead", 1, 30, value=7)
    confidence = st.slider("Confidence threshold", 0.0, 1.0, value=0.6, step=0.05)
    dry_run = st.checkbox("Dry run (classify only)", value=True)
    sync_button = st.button("Run sync", type="primary", use_container_width=True)

# --- Main: upcoming events ---
st.subheader(f"Upcoming events (next {days} days)")
try:
    events = calendar_client.list_events(
        calendar_id=settings.google_calendar_id, days_ahead=days
    )
except GoogleAuthError as e:
    st.error(str(e))
    st.stop()

if not events:
    st.caption("Nothing in this window.")
else:
    rows = []
    for ev in events:
        rows.append(
            {
                "start": ev.start.strftime("%Y-%m-%d %H:%M"),
                "title": ev.summary,
                "external_attendees": ", ".join(
                    a.email for a in ev.attendees if not a.is_self
                )[:80],
                "looks_like_interview": "yes" if looks_like_interview(ev) else "no",
                "already_processed": "yes" if calendar_store.is_processed(ev.event_id) else "no",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

# --- Sync action ---
if sync_button:
    event_extractor = EventExtractor(provider=pipeline.extract_provider)

    async def _run_sync() -> SyncReport:
        return await sync_calendar(
            calendar_client=calendar_client,
            event_extractor=event_extractor,
            pipeline=pipeline,
            calendar_store=calendar_store,
            output_dir=settings.output_dir,
            calendar_id=settings.google_calendar_id,
            self_emails=[],
            days_ahead=days,
            confidence_threshold=confidence,
            dry_run=dry_run,
        )

    with st.status(
        f"Syncing ({'dry-run' if dry_run else 'live'})...", expanded=True
    ) as status:
        try:
            report = asyncio.run(_run_sync())
            status.update(label="Done.", state="complete")
        except Exception as e:
            status.update(label=f"Failed: {e}", state="error")
            st.exception(e)
            st.stop()

    st.success(
        f"Events seen: {report.events_seen} · "
        f"already processed: {report.events_already_processed} · "
        f"generated: {len(report.generated)}"
    )
    rows = []
    for a in report.actions:
        rows.append(
            {
                "action": a.action,
                "start": a.event.start.strftime("%Y-%m-%d %H:%M"),
                "event": a.event.summary,
                "company": a.classification.company or "—",
                "confidence": f"{a.classification.confidence:.2f}",
                "prep": Path(a.prep_path).name if a.prep_path else "—",
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

# --- Processed history ---
st.divider()
st.subheader("Recently processed events")
processed = calendar_store.list_recent(limit=20)
if not processed:
    st.caption("Nothing processed yet.")
else:
    st.dataframe(
        [
            {
                "processed_at": datetime.fromtimestamp(p.processed_at).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "event": p.summary,
                "company": p.company or "—",
                "confidence": f"{p.confidence:.2f}",
                "prep": Path(p.prep_path).name if p.prep_path else "—",
            }
            for p in processed
        ],
        use_container_width=True,
        hide_index=True,
    )
