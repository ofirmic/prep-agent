# System Design Mock Drill — Flashcard Q&A + Cheat Sheet

> Same format as `amc-mock-drill.md`. Pure practice. Read the question, answer out loud, then read the model answer to check.
>
> Three parts:
> 1. **Design exercises** — 6 prompts, each walked through with the 5-layer framework.
> 2. **Pushback Q&A** — interviewer follow-ups, with model answers.
> 3. **Cheat sheet** — back-of-envelope numbers + pattern reference.

---

## How to use this

- **First pass:** read the design exercises slowly. Pause at each layer (Problem / Constraints / Shape / Implementation / Open issues) and try to predict what comes next before reading.
- **Second pass:** cover the answers. Take 5 minutes per design exercise. Compare to the model.
- **Third pass (day-of):** read the cheat sheet only. The numbers and patterns should be available like keyboard shortcuts.

---

## Part 1 — Design exercises (5-layer walks)

### Exercise 1 — Real-time ML feature store

**Prompt:** "Design a system where data scientists define features once and both online inference and offline training read them consistently."

**1. Problem.** A feature is defined once (e.g., "user's avg purchase value last 30 days"). Online: model serves prediction in <50ms. Offline: training reads the same feature at a past timestamp. The killer requirement is *training-serving consistency*.

**2. Constraints.**
- Read p99 < 50ms online.
- Point-in-time correctness offline.
- Multi-tenant — features belong to namespaces.
- Schema evolution — features change shape over time.

**3. Shape.**
- **Definition layer:** Python classes → feature registry.
- **Compute layer:** streaming for fresh features, batch for slow features.
- **Storage:** online KV (low-latency) + offline columnar (point-in-time).
- **Resolution API:** `get_features(entity, ts)` for offline; `get_features(entity)` for online.

**4. Implementation.**
- Online: Redis or DynamoDB. Key = `(tenant, entity_id, feature_name, version)`. TTL on freshness.
- Offline: Iceberg/Delta on S3. Partition by event-time. Snapshot reads give point-in-time correctness.
- Streaming: Flink / Spark Structured Streaming.
- The trick: **shared feature definition compiles to both pipelines.** One source of truth.

**5. Open issues.**
- Backfill (new feature, no history) → batch backfill from raw events, marked as `bootstrap` until the streaming pipeline catches up.
- Schema evolution → version every feature; dual-write old + new for one cycle.
- Training-serving skew detection → sample both, diff.

**Bridge to Skai:** "This is the same Snowflake-vs-SingleStore split we did at Skai — analytical store for offline, low-latency store for online, boundary as a versioned schema."

---

### Exercise 2 — Kubernetes pod rightsizer

**Prompt:** "Design a system that observes thousands of customer clusters' resource usage and rightsizes pods in real time without downtime."

**1. Problem.** Customer's pods are over- or under-provisioned. We observe usage, compute new resource requests, apply safely, rollback if anything regresses.

**2. Constraints.**
- Multi-tenant — per-cluster isolation.
- No downtime when applying.
- Real-time observation (seconds, not minutes).
- Auto-rollback on regression (SLA must improve, never regress).

**3. Shape.**
- **Agent:** in-cluster DaemonSet streams metrics to central ingest.
- **Ingest:** time-series store for raw metrics.
- **Recommender:** stream of metrics → per-pod resource recommendation.
- **Apply:** K8s operator (Reconcile loop) — patches Deployment specs.
- **Safety:** per-pod canary + auto-rollback on regression.

**4. Implementation.**
- Agent: DaemonSet using cAdvisor/metrics-server.
- TSDB: Prometheus-compatible (Mimir / VictoriaMetrics) — or ClickHouse if you need analytical queries.
- Recommender: Flink stream job. Percentile-based recommendation on rolling windows (e.g., `p95 over 24h`).
- Apply: K8s operator pattern, not mutating webhook. Operator's desired-vs-observed reconcile loop is what makes rollback natural.
- Safety: canary one replica, watch error rate + p99 latency for N min, auto-rollback on regression.

