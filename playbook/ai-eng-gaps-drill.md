# AI Engineering Gap Drill

> Five topics that show up in AI infra interviews where you don't have shipped experience yet: **LangChain + LangGraph, Production RAG + RAGAS, ReAct + Plan-Execute, MCP, AWS Bedrock.**
>
> Goal: get fluent enough to *discuss* each, and have a honest **bridge from what you HAVE shipped** ready to deploy.
>
> The senior move when you haven't used a tool: don't fake it. Say "I haven't shipped this; I built the equivalent from scratch — let me compare." Calibration is the closer.

---

## How to use this doc

For each topic, three sections:
1. **The crash course** — minimum vocabulary to discuss it credibly.
2. **Your bridge** — the thing you HAVE built that maps to it.
3. **Mock Q&A** — the interview questions, with model answers including the honest framing.

---

# 1. LangChain + LangGraph

## 1.1 Crash course

**LangChain** is a Python (and JS) framework for composing LLM applications. Its primitives:
- **LLMs / chat models** — wrappers over OpenAI, Anthropic, Bedrock, etc. with a uniform interface.
- **Prompt templates** — string templating with input variables.
- **Chains** — sequences of calls (e.g., prompt → LLM → parser → next prompt). Mostly superseded now by **LCEL** (LangChain Expression Language).
- **Tools** — function definitions the LLM can call (web search, calculator, SQL, custom).
- **Agents** — LLM + tools + loop. Pre-built ReAct/OpenAI-function agents.
- **Memory** — conversation history, sometimes summarized.
- **Retrievers** — abstraction over vector DBs for RAG.

**LangGraph** is the same authors' newer, opinionated **stateful-graph orchestrator** for agents:
- You define a **graph** of nodes (each node is a function or LLM call).
- A **state object** flows through the graph; each node reads/updates it.
- **Conditional edges** route based on state (e.g., "if tool call → tool node; if done → end").
- Supports **persistence** (checkpoint state at every step), **human-in-the-loop** (pause at a node, wait for human input, resume), and **time-travel debugging**.
- Bigger structural commitment than LangChain's chains, but easier to reason about for non-trivial agents.

**The picture:** LangChain = library of primitives. LangGraph = framework for stateful agent loops. They're complementary.

## 1.2 Your bridge

You built **the equivalent of LangGraph from scratch** in the Skai AI agents work — agent loop with tool calls, state passed between steps, observability of each step. You just didn't use the framework.

> *"I haven't shipped LangGraph in production. I built the equivalent — stateful agent loop with checkpointing for replay, tool schemas with strict JSON validation, per-step tracing. The trade-off picking framework-vs-DIY is the same one you make for any framework: framework wins on conventions + ecosystem, DIY wins on transparency + no lock-in. For a single team owning the agent end-to-end, DIY was the right call. For a platform team serving many agent authors, I'd reach for LangGraph."*

## 1.3 Mock Q&A

> **Q: "Have you used LangChain / LangGraph?"**
> A: Honest framing above. Add: "What I've built maps to LangGraph's node-state-edges model. Let me walk through the comparison if useful."

> **Q: "When would you pick LangChain over rolling your own?"**
> A: "Three signals: (1) you have multiple agent authors and need conventions, (2) you want to swap LLM providers without code changes — the abstraction earns its keep, (3) you're prototyping fast and don't yet know which patterns will stick. Pure infra teams with one agent often outgrow the abstraction; that's when DIY wins."

> **Q: "What's a weakness of LangChain?"**
> A: "Two real ones. First, abstraction tax — for simple use cases (single LLM call + parse), LangChain's primitives add indirection without much benefit. Second, version churn — LangChain has changed APIs multiple times. Production systems get pinned and behind. LCEL was the response to the first; LangGraph was the response to the second. Both better, both still evolving."

> **Q: "What does LangGraph give you that a plain Python loop doesn't?"**
> A: "Three things: (1) **state as first-class** — every node reads/writes a typed state object, so you can reason about invariants; (2) **persistence + replay** — checkpoint at every step, resume from anywhere; (3) **human-in-the-loop** — pause at a node, wait for approval, resume. The plain loop can do all of this, but you'd build the same primitives. LangGraph's contribution is naming them."

---

