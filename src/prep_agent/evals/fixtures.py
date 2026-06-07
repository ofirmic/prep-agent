"""Snapshot fixtures: cached signals + chunks per company.

Why fixtures matter:
- Evals must be reproducible. If every run hits Tavily + Anthropic for
  extraction, you can't compare today's synthesis-prompt change against
  yesterday's because the inputs differ.
- Fixtures freeze the inputs (signals + retrieved chunks) so evals isolate
  what they're actually measuring: synthesis quality.
- Regenerate a fixture on purpose with `prep-agent eval snapshot <company>`.

Layout: evals/fixtures/{slug}.json
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from prep_agent.models import CompanySignals
from prep_agent.rag.store import RetrievedChunk


@dataclass(frozen=True)
class Fixture:
    company: str
    signals: CompanySignals
    chunks: list[RetrievedChunk]
    captured_at: datetime

    def chunks_text(self) -> str:
        if not self.chunks:
            return "(no chunks retrieved)"
        return "\n\n".join(
            f"### Chunk {i + 1} — {c.source} > {c.heading_path}\n{c.content}"
            for i, c in enumerate(self.chunks)
        )


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fixture_path(fixtures_dir: Path, company: str) -> Path:
    return fixtures_dir / f"{slug(company)}.json"


def save_fixture(
    fixtures_dir: Path,
    company: str,
    signals: CompanySignals,
    chunks: list[RetrievedChunk],
) -> Path:
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    path = fixture_path(fixtures_dir, company)
    payload = {
        "company": company,
        "captured_at": datetime.utcnow().isoformat(),
        "signals": signals.model_dump(mode="json"),
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "source": c.source,
                "heading_path": c.heading_path,
                "content": c.content,
                "distance": c.distance,
            }
            for c in chunks
        ],
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def load_fixture(fixtures_dir: Path, company: str) -> Fixture | None:
    path = fixture_path(fixtures_dir, company)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Fixture(
        company=raw["company"],
        signals=CompanySignals.model_validate(raw["signals"]),
        chunks=[
            RetrievedChunk(
                chunk_id=c["chunk_id"],
                source=c["source"],
                heading_path=c["heading_path"],
                content=c["content"],
                distance=c["distance"],
            )
            for c in raw["chunks"]
        ],
        captured_at=datetime.fromisoformat(raw["captured_at"]),
    )
