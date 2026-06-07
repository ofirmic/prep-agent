# prep-agent

> Personal interview prep, automated. Generates a company-tailored prep doc in 30 seconds — pulls public signals (Glassdoor, Reddit, levels.fyi, engineering blogs), matches them against your own playbook, and writes the doc.

<!-- Replace with a real screenshot. See docs/screenshots/. -->
<!-- ![Home page](docs/screenshots/home.png) -->

## Why I built this

I was about to start interviewing and noticed I was doing the same research process for every company — pulling Glassdoor reports, recent news, tech stack, then matching them against my own prep frameworks. So I turned it into an agent.

Built end-to-end over a couple of weekends. It's a personal tool, but designed like production software because that's how I work.

## What's in it

A walk-through of the engineering decisions (each is an interview talking point):

| Layer | Choice | Why |
|---|---|---|
| LLM | `ChatProvider` Protocol with Anthropic + Gemini implementations | Provider-agnostic so swapping is one env var. Gemini's free tier means $0 to run. |
| Search | Tavily, 9 parallel queries per company | Targeted site: queries for Glassdoor/Reddit/levels.fyi/HN catch interview reports + comp data. |
| Structured output | Anthropic tool-use; Gemini native `response_schema` | Each provider uses its own best mechanism — caller sees a clean `chat_structured(schema=…)` API. |
| RAG | FastEmbed (local ONNX, $0) + ChromaDB persistent | Personal playbook docs become retrieval-augmented context. Embedder is a `Protocol` — swap to Voyage/OpenAI later in one file. |
| Eval harness | Golden set + LLM-as-judge across 4 axes | Specificity / Grounding / Actionability / Personalization. Per-axis manual calibration field to compare judge vs human grading. |
| Observability | SQLite trace store + `@traced` stage decorator + per-call cost/token/latency | Every LLM call logged with cost shape; charts show "extract is 80% of latency, synthesize is 80% of cost". |
| Resilience | Exponential backoff + retry classifier (only 429/5xx) | Transient errors retry, user errors fail fast. |
| Auth | `hmac.compare_digest` password gate on Streamlit | For hosted demo URL, keeps random visitors off the API budget. |
| Deploy | Dockerfile (multi-stage, non-root, `/data` volume) + Railway + Fly.io configs | Cold-start ingest from baked-in playbook. |

## Demo

