"""Orchestrator: company name → PrepDoc.

Each stage is testable on its own; this just wires them.

Provider-agnostic: at construction we ask the factory for two ChatProviders
(one per stage). Whether that's Anthropic or Gemini is decided by Settings.
"""
from __future__ import annotations

from prep_agent.config import Settings
from prep_agent.models import PrepDoc
from prep_agent.obs.context import trace_context
from prep_agent.obs.store import TraceStore
from prep_agent.provider.factory import make_provider
from prep_agent.rag.embeddings import FastEmbedEmbedder
from prep_agent.rag.retrieve import Retriever
from prep_agent.rag.store import PlaybookStore
from prep_agent.research.extract import Extractor
from prep_agent.research.search import SearchClient
from prep_agent.synthesize.generate import Synthesizer


def _queries_for(company: str) -> list[str]:
    """Search queries we run in parallel for one research.

    Mix of:
    - general company / tech stack / news (catch-all)
    - site-targeted queries to known interview/comp data sources
      (Tavily caches a lot of Glassdoor + Reddit content even when those sites
       block direct scraping)
    - tone-checking queries (Reddit, HN, Blind discussions)
    """
    return [
        # Core
        f"{company} company what they do product 2026",
        f"{company} engineering tech stack",
        f"{company} funding stage employees layoffs",
        # Interview-specific (high-value, often hits Glassdoor cache)
        f"{company} interview questions glassdoor software engineer",
        f"{company} interview process rounds software engineer",
        f"{company} reddit interview experience",
        # Compensation
        f"{company} salary levels.fyi software engineer",
        # Engineering signal
        f"{company} engineering blog architecture",
        # Recent / Hacker News signal
        f"{company} hacker news discussion",
    ]


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.trace_store = TraceStore(db_path=settings.trace_db_path)

        # Build providers — same factory drives Anthropic vs Gemini.
        extract_provider = make_provider(
            settings, model=settings.extract_model, trace_store=self.trace_store
        )
        synth_provider = make_provider(
            settings, model=settings.synthesize_model, trace_store=self.trace_store
        )
        # Exposed so other consumers (calendar sync) can reuse the same
        # extract provider rather than constructing another one.
        self.extract_provider = extract_provider
        self.synth_provider = synth_provider

        embedder = FastEmbedEmbedder(model_name=settings.embedding_model)
        store = PlaybookStore(
            embedder=embedder,
            persist_dir=settings.chroma_dir,
            collection_name=settings.playbook_collection,
        )
        self._search = SearchClient(api_key=settings.tavily_api_key)
        self._extract = Extractor(provider=extract_provider)
        self._retrieve = Retriever(store=store)
        self._synth = Synthesizer(provider=synth_provider)

    async def run(self, company: str) -> PrepDoc:
        async with trace_context(self.trace_store, label=company, kind="research"):
            results = await self._search.search_many(_queries_for(company))
            signals = await self._extract.extract(company, results)
            chunks = self._retrieve.retrieve(signals)
            return await self._synth.synthesize(signals, playbook_chunks=chunks)
