# Interview Drill Sheet — Skai Project + System Design

> Compact drill, not a script. Two halves: **A. Skai/AMC narrative** + **B. System design**.
> Use this 60 min the night before and 15 min morning-of. Read every model answer **out loud**.
> Star any answer you can't deliver in under 30 seconds — those are tomorrow morning's drill.

---

## How to use this sheet

1. **Day before (60 min):** read A and B end to end out loud. Star weak spots.
2. **Morning of (15 min):** re-read only the starred items + numbers you must know cold (§A.4).
3. **Last 2 min before joining the call:** read the 60-second pitch (§A.1). That's your opener and you want it muscle-memory.

---

# PART A — Skai project narrative (AMC integration)

The interviewer will give you 5–60 minutes for this. You need three lengths.

## A.1 The 60-second pitch (memorize verbatim)

> "At Skai I owned the end-to-end AMC integration — Amazon Marketing Cloud is a clean-room SQL warehouse Amazon exposes for advertisers. We built a Java microservice that consumes query requests from SQS and triggers Airflow DAGs that submit the query to AMC, poll for completion, and pull the result file via a cross-account Lambda into Snowflake. From Snowflake we run a reverse-ETL into SingleStore so customer dashboards serve sub-second. It's multi-tenant, every row is tenant-scoped, and cost is attributed per customer via query tags. The hard parts were idempotency end to end, cross-account IAM, and the warehouse-versus-serving boundary — I'll go deeper on whichever you want."

**Why this works:** sets domain context (what AMC is, in one phrase), names the two halves (top: ingest, bottom: serving), names three architecture-led decisions (idempotency, IAM, warehouse/serving split), ends with an open hand to the interviewer.

**Pitfalls:**
- Don't say "we worked on" — say "I owned."
- Don't list tech without why. "Snowflake for analytical storage, SingleStore for sub-second serving" is OK because the *why* is implicit in the contrast.
- Don't bury the lede. The first sentence has to land what AMC is. If they don't know AMC, your whole story is fog.

## A.2 The 3-minute deep dive (structure, not script)

Use the 5-layer framework. Walk it in this exact order:

1. **Problem (15s).** Customers want to run SQL queries on Amazon's clean-room data and see results in their Skai dashboards. AMC is async (minutes to hours), result lives in Amazon's S3, we serve dashboards from our infra.
2. **Constraints (30s).**
   - AMC is a third-party with hard rate limits and an org-level wall — we can't ask Amazon to scale us.
   - Sub-second dashboard reads = serving layer separate from analytical store.
   - Multi-tenant: every row scoped, every cost attributable.
   - Cross-account: AMC's S3 lives in Amazon's AWS account, our infra lives in ours.
3. **Shape (45s).** Two halves with Snowflake as the boundary.
   - Top half (ingest): SQS → Java MS → Airflow DAG → AMC API → HttpSensor poll → Lambda fetch → Snowflake.
   - Bottom half (serving): Snowflake → reverse ETL (`singleStoreWriter`) → SingleStore → Reporting API → dashboards.
   - Side channel: status callback via separate SQS queue (Airflow → Java MS) so Airflow never holds DB credentials.
4. **Implementation (60s).** Lead with 2–3 specific decisions and *why*:
   - **HttpSensor per-DAG** instead of one central poller. Trade: more Airflow worker slots, gain failure isolation per tenant — one bad query can't blow up the polling layer for everyone.
   - **Lambda at the cross-account trust boundary.** Pre-signed URL has a 15-min TTL; Lambda has a 15-min hard cap; runtime + memory tuned. Lambda sits at the IAM seam so the trust crossing is minimal-surface.
   - **Status callback as a separate SQS queue.** Decoupled because Airflow shouldn't hold our DB credentials. Idempotent because `UPDATE status='SUCCEEDED'` is a no-op on retry.
5. **Open issues (30s).**
   - Webhook from AMC would kill the polling pressure; AMC doesn't expose one yet.
   - Lambda 15-min cap is a real wall for big results — chunked byte-range download or ECS for the tail.
   - Stuck-job sweep DAG is the lazy version of a proper saga/orchestration recovery.

