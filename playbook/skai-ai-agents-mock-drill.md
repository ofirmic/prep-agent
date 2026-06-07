# Skai AI Agents Mock Drill — Flashcard Q&A

> The recent AI work at Skai — agents that automated the AMC workflow + the LLM observability tooling that made them shippable.
> Same format as the other drills: read Q, answer aloud, check.
>
> If you're interviewing at an AI infra company (Chalk, ScaleOps, Anthropic, OpenAI infra, anything with "agent" or "platform" in the role) — this is the doc that converts your *experience* into *talking points*.

---

## How to use this

- Speak every answer out loud. Reading silently is fake practice.
- If you can't fill in the blanks (`[your specific X]`), that's a gap — write your real number in pencil before the interview.
- Goal: by Friday, you can answer any Q here in 30–60 seconds, conversationally.

---

## Category 1 — Pitches

### Q1. What's the 30-second version of your AI agent work?

**A.** "Recently at Skai I built internal AI agents that automate parts of our AMC workflow — things like query authoring, validation, and re-execution on failure. To make them shippable I built LLM observability tooling alongside: per-call tracing, cost shape, and an eval harness. The thing I learned is that agents fail in a different way than services — silently and plausibly — so the observability layer is what makes them production-grade, not the model choice."

**Why this works:**
- Names the *product* (automate AMC workflow) before the *tech* (LLMs, agents).
- Implicitly claims a *senior* insight ("observability matters more than model choice").
- Ends with a thesis the interviewer can probe.

---

### Q2. Give me the 3-minute version using the 5-layer framework.

