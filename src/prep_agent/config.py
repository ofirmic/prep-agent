"""Runtime config loaded from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv()


ProviderName = Literal["anthropic", "gemini"]


@dataclass(frozen=True)
class Settings:
    llm_provider: ProviderName
    # Only the active provider's key is required; the other is optional.
    anthropic_api_key: str
    gemini_api_key: str
    tavily_api_key: str
    extract_model: str
    synthesize_model: str
    output_dir: Path
    embedding_model: str
    chroma_dir: Path
    playbook_collection: str
    trace_db_path: Path
    google_client_secret_path: Path
    google_token_path: Path
    google_calendar_id: str

    @classmethod
    def from_env(cls) -> Settings:
        default_google_dir = Path.home() / ".config" / "prep-agent"
        provider = _provider_from_env()

        # Sensible default models per provider. Override via env if needed.
        if provider == "gemini":
            default_extract = "gemini-2.5-flash"
            default_synth = "gemini-2.5-flash"
        else:
            default_extract = "claude-haiku-4-5-20251001"
            default_synth = "claude-sonnet-4-6"

        return cls(
            llm_provider=provider,
            anthropic_api_key=_require_for(provider == "anthropic", "ANTHROPIC_API_KEY"),
            gemini_api_key=_require_for(provider == "gemini", "GEMINI_API_KEY"),
            tavily_api_key=_require("TAVILY_API_KEY"),
            extract_model=os.getenv("EXTRACT_MODEL", default_extract),
            synthesize_model=os.getenv("SYNTHESIZE_MODEL", default_synth),
            output_dir=Path(os.getenv("OUTPUT_DIR", "./prep")).expanduser().resolve(),
            embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
            chroma_dir=Path(os.getenv("CHROMA_DIR", "./.chroma")).expanduser().resolve(),
            playbook_collection=os.getenv("PLAYBOOK_COLLECTION", "playbook"),
            trace_db_path=Path(os.getenv("TRACE_DB_PATH", "./traces.sqlite"))
            .expanduser()
            .resolve(),
            google_client_secret_path=Path(
                os.getenv(
                    "GOOGLE_CLIENT_SECRET_PATH",
                    str(default_google_dir / "google_client_secret.json"),
                )
            ).expanduser(),
            google_token_path=Path(
                os.getenv(
                    "GOOGLE_TOKEN_PATH",
                    str(default_google_dir / "google_token.json"),
                )
            ).expanduser(),
            google_calendar_id=os.getenv("GOOGLE_CALENDAR_ID", "primary"),
        )


def _provider_from_env() -> ProviderName:
    raw = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
    if raw not in ("anthropic", "gemini"):
        raise RuntimeError(
            f"Invalid LLM_PROVIDER={raw!r}. Must be 'anthropic' or 'gemini'."
        )
    return raw  # type: ignore[return-value]


def _require_for(active: bool, name: str) -> str:
    """Required only when the corresponding provider is active."""
    val = os.getenv(name, "")
    if active and not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val