- **Live URL**: _(deploy via the `railway.toml` / `fly.toml` and link here)_
- **Sample output**: [`examples/sample-prep-chalk.md`](examples/sample-prep-chalk.md) — a real prep doc generated for [Chalk](https://chalk.ai), $0 cost, ~30 seconds
- **Walkthrough video**: _(record a 2-min Loom and link here)_

## Quickstart

```bash
uv sync
cp .env.example .env  # pick a provider + fill in keys (see below)

# One-time: chunk + embed your playbook docs (~/Documents/*.md by default)
uv run prep-agent ingest

# Per-company: research + RAG + synthesize
uv run prep-agent research "Chalk"

# Or use the web UI (Home / History / Observability)
uv run prep-agent ui

# Debug retrieval directly
uv run prep-agent query "feature platform real-time ML"
```

Output lands in `prep/{company-slug}-{date}.md`.

### Pick a provider

```ini
# Free, no credit card. Get a key at https://aistudio.google.com/apikey
LLM_PROVIDER=gemini
GEMINI_API_KEY=...

# Or: requires $5 prepaid balance
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
```

Tavily is required for web search either way (1,000 free searches/month).

The pipeline is built around a `ChatProvider` Protocol with two implementations (`AnthropicChatProvider` uses tool-use for structured output; `GeminiChatProvider` uses native `response_schema`). Stages, the eval judge, and the calendar classifier all talk to the Protocol — switching providers is one env var.

## Architecture

```
                              ┌──────────────────────┐
   research "Chalk"  ─────────▶│   Pipeline           │
                              └──────────┬───────────┘
                                         │
                ┌────────────────────────┼────────────────────────┐
                ▼                        ▼                        ▼
        Tavily search            FastEmbed + Chroma         Anthropic
        (parallel queries)       (RAG over playbook)        (Haiku → Sonnet)
                │                        │                        │
                ▼                        ▼                        ▼
        SearchResult[]           RetrievedChunk[]            PrepDoc
                │
                ▼
       Extractor (Haiku) ──▶ CompanySignals ──▶ Retriever ──▶ Synthesizer
```

**Design decisions worth defending:**

- **Two-tier LLM routing** — Haiku for structured extraction (cheap, parallelizable), Sonnet for synthesis (quality-sensitive, sequential).
- **Local embeddings via FastEmbed** — `BAAI/bge-small-en-v1.5` ONNX model, ~80MB, $0/query. Embedder is a Protocol so swapping to Voyage/OpenAI is one file.
- **Markdown chunking by H2/H3 headers** — semantic boundaries beat fixed-size for already-structured docs. Heading path travels with each chunk so retrieval results stay interpretable.
- **Retrieval query built from signal categories, not company name** — embedding raw "Chalk" matches nothing in a personal playbook; the category vocabulary is what bridges company → topic.
- **ChromaDB persistent client** — zero infra, file-based. Wrapped in `PlaybookStore` so a future move to pgvector touches one file.
- **Idempotent ingest** — chunk IDs are content-hashed, re-running over unchanged files is a no-op upsert.

## Eval harness (Phase 3)

```bash
# 1. Snapshot inputs once per company — freezes signals + chunks for repeatable evals.
uv run prep-agent eval snapshot "Chalk"
uv run prep-agent eval snapshot "Skai"
uv run prep-agent eval snapshot "Anthropic"

# 2. Run the harness — synthesizes prep docs from fixtures and judges them.
uv run prep-agent eval run
```

**Why the fixture step?** Evals must be reproducible. If every run re-hits Tavily, the inputs change and you can't compare prompt change A against prompt change B. Fixtures freeze the inputs so evaluation measures what changed: synthesis quality.

**Rubric** (1-5 per axis, single judge call via Claude Sonnet with tool-use structured output):
- **Specificity** — concrete company-grounded vs generic interview advice
- **Grounding** — claims traceable to signals or playbook chunks vs hallucinated
- **Actionability** — concrete prep actions vs vague guidance
- **Personalization** — uses candidate's own playbook frameworks vs generic ones

**Retrieval evaluation** is graded separately on `expected_topics` recall — the senior failure mode is conflating retrieval and generation quality.

**Calibration**: each golden case can carry `manual_scores`. When set, the report flags any LLM-judge axis that disagrees with the human grade by more than 1. That's how "LLM-as-judge" becomes defensible instead of hand-wavy.

Reports land in `evals/results/eval-{timestamp}.md`.

## Observability (Phase 4)

Every LLM call is auto-logged with stage, model, input/output tokens, cost, and latency. The data lives in SQLite next to the project; no separate service.

```bash
uv run prep-agent traces list             # last 20 traces with cost + latency
uv run prep-agent traces show <trace_id>  # every LLM call in the trace
```

**Design notes:**
- `TracedAnthropic` wraps `AsyncAnthropic.messages.create`. Stages don't know about logging; the wrapper records before/after each call.
- `@traced("stage")` on stage methods sets a ContextVar so calls inside it get tagged with the stage name. ContextVars are async-safe — concurrent pipeline runs don't cross-contaminate.
- `trace_context()` async context manager opens/closes a trace row. Status flips to `error` automatically if the wrapped code raises.
- Trace totals are recomputed from `llm_calls` at close time, so the trace row can't drift from its children (a class of cost-dashboard lies this design prevents).
- Pricing is a module-level table (`obs/pricing.py`) — update when Anthropic changes prices.

## Web UI (Phase 5)

```bash
uv run prep-agent ui      # opens http://localhost:8501
```

Three pages:

- **prep-agent** — company input + Generate. Pipeline runs with progressive status updates per stage (search → extract → retrieve → synthesize) instead of one opaque spinner; the trace ID is surfaced so you can drill into observability.
- **History** — past prep docs from `OUTPUT_DIR`, newest first, rendered or raw.
- **Observability** — aggregate cost + tokens, cost-over-time line chart, per-stage cost/p95-latency breakdown, recent traces table with drill-in to per-call detail.

The UI reads from the same SQLite trace DB and ChromaDB the CLI uses — no separate data plane.

## Calendar integration (Phase 6)

Auto-detect interview events on your Google Calendar and generate prep docs for them.

### One-time setup

1. **Create a Google Cloud project** at <https://console.cloud.google.com>.
2. **Enable the Calendar API** for the project (APIs & Services → Library → "Google Calendar API" → Enable).
3. **Create an OAuth client** (APIs & Services → Credentials → Create Credentials → OAuth client ID → **Desktop app**). Download the JSON.
4. Save the JSON as `~/.config/prep-agent/google_client_secret.json` (or set `GOOGLE_CLIENT_SECRET_PATH`).
5. Run the auth flow once — opens a browser, captures the refresh token:
   ```bash
   uv run prep-agent calendar auth
   ```

The scope is **read-only** (`calendar.readonly`); prep-agent never writes back to your calendar.

### Day-to-day

```bash
uv run prep-agent calendar list                 # show upcoming interview-like events
uv run prep-agent calendar sync --dry-run       # classify without generating
uv run prep-agent calendar sync                 # for real
uv run prep-agent calendar sync --days 14       # widen the window
```

Pipeline:

1. List events in the window.
2. Pre-filter by keyword on title/description (interview, screen, intro, …).
3. Skip events already in the processed store (idempotent — runs twice produce one prep).
4. **Classify each remaining event with Haiku** — extracts `company`, `role_hint`, `confidence`, plus a one-sentence `reasoning` for debug. Email-domain attendees are a strong signal (with personal domains filtered out, and the candidate's own employer treated as internal).
5. For confident interview events (default `--confidence 0.6`): trigger the same RAG-backed pipeline `prep-agent research` uses. The prep doc lands in `OUTPUT_DIR` and a `processed_calendar_events` row prevents re-prep.

Calendar trace events appear in **Observability** the same as research traces (the LLM classification call is decorated `@traced("calendar_extract")`).

The Streamlit **Calendar** page shows upcoming events, a Sync button with adjustable `days` / `confidence` / dry-run, and a recently-processed history.

## Deploy (Phase 7)

The repo ships with everything a single-user hosted instance needs:

- **`Dockerfile`** — multi-stage (uv builder → slim runtime), non-root user, FastEmbed model + ONNX cache writable, ChromaDB + traces + prep outputs on a `/data` volume, healthcheck on Streamlit's built-in `/_stcore/health` endpoint.
- **`entrypoint.sh`** — bootstraps ChromaDB from baked-in `playbook/` on cold start if empty, then `exec streamlit`.
- **`railway.toml`** — Dockerfile build + healthcheck + restart policy. Volume + secrets configured in the dashboard.
- **`fly.toml`** — Dockerfile build, persistent volume, auto-stop-machines (scales to zero while idle).
- **`STREAMLIT_AUTH_PASSWORD`** — single-password gate via `hmac.compare_digest`. Unset locally, set on hosted instances to keep random visitors off your Anthropic budget.

### Build local

```bash
# Copy your playbook docs so they get baked into the image
cp ~/Documents/interview-*.md playbook/
cp ~/Documents/amc-*.md playbook/
docker build -t prep-agent .

# Run with your local .env file
docker run --rm -p 8501:8501 --env-file .env \
  -v "$(pwd)/data:/data" prep-agent
```

### Deploy: Railway

```bash
railway login
railway init                       # link to a new project
railway variables set \
  ANTHROPIC_API_KEY=sk-ant-... \
  TAVILY_API_KEY=tvly-... \
  STREAMLIT_AUTH_PASSWORD=change-me
# Add a Volume (Settings → Volumes → mount path: /data)
railway up
```

### Deploy: Fly.io

```bash
fly launch --no-deploy             # answer prompts; uses fly.toml
fly volumes create prep_data --size 1 --region iad
fly secrets set \
  ANTHROPIC_API_KEY=sk-ant-... \
  TAVILY_API_KEY=tvly-... \
  STREAMLIT_AUTH_PASSWORD=change-me
fly deploy
```

### Notes for hosted instances

- **Calendar Phase 6 doesn't translate to hosted as-is.** `InstalledAppFlow.run_local_server` is for a local OAuth listener. To use Calendar in production you'd need the OAuth *web* flow, an authorized redirect URI in Google Cloud, and a published consent screen. For a single-user portfolio deploy, the simpler path is: leave Calendar disabled on hosted instances and run the sync locally with your CLI.
- **Expected cost**: ~$5/month on Railway (Hobby plan) or ~$0–3/month on Fly.io (scale-to-zero + 1GB volume). Plus your Anthropic + Tavily usage, which is variable.
- **Memory**: 1GB is comfortable for one user. Below 512MB, FastEmbed + ChromaDB + Streamlit start to swap.
- **Cold start**: ~10–25s on first request after idle (model load + Chroma open). Subsequent requests are sub-second.

## Roadmap

- [x] Phase 0: scaffold
- [x] Phase 1: end-to-end happy path
- [x] Phase 2: RAG over personal playbook
- [x] Phase 3: eval harness (golden set + LLM-as-judge + retrieval eval)
- [x] Phase 4: observability (SQLite traces, per-call cost + latency)
- [x] Phase 5: web UI (Streamlit, 3 pages)
- [x] Phase 6: Google Calendar integration (OAuth + classifier + sync orchestrator)
- [x] Phase 7: deploy (Dockerfile + Railway/Fly configs + auth gate)

See `../prep-agent-build-plan.md` for the full plan.
