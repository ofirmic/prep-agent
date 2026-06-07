"""Extraction stage: raw search results → structured CompanySignals.

Provider-agnostic. The ChatProvider abstracts whether we're using Claude's
tool-use or Gemini's native response_schema under the hood.
"""
from __future__ import annotations

import json

from prep_agent.models import CompanySignals, SearchResult
from prep_agent.obs.decorator import traced
from prep_agent.provider.types import ChatProvider

_SYSTEM = """You extract structured interview-prep signals from web search results.

Rules:
- Every fact is one concrete sentence. No marketing language ("cutting-edge", "innovative", "leading").
- No hedging ("seems to", "appears to"). State or omit.
- Prefer dates, numbers, named people, named technologies.
- If a search snippet is generic boilerplate, skip it. Quality over quantity.

Pay special attention to these high-value signal types:
- **specific_question_asked**: exact interview questions reported by past
  candidates (Glassdoor, Reddit, Blind). Quote them verbatim.
- **interview_process**: number of rounds, types (phone screen, system design,
  behavioral, take-home), timing from application to offer, recruiter style.
- **salary_data**: comp ranges by level from levels.fyi or Glassdoor. Include
  the level name and the range, e.g. "L4 SWE: $200-280k total comp".
- **layoff_signals**: any reports of recent layoffs, RIFs, hiring freezes —
  these matter for risk assessment.
- **growth_signals**: hiring sprees, new offices, recent funding, headcount growth.

Extract as many distinct facts as you can find. 15-25 signals is typical for a
well-documented company. Empty categories are fine — don't fabricate.
"""

_PROMPT_TEMPLATE = """Extract interview-prep signals for: {company}

Search results (JSON):
{results}"""


class Extractor:
    def __init__(self, provider: ChatProvider) -> None:
        self._provider = provider

    @traced("extract")
    async def extract(self, company: str, results: list[SearchResult]) -> CompanySignals:
        results_json = json.dumps(
            [r.model_dump() for r in results], indent=2, default=str
        )
        return await self._provider.chat_structured(
            system=_SYSTEM,
            user=_PROMPT_TEMPLATE.format(company=company, results=results_json),
            schema=CompanySignals,
            max_tokens=4096,
        )
