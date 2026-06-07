"""Sync orchestrator: calendar → classify → prep doc.

Flow per sync:
1. List events in next N days.
2. Pre-filter by keyword (cheap).
3. Skip events already in CalendarStore.
4. Classify remaining via LLM.
5. For each that's a confident interview with a known company:
   - Generate prep doc through Pipeline (RAG + synthesis).
   - Persist prep markdown.
   - Record event in CalendarStore so we don't re-do it.

Dry-run mode short-circuits before step 5 — useful for "what would happen?"
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from prep_agent.calendar.client import GoogleCalendarClient
from prep_agent.calendar.extract import EventExtractor, looks_like_interview
from prep_agent.calendar.models import CalendarEvent, InterviewClassification
from prep_agent.calendar.store import CalendarStore
from prep_agent.pipeline import Pipeline


@dataclass(frozen=True)
class SyncAction:
    event: CalendarEvent
    classification: InterviewClassification
    action: str  # 'generated' | 'skipped_low_confidence' | 'skipped_not_interview' | 'dry_run'
    prep_path: str | None = None


@dataclass(frozen=True)
class SyncReport:
    events_seen: int
    events_filtered: int  # passed keyword filter
    events_already_processed: int
    actions: list[SyncAction]

    @property
    def generated(self) -> list[SyncAction]:
        return [a for a in self.actions if a.action == "generated"]


# Companies that match are NOT generated — the candidate's own employer, etc.
_BLOCKLIST_COMPANIES = {"skai", "kenshoo"}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


async def sync(
    calendar_client: GoogleCalendarClient,
    event_extractor: EventExtractor,
    pipeline: Pipeline,
    calendar_store: CalendarStore,
    output_dir: Path,
    calendar_id: str,
    self_emails: list[str],
    days_ahead: int = 7,
    confidence_threshold: float = 0.6,
    dry_run: bool = False,
) -> SyncReport:
    events = calendar_client.list_events(calendar_id=calendar_id, days_ahead=days_ahead)

    candidates: list[CalendarEvent] = []
    already = 0
    for e in events:
        if not looks_like_interview(e):
            continue
        if calendar_store.is_processed(e.event_id):
            already += 1
            continue
        candidates.append(e)

    actions: list[SyncAction] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for event in candidates:
        classification = await event_extractor.classify(event, self_emails)

        if not classification.is_interview:
            actions.append(
                SyncAction(event=event, classification=classification,
                           action="skipped_not_interview")
            )
            continue

        company = (classification.company or "").strip()
        if (
            not company
            or classification.confidence < confidence_threshold
            or company.lower() in _BLOCKLIST_COMPANIES
        ):
            actions.append(
                SyncAction(event=event, classification=classification,
                           action="skipped_low_confidence")
            )
            continue

        if dry_run:
            actions.append(
                SyncAction(event=event, classification=classification, action="dry_run")
            )
            continue

        prep = await pipeline.run(company)
        prep_path = output_dir / f"{_slug(company)}-{date.today().isoformat()}.md"
        prep_path.write_text(prep.raw_markdown, encoding="utf-8")

        # Record so subsequent syncs don't re-prep the same event.
        # trace_id is harder to thread here (Pipeline.run owns the trace) — we
        # leave it null for now and revisit if we ever need to deep-link.
        calendar_store.record(
            event_id=event.event_id,
            summary=event.summary,
            start_iso=event.start.isoformat(),
            company=company,
            confidence=classification.confidence,
            prep_path=str(prep_path),
            trace_id=None,
        )
        actions.append(
            SyncAction(
                event=event,
                classification=classification,
                action="generated",
                prep_path=str(prep_path),
            )
        )

    return SyncReport(
        events_seen=len(events),
        events_filtered=len(candidates) + already,
        events_already_processed=already,
        actions=actions,
    )
