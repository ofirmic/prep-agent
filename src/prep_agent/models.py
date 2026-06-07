"""Structured types crossing LLM boundaries.

Every contract with an LLM is a pydantic model. This is what makes the pipeline
debuggable: malformed outputs surface as validation errors, not silent drift.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """One web search hit from Tavily."""
    url: str
    title: str
    content: str
    score: float | None = None


class InterviewSignal(BaseModel):
    """A single concrete prep-relevant fact extracted from search results."""
    category: Literal[
        "company_overview",
        "tech_stack",
        "recent_news",
        "funding",
        "interview_format",
        "interview_question",
        "interview_process",  # rounds, timing, structure
        "specific_question_asked",  # actual question reported by past candidates
        "salary_data",  # comp ranges from levels.fyi / glassdoor
        "engineering_blog",  # links to public engineering content
        "growth_signals",  # hiring sprees, expansion
        "layoff_signals",  # layoffs, retention concerns
        "culture",
        "team",
    ]
    fact: str = Field(description="One concrete sentence. No hedging, no marketing copy.")
    source_url: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"


class CompanySignals(BaseModel):
    """Structured output of the extraction stage."""
    company: str
    one_liner: str = Field(description="What does this company do? Plain language, no buzzwords.")
    signals: list[InterviewSignal]
    extracted_at: datetime = Field(default_factory=datetime.utcnow)


class PrepDoc(BaseModel):
    """Final synthesis output. Sections are parsed best-effort; raw_markdown is canonical."""
    company: str
    summary: str
    likely_questions: list[str]
    specific_questions_reported: list[str] = []
    interview_process: list[str] = []
    talking_points: list[str]
    smart_questions_to_ask: list[str]
    red_flags_to_probe: list[str]
    salary_intel: list[str] = []
    raw_markdown: str
