#!/usr/bin/env bash
# Container entrypoint.
#
# 1. If ChromaDB is empty, ingest baked-in playbook docs (idempotent re-ingest
#    is safe per chunk-hash IDs, but skipping if non-empty saves cold start).
# 2. Launch Streamlit on the port the host provides.
#
# Failure to ingest is non-fatal — the UI still renders, retrieval just
# returns no chunks. We surface the warning to stdout so it lands in logs.
set -euo pipefail

PORT="${PORT:-8501}"
CHROMA_DIR="${CHROMA_DIR:-/data/chroma}"

if [ -d "$CHROMA_DIR" ] && [ -z "$(ls -A "$CHROMA_DIR" 2>/dev/null)" ]; then
    if [ -d /app/playbook ] && [ -n "$(ls -A /app/playbook 2>/dev/null)" ]; then
        echo "[entrypoint] Empty Chroma store, ingesting /app/playbook..."
        prep-agent ingest /app/playbook || \
            echo "[entrypoint] WARN: ingest failed; UI will run with empty retrieval"
    else
        echo "[entrypoint] No /app/playbook docs baked in; skipping ingest"
    fi
fi

exec streamlit run /app/src/prep_agent/ui/app.py \
    --server.port "$PORT" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
