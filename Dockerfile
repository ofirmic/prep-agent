# syntax=docker/dockerfile:1.7
# ---------- Stage 1: builder ----------
# uv handles the lockfile + venv. Doing this in a builder stage keeps build
# tools and cache out of the runtime image.
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Install uv via the official installer (smaller surface than pip-install-uv).
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# Layer caching: copy lockfile + project metadata FIRST, then sync, THEN copy
# the source. Source edits don't bust the dep layer.
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN uv sync --frozen --no-dev

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    # FastEmbed downloads ONNX models the first time; cache to a writable dir.
    HF_HOME=/data/hf-cache \
    FASTEMBED_CACHE=/data/fastembed-cache

# Streamlit + chromadb need a few runtime libs; nothing else is required.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -r app && useradd -r -g app -d /app app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/
COPY pyproject.toml uv.lock README.md ./

# Optional: bake playbook docs into the image so first-boot ingest has source
# material. Drop your *.md into ./playbook/ before building.
COPY playbook/ ./playbook/

# Mutable state: vector store + trace DB + prep outputs.
# Mount a volume here on hosted providers (Fly.io / Railway).
RUN mkdir -p /data/chroma /data/prep /data/hf-cache /data/fastembed-cache \
 && chown -R app:app /app /data

ENV OUTPUT_DIR=/data/prep \
    CHROMA_DIR=/data/chroma \
    TRACE_DB_PATH=/data/traces.sqlite

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER app
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request, sys; \
    sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/entrypoint.sh"]
