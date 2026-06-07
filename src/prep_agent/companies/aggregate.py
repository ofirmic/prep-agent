"""Companies aggregator — joins prep docs + traces + calendar events by slug.

Read-time aggregation, no separate `companies` table. For ~dozens of companies
that's the right call: simpler, no schema migration, no consistency drift
between the master table and its sources of truth.

If this ever scales past ~hundreds of companies (it won't, this is a personal
tool) the upgrade is straightforward: persist a denormalized table that the
sync writes to.

Email integration is left as a future hook. The `Company` dataclass already
carries an `email_hits: list[EmailHit]` field; an Gmail sync would populate it
the same way calendar events populate `calendar_events`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from prep_agent.calendar.store import CalendarStore, ProcessedEventRow
from prep_agent.obs.store import TraceRow, TraceStore


@dataclass(frozen=True)
class PrepFile:
    path: Path
    date: datetime
    size_bytes: int


@dataclass(frozen=True)
class EmailHit:
    """Placeholder for future Gmail integration."""
    subject: str
    sender: str
    received_at: datetime
    snippet: str


@dataclass(frozen=True)
class Company:
    name: str
    slug: str
    prep_files: list[PrepFile]
    research_traces: list[TraceRow]
    calendar_events: list[ProcessedEventRow]
    email_hits: list[EmailHit] = field(default_factory=list)

    @property
    def last_seen_at(self) -> datetime | None:
        """Most recent moment we touched this company across any source."""
        candidates: list[datetime] = []
        for p in self.prep_files:
            candidates.append(p.date)
        for t in self.research_traces:
            candidates.append(datetime.fromtimestamp(t.started_at))
        for e in self.calendar_events:
            candidates.append(datetime.fromtimestamp(e.processed_at))
        return max(candidates) if candidates else None

    @property
    def total_cost_usd(self) -> float:
        return sum(t.total_cost_usd for t in self.research_traces)

    @property
    def total_tokens(self) -> int:
        return sum(t.total_tokens for t in self.research_traces)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def aggregate_companies(
    prep_dir: Path,
    trace_store: TraceStore,
    calendar_store: CalendarStore,
    trace_limit: int = 500,
    calendar_limit: int = 500,
) -> list[Company]:
    """Return one Company entry per slug across all three sources."""
    # Group prep files by slug. Filename format: {slug}-{YYYY-MM-DD}.md
    files_by_slug: dict[str, list[PrepFile]] = {}
    name_by_slug: dict[str, str] = {}
    if prep_dir.exists():
        for path in prep_dir.glob("*.md"):
            s, display_name = _parse_prep_filename(path)
            if not s:
                continue
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            files_by_slug.setdefault(s, []).append(
                PrepFile(path=path, date=mtime, size_bytes=path.stat().st_size)
            )
            name_by_slug.setdefault(s, display_name)

    # Group research traces by slug-of-label.
    traces_by_slug: dict[str, list[TraceRow]] = {}
    for t in trace_store.list_traces(limit=trace_limit):
        if t.kind not in ("research", "eval_case"):
            continue
        s = slug(t.label)
        if not s:
            continue
        traces_by_slug.setdefault(s, []).append(t)
        name_by_slug.setdefault(s, t.label)

    # Group calendar events by company.
    events_by_slug: dict[str, list[ProcessedEventRow]] = {}
    for e in calendar_store.list_recent(limit=calendar_limit):
        if not e.company:
            continue
        s = slug(e.company)
        events_by_slug.setdefault(s, []).append(e)
        name_by_slug.setdefault(s, e.company)

    all_slugs = set(files_by_slug) | set(traces_by_slug) | set(events_by_slug)
    companies = [
        Company(
            name=name_by_slug.get(s, s),
            slug=s,
            prep_files=sorted(
                files_by_slug.get(s, []), key=lambda p: p.date, reverse=True
            ),
            research_traces=sorted(
                traces_by_slug.get(s, []), key=lambda t: t.started_at, reverse=True
            ),
            calendar_events=sorted(
                events_by_slug.get(s, []), key=lambda e: e.processed_at, reverse=True
            ),
        )
        for s in all_slugs
    ]

    # Surface most-recently-touched companies first.
    companies.sort(
        key=lambda c: c.last_seen_at or datetime.min, reverse=True
    )
    return companies


def _parse_prep_filename(path: Path) -> tuple[str, str]:
    """Filename format: {slug}-{YYYY-MM-DD}.md → (slug, display_name).

    Strips the trailing -YYYY-MM-DD suffix to derive the slug; capitalizes
    the slug as a fallback display name.
    """
    stem = path.stem
    m = re.match(r"^(.*)-(\d{4}-\d{2}-\d{2})$", stem)
    s = m.group(1) if m else stem
    display = " ".join(part.capitalize() for part in s.split("-"))
    return s, display
