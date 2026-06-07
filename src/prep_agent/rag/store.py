"""Vector store wrapper around ChromaDB persistent client.

The wrapper exists so the rest of the code talks to a tiny stable API.
If we later move to pgvector or LanceDB, only this file changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import chromadb
from chromadb.config import Settings as ChromaSettings

from prep_agent.rag.chunker import Chunk
from prep_agent.rag.embeddings import Embedder


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk plus its retrieval score and metadata."""
    chunk_id: str
    source: str
    heading_path: str
    content: str
    distance: float


class PlaybookStore:
    def __init__(
        self,
        embedder: Embedder,
        persist_dir: Path,
        collection_name: str,
    ) -> None:
        self._embedder = embedder
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        # Cosine distance is the right metric for sentence embeddings;
        # L2 happens to work on normalized vectors but cosine is the honest answer.
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, chunks: list[Chunk]) -> int:
        """Upsert chunks. Returns count of vectors written.

        Idempotent: upserting the same chunk_id twice replaces, doesn't dupe.
        """
        if not chunks:
            return 0
        embeddings = self._embedder.embed([c.content for c in chunks])
        self._collection.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=cast(Any, embeddings),
            documents=[c.content for c in chunks],
            metadatas=[
                {"source": c.source, "heading_path": c.heading_path}
                for c in chunks
            ],
        )
        return len(chunks)

    def query(self, query_text: str, top_k: int = 5) -> list[RetrievedChunk]:
        """Embed query, retrieve top-k nearest chunks by cosine distance."""
        if self._collection.count() == 0:
            return []
        [query_vec] = self._embedder.embed([query_text])
        raw = self._collection.query(
            query_embeddings=cast(Any, [query_vec]),
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        results: list[RetrievedChunk] = []
        ids = (raw.get("ids") or [[]])[0]
        docs = (raw.get("documents") or [[]])[0]
        metas = (raw.get("metadatas") or [[]])[0]
        dists = (raw.get("distances") or [[]])[0]
        for chunk_id, doc, meta, dist in zip(ids, docs, metas, dists, strict=False):
            results.append(
                RetrievedChunk(
                    chunk_id=str(chunk_id),
                    source=str(meta.get("source", "")),
                    heading_path=str(meta.get("heading_path", "")),
                    content=str(doc),
                    distance=float(dist),
                )
            )
        return results

    def count(self) -> int:
        return self._collection.count()
