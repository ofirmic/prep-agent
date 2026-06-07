"""Golden set: companies + expected criteria for the prep doc.

The golden set is the ground truth — what we'd write by hand for a great prep
doc. It's intentionally small (3-5 cases): the goal isn't statistical coverage,
it's catching regressions in the dimensions we care about.

A case has three parts:
- must_mention_topics: facts/themes the doc MUST surface. Tested by judge.
- must_connect_to_background: candidate-background hooks the doc MUST use.
- forbidden: things the doc must NOT do (generic advice, hallucinated facts).
- retrieval.expected_topics: substrings expected to appear in retrieved chunks'
  heading_path. Measured separately as retrieval precision/recall.

Manual scores (optional) let us calibrate the LLM judge against my own grading.
If LLM-judge mean disagrees with my mean by >1, the judge prompt needs work.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RetrievalExpectations:
    expected_topics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GoldenCase:
    company: str
    one_liner: str
    must_mention_topics: list[str]
    must_connect_to_background: list[str]
    forbidden: list[str]
    retrieval: RetrievalExpectations
    manual_scores: dict[str, int] | None = None  # axis -> 1..5, optional

    def golden_text(self) -> str:
        """Render the criteria as text for the judge prompt."""
        parts = [
            f"One-liner: {self.one_liner}",
            "Must mention topics:",
            *(f"  - {t}" for t in self.must_mention_topics),
            "Must connect to candidate background:",
            *(f"  - {b}" for b in self.must_connect_to_background),
            "Forbidden:",
            *(f"  - {f}" for f in self.forbidden),
        ]
        return "\n".join(parts)


def load_golden(path: Path) -> list[GoldenCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected list at top level of {path}, got {type(raw).__name__}")
    return [_parse_case(item) for item in raw]


def _parse_case(item: dict[str, Any]) -> GoldenCase:
    retrieval_raw = item.get("retrieval", {}) or {}
    return GoldenCase(
        company=item["company"],
        one_liner=item["one_liner"],
        must_mention_topics=list(item.get("must_mention_topics", [])),
        must_connect_to_background=list(item.get("must_connect_to_background", [])),
        forbidden=list(item.get("forbidden", [])),
        retrieval=RetrievalExpectations(
            expected_topics=list(retrieval_raw.get("expected_topics", []))
        ),
        manual_scores=item.get("manual_scores"),
    )