**5. Open issues.**
- Cold start (new pod, no history) — conservative default until N hours of data.
- Bursty workloads — p95 over a long window, not p50 over a short one.
- Noisy neighbor — per-customer agent quotas.

**Bridge to Skai:** "The per-tenant cost attribution is the same pattern as our AMC query tags — every metric is tenant-labeled at ingestion, so the question 'who's driving X' has a SQL answer."

---

### Exercise 3 — Distributed rate limiter

**Prompt:** "Design a rate limiter that enforces 'X requests per second per API key' across thousands of API servers."

**1. Problem.** Multi-tenant API. Each key has a quota. Servers are stateless and horizontal. The limit must be enforced globally, not per-server.

**2. Constraints.**
- Decision latency: < 5ms per request.
- Accuracy: ±5% is fine; ±50% is not.
- Available: limiter failure must *not* take down the API. Fail open or fail closed?

**3. Shape.**
- **Server side:** middleware calls limiter on every request.
- **Limiter:** Redis with atomic ops (or a custom service backed by Redis).
- **Algorithm:** sliding window counter — keys = `(api_key, time_bucket)`.

**4. Implementation.**
- Redis cluster, key per `(api_key, minute_bucket)`. INCR + EXPIRE in a Lua script (atomic).
- Sliding window = sum the current and previous bucket, weighted by time elapsed in current.
- Fail open (allow request) on Redis error — better to over-serve than break the API.
- Pre-warm hot keys in the Redis client.

**5. Open issues.**
- Per-region rate limiters (faster, but inconsistent global view) vs global (consistent, more latency).
- DDoS spike vs sustained traffic — token bucket lets bursts through; sliding window doesn't.
- Per-endpoint vs per-key vs per-(key, endpoint) — depends on whether some endpoints are 100× more expensive.

**Bridge to Skai:** "External rate limits — AMC's API limit was a hard wall I lived with. I learned that the right place to enforce limits is at the *trust boundary*, not at every service."

---

### Exercise 4 — Job scheduler at scale

**Prompt:** "Design a job scheduler that handles 100K scheduled cron-like jobs per hour, with at-least-once execution, across a fleet of workers."

**1. Problem.** Users define jobs with schedules. The system picks up due jobs, dispatches them to workers, tracks completion, retries on failure.

**2. Constraints.**
- At-least-once execution (better duplicate than missing).
- 100K jobs/hour = ~28/sec average, ~300/sec at peak (10× spike).
- Worker pool is heterogeneous and can scale up/down.

**3. Shape.**
- **Scheduler:** scans a DB index of `(next_run_at)`, leases due jobs to itself.
- **Dispatcher:** publishes leased jobs to a job queue.
- **Workers:** pull from queue, execute, ack.
- **Completion tracker:** updates job status, schedules next run.

**4. Implementation.**
- DB: PostgreSQL with `SELECT ... FOR UPDATE SKIP LOCKED` to atomically lease N jobs.
- Queue: SQS (simple) or Redis Streams (lower latency).
- Workers: stateless; consumer-group semantics; ack-on-success, nack-on-failure.
- Idempotency: every job has a `(job_id, scheduled_for)` key — workers check before executing.

**5. Open issues.**
- Worker crashes mid-job → visibility timeout in SQS; the job redelivers. Idempotency makes that safe.
- Scheduler crashes between lease and dispatch → leased jobs sit "in flight" forever. Lease has a TTL; expired leases get re-leased.
- Time skew across hosts → use a single source of truth for "now" (DB clock).

**Bridge to Skai:** "Same shape as AMC's `newQueryRequestQueue` driving Airflow DAGs — SQS for the kick, idempotency on the receiving side, durable anchor row in the DB."

---

### Exercise 5 — Multi-tenant log ingestion

**Prompt:** "Design a system that ingests application logs from thousands of customers and serves search queries over them with <1s p95."

**1. Problem.** Apps emit logs → we collect, store, index, serve. Multi-tenant. Customers want full-text search.

**2. Constraints.**
- Ingest 1M events/sec across tenants.
- Search p95 < 1s for the last 7 days; relaxed for older.
- Per-tenant isolation in both storage and query cost.

