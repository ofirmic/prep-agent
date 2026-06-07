"""Embeddings.

Default: FastEmbed local ONNX model. No API key, no per-call cost.

The Embedder Protocol is the seam. To swap to Voyage (Anthropic's recommended
partner) or OpenAI, implement the Protocol and wire it in `pipeline.py`.

Why local for this project:
- Personal use: ~50 docs, batch ingest once a month at most. API cost is
  rounding error but a vendor relationship is real friction.
- Portfolio narrative: "I picked the embedding tier that matched the workload
  shape" reads more senior than "I defaulted to the most popular cloud API."
"""
from __future__ import annotations

from typing import Protocol

from fastembed import TextEmbedding


class Embedder(Protocol):
    """One method, two contracts: embeds, and tells you its output dimension."""

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


# Model dimensions — declared here, asserted at first embed so a misconfigured
# env var fails loudly instead of silently corrupting the vector store.
_MODEL_DIMENSIONS = {
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
}


class FastEmbedEmbedder:
    """Local ONNX embeddings via FastEmbed."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        if model_name not in _MODEL_DIMENSIONS:
            raise ValueError(
                f"Unknown model {model_name!r}. Known: {sorted(_MODEL_DIMENSIONS)}"
            )
        self._model_name = model_name
        self._model = TextEmbedding(model_name=model_name)
        self._dimension = _MODEL_DIMENSIONS[model_name]

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # FastEmbed returns a generator of numpy arrays.
        vectors = [v.tolist() for v in self._model.embed(texts)]
        # Belt-and-braces: assert the contract at the boundary.
        if vectors and len(vectors[0]) != self._dimension:
            raise RuntimeError(
                f"Embedder produced dim={len(vectors[0])}, expected {self._dimension}. "
                "This likely means the model changed under us."
            )
        return vectors