# 2. Production RAG + RAGAS

## 2.1 Crash course

**Production RAG** is RAG that survives real users. The hard parts aren't "embed + nearest neighbor" — they're everything around it.

**Chunking strategies:**
- **Fixed-size** (e.g., 512 tokens) — simple, breaks semantic boundaries.
- **Semantic** (split on headings, paragraphs, sentences) — preserves coherence, harder to tune.
- **Late chunking** — embed the whole doc first, then chunk; gives chunks doc-level context.
- **Hierarchical** — child chunks for retrieval, parent chunks for context (small-to-big).

**Retrieval:**
- **Dense (vector)** — embeddings + cosine. Good for paraphrased queries.
- **Sparse (BM25 / keyword)** — exact-term match. Wins on proper nouns, IDs, code.
- **Hybrid** — combine dense + sparse with weighted scoring. **Almost always beats either alone.**
- **Reranking** — second-stage cross-encoder (Cohere reranker, BGE reranker) scoring (query, chunk) pairs. Dramatic precision win at top-K.

**Generation:**
- **Citations** — answer with `[1][2]` pointing to chunks. Forces grounding.
- **"Don't know" mode** — if no chunk is relevant, say so. Lowers hallucination.
- **Multi-query rewriting** — LLM reformulates query into N variants, retrieves union.

**Eval — the hard part. This is where RAGAS comes in.**

**RAGAS** = Retrieval-Augmented Generation Assessment. Open-source eval framework with metrics specifically designed for RAG:

| Metric | What it measures | How |
|---|---|---|
| **Faithfulness** | Is the answer grounded in retrieved context (vs. hallucinated)? | LLM judges: every claim in the answer must be inferable from context. |
| **Answer relevance** | Does the answer address the question? | LLM generates synthetic questions from the answer; compares to original. |
| **Context precision** | Are retrieved chunks relevant to the question? | LLM scores each chunk for relevance. |
| **Context recall** | Did we retrieve all the chunks needed to answer? | Requires ground-truth answers; compares retrieved chunks to what's needed. |

The framework lets you trend these over time, compare retrieval changes, and catch regressions.

## 2.2 Your bridge

You've built **RAG end-to-end in the prep-agent**: FastEmbed local ONNX embeddings, ChromaDB persistent client, semantic chunking by H2/H3 markdown headings, retrieval query built from signal categories (not raw company name), eval harness with 4-axis rubric.

> *"The prep-agent I built does RAG end-to-end — FastEmbed local embeddings (BAAI/bge-small, $0/query), ChromaDB persistent. Chunking is semantic on H2/H3 markdown headings — semantic boundaries beat fixed-size for structured docs. Retrieval query is built from signal categories, not the company name — because embedding 'Chalk' alone matches nothing in a personal playbook. The eval harness measures 4 axes with LLM-as-judge: specificity, grounding, actionability, personalization. I haven't used RAGAS specifically — but the metrics map closely. Faithfulness ≈ my grounding axis. Answer relevance ≈ my specificity axis. The harness pattern is the same: golden set, judge, calibrate."*

## 2.3 Mock Q&A

> **Q: "Walk me through a production RAG system."**
> A: 5-layer answer. Use the prep-agent as your worked example. Mention hybrid search and reranking as the things you'd add next if you needed precision.

> **Q: "How do you eval RAG?"**
> A: "Two separable concerns: retrieval quality and generation quality. Retrieval: precision@K and recall@K on a labeled golden set. Generation: faithfulness (grounded vs hallucinated) and answer relevance (does it actually address the question). I built an LLM-as-judge harness with 4 axes; RAGAS gives you the same metrics standardized — I'd use RAGAS next time over rolling my own because it bakes in calibration patterns."

> **Q: "What's the most impactful change you'd make to a RAG system that's underperforming?"**
> A: "Depends on the failure mode. Retrieving wrong chunks → add hybrid search (BM25 + vector) or add a reranker. Retrieving right chunks but bad answers → improve chunking (small-to-big retrieval) or tighten the answer prompt. Hallucination → mandate citations + "don't know" mode. Diagnose before treating."

