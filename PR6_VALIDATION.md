# PR 6 Validation — Durable Production Execution

This document records the merge gate for PR 6 of `LONGFORM_BOLT_EXPLAINER_ROADMAP.md`.

## Requirement disposition

| Roadmap requirement | Disposition | Evidence |
|---|---|---|
| Durable workflow/queue | PASS | Postgres queue with `FOR UPDATE SKIP LOCKED`, exact-job dispatch, renewable worker leases, expiry recovery, and attempt exhaustion |
| DB-backed jobs/events/stages/costs | PASS | Strict `generation_jobs`, `generation_events`, `generation_stages`, and `generation_artifacts` ledgers; storage exceptions are never converted to empty results |
| Blob-backed assets/checkpoints | PASS | Official Vercel Python SDK upload/download/delete; SHA-256 verification; safe checkpoint archive extraction; immutable stage and final paths |
| Stage-level idempotency | PASS | Stable request-hash/idempotency keys, reservation before calls, completed-stage restore, and request-content collision rejection |
| Cross-worker resume | PASS | New workers restore `_state.json`, human review, and every paid file from Blob; durable runtime context is explicitly propagated into pipeline worker threads |
| Explicit storage failures | PASS | Queue, worker, SSE, artifact, and finished-library failures return explicit retryable storage states; UI displays storage outage separately |
| Reliable `/finished` | PASS | Completed video metadata and artifact URLs finalize atomically in Postgres; an empty DB remains empty while a DB outage is HTTP 503 |
| Orphan cleanup/finalization | PASS | Registered provisional artifacts from terminal jobs and aged unregistered objects under `jobs/`/`finished/` are reconciled; unresolved reservations are conservatively charged at finalization |

## Acceptance evidence

| Acceptance criterion | Proof |
|---|---|
| Terminate a worker and resume elsewhere | Crash-window fixture leaves an in-flight reservation; a second runtime uses the same stage key and provider idempotency key. Separate checkpoint fixture restores state and hash-bound review files into another worker directory. |
| Never repurchase a completed provider stage | A completed paid image is downloaded from Blob by worker B while a replacement provider callback is configured to fail if invoked. |
| Cross-instance status | Events and terminal state are read from Postgres on every SSE poll; no process-memory dependency exists in durable mode. |
| Blob/DB failures visible and recoverable | Storage failures produce `storage_error`/503; retry and review-approved jobs requeue from the persisted checkpoint. |
| `/finished` never masks an outage | Route-level tests distinguish an empty authoritative table (200, zero videos) from a connection failure (503 `FINISHED_STORAGE_UNAVAILABLE`). |
| Retries respect spend envelope | Every new stage reserves against committed + reserved cost before its provider call and is bounded by the single-call ceiling. A crash retry keeps one reservation and one stable key; uncertain accepted calls are charged at their full reservation. |

## Defects found during adversarial verification

The first implementation was not accepted. Verification found and corrected:

- an exact dispatch could claim another queued job due to SQL `AND`/`OR` precedence;
- parallel TTS/image/motion threads lost the durable `ContextVar` and could bypass the ledger;
- long local/provider work had no independent lease heartbeat;
- exhausted jobs could remain perpetually retryable;
- failed-provider reservations could remain unexplained after successful fallback/finalization;
- Blob objects created immediately before process death were not discoverable by registered-only cleanup;
- the finished library could visually resemble an empty library during an outage;
- schema DDL would have run on every SSE polling cycle.

## Verification performed

```text
python -m compileall -q app.py explainer_pipeline.py durable_execution.py finished_api.py private_access.py
python -m pytest
node --check < extracted static/index.html script
python -m build --wheel --sdist
git diff --check
```

Local result before publication: **164 passed**. SDK introspection verified the installed
`vercel==0.7.0` Blob signatures and OpenAI image, speech, and video `extra_headers` support.

The local sandbox could not resolve the configured Neon hostname, so it could not serve as a live
database integration environment. This is recorded as an environment verification item, not silently
reported as a pass. GitHub CI, the Vercel preview build, and deployed production-readiness/storage
checks remain mandatory before merge.

## Cost guarantee boundary

The system guarantees the configured committed-plus-reserved cap before each new provider call. If a
worker dies after a provider accepts a request but before the result is committed, one call can remain
ambiguous. The retry reuses the same provider idempotency key and the ledger retains/ultimately charges
the original reservation. Provider-side idempotency is defense in depth; the database guarantee does
not pretend that an external provider can never bill an accepted request whose response was lost.

## Rollback

- Pre-PR6 production baseline: `checkpoint/pre-pr6-main-0d37832`

PR6 can be reverted as one phase without reverting PRs 1–5 or the roadmap.
