"""LLM-as-judge rubric.

Why this exists:
- LLM outputs are non-deterministic; "iterate on prompts based on vibes" is
  the senior failure mode. The eval harness is what makes iteration scientific.
- Four axes that catch the four common failure modes of LLM-generated prep:
  1. Specificity      — generic platitudes vs concrete company-grounded advice
  2. Grounding        — hallucinated facts vs claims tied to retrieved evidence
  3. Actionability    — vague guidance vs "do this before the interview"
  4. Personalization  — generic frameworks vs the candidate's own playbook

Provider-agnostic. The judge could be Claude or Gemini; what matters is the
structured rubric output is validated against the pydantic schema.

Calibration is the senior signal: once we have ~3 cases I manually graded,
we compare LLM scores against my scores. Disagreement > 1 on any axis flags
a judge prompt that needs tightening.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from prep_agent.obs.decorator import traced
from prep_agent.provider.types import ChatProvider

JUDGE_AXES = ("specificity", "grounding", "actionability", "personalization")
AxisName = Literal["specificity", "grounding", "actionability", "personalization"]


class AxisScore(BaseModel):
    axis: AxisName
    score: int = Field(ge=1, le=5)
    reasoning: str = Field(description="One sentence — what evidence supports this score.")
    citation: str = Field(
        default="",
        description="Quote from the prep doc or input that justifies the score. Empty if N/A.",
    )


class RubricResult(BaseModel):
    company: str
    scores: list[AxisScore]
    overall_notes: str = Field(
        default="",
        description="One paragraph summarizing the verdict. What's strong; what to fix.",
    )

    @property
    def mean(self) -> float:
        if not self.scores:
            return 0.0
        return sum(s.score for s in self.scores) / len(self.scores)

    def by_axis(self) -> dict[str, AxisScore]:
        return {s.axis: s for s in self.scores}


_SYSTEM = """You are a strict but fair evaluator for AI-generated interview prep docs.

You will receive:
1. The generated prep doc.
2. The signals used to generate it (facts extracted about the company).
3. The retrieved playbook chunks used to personalize it.
4. The golden criteria — what a good doc MUST mention and what's forbidden.

Grade the prep doc on four 1-5 axes. Use the full range:
- 1: completely fails this axis
- 3: meets the bar, nothing special
- 5: exceptional — clearly leverages the input

Strict rules:
- Grounding: if the doc states a fact, you must be able to point to its origin
  in the signals OR the playbook chunks. Generic interview wisdom is NOT grounded.
- Specificity: "be enthusiastic about Chalk's mission" is GENERIC. "Mention that
  Chalk's Rust-speed feature platform maps to your AMC SingleStore serving tier
  experience" is SPECIFIC.
- Personalization: scores 5 only if the doc explicitly uses frameworks or
  vocabulary from the retrieved playbook chunks (cite them).
- Actionability: the candidate should know exactly what to do/say/ask. Scoring 5
  requires concrete prep actions.

For each axis, return {score, reasoning, citation}. Then overall_notes."""

_PROMPT_TEMPLATE = """Evaluate this prep doc for **{company}**.

## Prep doc to grade
{prep_doc}

## Signals (extracted facts)
{signals}

## Retrieved playbook chunks
{chunks}

## Golden criteria
{golden}
"""


class Judge:
    def __init__(self, provider: ChatProvider) -> None:
        self._provider = provider

    @traced("judge")
    async def grade(
        self,
        company: str,
        prep_doc: str,
        signals_json: str,
        chunks_text: str,
        golden_text: str,
    ) -> RubricResult:
        return await self._provider.chat_structured(
            system=_SYSTEM,
            user=_PROMPT_TEMPLATE.format(
                company=company,
                prep_doc=prep_doc,
                signals=signals_json,
                chunks=chunks_text,
                golden=golden_text,
            ),
            schema=RubricResult,
            max_tokens=2048,
        )
