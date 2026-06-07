"""Synthesis stage: CompanySignals + retrieved chunks → PrepDoc."""
from __future__ import annotations

from prep_agent.models import CompanySignals, PrepDoc
from prep_agent.obs.decorator import traced
from prep_agent.provider.types import ChatProvider
from prep_agent.rag.store import RetrievedChunk

_SYSTEM = """You are an interview prep coach for a senior software engineer.

You receive structured signals about a company AND relevant chunks from the
candidate's personal interview playbook. The candidate's flagship work is at
Skai (formerly Kenshoo) — the AMC integration on team Nexus, plus AI agents
and observability tooling. Your job is to map every interview topic to a
concrete Skai project the candidate can talk about.

Rules:
- Write to the candidate ("you"), not about them.
- Every section must be specific to THIS company's signals. No generic interview advice.
- When you use a playbook chunk, briefly cite it: "(from {source} > {heading})".
- **For every likely topic, name the Skai project that's the closest analog
  and a one-line bridge phrase the candidate can use to pivot.**
  Examples of analogs you should look for:
    - real-time feature serving → Skai's SingleStore tier for sub-second AMC dashboard reads
    - async data pipelines with completeness → Skai's AMC async API + Airflow polling
    - training-serving consistency / data freshness → Skai's Snowflake → SingleStore freshness handoff
    - multi-tenant SaaS isolation → Skai's per-customer scoping in AMC integration
    - LLM agents / AI eval → Skai's internal AI agents + observability tooling
    - cost / scaling reasoning → AMC project's per-component cost shape
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

## Interview topics they'll probably hit
The 5-7 topics most likely to come up, ranked HIGH/MED/LOW probability.
For EACH topic, write four lines:
  - **Topic** (HIGH/MED/LOW) — short label
  - **Why this comes up:** one sentence citing the specific signals that imply it
  - **Your Skai angle:** the closest project from the candidate's Skai work
  - **30-second pitch:** the actual sentences the candidate can say to bridge

## Interview process
What rounds, in what order, how long, what each round optimizes for.
Use only `interview_process` signals — if there are none, write "No specific
process details surfaced in search; ask the recruiter directly."

## Specific questions reported
Verbatim questions ex-candidates have reported being asked.
Use only `specific_question_asked` signals. If none, omit this section entirely.

## Likely questions
Concrete questions YOU should expect. Each item: the question + one-line Skai
angle to answer with.

## Talking points
How to connect the candidate's background to this company. Cite playbook
chunks where they fit. Each bullet: claim → which Skai experience supports it.

## Smart questions to ask
Forward-looking, signal seniority. Reference specific company facts from signals.

## Compensation intel
Salary ranges by level if `salary_data` signals exist. Else omit this section.

## Red flags to probe diplomatically
Surface `layoff_signals` + funding concerns + culture concerns. Phrase as
questions to ask diplomatically, not accusations.
"""

_DEFAULT_BACKGROUND = """Ofir Michaely — senior software engineer, 6 years at Skai (formerly Kenshoo) on team Nexus.

## Flagship Skai project: end-to-end AMC (Amazon Marketing Cloud) integration

- Java microservice consuming SQS messages from Dataset Manager MS, kicking
  Airflow DAGs that submit queries to AMC.
- HttpSensor polling per-DAG (chose isolation over central poller — cost is
  worker slots at scale, benefit is failure isolation).
- AWS Lambda for cross-account S3 result fetch (pre-signed URL with TTL trap,
  15-min hard cap, runtime+memory tuned, sits at the trust boundary between
  AMC's AWS account and Skai's).
- Snowflake for analytical storage (raw + enriched tables + ConversionAggregator
  rollups by campaign + time bucket).
- SingleStore for sub-second dashboard serving (the warehouse-vs-serving split,
  reverse ETL via signleStoreWriter).
- Status callback via separate SQS queue (decoupled because Airflow shouldn't
  hold DB credentials; idempotent because UPDATE status='SUCCEEDED' is a no-op
  on second run).
- Architecture challenges led: cross-account IAM design, per-stage idempotency,
  multi-tenancy isolation (every row tenant-scoped, query tag cost attribution),
  stuck-job sweep DAG for lost SQS messages, schema-as-versioned-interface at
  the Snowflake → SingleStore boundary.

## Recent work (Skai AI tooling)

- Built AI agents that automated the AMC workflow.
- Internal LLM observability tooling — per-call tracing, cost shape, eval harness.

## Stack

Java (Spring), Python, SQL, AWS (SQS, Lambda, IAM, S3), Snowflake, SingleStore,
Airflow, Kafka. Strong on distributed systems + data pipelines.

## What this candidate is looking for

AI Engineer / ML Platform / Backend Infra roles. Real engineering depth,
customer-adjacent problems, early-to-mid stage scope. Prefers in-person or
hybrid in Israel; open to international roles."""


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
        predicted_topics=_bullets(
            sections.get("interview topics they'll probably hit", "")
        ),
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
