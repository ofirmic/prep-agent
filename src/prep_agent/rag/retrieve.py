"""Retriever: CompanySignals → relevant playbook chunks.

Key insight: don't embed the company name and hope for the best. Build a
*retrieval query* that describes the situation in vocabulary the playbook
chunks were written in.

Strategy: combine the company one-liner with the categories of signals we
actually found. A company with `tech_stack` + `interview_format` signals
should pull different playbook chunks than one with only `funding` + `culture`.
"""
from __future__ import annotations

from prep_agent.models import CompanySignals
from prep_agent.rag.store import PlaybookStore, RetrievedChunk

# Mapping from extracted signal categories → playbook topic vocabulary.
# The right side is what's likely to appear in YOUR playbook docs.
_CATEGORY_HINTS = {
    "company_overview": "company background and product positioning",
    "tech_stack": "system design technical interview backend distributed systems",
    "recent_news": "current events business context",
    "funding": "startup stage Series A scope ownership",
    "interview_format": "interview process structure rounds preparation",
    "interview_question": "common interview questions answer framework",
    "culture": "behavioral interview team fit values",
    "team": "team structure engineering org",
}


class Retriever:
    def __init__(self, store: PlaybookStore, top_k: int = 6) -> None:
        self._store = store
        self._top_k = top_k

    def retrieve(self, signals: CompanySignals) -> list[RetrievedChunk]:
        """Build a query from signals, return top-k playbook chunks."""
        if self._store.count() == 0:
            return []
        query = _build_query(signals)
        return self._store.query(query, top_k=self._top_k)


def _build_query(signals: CompanySignals) -> str:
    """Compose a retrieval query that gives the embedder enough signal to
    discriminate between playbook topics.

    Pure company name is a terrible query — it won't match anything in the
    playbook because the playbook doesn't mention the company. Use the
    *categories* of facts we found as the bridge between company and topics.
    """
    categories = {s.category for s in signals.signals}
    hint_phrases = [_CATEGORY_HINTS[c] for c in categories if c in _CATEGORY_HINTS]
    parts = [
        signals.one_liner,
        *hint_phrases,
    ]
    return " | ".join(p for p in parts if p)
