"""Markdown chunker.

Strategy: split by H2/H3 headers. Interview-prep markdown is already
topic-organized — semantic boundaries beat character-count splitting.

Each chunk carries its heading path so retrieval results stay interpretable
("from Part 3.2 — The custom asset concept") instead of free-floating snippets.

Fallback: if a single H2/H3 section is too large for the embedding model's
context budget, split it by paragraphs. We never silently truncate.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

# bge-small-en-v1.5 has a 512-token limit. ~4 chars per token → ~2000 chars
# safe budget. Use ~1800 to leave headroom for the heading prefix.
_MAX_CHARS_PER_CHUNK = 1800


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit of playbook content."""
    chunk_id: str  # deterministic hash → safe upsert
    source: str  # filename
    heading_path: str  # "Part 3 — Result flow > 3.2 — Custom asset concept"
    content: str
    char_count: int


def chunk_markdown_file(path: Path) -> list[Chunk]:
    """Read a markdown file and split it into Chunks."""
    text = path.read_text(encoding="utf-8")
    raw_sections = _split_by_headers(text)
    chunks: list[Chunk] = []
    for heading_path, section_text in raw_sections:
        for piece in _split_oversized(section_text):
            content = f"{heading_path}\n\n{piece}".strip()
            chunks.append(
                Chunk(
                    chunk_id=_hash(path.name, heading_path, piece),
                    source=path.name,
                    heading_path=heading_path,
                    content=content,
                    char_count=len(content),
                )
            )
    return chunks


def _split_by_headers(text: str) -> list[tuple[str, str]]:
    """Walk the doc, accumulating sections keyed by their H2 > H3 path.

    Lines before the first H2 are dropped (usually title + intro fluff).
    """
    sections: list[tuple[str, str]] = []
    current_h2: str | None = None
    current_h3: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        if current_h2 is None:
            buf = []
            return
        body = "\n".join(buf).strip()
        if not body:
            buf = []
            return
        path = current_h2 if current_h3 is None else f"{current_h2} > {current_h3}"
        sections.append((path, body))
        buf = []

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            current_h2 = line[3:].strip()
            current_h3 = None
        elif line.startswith("### "):
            flush()
            current_h3 = line[4:].strip()
        else:
            buf.append(line)
    flush()
    return sections


def _split_oversized(text: str) -> list[str]:
    """If a section is over budget, split by paragraphs.

    We never break mid-paragraph — that destroys the semantic signal the
    embedder relies on. If a single paragraph blows the budget, we emit it
    anyway and let the embedder truncate; the alternative (silent splitting
    mid-sentence) is worse.
    """
    if len(text) <= _MAX_CHARS_PER_CHUNK:
        return [text]
    paragraphs = re.split(r"\n\s*\n", text)
    out: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if buf_len + len(para) > _MAX_CHARS_PER_CHUNK and buf:
            out.append("\n\n".join(buf))
            buf = [para]
            buf_len = len(para)
        else:
            buf.append(para)
            buf_len += len(para) + 2
    if buf:
        out.append("\n\n".join(buf))
    return out


def _hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]