**A.**
1. **Problem (15s).** Our AMC workflow had repetitive engineering tasks — drafting query SQL, validating it against AMC's quirky dialect, fixing it when AMC returned an error, re-submitting. Engineer time per query was the bottleneck.
2. **Constraints (30s).** Agents had to be reliable on a non-deterministic stack. Cost had to be predictable. Each agent run needed a clear audit trail because the output (the SQL) was customer-impacting. Multi-tenant — agents work for specific customer instances.
3. **Shape (45s).** Three components: (a) the agent runtime — tool-use loop with a small set of well-scoped tools (lint SQL, dry-run, fetch schema, submit); (b) the observability layer — every LLM call traced with prompt, response, tokens, cost, latency; (c) the eval harness — a golden set of queries with known good answers, run on every prompt change.
4. **Implementation (60s).** Python. Agent loop uses tool-use with strict JSON schemas to prevent hallucinated arguments. Cap on iterations (~10) to bound cost. Observability is a SQLite trace table + per-call cost from a pricing table — same pattern as the prep-agent. Evals run before any prompt change merges; LLM-as-judge with 4-axis rubric.
5. **Open issues (30s).** Caching identical LLM calls (cost win, freshness loss). Auth on agent tool calls (today the agent runs as a service identity; should be the user's identity for sensitive tools). Cost runaway if an agent loops on a bad input — solved by hard iteration limit, but a smarter limit would be confidence-aware.

---

### Q3. What was the *outcome*? (interviewers always ask)

**A.** [Fill in your real numbers. Skeleton:]
- N queries / week now go through the agent instead of an engineer drafting from scratch.
- Engineer time per query dropped from [~X min] to [~Y min].
- Cost: ~$Z per agent run, dominated by the [extraction / validation] step.
- Reliability: ~K% of agent runs hit a clean answer on first pass; the rest hit a retry path.

If you don't have numbers, say so: "I don't have the exact ratio off the top of my head — I'd verify before quoting it." Calibration is senior.

---

## Category 2 — Architecture decisions

### Q4. Why a tool-use agent and not a single-shot LLM call?

**A.** The task has *steps that depend on each other's outputs* — fetch the schema, draft the SQL, dry-run it, fix the error, re-submit. A single-shot call would need to do all of that in one prompt, which means cramming the schema + history + error into context, hoping the model gets it right in one shot.

Tool-use externalizes state. Each tool returns a *real result* (not a model prediction of a result). The model's job is reasoning over real data, not predicting it.

**Trade-off:** more LLM calls = more cost + latency. We bounded cost with hard iteration limits and an "if you can't fix it in 5 tries, return the error to the human" escape hatch.

---

### Q5. Why a small set of tools instead of many?

**A.** Two reasons:
1. **Schema discipline.** Every tool needs a strict JSON schema. The looser the schema, the more the model hallucinates arguments. With 5 well-defined tools, we hand-tune each schema and validate every call. With 50, schema quality degrades.
2. **Agent reasoning.** Model picks worse with more options. The performance gap between "5 tools" and "50 tools" agents is real. Keep the tool set small until you have evidence you need more.

**Trade-off:** harder to extend. Each new tool needs schema design + eval cases. But adding a 6th tool with care beats having 30 noisy ones.

---

### Q6. How do you handle a hallucinated tool argument?

**A.** Two layers:
1. **Schema validation at the call site** — JSON Schema rejects malformed args. The agent gets a tool-error response and tries again.
2. **Semantic validation inside the tool** — even if the arg is the right shape, is it valid? E.g., "is this `agency_id` actually one this tenant can access?" If no, return an error. The agent retries with a different arg.

**Senior signal:** distinguish *syntactic* validation (schema) from *semantic* validation (does it make sense in our domain). Most tutorials only do syntactic.

---

### Q7. What's your prompt versioning story?

**A.** Prompts are *code*. They live in the repo, get reviewed, get versioned. Every prompt change merges through a PR that includes:
1. The diff.
2. The eval-harness output on the golden set (before vs after).
3. A short rationale in the PR description.

Production reads from a registry that pins a specific version. Rollback = flip the version pointer.

**Trade-off:** moving slower than "tweak the prompt in the playground." But once an agent is customer-impacting, prompt changes without evals are a class of outage.

---

## Category 3 — Observability

### Q8. What does your LLM tracing look like?

**A.** Every LLM call is logged with:
- `trace_id` (one per agent run)
- `call_id` (one per LLM call within a run)
- `stage` (e.g., `plan`, `tool_select`, `summarize`)
- `model`
- `input_tokens`, `output_tokens`
- `cost_usd` (from a pricing table)
- `latency_ms`
- `prompt` and `response` (for replay)
- `error` (null on success)

Stored in SQLite. Queryable by stage to see cost shape. The killer query is "show me the trace for the run that produced wrong output for tenant X."

**Why SQLite:** for our scale, file-based wins. The moment we exceed it, swap to Postgres — the schema is unchanged.

---

### Q9. What's the cost shape of an agent run?

**A.** Two heuristics:
- **By stage.** Usually one or two stages dominate. For us, [the validation step / the summary step] is the long-tail. We optimize that one and ignore the rest.
- **By call count.** Cost scales linearly with iterations. The iteration cap is a cost cap.

Concretely: ~70% of cost in one stage, ~20% in another, the rest is noise. A 2× cost reduction always comes from optimizing the dominant stage — bigger model → smaller, fewer tokens, better caching.

**Senior signal:** name the *shape* before the *number*. "It's dominated by stage X" tells me you measured. A specific dollar number without that context is just a fact, not understanding.

---

### Q10. How do you detect a regression in agent quality?

**A.** Three layers:
1. **Eval harness on prompt change** — golden set + LLM-as-judge. If quality drops on the rubric axes, block the merge.
2. **Sampling in production** — k% of agent runs get a follow-up judge call. Trended over time. Flat = good; trending down = regression.
3. **User feedback signal** — agents have a "this was wrong" button. Wired into a triage queue.

**Trap:** LLM-as-judge has its own bias. Calibrate the judge against human grades on a subset; if judge disagrees with humans by > 1 on the rubric, the judge needs work, not the agent.

---

### Q11. Walk through your eval harness.

**A.**
1. **Golden set** — N (~30–100) input examples with known good outputs. Curated by hand; updated when we find a real-world failure that wasn't in the set.
2. **Run the agent on each input.** Capture output.
3. **Judge the output.** LLM-as-judge with a 4-axis rubric (specificity / grounding / actionability / personalization, or whatever the task needs). Returns a 1–5 score per axis + reasoning.
4. **Aggregate.** Mean per axis, flag any score below threshold.
5. **Report.** Markdown file dumped per run; trended over time.

**Calibration:** every golden case has a `manual_scores` field (optional). When set, the report flags judge axes that disagree with human grades by > 1. That's how LLM-as-judge becomes defensible.

**Bridge to Skai:** "Same observability pattern as our service-level RED metrics — three audiences (on-call, team, finance) and the eval is the test suite for an untestable thing."

---

## Category 4 — Reliability

### Q12. Agents fail silently. How do you stop that?

**A.** Three classes of silent failure:
1. **Plausible but wrong** — answer looks right but isn't. Caught by evals + production sampling.
2. **Tool succeeds but agent uses the result wrong** — e.g., tool returns "no results found"; agent treats that as an empty success. Caught by validating *agent reasoning over tool output*, not just tool output itself.
3. **Cost / iteration runaway** — agent loops on a bad input. Caught by hard caps + alarming on long-running traces.

The unifying principle: **define what "correct" means *before* shipping the agent**, write checks for it, run them in CI and in production.

**Trap:** most "agent eval" tutorials only catch #1. The expensive bugs are #2 and #3.

---

### Q13. What's the worst agent bug you've shipped?

[Pick a real story. Structure: situation → tension → action → result → reflection.]

**Skeleton:**
- Situation: agent started returning [wrong thing] for [specific customer / case].
- Tension: it looked plausible enough that automated checks didn't fire; a customer caught it.
- Action: traced the run (because we had per-call tracing), found that [specific step] was being misled by [specific edge case in input data]. Added a golden case for it; tightened the prompt; redeployed.
- Result: caught the same class of bug twice more after that, all in eval runs before reaching prod.
- Reflection: the eval set is only as good as the failures you've seen. The agent system needs to *generate* its own failures continuously, not wait for users to find them.

---

### Q14. How do you bound cost for a single agent run?

**A.** Three levers, in order:
1. **Max iterations** — hard cap (~10). Beyond that, return whatever the agent has + a "needed-human-review" flag.
2. **Per-call token budget** — `max_tokens` on every call, tight to the expected output. Stops runaway generations.
3. **Per-run cost ceiling** — sum the per-call costs; abort if it exceeds $X. Rare in practice but cheap insurance.

**Trade-off:** capped iterations means some runs return incomplete answers. Better to fail loudly than burn $50 on a single run.

---

## Category 5 — Bridge stories

### Q15. How does this AI work connect to your AMC engineering?

**A.** Two angles:
1. **It's a layer on top of the same system.** The agents call tools that are wrappers around the AMC integration — `dry-run a query`, `fetch the schema for this instance`. The agent is a *user* of the AMC platform I built. So the system thinking is the same: idempotency, multi-tenancy, error propagation.
2. **The observability story carries over.** Per-tenant attribution for AI cost is the same query-tag pattern we did for Snowflake. RED metrics on agent runs are the same shape as RED metrics on the Java service. The senior leap is recognizing the patterns are universal — the substrate changed (LLM vs service), the discipline didn't.

**This is the answer that maps your work to "AI Engineer" roles.** You're not pivoting from data to AI; you're applying senior data-system discipline to AI.

---

### Q16. (Chalk-flavored) "We build infra for real-time AI/ML. What in your background maps?"

**A.** Three things:
1. **The warehouse-vs-serving split.** Snowflake → SingleStore at Skai is the same pattern as offline-store → online-store at Chalk. Versioned schema as the boundary, freshness SLA as the contract.
2. **Multi-tenancy with cost attribution.** AMC's query-tag-based cost shape is the same shape you'd want for per-tenant feature compute at Chalk.
3. **Observability as a first-class feature.** The LLM trace store I built is one substrate-change away from what an ML feature platform needs — feature-level tracing, per-feature cost, eval harness.

I'd land in Chalk as someone who's already built the discipline, on a different substrate.

---

### Q17. (ScaleOps-flavored) "We automate Kubernetes infra. What maps?"

**A.** Two things:
1. **Multi-tenant observation at scale.** The cost-attribution pattern for AMC tags is the same shape as per-cluster cost attribution for Kubernetes workloads. Different substrate, same discipline.
2. **The reliability-vs-automation tension.** My AI agents automate engineering work in a domain where wrong answers have customer impact. ScaleOps automates infra changes in a domain where wrong answers have customer impact. Same problem class: safe automation requires observability + eval + rollback — and the agent eval harness pattern is *exactly* what a safe-automation platform needs.

I'd come in with the discipline; need to learn the K8s primitives, which I can do in weeks.

---

### Q18. "Why are you a fit for an AI infra role specifically?"

**A.** Three reasons:
1. **I've built it.** The agent + observability + eval triad I shipped at Skai is the same triad an AI infra company sells.
2. **I think in trade-offs.** Senior signal is naming what you gave up. I can name the iteration-cap trade-off, the schema-strictness trade-off, the eval-coverage trade-off out loud.
3. **I came from data systems.** AI infra is data infra with a model on top. My six years of Snowflake / Airflow / SQS / Lambda translate directly. I'm not learning data discipline; I'm bringing it.

---

## Category 6 — What you'd do differently

### Q19. Clean sheet — what's the one thing you'd change?

**A.** **Treat the eval set as a continuously-generated artifact, not a hand-curated one.**

What we did: hand-built golden cases. They cover what we've seen but miss what's coming.

What I'd do: every production agent run that triggers a confidence flag or a user-feedback signal is a *candidate eval case*. A triage queue lets us label and promote them. The eval set grows with the agent's exposure to the world.

**Trade-off:** more infra to build (the queue, the labeling UI). Win: the eval set never grows stale.

---

### Q20. What about the agent runtime itself?

**A.** Two things:
1. **Confidence-aware iteration cap.** Today's cap is a fixed number. A better cap would let the agent run longer on high-confidence paths and shorter on dead ends. Cheap to build with a `confidence` field returned by each reasoning step.
2. **Tool result caching.** Same input args → same result. Tools that are pure functions should cache. Cheap; saves real money on iterative refinement loops.

---

### Q21. What about the observability layer?

**A.**
1. **Cost-trace dashboards per agent, per tenant** — we have the data; we'd build the UI. Finance question becomes a query.
2. **Anomaly alerts on cost or latency** — agent cost jumped 3× yesterday; alert. We don't have this; we react to monthly bill spikes.

Both are "we have the data, we just haven't built the views" — pure productization work.

---

## Daily 5-minute drill

Pick 5 Qs at random from this doc. Set a 30-second timer per Q. Answer out loud. The goal is not perfect recall; it's **conversational fluency** — answering at interview pace, not study pace.

If you can't answer 5 Qs in under 5 minutes, your answers are too long. Cut them.