**3. Shape.**
- **Ingest:** SDK in each customer app → regional ingest endpoint → message bus.
- **Storage:** hot (last 7d, fast search) vs cold (older, archival).
- **Index:** inverted index per-tenant or per-(tenant, time-bucket).
- **Query:** API routes to hot or cold based on time range.

**4. Implementation.**
- Bus: Kafka, partitioned by tenant_id (preserves order within tenant).
- Hot store: OpenSearch / ElasticSearch, with per-tenant indices.
- Cold store: S3 + Parquet, partitioned by `(tenant, date)`. Queryable via Athena or DuckDB.
- API: tier-aware — last 7d → ES; older → Athena. Combine if range spans both.

**5. Open issues.**
- Hot-tenant fan-in (one customer hogs Kafka partition) → key by (tenant, hash bucket); pick the bucket count by tenant volume.
- Index bloat → per-(tenant, week) indices; close old ones.
- Cost attribution → query tags (same trick as Snowflake).

**Bridge to Skai:** "Hot/cold tiering with a versioned boundary — same as Snowflake → SingleStore at Skai. The boundary is where you serialize the schema contract."

---

### Exercise 6 — LLM agent platform (closest to ScaleOps / Chalk territory)

**Prompt:** "Design an internal platform that lets teams build LLM agents — define tools, set up retrieval, evaluate, deploy."

**1. Problem.** Many teams want agents. Today everyone reinvents prompt construction, tool definition, observability, evals. Build the platform.

**2. Constraints.**
- Latency: end-to-end agent loop p95 < 5s.
- Cost: per-agent-call cost must be visible to the team that owns the agent.
- Multi-tenant: agents from different teams can't see each other's data.
- Eval: prompt changes are testable before deploy.

**3. Shape.**
- **Definition layer:** YAML or Python decorators define an agent (tools, system prompt, retrieval source).
- **Compile layer:** validates definition → registers in a registry.
- **Runtime:** receives a query, runs the loop (think → tool → think → answer).
- **Observability:** every LLM call traced (cost, tokens, latency).
- **Eval:** golden set per agent + LLM-as-judge + retrieval-precision eval.