> **Q: "Why hybrid search?"**
> A: "Dense vectors handle paraphrase but miss exact-term queries — IDs, proper nouns, code identifiers. BM25 handles those. Combining them with weighted score (or reciprocal rank fusion) covers both modes. In practice hybrid beats either alone on most benchmarks; the only time pure vector wins is highly conversational search where users never use exact terms."

> **Q: "What's reranking and why?"**
> A: "Initial retrieval (vector or hybrid) is fast but coarse — it ranks chunks by similarity, not by 'how well does this answer the query.' A reranker is a cross-encoder model that takes (query, chunk) pairs and scores each pair specifically. Slower per-item but only run on top-K (~20), so cost is bounded. The precision lift on top-5 is usually significant."

---

# 3. AI Agents — ReAct + Plan-Execute

## 3.1 Crash course

Two dominant agent architectures.

**ReAct (Reason + Act)** — the original. The loop:
1. **Thought**: model reasons about what to do next.
2. **Action**: model picks a tool + args.
3. **Observation**: tool runs, result comes back.
4. **Repeat** until "Thought: I have the answer."

Interleaves reasoning and action. Same model handles both.

```
Thought: I need to know the user's last order date.
Action: lookup_user_orders(user_id=123)
Observation: [{"order_id": 99, "date": "2025-01-15"}, ...]
Thought: The last order was Jan 15. Now I need to check the return policy.
Action: get_return_policy(product_id=99)
...
```

**Plan-Execute** — newer, addresses ReAct's failure modes:
1. **Plan phase**: model produces a multi-step plan first. ("Step 1: lookup user. Step 2: check policy. Step 3: compute eligibility.")
2. **Execute phase**: a different (often cheaper) model executes each step in order.
3. **Replan** if a step fails or returns unexpected data.

Separates "what to do" from "do it." Cheaper, more predictable, easier to interrupt and resume.

**Pros / cons:**

| Architecture | Pros | Cons |
|---|---|---|
| **ReAct** | Simple, adaptive, handles unexpected mid-task info well | Can loop forever; expensive (every step calls smart model); harder to predict cost |
| **Plan-Execute** | Predictable cost, cheaper execution, easy to validate plan before running | Brittle to unexpected data mid-execute; needs replan path |

**Variants worth naming:**
- **ReAct + reflection** — model critiques its own output, retries if bad.
- **Plan-Execute + tree-of-thoughts** — explore multiple plans, pick best.
- **Multi-agent** — specialized agents (researcher, writer, critic) coordinate via shared state.

## 3.2 Your bridge

You built a **tool-use agent loop with strict schemas, iteration cap, and per-call cost tracking** at Skai. That's a ReAct loop in production. You also built the **observability + eval discipline** that makes the architecture choice (ReAct vs Plan-Execute) defensible.

> *"At Skai I shipped a tool-use ReAct loop — model picks a tool, executes, reads result, decides next step. Hard iteration cap of ~10 to bound cost. I haven't done Plan-Execute in production, but the trade-off is clear: ReAct adapts mid-task, Plan-Execute is cheaper and more predictable. For our case — query authoring where errors cascade — ReAct was right because the agent needs to react to AMC's validation errors mid-flow. For a workflow with clean, predictable steps I'd reach for Plan-Execute."*

## 3.3 Mock Q&A

> **Q: "When would you pick ReAct vs Plan-Execute?"**
> A: "ReAct when the task is exploratory — agent doesn't know what it'll find. My Skai use case (query authoring with AMC's validation errors) is ReAct because errors guide the next step. Plan-Execute when the task is structured — research, multi-tool workflows where steps are independent. Plan-Execute is cheaper because the planner runs once with a smart model, the executor runs many times with a cheaper one."

> **Q: "How do you stop an agent from looping forever?"**
> A: "Three layers: (1) hard iteration cap, (2) cost cap per run, (3) confidence-aware termination — if the model's confidence is high enough, accept and exit. The first two are mandatory; the third is the senior version. Most production agent failures I've debugged are silent runaway, not crashes."

> **Q: "What's the hardest failure mode for an agent?"**
> A: "Plausible-but-wrong output. A crash, you catch. A wrong-but-confident answer, the user catches and you've lost trust. The defense is evals — golden set + LLM-as-judge + production sampling. The architecture (ReAct vs Plan-Execute) doesn't fix it; observability does."

