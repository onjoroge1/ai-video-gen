# Illustrated flow repair review — September 5, 2026

Reviewed baseline: `7d3a171`, latest `main` after PR #76. This review builds on `920c099` and
`3777449`; it does not rewrite those commits or claim their historical live samples were repeated.

## Finding

The runtime experiment is useful but does not establish that a five-milestone engine cannot fit
170 seconds. Cobra's labelled mechanism begins at 36 seconds. The existing 20% gate permits that
unchanged opening at exactly 180 seconds; 170 seconds permits 34 seconds. One 220-second result
without LATE_MECHANISM is encouraging, not an established pass rate. ENGINE_ORDER still failed.

Source inspection found additional deterministic contradictions after the earlier timing fix:

- The illustrated sheet inherited cinematic mechanism-at-scene-two and reversal-then-escalation
  instructions. The expansion pass repeated these instructions, overriding the planned engine.
- The labeller demanded every engine use all singleton roles and placed the hinge immediately
  after false resolution. Its deadline was stated as a fraction of the beat list, not speech.
- The sheet-selected engine was passed as a hard pin even on the initial labeling pass.
- Equal expansion budgets competed with the compact opening; the spoken hook and format tag
  needed to be reserved before allocating opening words.
- The 25-word scene floor could shrink a short request below the engine's required beat count;
  slicing surplus returned beats from the end could delete the closing payoff.

## Changes

| Area | Repaired behavior |
|---|---|
| Engine choice | Supplies reference opening times, support counts and target compression as planning evidence; no engine bans or relaxed deadlines. |
| Planning | Retrieves the reference before the sheet and uses one illustrated order/timing contract. Exact seconds replace rounded-down minutes. |
| Labeling | Initial engine is a preference, repair attempts remain pinned, and the final choice/reason is retained. An engine switch no longer forces the former mechanism slot onto it. |
| Narration | Per-beat budgets preserve the short opening, including hook/tag overhead, and retain the complete causal ending. Expansion follows the selected engine. |
| Candidate selection | Fewer causal failures outrank retention when both candidates fail. Editorial improvement cannot replace a causally valid draft with a broken one. |
| Truncation | SDK metadata survives caching. Truncated/paused responses settle as incomplete with their costs recorded. Expansion halves failed batches down to one beat. |
| Restart | An identical incomplete response is replayed without another provider call; smaller revised requests have distinct reservations. Legacy truncated caches are reclassified without a second charge. |
| Research | Uses the native Anthropic search client even when plain script calls use OpenAI; usage is estimated at the existing native rates. |
| Local launch | Uses `python3` from PATH instead of one developer's Homebrew executable. Dependencies still need to be installed. |
| Sampling | Supports illustrated mode, fresh repeated samples, incremental JSON reports, and production script checks. Preserves failures and reports incomplete cost estimates honestly. |

No quality threshold changed. Invalid scripts still fail. No fabricated claims, manual beat
relabeling, imagery replacement, paid generation or production mutation was used to validate this PR.

## Verification and its limits

Local CI-equivalent result: **862 passed, 8 skipped**, using
`python -m pytest -o addopts='' -q tests bolt_seq/tests/test_state.py`. The eight existing skips
remain; no new skip was introduced. `git diff --check` is clean.

The automated suite includes behavioral tests for preference versus retry pin, reference timing
at 170/180/220 seconds, complete short-story endings, causal-error ranking, provider routing, and
truncation recovery. The real script expander is exercised with a fake provider and durable store:
a 10-scene truncated batch becomes batches 1–5 and 6–10; a replacement worker replays the result
without additional provider calls or duplicate spend. SQL settlement behavior is unit-tested; no
live Postgres failover or production process termination was performed.

These tests prove deterministic behavior under supplied responses. They do not establish that a
live model follows the revised prompts, that actual TTS meets the estimated timing, or that a
publishable MP4 can complete production. The reference corpus has only five timed references and
cannot establish statistical engine/runtime limits.

## Remaining production work

1. **Illustrated agent entry and exact approval.** The public agent API accepts directed pilot
   and full-film specs, not topic-based illustrated requests. The generic endpoint requires a
   session/secret, and controlled illustrated pilots are rejected. Add an immutable proposal
   operation with truthful script/media scope and enforced costs; keep the existing auth boundary.
2. **Worker readiness and continuation.** Provider credentials/model access are absent from
   readiness. The UI still defaults to 600 seconds against an 800-second worker invocation, and
   there is no cooperative deadline-aware yield. A blanket `ValueError` classification makes
   transient research failures terminal; the browser closes its event stream on retry errors.
3. **Approval scope invariant.** The Hippo Weed spec declares a 208-second pilot while the UI says
   first 45 seconds. Its $25 request is rejected by the default $5 action cap and it is not an
   allowlisted bundle, so this is a latent configuration-dependent defect. Enforce the 45-second
   scope in action validation before exposing that path; do not simply increase the cap.
4. **Provider output and accounting.** Completed-but-malformed JSON still needs validation at
   structured call sites. Generic cache serialization cannot decide each schema. Native durable
   cost estimates retain old fixed token rates and omit search/cache pricing; they are not a
   provider billing ledger. Paused research calls still need explicit continuation support.
5. **Production acceptance.** After approved script sampling passes, verify request → approval →
   queue → script → TTS/images → MP4 → Blob → Finished Videos, including a real worker restart.
   A component test or one successful script is not that acceptance test.

## Next experiment

Use the new sampler at the intended duration with unchanged gates and fresh drafts. Record all
outcomes, final/planned engine, causal timing, model, flags and recorded cost. A matched 220-second
control can test the runtime hypothesis separately. The command is paid and has no aggregate spend
enforcement, so obtain a concrete sampling budget first; do not promise five samples cost $5.

The first media canary should follow passing scripts and the repaired approval/worker path.
Do not default to a 60-second Cobra canary as if it were the most calibrated choice: that gives
the opening only 12 seconds against the sole observed 36-second reference.