## A.3 The 10-minute whiteboard walkthrough

If they say "go deeper," draw the diagram first, then walk it. The drawing order matters — it's the order you build the narrative.

**Drawing order:**
1. Customer / Dataset Manager MS (left).
2. SQS `newQueryRequestQueue` arrow into AMC MS.
3. AMC MS box → MySQL (idempotency + state).
4. AMC MS → Airflow trigger (POST).
5. Airflow DAG box with 5 internal steps: submit → HttpSensor poll → pre-signed URL → Lambda → Snowflake COPY INTO.
6. AMC's AWS account (separate cloud-shaped box) with S3 inside.
7. Lambda spans the boundary between Amazon's account and Skai's account — emphasize this.
8. Snowflake (right of Airflow). Then arrow down to `singleStoreWriter` reverse ETL → SingleStore → Reporting API → Dashboards.
9. Side arrow: Airflow → `query_status_update` SQS → AMC MS (status callback).

**Narrate in this order, naming the principle at each step:**
- "REST for `get queries`, SQS for `fetch_request` — match the channel to the latency budget."
- "Java MS persists DB row *before* triggering Airflow — durable anchor for recovery."
- "HttpSensor inside the DAG run, not a central poller — failure isolation."
- "Lambda at the trust boundary — minimum-surface IAM crossing."
- "Snowflake is the warehouse, SingleStore is the serving layer — different stores for different reads."
- "Status callback separate queue — Airflow stays credential-free."

## A.4 Numbers you must know cold

Drill these until you can say them without looking:

- **Java microservice retry trigger:** 10 attempts, 10s between.
- **`max_active_runs` on the DAG:** 60 concurrent.
- **HttpSensor poke interval:** ~30s (verify).
- **Lambda hard cap:** 15 minutes. Memory/runtime tuned. Cold-start measured in low seconds.
- **Pre-signed URL TTL:** matches Lambda's window — same 15-min order. The trap: if you generate it and Lambda is queued cold, the URL expires before fetch.
- **Snowflake warehouse size:** XS for the integration's `COPY INTO`; we'd scale up for backfill, not steady-state.
- **SingleStore dashboard SLA:** **sub-second** reads. That's the *reason* SingleStore exists in the stack.
- **Status callback queue:** separate from `newQueryRequestQueue` — the reason is credential isolation.
- **Stuck-job sweep threshold:** rows in `RUNNING` older than ~6 hours.

If you don't remember an exact number, say so: "the configured value was around X — I'd verify in the repo." Calibration is a senior signal.

## A.5 Architecture decisions to lead with

For each one: name the decision, name the *alternative you considered*, name the *trade-off*.

| Decision | Alternative considered | Trade-off |
|---|---|---|
| HttpSensor poll inside per-tenant DAG | Single central polling DAG | Lose: worker slots. Gain: failure isolation, no shared blast radius. |
| Lambda for cross-account S3 fetch | ECS task or EC2 worker | Lose: 15-min cap, no streaming. Gain: zero idle cost, sits naturally at trust boundary, minimal IAM surface. |
| Snowflake → SingleStore reverse ETL | Single store (just Snowflake, or just SingleStore) | Lose: pipeline complexity, dual-write reasoning. Gain: cheap analytical store + sub-second serving store, each in its lane. |
| Status callback via separate SQS queue | Airflow writes status directly to MySQL | Lose: extra hop. Gain: Airflow never holds DB creds; decoupling; queue retries the callback for free. |
| Per-stage idempotency (every write checks state) | Whole-pipeline transactional retry | Lose: every stage has to think about it. Gain: SQS at-least-once delivery is safe; retries are cheap; partial failure recovers stage-by-stage. |
| Per-customer query tags for cost attribution | Aggregate costs at infra level | Lose: tag discipline. Gain: a finance question (which customer is expensive?) has a SQL answer. |

## A.6 Hard questions — drill these out loud

> **"Why Lambda and not ECS or EC2?"**
Lambda is the right tool when the work is short, bursty, and cheap to start. Cross-account S3 fetch is exactly that. Trade-off: the 15-minute hard cap. For very large results we'd hit it, and the right move is byte-range chunking or routing the tail to an ECS task. We didn't *need* that for the common case; we'd add it the moment a customer hit it. Also: Lambda sits naturally at the trust boundary — the IAM crossing is one resource, not a whole VPC.

