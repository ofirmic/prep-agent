# AMC Mock Drill — Flashcard Q&A

> Pure practice prompts. Read the question, **answer out loud**, then read the model answer to check yourself.
> Anything you can't answer in 30 seconds → star it for tonight's drill.
>
> Not a replacement for `amc-project-deepdive.md` (which is the explanation). This is the gym.

---

## How to use this

1. Pick a category.
2. Cover the answer with your hand or scroll past.
3. Speak the answer out loud (don't read in your head — the bottleneck is verbal recall, not understanding).
4. Compare. Be honest. If you mumbled, star it.

---

## Category 1 — Ingest flow (who talks to whom, and why)

### Q1. Who initiates an AMC query request?

**A.** `Dataset Manager MS` owns scheduling. Its `QueryTriggerJob` (cron-like) publishes `fetch_request` messages to `newQueryRequestQueue` (SQS). `AMC MS` is the consumer.

**Follow-up trap:** "Why not have AMC MS pull a list of queries on its own schedule?"
→ Because **DSM is the source of truth for *what* should run**. AMC MS is the source of truth for *how to run it*. Mixing those couples them. The queue is the contract.

---

### Q2. Why REST for `get queries` but SQS for `fetch_request`?

**A.** Match the channel to the latency budget.
- `get queries` = synchronous read, must return now, small payload → REST.
- `fetch_request` = long-running work (minutes to hours), producer can't hold a connection → SQS.

**Pitfall:** Don't say "SQS for reliability." Reliability matters but the *primary* reason is the latency budget. REST is also reliable.

---

### Q3. Walk through what AMC MS does when it pulls a message off `newQueryRequestQueue`.

**A.** Four steps:
1. **Idempotency check** — does `query_request_id` already exist in MySQL with non-NEW status? If yes, skip (duplicate delivery).
2. **Persist** — write a `QUERY_REQUEST` row with status `NEW`.
3. **Trigger** — HTTP POST to Airflow REST API to start `amc_query_result_processing`.
4. **Flip status** — on trigger ack, update to `RUNNING`.

The pattern is **DB write → side effect → state update**. The DB row is the durable anchor; everything else is recoverable from it.

---

### Q4. Why does the status flip to `RUNNING` *before* AMC has actually started executing?

**A.** Because that's the latest event AMC MS has visibility into. After triggering the DAG, AMC MS is blind. The `RUNNING` state means "we handed off; expect a callback."

**Pitfall:** It's a *lie* to the customer dashboard — the UI shows "running" when the DAG might still be queueing. The real version would be a finer enum (`SUBMITTED → AMC_QUEUED → AMC_RUNNING → FETCHING → INGESTING → DONE`). Acknowledge the lazy decision; don't defend it.

---

### Q5. What does the DAG (`amc_query_result_processing`) own?

**A.** Everything between trigger and completion. Five steps:
1. **Submit** — call AMC's `triggerWorkFlowExecution`, store `executionId`.
2. **Poll** — `HttpSensor` hits `getStatusOfExecution` repeatedly. DAG run stays alive for the whole query duration.
3. **Fetch URL** — on SUCCEEDED, call `getPreSignedURL` for the S3 result.
4. **Invoke Lambda** — Lambda downloads from AMC's pre-signed URL, uploads to Skai's S3.
5. **Ingest** — Snowflake `COPY INTO` raw, transform, write to custom asset tables.
6. **Callback** — push status to `query_status_update` SQS.

---

### Q6. Why is the AMC poll *inside* the DAG (HttpSensor) and not a central poller service?

**A.** Trade-off:
- **Lose:** Airflow worker slots — each in-flight query holds a slot just to sleep between pokes.
- **Gain:** Failure isolation. One bad query / one stuck poll can't blow up the polling layer for every other tenant.

At small scale this is the right call. At 100x scale this becomes the wall — fix is deferrable operators (release the worker between pokes) or central poller (re-introducing the shared blast radius we chose to avoid).

---

## Category 2 — The Lambda and the cross-account S3 fetch

### Q7. Why a Lambda for the S3 transfer instead of Airflow doing the GET directly?

**A.** Three reasons:
1. **Trust boundary** — the IAM crossing between AMC's AWS account and Skai's needs minimum surface. Lambda is one resource with one execution role. Airflow workers are a VPC.
2. **Operational simplicity** — Lambda has zero idle cost; Airflow workers don't.
3. **Failure containment** — a hung download in Lambda is bounded by the timeout. A hung download in an Airflow worker holds the slot.

**Trap:** "Why not ECS?" → ECS has none of #1's minimal-surface benefit; you're already paying for #2; #3 is the same. ECS only wins when result size exceeds Lambda's 15-min cap. Then the right move is *hybrid*: Lambda for the common case, ECS for the tail.

---

### Q8. The pre-signed URL is a time bomb. Why, and how do you defuse it?

**A.** The URL is generated when the DAG asks AMC for it. The URL has a short TTL (matching Lambda's window). If the Lambda invocation queues cold-start *after* URL generation, the URL may expire before fetch. Lambda dies, DAG retries — but the **same expired URL** is in the retry, so the retry also fails.

**Real fixes:**
- Generate the URL *inside* the Lambda invocation (URL refresh in the retry boundary).
- Move the GET call as close to URL generation as possible.

We accepted the tail failure rate because cold starts are rare. If it became a SLA problem, move URL gen inside Lambda.

---

### Q9. What's Lambda's hard cap and what happens when you hit it on a large result?

**A.** **15 minutes**, hard. Hitting it:
- Lambda dies mid-transfer.
- DAG task fails, Airflow retries (with the same — possibly expired — URL).
- After max retries, job FAILED.

**Real fixes:**
- Byte-range chunked downloads (multiple Lambda invocations).
- Route the tail to an ECS task that has no 15-min cap.
- Stream-instead-of-buffer if Lambda memory becomes the constraint instead of time.

The lazy version: only fix once you have a customer hitting it.

---

### Q10. What does the Lambda actually do (5-step contract)?

**A.**
1. Receive payload (URL, dest bucket, dest path).
2. Stream-download from AMC's pre-signed URL.
3. Upload to Skai's S3 at canonical path `s3://...agency/dataset/report/date/year-month-week.csv`.
4. Return success/failure to caller.
5. No state, no DB writes — it's pure transfer.

**Why no state in Lambda:** the DAG is the orchestrator. Lambda is one stateless step. Mixing state into Lambda re-creates the durability problem the DAG already solved.

---

## Category 3 — Status state machine and the callback

### Q11. Why is the status callback on a *separate* SQS queue (`query_status_update`), not a direct DB write from Airflow?

**A.** Two reasons:
1. **Credential isolation** — Airflow workers should not hold the MySQL connection string or write credentials. The Java MS is the only thing with write access.
2. **Decoupling** — SQS has built-in retries. If MySQL is briefly down, the message waits. A direct write would fail and lose state.

The cost is one extra hop. The benefit is a hard isolation boundary.

---

### Q12. What status transitions exist, and which are idempotent?

**A.**
- `NEW → RUNNING` (when AMC MS triggers DAG).
- `RUNNING → SUCCEEDED` (when callback arrives).
- `RUNNING → FAILED` (when callback arrives with error, or sweep DAG times it out).
- `* → CANCELED` (rare, on manual ops).

**Idempotency:** every transition is implemented as `UPDATE status='X' WHERE id=Y`. Re-running the UPDATE on a row already at `X` is a no-op — that's why SQS at-least-once delivery is safe.

**Trap:** if you ever introduce `RUNNING → RUNNING_PARTIAL → SUCCEEDED`, you must verify that re-applying the same transition is safe. Usually yes; check before adding.

---

### Q13. The status enum is too coarse. What does that cost you?

**A.** The customer-facing dashboard can only show "running" or "done." It can't distinguish:
- Queued in Airflow
- DAG starting
- Submitted to AMC
- AMC executing
- Fetching result
- Ingesting

So when a query takes 4 hours, the customer has no idea where in the pipeline it is. The lazy fix is a `sub_status` column with structured stages. The cleaner fix is splitting the enum.

The price of *not* fixing it: support tickets. Customers ask "is it stuck or just slow?" and we can't answer in the UI — only by digging logs.

---

### Q14. What happens if the status callback message is *lost*?

**A.** The job sits in `RUNNING` forever in MySQL. The UI shows running. No automatic detection from the loss event itself.

**Recovery path:**
1. Stuck-job sweep DAG (runs hourly), finds rows in `RUNNING` older than ~6h.
2. Marks them `FAILED` with reason `stuck_timeout`.
3. Alerts on-call.
4. Operator runs `amc_cleanup_by_request_id` to drop partial Snowflake rows.
5. Operator re-triggers the original `fetch_request`.

**Trap:** the sweep DAG is the *lazy* version of saga compensation. A real orchestration system would have recovery as a first-class state, not a forensics tool.

---

## Category 4 — Cross-account IAM

### Q15. The S3 bucket with results lives in AMC's AWS account, not Skai's. Walk through the IAM design.

**A.**
- **AMC side:** their pre-signed URL embeds time-limited credentials that grant read access to the specific object.
- **Skai side:** the Lambda's execution role lets it (a) accept the inbound URL, (b) write to Skai's S3 with our own creds.

The Lambda is the boundary. AMC never sees Skai's creds. Skai never holds long-lived AMC creds.

**Pitfall:** the pre-signed URL is the *only* AMC credential that ever crosses the boundary, and it's short-lived. Anything else (assume-role from AMC, AMC IAM user keys stored at Skai) is a security smell.

---

### Q16. What's the customer onboarding ordering problem?

**A.** When a new advertiser signs up:
- AMC needs to know about Skai's IAM principal (the Lambda role) to authorize pre-signed URL issuance.
- Skai needs to know about the customer's AMC instance ID and S3 bucket.

If you provision in the wrong order, the first query fails with "access denied" and there's no clean rollback. Onboarding becomes a runbook: AMC config first, Skai config second, then a smoke test query.

**Trap:** the dependency is *not* enforced anywhere in code. It's tribal knowledge in the runbook. Real fix: onboarding wizard that runs the smoke test as a final step before marking the customer "live."

---

## Category 5 — Idempotency

### Q17. Where in the pipeline can a message get delivered twice, and what does each stage do about it?

**A.** SQS is at-least-once. Every consumer must handle duplicates.

| Stage | Duplicate handling |
|---|---|
| AMC MS reads `newQueryRequestQueue` | Idempotency check on `QUERY_REQUEST.id`. Duplicate → skip. |
| Airflow triggers a DAG | If a DAG run already exists for this `query_request_id`, Airflow's DAG ID uniqueness blocks the duplicate. |
| Lambda invocation | Pure transfer — re-running overwrites the same S3 object. Same result. |
| Snowflake `COPY INTO` | We use `FORCE = FALSE` so already-loaded files are skipped. |
| Status callback `query_status_update` | `UPDATE status='SUCCEEDED' WHERE id=X` is a no-op on retry. |

The unifying pattern: **every external effect is keyed by a stable ID, and applying the effect twice has the same outcome as applying once.**

---

### Q18. Why can't you just rely on SQS's deduplication?

**A.** SQS FIFO has deduplication for 5 minutes. AMC queries take *hours*. So if a duplicate arrives 6 hours later (e.g., from a retry storm or a DLQ replay), FIFO dedup won't catch it. You need application-level idempotency anyway. Don't trust the queue.

---

## Category 6 — Multi-tenancy

### Q19. How is each customer's data isolated?

**A.** Defense in depth, in three layers:
1. **Storage layer:** every row in Snowflake / SingleStore is tagged with `agency_id` and / or `instance_id`. Queries that omit the tenant filter raise an exception.
2. **Service layer:** AMC MS injects `tenant_id` into every query at the ORM level.
3. **Audit:** every read / write logs `tenant_id`. We can prove what each tenant touched.

The store is the floor — even if a bug in the service layer drops the filter, the store policy catches it. (Or *would* catch it if we had row-level security configured. Currently we don't; we rely on the service layer. Acknowledge the gap.)

---

### Q20. How do you attribute *cost* to a specific customer?

**A.** Query tags. Every Snowflake query carries `QUERY_TAG = 'agency=X,instance=Y,dataset=Z'`. Snowflake's billing API exposes credits per query, so:

```sql
SELECT
  PARSE_JSON(query_tag):agency::string AS agency_id,
  SUM(credits_used_cloud_services + credits_used) AS credits
FROM snowflake.account_usage.query_history
WHERE query_tag IS NOT NULL
GROUP BY agency_id;
```

That's how a finance question ("which customer drove last month's bill?") becomes a SQL answer instead of a guess.

**Trap:** Lambda and Airflow worker costs aren't query-tagged. We approximate by job count × average duration. Honest answer: cost attribution is *most accurate at the warehouse layer*, *approximate at compute*.

---

## Category 7 — Scaling

### Q21. Walk me through the per-component cost shape at 1×, 10×, 100×.

**A.** Bottleneck moves as scale increases.

| Component | 1× | 10× | 100× |
|---|---|---|---|
| Java MS | Negligible | Negligible | Config (bigger instances) |
| Airflow workers | 60 slots | Need 600 slots — $$$ | **Wall**: 6000 slots polling = absurd |
| AMC API rate limit | Fine | Probably fine | **Org wall**: needs negotiation with Amazon |
| Lambda concurrency | Fine | Bump reserved concurrency | Fine if Amazon raises limit |
| Snowflake | XS warehouse | M warehouse | L warehouse + per-tenant warehouses |
| SingleStore | Fine | Read replicas | Sharded by tenant |

**Killer insight:** the *first wall* is the polling load on Airflow, not the data layer. Fix order:
1. Deferrable operators (releases worker between pokes) — config change.
2. Central poller DAG — re-introduces shared blast radius.
3. Webhooks from AMC — requires Amazon to ship them.

---

### Q22. Which scaling changes are "config" vs "money" vs "engineering" vs "org wall"?

**A.**
- **Config:** Snowflake warehouse size, Airflow `max_active_runs`, Lambda concurrency.
- **Money:** more Airflow workers, bigger Snowflake warehouse, SingleStore replicas.
- **Engineering:** deferrable operators, central poller, byte-range Lambda chunking, schema versioning.
- **Org wall:** AMC API rate limit (negotiate with Amazon), pre-signed URL TTL (Amazon-side config), customer onboarding ordering (cross-team).

The point of this distinction: **the easy fixes are at the bottom of the list, but the actual bottleneck at 100× is the org wall.** Senior signal: name the org wall first.

---

## Category 8 — Failure modes

### Q23. List every way an AMC query can fail end-to-end, and how each is detected.

**A.**
| Failure | Where | Detection |
|---|---|---|
| Bad query SQL | AMC side | AMC returns error → DAG fails → callback `FAILED`. |
| AMC API down | Trigger / poll | HttpSensor retries; eventually DAG task fails. |
| Pre-signed URL expired | Between gen and Lambda | Lambda 4xx from S3; DAG retries (usually fails again). |
| Lambda timeout | Transfer | Lambda invocation error; DAG retries. |
| Snowflake `COPY INTO` schema mismatch | Ingest | Snowflake error → DAG task fails. |
| Lost SQS callback | Status update | Stuck-job sweep DAG (~6h delay) catches it. |
| Lost `fetch_request` SQS message | Trigger | **No detection** — the job never starts. Only the customer asking "where's my query" catches it. |
| Schema drift in AMC custom tables | Customer-side | Query returns weird shape → COPY INTO fails or worse, succeeds with wrong data. **Hardest to detect.** |

**Trap:** the lost-fetch-request case is the worst — silent failure. There's no anchor row because the row is *created from* the message. Real fix: DSM logs every fetch_request it publishes, and a reconciler compares DSM's log vs AMC MS's table.

---

### Q24. "Customer says one specific number on their dashboard is wrong." Walk your diagnostic flow.

**A.**
1. **Get the query** — what filter, what date range, what custom asset.
2. **Find the row in SingleStore** — does the number match what they see? If yes, problem is at serving or further upstream.
3. **Compare to Snowflake** — does Snowflake have the right number? If yes, problem is in the SingleStore reverse-ETL.
4. **Compare to the raw S3 file** — does the raw match Snowflake? If no, problem is `COPY INTO` or the transform.
5. **Compare raw to AMC** — re-run the AMC query manually. Does it match the raw file? If no, AMC's the source.

Five layers, five comparisons. The bug is at the layer where the comparison *first* breaks.

**Trap:** customers often think the bug is "the dashboard" when it's actually "the source." Run all five layers before concluding.

---

### Q25. How do you safely deploy AMC MS during business hours?

**A.**
- **Rolling deploy** with health checks — old pods drain SQS messages they're already processing; new pods start consuming.
- **In-flight DAG runs are unaffected** — they're owned by Airflow, not the Java MS.
- **MySQL schema changes** — backward-compatible only (additive columns). Never drop or rename in the same deploy.
- **Feature flag for new behavior** — turn it on for one customer first.

**Trap:** the failure mode that breaks this is a *queue consumer* that crashes mid-message-processing without releasing visibility. SQS will redeliver after the visibility timeout. The new consumer picks it up; idempotency (Q17) makes that safe.

---

## Category 9 — What would you do differently?

### Q26. Clean sheet — what's the one architectural change you'd make first?

**A.** **Saga-style orchestrator** with recovery as a first-class state, not a sweep DAG.

Current: Airflow runs the happy path; the sweep DAG is a forensics tool that finds stuck rows hours later.

Better: Step Functions or a custom orchestrator where every step has a defined compensation action. Recovery is then *automatic* and *bounded in time*, not "we'll find it within 6 hours."

The price: more upfront design, more code to maintain. The win: stuck jobs become impossible by construction.

---

### Q27. What about Airflow specifically — would you keep it?

**A.** Yes for the DAG model (it's the right abstraction for our DAG-shaped problem). But two changes:
1. **Deferrable operators from day one** — the HttpSensor's worker-slot pressure is foreseeable. We took the lazy path.
2. **Better isolation between tenants** — currently one bad query can starve other tenants of worker slots. Per-tenant `pool` config in Airflow would fix this with one config change. We didn't because we never hit it. Senior version: ship it anyway because it's almost free.

---

### Q28. What about the status enum?

**A.** Replace the coarse `(NEW, RUNNING, SUCCEEDED, FAILED)` with a finer state machine:
```
SUBMITTED → AMC_QUEUED → AMC_RUNNING → FETCHING → INGESTING → DONE
                                                            ↘ FAILED (with stage tag)
```
Add a `sub_status` column for free-text detail.

Benefit: customer-facing UI can show real progress; on-call can debug by stage; metrics dashboards show p95 latency per stage.

Cost: every transition needs a new test. Old code that filters on `RUNNING` needs updating.

---

### Q29. What's the worst on-call you had with this system?

[Pick a real story. Structure: situation → tension → action → result → reflection. Use "I" not "we." Numbers in the result. Lesson in the reflection.]

**Skeleton if you need one:**
- Situation: customer-facing dashboard showed stale data for ~6 hours.
- Tension: support ticket arrived 4h after stale data started; we didn't catch it ourselves.
- Action: traced through the 5 layers (Q24); found `query_status_update` SQS queue had ~200 messages stuck in DLQ.
- Result: re-drove the DLQ; data caught up in 30 min; ran the cleanup DAG for affected tenants.
- Reflection: we shipped a DLQ alarm the next day. The bug was "we have a DLQ but no one watches it."

---

## Daily 5-minute drill

Pick 5 Qs at random. Set a 30-second timer per question. Speak the answer out loud. If you can't finish in 30s, the answer's not crisp enough yet.

The goal isn't perfect recall. The goal is **conversational fluency** — answering at interview pace, not study pace.
