"""Structured types for calendar events and interview classifications."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Attendee:
    email: str
    display_name: str | None
    is_self: bool  # True for the calendar owner


@dataclass(frozen=True)
class CalendarEvent:
    """One Google Calendar event, normalized."""
    event_id: str
    summary: str
    description: str
    start: datetime
    end: datetime
    attendees: tuple[Attendee, ...]
    location: str | None
    hangout_link: str | None

    def external_attendee_emails(self) -> list[str]:
        """Non-self attendees, useful as a company-domain signal."""
        return [a.email for a in self.attendees if not a.is_self]


class InterviewClassification(BaseModel):
    """LLM-extracted summary of what kind of event this is."""
    is_interview: bool = Field(
        description="True if this is a hiring/recruiting/interview event."
    )
    company: str | None = Field(
        default=None,
        description="Best guess at the company name. Null if unclear.",
    )
    role_hint: str | None = Field(
        default=None,
        description="Role title mentioned in the event, e.g. 'Senior SWE'.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="0.0-1.0; how confident is the classification.",
    )
    reasoning: str = Field(
        default="",
        description="One sentence explaining the call. Used for debugging.",
    )
