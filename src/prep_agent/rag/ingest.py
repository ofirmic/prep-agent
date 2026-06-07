"""Ingestion: scan a directory of markdown files → chunk → embed → store.

Idempotent by design: chunk IDs are content-hashed, so re-running over an
unchanged file is a no-op upsert. Edit the playbook, re-run, only the changed
chunks get new IDs.

Defaults are tuned for the user's setup: scan ~/Documents and pick up the
known playbook files. Override via the `paths` parameter.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from prep_agent.rag.chunker import chunk_markdown_file
from prep_agent.rag.store import PlaybookStore

# The playbook docs we built earlier. Other markdown in ~/Documents is excluded
# by default to avoid embedding unrelated files (CVs, meeting notes, etc.).
DEFAULT_PLAYBOOK_FILES = (
    "interview-playbook.md",
    "interview-drill.md",
    "interview-hebrew.md",
    "amc-project-deepdive.md",
    "amc-deepdive-answers.md",
    "prep-agent-build-plan.md",
)


@dataclass(frozen=True)
class IngestReport:
    files_scanned: int
    files_skipped: int
    chunks_written: int


def discover_playbook_files(root: Path) -> list[Path]:
    """Find playbook files in `root`, in the order DEFAULT_PLAYBOOK_FILES lists.

    Missing files are silently skipped — we don't fail the whole ingest if the
    user hasn't created all the docs yet.
    """
    found: list[Path] = []
    for name in DEFAULT_PLAYBOOK_FILES:
        candidate = root / name
        if candidate.exists() and candidate.is_file():
            found.append(candidate)
    return found


def ingest(
    store: PlaybookStore,
    files: Iterable[Path],
) -> IngestReport:
    files = list(files)
    if not files:
        return IngestReport(files_scanned=0, files_skipped=0, chunks_written=0)

    all_chunks = []
    skipped = 0
    for path in files:
        try:
            all_chunks.extend(chunk_markdown_file(path))
        except OSError:
            skipped += 1
            continue

    written = store.upsert(all_chunks)
    return IngestReport(
        files_scanned=len(files) - skipped,
        files_skipped=skipped,
        chunks_written=written,
    )