> **"What if the pre-signed URL expires before Lambda runs?"**
That's a real failure mode. Lambda dies, DAG task fails, Airflow retries — but the *same* expired URL doesn't help. Real fix: re-issue the pre-signed URL inside the Lambda invocation, or move URL generation as close to use as possible. We accepted the failure rate because cold starts were rare; if it became a tail-latency problem we'd put the URL refresh inside the retry boundary.

> **"How do you detect a stuck job?"**
Stuck-job sweep DAG that runs hourly, finds rows in `RUNNING` older than ~6h, flips them to `FAILED` with reason `stuck_timeout`, alerts on-call, and operators run `amc_cleanup_by_request_id` to drop partial Snowflake rows and re-trigger. The sweep is the *lazy* version of saga compensation — it works but it's not pretty. The real version would be an orchestrator that owns recovery as a first-class state, not a forensics tool.

> **"Cost at 10x? At 100x?"**
At 10x: probably config-tuneable — bigger Snowflake warehouse for ingest, more Airflow workers, maybe Lambda concurrency cap. Money problem.
At 100x: architecture wall. HttpSensor polling becomes the dominant cost — 6000 mostly-idle workers polling. Fixes in order: deferrable operators (releases worker between pokes), or central poller DAG (re-introducing the shared-blast-radius we deliberately avoided), or webhooks if AMC ships them. The org-level wall (AMC's API rate limit) is unreachable from our side — it's negotiation, not engineering.

> **"What would you do differently?"**
Three things. (1) Saga-style orchestrator with recovery as a first-class state, not a sweep DAG. (2) Deferrable HttpSensor from day one — it's only a small code change and saves us the 100x scaling pain. (3) The `status` enum is too coarse — `RUNNING` conflates four sub-states and the dashboard can't show real progress to the customer.

> **"Worst bug you shipped?"**
[Pick one real story. Structure it: situation → tension → action → result → reflection. Use "I" not "we." Name a metric in the *result* line. Name the *lesson* in the reflection.]

> **"Tell me about a disagreement with a teammate / lead."**
[Pick a real case. Frame: I held position X, they held Y. I named our different priorities (e.g. velocity vs. correctness). We agreed on a decision-making test (e.g. "if it can lose a customer's data, correctness wins"). Outcome and what I'd do differently.]

## A.7 The AI / agents layer (recent work)

When they ask "what have you done recently" or "any LLM experience":

> "Lately I've built internal AI agents that automate the AMC workflow — query authoring, validation, and re-execution on failure. That work pushed me to build LLM observability tooling on top: per-call tracing, cost shape per call and per agent run, and a small eval harness so prompt changes are testable, not vibes. The thing I learned is that agents fail in a different way than services — silently and plausibly — so the observability layer is what makes them production-grade, not the model choice."

**Why this pairs well with AMC:** it lets you bridge "data infra senior" → "AI infra senior" without sounding like a junior trying to crowbar AI into their resume.

---

# PART B — System design drill

The interviewer will give you a vague prompt. **Don't draw immediately.** Run the 5-layer framework. Out loud.

## B.1 The 5-layer framework

1. **Problem.** Restate it back. Ask: who's the user, what's the input, what's the output, what does success look like?
2. **Constraints.** Functional (must do X). Non-functional (latency, throughput, consistency, multi-tenancy, cost). State your *assumptions* explicitly.
3. **Shape.** High-level boxes and arrows. Name the data flow. Don't pick tech yet — pick *categories* (queue, store, cache).
4. **Implementation.** Now pick tech. Justify each choice. Trade-off out loud. "Snowflake because X, *but* SingleStore for Y."
5. **Open issues.** What you'd verify, what would break at scale, what you'd build next.

## B.2 The universal opener (memorize)

> "Before I start drawing, let me confirm what we're solving. [Restate.] My understanding of the constraints is: [list 3]. Some assumptions I'm making — push back if any are wrong: [list 3]. I'll go requirements → high-level shape → then we can deep-dive on whichever piece you care most about. Sound good?"

This buys you 60 seconds to *think*, signals seniority, and gives the interviewer a chance to steer.

## B.3 Worked example 1 — Real-time feature store (Chalk flavor)

Prompt: "Design a system that serves ML features in real-time, with offline training reading the same definitions."

**Problem.** A data scientist defines a feature once. An online model reads it sub-50ms at inference. An offline training job reads the same feature for the same entity *at a past timestamp*.

**Constraints.** Read p99 < 50ms. Training-serving consistency (online and offline must agree). Multi-tenant. Feature definitions in code (Pythonic).

**Shape.**
- Definition: Python classes → registered with a feature registry.
- Compute: streaming for fresh features, batch for slow ones.
- Storage: online KV store (low-latency reads) + offline columnar store (point-in-time correct).
- Resolution: serving API reads online; training API reads offline-at-time-T.

**Implementation.**
- Online: Redis or DynamoDB. Key = (tenant, entity, feature, version). TTL on freshness.
- Offline: Iceberg / Delta on S3 or a warehouse. Partition by event-time. Snapshot reads = point-in-time correctness.
- Streaming compute: Flink or Spark Structured Streaming.
- The *trick*: shared feature definition compiles to both pipelines. Single source of truth.

**Open issues.** Backfill story (new feature, no history). Schema evolution (versioned feature, dual-write window). Training-serving skew detection (sample both, diff).

**Bridge to Skai:** "This is the same warehouse-vs-serving split we did at Skai with Snowflake-plus-SingleStore — analytical store for offline, low-latency store for online, with the boundary defined as a versioned schema."

## B.4 Worked example 2 — Kubernetes rightsizer at scale (ScaleOps flavor)

Prompt: "Design a system that observes thousands of customer clusters' pod resource usage and rightsizes them in real-time without downtime."

**Problem.** Customer has K8s clusters. Pods are over/under-provisioned. Our system observes usage, recommends new resource requests, and applies them safely.

**Constraints.** Multi-tenant (per-customer cluster isolation). No downtime when applying changes. Real-time observation (seconds, not minutes). Safe rollback if a recommendation kills a workload.

**Shape.**
- Agent: in-cluster pod that streams metrics out.
- Ingest: time-series store for raw metrics.
- Recommender: stream of metrics → per-pod resource recommendation.
- Apply: mutating webhook or controller that patches deployments rolling.
- Safety: per-pod canary + automatic rollback on failure signal.

**Implementation.**
- Agent: DaemonSet using cAdvisor / metrics-server. Streams to our ingestion endpoint.
- Time-series: Prometheus-compatible store (Mimir, VictoriaMetrics) or ClickHouse for analytics queries.
- Recommender: stream processor (Flink) computing percentile-based recommendations on rolling windows.
- Apply: K8s mutating admission webhook *or* operator pattern (Reconcile loop). Operator pattern wins for rollback — desired state vs observed state is first-class.
- Safety: rollout one replica at a time, watch error rate + p99 latency for N minutes, auto-rollback on regression.

**Open issues.** Cold-start (new pod, no history — fall back to a conservative default). Bursty workloads (use p95 over a long window, not p50 over a short one). Multi-tenant noisy neighbor (per-customer agent quotas).

**Bridge to Skai:** "The multi-tenant cost-attribution pattern is the same one I built in AMC — every metric tagged at ingestion with customer_id, so the cost question 'who's driving X' has a SQL answer rather than a guess."

**Pushback to prep for:** "How do you handle a customer with a workload your recommender hasn't seen before?" — answer: bootstrap on a conservative percentile, label the recommendation as low-confidence, observe for N hours before applying. Confidence is first-class.

## B.5 Worked example 3 — Multi-tenant async pipeline (generic, leverage AMC directly)

Prompt: "Design a system that lets customers submit long-running compute jobs and serves results in a dashboard."

This is *literally AMC*. Walk the AMC architecture (§A.2) as the answer, with two changes:
- Frame it as a design exercise: "I'd run the 5-layer pass first, then I'll tell you we built something close to this — I'll point out where I'd do it differently with a clean sheet."
- The "differently" list: deferrable operators from day one; saga-style orchestration; finer-grained status enum (§A.6 "what would you do differently").

Why this is the most powerful answer of the three: you can go *infinitely* deep on every box because you actually built it.

## B.6 Common pushback questions — drill out loud

> **"How would you scale this 100x?"**
Per-component scan. For each component: which scaling axis (config / money / engineering / org wall). Walk the chain. Find the wall first — that's the bottleneck, not the easy parts. (Same drill as §A.6 "Cost at 100x" for AMC.)

> **"What if region X goes down?"**
Name the blast radius. Which stateful components are regional? Where's the replication? Recovery: RTO and RPO. Be honest about the trade-off between cost (multi-region) and recovery time.

> **"Where's the bottleneck?"**
Almost always: the stateful component (DB / store) before the stateless ones (services). Or the third-party with a rate limit. Name the *units*: it's not "the DB is slow," it's "writes per second exceed disk IOPS" or "reads exceed connection pool size."

> **"How would you monitor this?"**
Three layers: (1) RED metrics on services (rate, error, duration). (2) Per-stage business metrics (jobs submitted, jobs succeeded, p95 end-to-end latency). (3) Per-tenant attribution so you can answer "which customer broke it" in SQL.

> **"How do you ensure no two customers see each other's data?"**
Tenant ID on every row, every query, every cache key. Enforced at the lowest layer that can enforce it — usually at the store (row-level security or per-tenant prefix), not just at the service layer. Defense in depth: the service *also* checks, but the store is the floor.

## B.7 Common pitfalls — do NOT do these

- Start drawing boxes before clarifying the problem.
- Assume scale. ("Let's say 1M QPS.") Ask the interviewer.
- Pick tech without justifying. "Use Kafka" → why not SQS? Why not just an HTTP API?
- Single point of failure you didn't name. Every box is a SPOF until you say otherwise.
- Ignoring multi-tenancy. If it's a SaaS, every system needs a per-tenant story for data, cost, and failure.
- Hand-waving the database. "And then we store it in a database" is a junior signal. *Which* database, *what* schema shape, *what* read pattern.
- Not naming a trade-off. Every choice has a cost. If you can't name it, you don't understand the choice.

## B.8 Senior-signal phrases to use

Sprinkle these naturally; they re-frame you from candidate to peer:

- "The trade-off I'd make here is..."
- "I'm assuming X — push back if that's wrong."
- "I don't know that exact number; I'd verify it from [a source]. But the order of magnitude is..."
- "The interesting failure mode is..."
- "If we cared more about [X] than [Y] we'd flip this choice."
- "Want me to go deeper on storage, on the API layer, or on the failure modes?"

---

# PART C — 60-minute night-before drill (run this exactly)

| Time | Activity |
|---|---|
| 0:00–0:05 | Read §A.1 pitch out loud three times. Time yourself — under 60s. |
| 0:05–0:15 | Walk §A.2 (3-min deep dive). Talk to a wall. No notes second pass. |
| 0:15–0:25 | Draw the AMC diagram from memory. Then check §A.3. |
| 0:25–0:35 | Drill 4 hard questions from §A.6 out loud. Star ones that came out wobbly. |
| 0:35–0:40 | Read numbers in §A.4 out loud. Repeat each twice. |
| 0:40–0:50 | Pick *one* worked example from §B.3 / B.4 / B.5 — the closest to the company you're interviewing at. Walk the 5 layers out loud, end to end. |
| 0:50–0:55 | Drill 3 pushback questions from §B.6 out loud. |
| 0:55–1:00 | Re-read §A.1 pitch and §B.2 universal opener. Sleep. |

---

# PART D — Morning-of (15 min)

| Time | Activity |
|---|---|
| 0:00–0:03 | Read §A.1 pitch twice. |
| 0:03–0:06 | Read §B.2 universal opener. |
| 0:06–0:11 | Re-read your starred items from last night. |
| 0:11–0:14 | Read §A.4 numbers one more time. |
| 0:14–0:15 | Close the laptop. Walk. Coffee. You're ready. |
