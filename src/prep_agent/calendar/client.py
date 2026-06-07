"""Google Calendar API wrapper.

Only one read endpoint — events.list — because that's all this tool does.
Anything else (writing events, watching, batching) would be a different file.

The wrapper exists to (a) translate the API's loose dict shape into the
typed CalendarEvent model, and (b) keep all googleapiclient quirks in one
place. Adding a different calendar source (Outlook, CalDAV) becomes "implement
this interface" instead of "rewrite sync.py".
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from prep_agent.calendar.models import Attendee, CalendarEvent


class GoogleCalendarClient:
    def __init__(self, credentials: Credentials) -> None:
        # cache_discovery=False avoids file-system writes to a global cache;
        # better for sandboxed/CI environments and faster cold start.
        self._service = build(
            "calendar", "v3", credentials=credentials, cache_discovery=False
        )

    def list_events(
        self,
        calendar_id: str = "primary",
        days_ahead: int = 7,
    ) -> list[CalendarEvent]:
        now = datetime.now(UTC)
        end = now + timedelta(days=days_ahead)
        resp = (
            self._service.events()
            .list(
                calendarId=calendar_id,
                timeMin=_iso(now),
                timeMax=_iso(end),
                singleEvents=True,
                orderBy="startTime",
                maxResults=100,
            )
            .execute()
        )
        return [_to_event(item) for item in resp.get("items", []) if _has_time(item)]


def _has_time(item: dict[str, Any]) -> bool:
    """Filter out all-day events — they're never interviews."""
    return "dateTime" in item.get("start", {})


def _to_event(item: dict[str, Any]) -> CalendarEvent:
    start = _parse_dt(item["start"]["dateTime"])
    end = _parse_dt(item["end"]["dateTime"])
    attendees = tuple(_to_attendee(a) for a in item.get("attendees", []))
    return CalendarEvent(
        event_id=item["id"],
        summary=item.get("summary", "(no title)"),
        description=item.get("description", ""),
        start=start,
        end=end,
        attendees=attendees,
        location=item.get("location"),
        hangout_link=item.get("hangoutLink"),
    )


def _to_attendee(raw: dict[str, Any]) -> Attendee:
    return Attendee(
        email=raw.get("email", ""),
        display_name=raw.get("displayName"),
        is_self=bool(raw.get("self", False)),
    )


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_dt(s: str) -> datetime:
    # API returns RFC3339; fromisoformat handles "+HH:MM" but not "Z".
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
