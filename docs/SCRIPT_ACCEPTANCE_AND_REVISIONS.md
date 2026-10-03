# Script acceptance and immutable Studio revisions

This change addresses the PR159 audit's conflicting planning inputs, stale acceptance,
missing Studio diagnostics, expensive full-pipeline retries and unsafe offline fixtures.
It does not establish measured viewer retention or a 100% generation success rate.

## Text contract

The causal planner and Promptfoo share `story_planner.planner_prompt`. The production
prompt includes the hook/answer/callback brief. Optional attention functions require
supporting evidence; an ecological introduction no longer receives an unconditional
instruction to show that it worked or to invent an incentive-derived mechanism.

Expansion receives the accepted event as its factual beat. Unvalidated planner beliefs,
expected/actual outcomes, causal descriptions and state descriptions do not reach the
writer as competing facts. This preserves the distinction between documented intention
and observed success.

`script_finalizer.evaluate` runs after the last text repair for both script-only and full
illustrated delivery. Source/integrity validation, structure, storyboard, duplicate checks
and the exact-narration editorial review all block acceptance. Runtime follows the
existing advisory/hard policy. An earlier incomplete fact-check remains in history;
a complete review of the current words and evidence determines the current decision.

Readiness records bind the content, evidence, question, requested duration, factual-check
setting, provider/model and acceptance policy. Approval cannot carry over to a changed
version. Final provenance counts distinguish page-verified quotations from other source
provenance; a semantic pass is not independent retrieval or proof that a dated fact is current.

Grammar and time-scope findings join the integrity contract. Metric repairs may select a
correct measure already in the ledger, but any changed factual event must pass the existing
source/scope/fidelity cascade. No new research is purchased by this repair.

## Studio actions

`POST /api/studio/jobs/{job_id}/script-revisions` is authenticated and accepts:

- `mode`: `evaluate` or `render`
- the displayed `checkpoint_sha256` and `content_sha256`
- an explicit `cost_ceiling_usd`, bounded by the deployment limit and $10

Eligible sources are terminal ordinary illustrated jobs with a saved script and ledger.
Agent-action and controlled/directed jobs retain their original approval workflow.
The public generation API rejects caller-supplied revision seeds.

Evaluation creates an immutable child job from the saved script and ledger. It uses the
production fact-check, bounded repair, editorial and final acceptance path, skips research
and planning, and stops before media. The original failed job remains failed.

Rendering requires a source job awaiting script approval and a current passing certificate.
It copies the accepted script and skips all writing and grading stages. An enforced measured
runtime mismatch stops the render; it cannot authorize a silent TTS-time rewrite. Packaging
also preserves the approved title. Media has its own technical/visual gates and can still fail.

The deterministic child ID binds parent checkpoint, complete saved draft, operation,
settings, acceptance policy and cost cap. Duplicate clicks reuse that child job. A different
cap or operation is a different explicit spend boundary, not a recovery of the parent.
Studio shows the parent identity and final result in `script_revision.json`.

## Verification and rollout

The CLI sampler now calls production `run_explainer_pipeline(stop_after_script=True)`;
it cannot pass based on a shorter, independently maintained sequence. Fresh samples bypass
the optional development cache. Reported costs are estimates, not provider invoices.
Promptfoo editor acceptance uses the production edit transaction plus semantic validation.
The paid editor evaluation therefore includes additional judge calls and is not covered by
a Studio job's ceiling.

Offline tests block real HTTP transports before proxy routing and SDK retries. The transport
integration fixtures mock planning review, language judgments and credit probing explicitly;
real FFmpeg, checkpoints, paid-stage accounting and restored media still run. These synthetic
fixtures establish transport behavior, not script quality.

After merge/deploy, use the saved stoat draft as the first evaluation child with a displayed
cap. Inspect final narration, per-stage errors, provenance and revision history. Do not restart
research solely because a PR merged. Then use a small held-out set across story engines to
compare human judgments of hooks, causal progression, payoff and spoken cadence. Track
first-pass acceptance, repair acceptance, latency, spend and failures by stage. Actual retention
requires audience data; model grades remain editorial proxies.

Remaining audit work includes comprehensive source-date extraction/backfill, typed metric
validation upstream, source-fetch security hardening, broader multi-topic judge calibration,
and empirical retention measurement. The current change carries dates/metrics when available;
it does not infer missing publication dates or certify unreachable quotations.
