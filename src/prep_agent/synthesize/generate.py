"""Synthesis stage: CompanySignals + retrieved chunks → PrepDoc."""
from __future__ import annotations

from prep_agent.models import CompanySignals, PrepDoc
from prep_agent.obs.decorator import traced
from prep_agent.provider.types import ChatProvider
from prep_agent.rag.store import RetrievedChunk

_SYSTEM = """You are an interview prep coach for a senior software engineer.

You receive structured signals about a company AND relevant chunks from the
candidate's personal interview playbook. Produce a focused prep doc that
*uses the candidate's own frameworks* to tailor advice — quote, cite, and apply
the playbook chunks where they fit. Do not invent frameworks the playbook
doesn't have.

Rules:
- Write to the candidate ("you"), not about them.
- Every section must be specific to THIS company's signals. No generic interview advice.
- When you use a playbook chunk, briefly cite it: "(from {source} > {heading})".
- Likely questions: derive from tech stack, stage, and pain points implied by the signals.
- Talking points: connect the candidate's background to what this company values, using
  vocabulary from the playbook when it fits.
- Smart questions: forward-looking, signal seniority. Avoid "what's the culture like."
- Red flags: things to verify (funding runway, churn signals, attrition) in interviews.
  Phrase as questions to ask diplomatically.
- Output clean markdown. No preamble, no "Here is your prep doc."
"""

_PROMPT_TEMPLATE = """Generate interview prep for **{company}**.

## Signals
{signals}

## Candidate background
{background}

## Relevant playbook chunks (retrieved by RAG over candidate's own docs)
{playbook}

Produce markdown with EXACTLY these section headers in this order:

## TL;DR
3-5 sentences. What this company does, stage, why they hire engineers, tone.

## Interview process
What rounds, in what order, how long, what each round optimizes for.
Use only `interview_process` signals — if there are none, write "No specific
process details surfaced in search; ask the recruiter directly."

## Specific questions reported
Verbatim questions ex-candidates have reported being asked.
Use only `specific_question_asked` signals. If none, omit this section entirely.

## Likely questions
Questions YOU should expect, derived from tech stack, scale, recent news, and
the candidate's background. Each item: the question + a one-line answer angle.

## Talking points
How to connect the candidate's background to this company. Cite playbook
chunks where they fit. Each bullet: claim → which experience supports it.

## Smart questions to ask
Forward-looking, signal seniority. Reference specific company facts from signals.

## Compensation intel
Salary ranges by level if `salary_data` signals exist. Else omit this section.

## Red flags to probe diplomatically
Surface `layoff_signals` + funding concerns + culture concerns. Phrase as
questions to ask diplomatically, not accusations.
"""

_DEFAULT_BACKGROUND = """Senior software engineer, 6 years at Skai (formerly Kenshoo) on team Nexus.
Flagship project: end-to-end AMC (Amazon Marketing Cloud) integration —
SQS-driven Java microservice, Airflow DAGs, AWS Lambda for S3 result fetch,
Snowflake for analytical storage, SingleStore for sub-second serving.
Recently built AI agents and internal LLM observability tooling.
Targeting: AI Engineer / ML Platform / Backend Infra roles.
Comfortable in Java, Python, distributed systems, AWS.
Looking for: real engineering depth, customer-adjacent problems, early-stage scope."""


class Synthesizer:
    def __init__(self, provider: ChatProvider) -> None:
        self._provider = provider

    @traced("synthesize")
    async def synthesize(
        self,
        signals: CompanySignals,
        playbook_chunks: list[RetrievedChunk] | None = None,
        background: str | None = None,
    ) -> PrepDoc:
        markdown = await self._provider.chat_text(
            system=_SYSTEM,
            user=_PROMPT_TEMPLATE.format(
                company=signals.company,
                signals=signals.model_dump_json(indent=2),
                background=background or _DEFAULT_BACKGROUND,
                playbook=_format_playbook(playbook_chunks or []),
            ),
            max_tokens=4096,
        )
        return _parse(signals.company, markdown)


def _format_playbook(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(no playbook ingested — run `prep-agent ingest` to enable personalization)"
    return "\n\n".join(
        f"### Chunk {i + 1} — {c.source} > {c.heading_path}\n{c.content}"
        for i, c in enumerate(chunks)
    )


def _parse(company: str, markdown: str) -> PrepDoc:
    sections = _split_sections(markdown)
    return PrepDoc(
        company=company,
        summary=sections.get("tl;dr", "").strip(),
        interview_process=_bullets(sections.get("interview process", "")),
        specific_questions_reported=_bullets(
            sections.get("specific questions reported", "")
        ),
        likely_questions=_bullets(sections.get("likely questions", "")),
        talking_points=_bullets(sections.get("talking points", "")),
        smart_questions_to_ask=_bullets(sections.get("smart questions to ask", "")),
        salary_intel=_bullets(sections.get("compensation intel", "")),
        red_flags_to_probe=_bullets(sections.get("red flags to probe", "")),
        raw_markdown=markdown,
    )


def _split_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_key: str | None = None
    buf: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if current_key is not None:
                sections[current_key] = "\n".join(buf).strip()
            current_key = line[3:].strip().lower().rstrip(":")
            current_key = current_key.split("(")[0].strip()
            buf = []
        else:
            buf.append(line)
    if current_key is not None:
        sections[current_key] = "\n".join(buf).strip()
    return sections


def _bullets(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            cleaned = s.lstrip("-*0123456789.").strip()
            if cleaned:
                out.append(cleaned)
    return out