> **Q: "How does multi-agent compare?"**
> A: "Multi-agent (specialized roles like researcher / writer / critic) sounds elegant but adds two costs: coordination overhead (agents calling agents) and emergent failure modes (one bad agent corrupts shared state). Worth it when each role really needs a different prompt / model / tool set. Often a single ReAct agent with the right tool set does the same job for less."

---

# 4. MCP — Model Context Protocol

## 4.1 Crash course

**MCP (Model Context Protocol)** is Anthropic's open standard (released Nov 2024) for connecting LLM applications to tools and data sources through a uniform interface. Think of it as **LSP for LLM tools**.

**The problem it solves:** every LLM app re-implements its own tool integration. Slack, GitHub, file system, SQL — each app reinvents the same wiring. MCP standardizes the wire format so any MCP-compatible LLM client can talk to any MCP server.

**The architecture:**
- **MCP host** — the app the user talks to (Claude Desktop, an IDE plugin, your own agent).
- **MCP client** — the part of the host that speaks MCP.
- **MCP server** — exposes a set of **tools** (callable functions), **resources** (readable data like files), and **prompts** (templated workflows).
- **Transport** — usually stdio (server runs as a subprocess) or HTTP+SSE.

**What an MCP server provides:**
- `tools/list` → enumerate tools with JSON schema.
- `tools/call` → invoke a tool with args, get result.
- `resources/list` + `resources/read` → list and read files/data.
- `prompts/list` + `prompts/get` → fetch templated prompts.

**Why it matters:** if you build an MCP server for your product (say, an internal SQL database), then **any** MCP-compatible client gets your integration for free. The ecosystem is still young (early 2026) but growing fast — Anthropic, Cursor, Zed, Sourcegraph, others have shipped MCP support.

**The trap:** it's a protocol, not a sandbox. An MCP server can do anything its execution role allows. Auth + isolation are the host's job.

## 4.2 Your bridge

You haven't built an MCP server. But you've built the **conceptual equivalent** — the tool schema + dispatch + per-call tracing — for the AMC agents. MCP is a *standard* for what you built ad-hoc.

> *"I haven't built an MCP server. What I've built is the conceptual equivalent: tools defined with strict JSON schemas, dispatch from an agent loop, per-call tracing with cost shape. MCP is a standard for that pattern — and the standardization is the point. If we'd had MCP at Skai, the AMC tools we built for our internal agents could be exposed to any MCP-compatible client — say, Claude Desktop for an analyst to use directly — with no extra wiring. That's the architectural value: tool authoring decouples from agent authoring."*

## 4.3 Mock Q&A

> **Q: "What is MCP?"**
> A: "Anthropic's open standard for connecting LLM apps to tools and data sources. It's LSP-for-tools — instead of every LLM app reinventing its Slack / GitHub / SQL integration, MCP defines the wire format so any compatible client talks to any compatible server. Hosted by an MCP server that exposes tools, resources, and prompts; consumed by an MCP host (Claude Desktop, an IDE, your agent)."

> **Q: "When would you build an MCP server?"**
> A: "When your product has data or tools that LLM users want to access from multiple clients. Examples: internal knowledge base, ticket system, custom SQL warehouse. Build the MCP server once, get integration with every MCP-compatible client. The alternative is building a Claude integration AND a Cursor integration AND a Zed integration — same logic three times."

> **Q: "What's a weakness of MCP today?"**
> A: "Three: (1) it's a protocol, not a sandbox — MCP server can do anything its role allows; auth and isolation are the host's job and they're easy to get wrong; (2) ecosystem is young — clients vary in MCP completeness; (3) versioning — protocol is evolving fast; production deployments need to pin and follow the spec carefully. Worth tracking; worth piloting on a non-customer-facing use case first."

> **Q: "How does MCP relate to tool-use APIs from OpenAI / Anthropic?"**
> A: "Different layers. Tool-use APIs (function calling) are the LLM-side — model emits 'call tool X with args Y.' MCP is the tool-side — how the tool definition + execution is exposed to the app. They compose: an MCP server provides the tools; the LLM's tool-use API picks which to call; the MCP transport executes the call. Both are needed."

---

# 5. AWS Bedrock

## 5.1 Crash course