**4. Implementation.**
- Registry: PostgreSQL — versioned agent definitions, blue/green deploy.
- Runtime: stateless service. ContextVar-based stage labeling for tracing (same pattern as the prep-agent's `@traced`).
- Tool execution: sandboxed per-tool (subprocess or function call). Each tool registers its schema.
- Observability: SQLite/Postgres traces. Per-call cost from a pricing table.
- Eval: golden cases per agent; CI runs the judge before promote.

**5. Open issues.**
- Caching identical LLM calls (huge cost win, breaks freshness for some agents).
- Streaming responses (TTFB matters for UX; complicates observability).
- Auth on tool calls (the agent's identity should propagate to downstream services).
- Cost runaway (agent loops indefinitely) → hard limit on loop iterations + cost.

**Bridge to Skai:** "I built exactly this for the AMC workflow — agents with observability + evals + cost shape per call. The 6-pattern taxonomy in `interview-playbook.md` Part VI maps directly to the design choices here."

---

## Part 2 — Pushback Q&A (interviewer follow-ups)

### Q1. "How would you scale this 100×?"

**A.** Per-component scan. For each component name (a) the scaling axis it can use — config, money, engineering, or org-wall — and (b) where the *first* wall is.

The most senior signal: name the org-wall first. "Snowflake we can scale with money. Lambda we can scale with config. The wall at 100× is the third-party rate limit / the team that owns X / regulation."

---

### Q2. "What if a region goes down?"

**A.** Name the blast radius. Which components are regional? Where's the replication?
- **Stateless services:** load balance to other regions.
- **DBs:** sync to async replica → failover. RPO (data loss tolerance) and RTO (downtime tolerance) numbers.
- **Object storage:** cross-region replication.
- **Queues:** regional; messages buffered until consumer recovers.

Honest answer: full multi-region is *expensive*. Most systems are single-region with disaster-recovery to a second region (cold standby). The cost step from "single region" to "active-active multi-region" is ~10×.

---

### Q3. "Where's the bottleneck?"

**A.** Almost always: the stateful component (DB / store) before the stateless ones. Or the third-party with a rate limit.

Name the units. Not "the DB is slow" — "writes per second exceed disk IOPS" or "connection pool is exhausted before request capacity."

Pattern: **the bottleneck is wherever you can't easily add a replica.** Stateless = add a box. Stateful = pay the cost of replication.

---

### Q4. "How would you monitor this?"

**A.** Three layers, three audiences:
1. **RED on services** (rate, error, duration) — for on-call.
2. **Per-stage business metrics** (jobs submitted, jobs succeeded, p95 end-to-end) — for the team.
3. **Per-tenant attribution** — for support ("which customer broke it?") and finance ("which customer drove cost?").

Most teams skip #3 and regret it. It's hard to bolt on later because instrumentation must happen at *every* layer.

---

### Q5. "How do you ensure tenants can't see each other's data?"

**A.** Defense in depth:
- **Service layer:** every query injects `tenant_id`. ORM-level enforcement.
- **Store layer:** row-level security (Postgres RLS) or per-tenant prefixes (S3 / DynamoDB). The store is the *floor* — even if service-layer logic has a bug, the store says no.
- **Audit:** every read logs `tenant_id`. We can prove what each tenant touched.

Pure service-layer enforcement is fragile. Senior signal: name row-level security as the floor.

---

### Q6. "What's the consistency model?"

**A.** Be precise. "Eventually consistent" is too vague.
- **Strong consistency:** every read reflects the latest write. Cost: latency + leader dependency.
- **Read-your-writes:** within a session, reads see your own writes.
- **Monotonic reads:** subsequent reads don't go backward in time.
- **Eventual consistency:** reads catch up "eventually" — usually milliseconds.

Pick the weakest model that satisfies the product requirement. Strong consistency by default is over-engineering for most systems.

For multi-region: **causal consistency** is the right middle ground. Better than eventual, cheaper than strong.

---

### Q7. "How do you handle a poisoned message in the queue?"

**A.** Dead-letter queue (DLQ).
- Workers nack a message N times before SQS sends it to DLQ.
- Alarm on DLQ depth > 0.
- Triage: read the DLQ, identify the bug, fix it, replay messages.

The trap: **DLQ without alarming is worse than no DLQ.** Messages disappear into it; no one notices. (The Skai bug in `amc-mock-drill.md` Q29 was exactly this.)

---

### Q8. "How would you do a zero-downtime migration of the schema?"

**A.** Expand-contract pattern, three phases:
1. **Expand:** add new column, dual-write (writes go to both old + new). Reads still on old.
2. **Backfill:** copy old → new for historical rows.
3. **Contract:** switch reads to new. Drop old (eventually).

Each phase is independently deployable. The killer: **never drop and add in the same deploy.** Always two separate releases.

---

### Q9. "Walk me through your caching strategy."

**A.** Name the cache *pattern* and the *invalidation strategy* explicitly.

| Pattern | Invalidation |
|---|---|
| **Cache-aside (lazy)** | App reads cache; on miss, read DB + populate cache. TTL invalidates. |
| **Read-through** | Cache layer reads DB on miss transparently. TTL invalidates. |
| **Write-through** | Writes hit cache + DB simultaneously. Always fresh. |
| **Write-behind** | Writes hit cache only; cache flushes to DB async. Lowest write latency, risk of data loss. |

For most read-heavy workloads: **cache-aside with TTL**, plus *explicit invalidation* on the write path.

Anti-pattern: cache stampede. When the TTL fires, every replica races to refresh. Fix: per-key lock or pre-warm.

---

### Q10. "Your async queue keeps growing. What do you do?"

**A.** Three causes:
1. **Producer too fast** — rate-limit upstream or shed load.
2. **Consumer too slow** — scale consumers; profile the slow path.
3. **Consumer is failing silently** — alarm on DLQ; check error rate.

Order of operations:
1. **Stop the bleeding** — pause the producer if you have that lever.
2. **Diagnose** — look at consumer error rate and process time.
3. **Scale up consumers** if it's load.
4. **Fix the bug** if it's silent failures.

Senior signal: **always know the cause before scaling up**, because scaling up a buggy consumer just creates more failures faster.

---

## Part 3 — Cheat sheet

### A. Back-of-envelope numbers (memorize these)

| What | Number |
|---|---|
| L1 cache access | 0.5 ns |
| L2 cache access | 7 ns |
| Main memory access | 100 ns |
| SSD random read | 100 µs |
| Network RTT in datacenter | 0.5 ms |
| Disk seek (HDD) | 10 ms |
| Network RTT cross-region | 100 ms |
| 1 server stateless HTTP qps | 5–20K |
| 1 server with DB call qps | 1–5K |
| Redis ops/sec (single instance) | 100K |
| PostgreSQL writes/sec (single primary) | 5–10K |
| Kafka throughput per partition | 10K msgs/sec |
| S3 PUT per second per prefix | ~3.5K |
| Lambda cold start | 200 ms – 2 s |
| Cross-region replication lag | 50–500 ms |

**Daily storage growth back-of-envelope:**
- 1M events/day × 1KB each = ~1 GB/day = ~365 GB/year.
- 1M users × 1 KB profile = 1 GB.

---

### B. Pattern reference

#### Caching invalidation
- TTL only — simplest, accepts staleness.
- TTL + explicit invalidation on write — best for most cases.
- Event-driven invalidation (CDC from DB) — for systems where staleness is unacceptable.

#### Partitioning strategies
- **Hash on tenant_id** — even distribution, no range queries.
- **Range partition by time** — natural for time-series; old partitions roll off.
- **Geographic** — co-locate users with their data.

#### Replication
- **Single leader, sync replicas** — strong consistency, single-writer bottleneck.
- **Single leader, async replicas** — eventual consistency, faster writes.
- **Multi-leader** — write anywhere, conflict resolution needed.
- **Leaderless (Dynamo-style)** — quorum reads + writes, no leader.

#### Multi-tenancy isolation (3 axes)
- **Data isolation** — per-tenant DB / schema / row.
- **Compute isolation** — shared pool with quotas, or per-tenant containers.
- **Network isolation** — VPC peering, or shared with auth at every layer.

#### Failure-mode taxonomy (from `interview-playbook.md` Part IV)
- **Transient** — network glitch, retry succeeds.
- **Slow component** — high latency cascades; backpressure or fail fast.
- **Persistent component failure** — failover / circuit breaker.
- **Data corruption** — durable anchor + replay from logs.
- **Configuration drift** — IaC + verification post-deploy.

---

### C. The universal opener (memorize, use verbatim)

> "Before I draw anything, let me confirm what we're solving. [Restate the problem in one sentence.] The constraints I'm assuming: [name 3]. The assumptions I'm making — push back if any are wrong: [name 3]. I'll go requirements → high-level shape → then we can deep-dive on whichever piece you care most about. Sound good?"

That opener buys you 60 seconds to think and signals seniority. Use it every time.

---

### D. The 5-layer pattern (reminder)

1. **Problem** — what are we solving, for whom, what's success?
2. **Constraints** — functional + non-functional (latency, throughput, cost, multi-tenancy).
3. **Shape** — categories of components (queue, store, cache) and data flow.
4. **Implementation** — specific tech with *why*. Trade-off out loud.
5. **Open issues** — what would you verify, what would break at scale, what would you build next.

Run this in order. Skipping layers is the #1 reason interviews go sideways.

---

### E. Pitfalls to actively avoid

- Drawing boxes before clarifying the problem.
- Assuming scale ("let's say 1M QPS") instead of asking.
- Picking tech without justifying ("we use Kafka" → why not SQS?).
- Single point of failure you didn't name.
- Ignoring multi-tenancy on a SaaS.
- Hand-waving the database ("and then we store it") — *which* DB, *what* schema, *what* read pattern.
- Not naming a trade-off. Every choice has a cost. If you can't name it, you don't own it.

---

## Daily 10-minute drill

- 5 min: pick one design exercise (Part 1). Walk all 5 layers out loud.
- 3 min: pick 3 pushback Qs (Part 2). Answer each in <60s.
- 2 min: re-read the numbers (Part 3.A) and the universal opener (Part 3.C).
