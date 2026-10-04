# Seven-section narration experiment

The experiment keeps the current research, factual planner, claim ledger, targeted
editor, provider accounting and durable checkpoints. It replaces writing into
preallocated shot slots with one continuous narration call. Promptfoo remains an
evaluation harness. ShortGPT and the unmerged alternative rendering engines are
not required for this writing path; reverting the repository would also remove
the acceptance and recovery fixes this path needs.

## Flow and scope

1. Research and accept the factual outline with the existing planner and evidence
   cascade. A saved Studio child can reuse the parent's evidence. A structurally
   valid parent outline is reused; an obsolete outline (including duplicate
   single-use roles) is replanned from that ledger.
2. Assign seven editorial jobs: hook, original problem, proposed fix, overlooked
   behavior, consequences, outcome/answer, callback. They are not seven mandatory
   shots. The first evidence paragraph contains the hook and original problem;
   sections may contain several factual paragraphs.
3. Give one writer the complete accepted events, explicit context events and
   ledger. Request an evidence-bound outline, three hook candidates, a selected
   promise/payoff pair, and every stable paragraph ID in one continuous draft.
   Use the submission tool with explicit section/paragraph/claim IDs. Missing section evidence blocks drafting. Parallel effects must not be
   presented as a sourced chain just because the presentation is sequential.
4. Use existing fact-checking, evidence/integrity checks, convergent targeted
   repairs, runtime checks and final editorial grading on paragraph units. No
   automatic full-script replan to fix prose timing. Existing gates and repair
   ceilings still apply; a template is not a pass.
5. Freeze the final reviewed narration. Script-only stops here, with production
   planning explicitly marked as deferred. Studio displays paragraphs and the
   separate outline/source document.
6. A render child plans shots from exact character spans at sentence boundaries.
   Shot expansion must echo assigned words verbatim and may change visual fields
   only. Missing or rewritten rows use the existing two-attempt recovery. The
   reconstructed text, including separators, must equal the frozen narration.
   Evidence, structural and visual gates run before any TTS/image spending.

This initial template supports single-case intervention/consequence stories under
`removed_keystone` and `backfiring_solution`. Comparison-case/generalization
outlines and other engines are rejected rather than forced into the template.
The existing `scene_first` mode remains the default and the comparison baseline.

## Rejected drafts and one bounded repair (v2)

`seven_section_draft.json` retains the accepted plan and evidence identities,
each candidate (including malformed/truncated response text), field paths and
validation errors, per-attempt cost, and attempt status. It is private Studio
diagnostic data, not a script approval. Studio displays available candidate
paragraphs as unapproved and never enables rendering from this report.

The contract writer has two attempts total: the initial draft and at most one
repair. The repair receives the same accepted plan and evidence plus exact
field errors. Valid, unambiguous narration paragraphs are locked; a metadata
repair cannot rewrite them. A hook error can unlock the opening paragraph.
Explicit unresolved evidence gaps stop immediately rather than buying a
cosmetic repair. Missing fields, malformed output, and contract errors may use
the one repair. No factual or editorial gate is relaxed by structural acceptance.

The candidate and attempt counter are saved in the same checkpoint before
the repair call. Worker continuation reuses that state and durable provider
responses; operational, budget and storage failures propagate without buying
an extra draft. Exhausted attempts stay exhausted on replay. The job's existing
cap and provider reservation policy apply to both attempts.

The first live v1 test (`sr-68a3046dc3f25996bf3b7c92b305`) stopped with the generic
`SEVEN_SECTION_OUTLINE` error at $0.69, before fact-checking. Its exact rejected
response was not exposed by the old diagnostics, so the new recovery tests use
explicit synthetic failure cases, not an invented reproduction of that output.
This v2 change does not automatically restart that terminal v1 job or reinterpret
its approval policy. After deployment, create a new bounded draft from its
original evidence parent (`2bc5ef3a`); the updated policy gives that child a new
identity. Subsequent v2 continuations retain the plan and repair allowance.

## Using Studio

For a new illustrated landscape Standard story, select **Seven-section continuous
narration (test)** and **Script only**. For a saved eligible job, select **Try
seven-section narration** and a separate cost cap. The operation creates an
immutable child bound to parent checkpoint, content, policy and cap. The parent
is not changed. Repeated clicks return the same child. Agent-approved and directed
jobs remain in their original authorization/recovery workflow.

## What verification establishes

Offline tests use fake provider responses to exercise coverage, malformed prose,
source bindings, context claims, checkpoint replay, bounded retries, lossless
projection, stale reviews, child identity, and the actual script-only pipeline
boundary. They do not establish factual accuracy or improved viewer retention.

For the real comparison, use job `2bc5ef3a` as the saved evidence baseline. Record
the deployment/commit, child job, provider/model, cap, actual spend, elapsed time,
all rejection reports, final narration, factual errors, repair count and final
grades. Its original script failed; grade 75 (hook 78, story 72, ending 80,
repetition 58, cadence 82) is a preliminary model assessment, not an approved
baseline or measured YouTube retention. Compare final prose without revealing
which pipeline wrote it. Report failures even if the new draft reads better.

Known limits: one script cannot establish reliability; model scores are proxies;
exact projection protects words, not the factual correctness of generated images;
runtime remains advisory when the deployment's existing policy makes it advisory;
the current planner still plans a cold open that this writer does not prepend.
The template and old flow can therefore still incur planning and repair costs.

### PR164 live regression: case identity at the presentation boundary

The production test `sr-3decb63eed0999aa6cdbfa026c7a` passed the draft contract
on its first attempt, then failed the claim ledger with `INVALID_CONTEXT_REF`
for `event_04:hinge` and `event_09:tool`. Factual beats stored an empty
`parallel_case_id`; compiler-generated devices omitted it. Direct equality
mistook `None` and `""` for different cases. The accepted factual beats from
that run are retained in `tests/fixtures/pr164_stoat_accepted_beats.json`.

`story_fact_model.case_identity` now owns context case matching: normalized
scope plus trimmed case ID. Missing/blank primary IDs agree, while different
named cases and different scopes remain separate. Devices inherit their anchor's
scope/case; context resolution refuses self, nonfactual, and cross-case sources.
The seven-section brief validates presentation structure before drafting.
`presentation_context=canonical_case_v1` versions semantic acceptance and new
revision identity, so old validation results cannot masquerade as current passes.

A saved failed script can be evaluated through the existing bounded Studio
revision action without rewriting its words or repeating research/planning.
The original failed job stays failed. Normalizing identity only fixes the
structural defect; factual, editorial, and final approval gates still apply.
The PR164 draft's preliminary grade was 72 (cadence 62); this change makes no
claim that its creative quality or factual support is sufficient.