**AWS Bedrock** is AWS's managed service for foundation models. Multiple model providers (Anthropic, Meta, Mistral, Amazon's own Titan / Nova, Cohere) behind one API. Targeted at enterprise AWS shops.

**Key features:**
- **Model API** — invoke any supported model with one client (`boto3` or Bedrock Runtime API).
- **Knowledge Bases** — managed RAG. You point it at S3, it chunks, embeds, indexes, and serves retrieval — all behind an API.
- **Agents** — managed agent loops with tools. Lower-code than rolling your own.
- **Guardrails** — content filtering, PII redaction, blocklists, applied to inputs and outputs.
- **Model evaluation** — built-in benchmarking against custom datasets.
- **Provisioned throughput** — pay for dedicated capacity instead of per-token; lower per-call cost at scale.

**Why teams pick it:**
- Already on AWS — IAM, VPC, billing, security review all in one place.
- Compliance (HIPAA, FedRAMP, etc.) — pre-cleared.
- Multi-model — swap Claude 3.5 ↔ Llama 3 ↔ Titan without changing app code.

**Trade-offs:**
- **Cost** — Bedrock pricing is usually higher per-token than direct API access (Anthropic's API, OpenAI's API). The premium pays for compliance + integration.
- **Latency** — extra hop through AWS infra; often higher p99 than direct.
- **Feature lag** — new model versions sometimes land on Bedrock months after direct API.
- **Lock-in to AWS** — not a problem if you're already there; meaningful if you're not.

## 5.2 Your bridge

You haven't shipped Bedrock. But you've built **provider-agnostic LLM infrastructure** in the prep-agent — `ChatProvider` Protocol with Anthropic + Gemini implementations, swapping provider via one env var. That's the *pattern* Bedrock optimizes for at the platform level.

> *"I haven't shipped on Bedrock. The pattern I built in the prep-agent is provider-agnostic — a `ChatProvider` protocol with implementations for Anthropic and Gemini. Switching providers is one env var. Bedrock takes that pattern and bakes it into AWS infra — IAM, VPC, billing in one place, multiple model providers behind one API. For enterprise AWS shops with compliance constraints, that consolidation is the value. For independent teams, the per-token premium often doesn't pencil out vs direct provider APIs. The right choice depends on where the constraints actually bind — compliance, integration, or cost."*

## 5.3 Mock Q&A

> **Q: "When would you pick Bedrock over going directly to Anthropic / OpenAI?"**
> A: "Three signals: (1) already an AWS shop with IAM + VPC + compliance set up — Bedrock plugs in; (2) need multiple model providers behind one wire — Bedrock's catalog handles that; (3) regulated industry where compliance review of a new vendor is painful — Bedrock is pre-cleared. The cost premium is real but often dominated by the integration savings. For independent teams without those constraints, direct API access is usually cheaper and faster."

> **Q: "What's the latency profile?"**
> A: "Higher p99 than direct API in my experience — extra AWS hop, less control over routing. For latency-sensitive paths (sub-second user-facing), I'd benchmark direct vs Bedrock with realistic traffic before committing. For batch or async use cases, the latency premium is irrelevant."

> **Q: "How does Bedrock Knowledge Bases compare to building your own RAG?"**
> A: "Knowledge Bases is managed RAG — S3 → chunk → embed → index → serve, all behind an API. The trade-off is the standard managed-vs-custom one: faster to ship, less control. For an MVP or a use case where retrieval quality requirements are vanilla, KB is the right call. The moment you need a non-standard chunking strategy, custom rerankers, or hybrid search with specific weights, you outgrow it. I'd start with KB and migrate when retrieval quality plateaus."

> **Q: "What's the lock-in concern?"**
> A: "Real but bounded. The API is AWS-specific, but the *patterns* (provider abstraction, RAG, agents) port. Migration cost is rewriting the client layer — measured in days, not months. The bigger lock-in is the AWS IAM / VPC / compliance configuration you built around Bedrock. That's the part you don't want to migrate."

---

# Daily 5-min drill

Pick one of the five topics. Set a 60-second timer per Q. Answer out loud — including the **honest framing** when you haven't shipped the tool.

The senior signal isn't "I've used all five." It's "I can reason about all five and I'm calibrated about which ones I've actually shipped." That's the bar.
