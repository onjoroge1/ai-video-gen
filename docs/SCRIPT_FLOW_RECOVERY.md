# Script flow recovery and readiness

This change addresses the audit of Studio job `ad241e26` on PR150. It does not mark that failed
job successful or claim a live passing script. No new provider generation was purchased while
implementing the fixes.

## Persistent stages

`script_stages.py` saves job-local, input-addressed outputs under `script_stages/`. Each record
has input and output hashes and is uploaded through the existing durable checkpoint mechanism
before its consumer runs. It is an application-stage cache, in addition to provider-response replay.

Completed research is frozen: continuation does not refetch source pages and reorder verified
versus attested claims. Planning claim-support review, accepted plans, expansion progress,
graded drafts and fact-check outputs are also saved. Expansion progress carries the batch cursor,
previous narration and consumed count retry. Technical repairs are checkpointed before final
editorial review. Script-state corruption or write failure no longer silently starts paid work
from scratch. Existing durable job budgets, reservations and leases still apply.

An interruption inside an unfinished stage may replay its deterministic orchestration using
the existing provider responses. Completed semantic boundaries skip that orchestration entirely.
This is not a promise of provider-side exactly-once execution across ambiguous network outcomes;
the existing ambiguous-outcome protections remain authoritative.

Change the explicit stage contract version when a future code change makes a saved result
incompatible. Evidence revision is a different input and produces different descendant identities;
do not mutate a stored record or remove it to force a paid retry. Durable database spend remains
the billing source of truth; cached semantic outputs do not constitute new provider charges.

## Planner attempts and evidence

There are at most three alternative briefs: consequence-led, intervention-led and physical-object-led.
Each has stable request text, so each slot replays independently. Result hashes reveal duplicate
outputs even when the briefs differ. Deterministic candidate score is preflight, not semantic approval.

`research_attempts/` retains independently addressable attempts and verdict snapshots.
`selected_research_attempt.json` identifies the active plan. Studio resolves that selection from
the same checkpoint; evaluating a rejected alternative does not replace the active diagnosis.
Unavailability is named `UNSCORED_JUDGE_UNAVAILABLE`, even if required-role coverage is complete.

Before an illustrated plan is purchased, one bounded claim-support request compares each claim
to its attached quotation. Unsupported paraphrases are excluded from the planning set and retained
in the diagnostic dossier. The original research snapshot is unchanged. Reachability, quote
verification, provenance and claim kind are visible in planner context. This semantic check does
not turn an unreachable source into a verified one; downstream source and event gates still apply.

In addition to the existing incentive repair, one event-citation repair can address up to four
failed events using reachable, page-verified, primary-story claims already in the ledger. Only
citations can change. Proposals are recompiled and judged; failed proposals retain the previously
evaluated plan. Contradictions and unavailable judgments do not trigger speculative recitation.

## Final script readiness

Illustrated Script Only requires evidence, long-form structure, storyboard, no duplicate narration
and a final editorial report bound to the same narration identity. When fact-checking is requested,
its completion must be recorded; unavailable or rejected reviews cannot silently pass. Legacy
checkpoints without that review record require an explicit review/recovery rather than assumed approval.
Runtime remains advisory unless
`RUNTIME_HARD` is enabled; the report records this policy and any warning. A high-scoring baseline
now faces structural checks even when no polish edit is needed. Stale editorial reports cannot pass.

The readiness report records script/evidence hashes, gate results and policy. Studio displays its
warnings. Script approval is checkpointed and stops before media estimates, music generation and
media provider work. The generation manifest uses the awaiting-script-approval status, not failed.
This script policy does not silently arm every advisory full-film rendered gate.

## Cadence reference requested by the operator

Reference links:

- https://youtu.be/kS0qNsNmxN4
- https://youtu.be/WjVIH-djRpc

YouTube page/transcript retrieval was unavailable in the implementation session. The usable basis
is the operator's partial shark-meat opening, not a measured analysis of both complete videos.
No transcript, WPM, cut timing or whole-video retention result is invented.

The supplied opening demonstrates familiar setting → concrete action/details → ordinary expectation
→ unsettling reinterpretation. Short setting beats and natural everyday sentences build toward a
longer reveal. This is more useful than requiring every sentence to be short or every scene to ask
a question. The planner, expansion, polish and grading prompts share this guidance, while retaining
source limits, hook/hinge budgets and the mechanism deadline. Calm specificity can earn attention;
the grader no longer requires every opening to be a dramatic gut-punch.

`script_cadence.py` reports sentence lengths, median/range and warnings about monotonous or
overly clipped writing. Spoken chapter labels are excluded from those measurements. These metrics
are advisory; deliberate setting phrases are not equated with grammatically broken repairs. They
do not establish that the script matches or beats either reference. Full transcript/video access
and a read-aloud comparison of the next completed Studio script are still needed.

## Evaluation

The normal CI pytest suite includes `tests/test_script_flow_recovery.py`. It uses no network and
tests worker changes, checkpoint boundaries, rejected alternatives, citation scope, duplicate
candidate replay, baseline structure and stale grading. The installed-wheel smoke test imports
all new modules and the planner/editor/repair modules that were missing from the package list.

Promptfoo configurations now use the production script-provider adapter rather than a separately
hardcoded model. Paid evaluation requires `REELFORGE_PAID_EVAL=1`; it remains opt-in and does not
inherit a Studio job's dollar cap. See `evals/promptfoo/README.md` for scope and commands.

After merge/deployment: run one authenticated Script Only test, inspect the selected attempt and
readiness hashes, and review the actual script for concrete opening, progression, sentence rhythm
and earned ending. Do not infer audience retention from a model score.
