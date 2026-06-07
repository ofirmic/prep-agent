"""LLM-based event classifier.

Why an LLM here:
- Calendar event titles are unstructured. "Ofir / Sarah - chat", "Phone screen",
  "[Chalk] Round 2", "Anthropic intro", "kickoff" all describe different things.
- The signal isn't just the title — attendee email domains + descriptions
  reinforce or contradict. Combining these by hand is regex hell.
- Provider-agnostic — works against Claude or Gemini.

Pre-filter by keyword first so we don't spend tokens on the user's normal
recurring meetings.
"""
from __future__ import annotations

from prep_agent.calendar.models import CalendarEvent, InterviewClassification
from prep_agent.obs.decorator import traced
from prep_agent.provider.types import ChatProvider

# Title keywords that suggest this might be hiring. Permissive on purpose;
# the LLM is the discriminator, this is just a token-cost guard.
_INTERVIEW_KEYWORDS = (
    "interview",
    "screen",
    "intro",
    "hiring",
    "recruit",
    "round",
    "coding",
    "tech chat",
    "tech call",
    "system design",
    "behavioral",
    "phone screen",
    "loop",
)


def looks_like_interview(event: CalendarEvent) -> bool:
    text = f"{event.summary}\n{event.description}".lower()
    return any(kw in text for kw in _INTERVIEW_KEYWORDS)


_SYSTEM = """You classify calendar events as interview or not, and pull the
company name when possible.

You receive: event title, description, attendee emails, location/conference.

Rules:
- An "interview" includes: phone screens, recruiter intros, tech screens,
  system design rounds, hiring manager chats, take-home review meetings,
  onsite loops. Recurring team standups, 1:1s, and internal meetings are NOT
  interviews.
- For company: prefer the most reliable signal in this order:
  1. An explicit company name in the title or description.
  2. The email domain of a non-self, non-personal attendee (skip
     @gmail.com, @yahoo.com, @outlook.com, @hotmail.com, @proton.me, @icloud.com).
  3. The candidate's own current employer is NOT a target company; if the only
     external attendee is from the candidate's own employer, this is internal.
- Confidence reflects whether you'd bet on this. <0.5 means you're guessing.
- Reasoning: one sentence. What signal drove the call.
"""

_PROMPT_TEMPLATE = """Classify this calendar event.

Title: {title}
Description:
{description}

Start: {start}
End: {end}
Location: {location}
Conference link: {link}

Attendees:
{attendees}

Candidate's own emails (treat their domains as internal, NOT target companies):
{self_emails}
"""


class EventExtractor:
    def __init__(self, provider: ChatProvider) -> None:
        self._provider = provider

    @traced("calendar_extract")
    async def classify(
        self,
        event: CalendarEvent,
        self_emails: list[str],
    ) -> InterviewClassification:
        attendees_block = (
            "\n".join(
                f"  - {a.email}"
                + (f" ({a.display_name})" if a.display_name else "")
                + (" [self]" if a.is_self else "")
                for a in event.attendees
            )
            or "  (none)"
        )
        return await self._provider.chat_structured(
            system=_SYSTEM,
            user=_PROMPT_TEMPLATE.format(
                title=event.summary,
                description=event.description or "(empty)",
                start=event.start.isoformat(),
                end=event.end.isoformat(),
                location=event.location or "(none)",
                link=event.hangout_link or "(none)",
                attendees=attendees_block,
                self_emails=", ".join(self_emails) or "(none provided)",
            ),
            schema=InterviewClassification,
            max_tokens=512,
        )
