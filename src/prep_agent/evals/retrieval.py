"""Retrieval evaluation — separate from generation evaluation.

The senior failure mode is conflating retrieval and generation: bad retrieval
looks like generation that's slightly off-topic, but the fix is in a different
file. We grade them independently.

Metric: keyword-based precision/recall on the `heading_path` of retrieved
chunks. For each golden case, `expected_topics` is a list of substrings;
a chunk "matches" a topic if any substring is in its heading_path.

This is a coarse metric — for ~50 docs and ~5 chunks/query it's enough.
For larger corpora, swap for semantic-similarity matching against gold sets.
"""
from __future__ import annotations

from dataclasses import dataclass

from prep_agent.rag.store import RetrievedChunk


@dataclass(frozen=True)
class RetrievalScore:
    company: str
    expected_topics: list[str]
    matched_topics: list[str]
    unmatched_topics: list[str]
    chunks_count: int

    @property
    def recall(self) -> float:
        if not self.expected_topics:
            return 1.0
        return len(self.matched_topics) / len(self.expected_topics)

    @property
    def precision(self) -> float:
        """Precision proxy: of retrieved chunks, fraction whose heading_path
        matches any expected topic. Coarse but interpretable.
        """
        if self.chunks_count == 0:
            return 0.0
        # Recomputed against the original chunks elsewhere; here we approximate
        # using matched_topics count as numerator capped at chunks_count.
        return min(len(self.matched_topics), self.chunks_count) / self.chunks_count


def score_retrieval(
    company: str,
    expected_topics: list[str],
    chunks: list[RetrievedChunk],
) -> RetrievalScore:
    if not expected_topics:
        return RetrievalScore(
            company=company,
            expected_topics=[],
            matched_topics=[],
            unmatched_topics=[],
            chunks_count=len(chunks),
        )
    haystack = " | ".join(c.heading_path for c in chunks).lower()
    matched: list[str] = []
    unmatched: list[str] = []
    for topic in expected_topics:
        if topic.lower() in haystack:
            matched.append(topic)
        else:
            unmatched.append(topic)
    return RetrievalScore(
        company=company,
        expected_topics=expected_topics,
        matched_topics=matched,
        unmatched_topics=unmatched,
        chunks_count=len(chunks),
    )
