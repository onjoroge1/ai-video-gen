# Script reliability: recover work, not verdicts

## What the production evidence says

PR157 job `b88682ec` stopped at $1.01 after research with
`UNSCORED_JUDGE_UNAVAILABLE: planning claim support [INCOMPLETE_COVERAGE]`.
The saved research contains 30 claims. The old reviewer required one exact, complete
array for the whole dossier and made a single call. Missing, duplicate or unknown IDs
collapsed into the same error. No planner, hook or script was generated. We have not
recovered the exact missing/duplicate IDs from this legacy response in this change;
the migration rechecks the saved provider response before allowing any restart.

This is different from PR156 job `b3cf7a4f`: that job wrote a script and failed factual
validation after two rejected repair/trim candidates. Its 75/100 score was preliminary,
not a delivery approval or measured viewer retention. New hooks do not repair the
underlying evidence lifecycle by themselves.

## First principles

1. A factual decision belongs to an immutable claim/passage and review contract.
   Supported, unsupported and unreviewed are three different states. Missing output
   must never become unsupported evidence or a pass.
2. Recover at the smallest useful unit. A malformed response should not force new
   research or discard valid decisions for other claims.
3. A retry budget belongs to the job and its exact inputs, not a worker process.
   Completed paid responses and review progress must survive crashes and resumes.
4. Separate request execution from semantic acceptance. The provider may have charged
   for a successfully returned response that failed the application's schema. An
   unknown provider outcome cannot be replaced with a new paid request.
5. Delivery still requires complete validation. Editorial grades and speculation about
   retention must not disguise factual failures or missing checks.

## Implemented in this change

- At most eight claims per response; at most two attempts per batch. The second call
  contains only unresolved claims. Reasons are concise and output is capped at 2400 tokens.
- Unique, well-formed decisions are retained. Duplicate IDs are unresolved even if the
  repeated decisions agree. Unknown IDs are recorded but never enter the dossier.
  Truncated/unexpected tool responses are not partially accepted.
- Each response checkpoints accepted decisions, per-batch attempt counts, requested IDs,
  missing/duplicate/unknown/invalid IDs and status. Exact dossier, model and contract
  identify this progress. The normal completed research cache is unchanged.
- Exhaustion fails closed and remains exhausted after restart. Provider exceptions
  propagate to the existing durable/account recovery layer. No automatic new job.
- Studio exposes `planning_review.json` alongside its other private saved checks.
- Explicit, checkpoint-bound migration for the old incomplete-coverage failure only.
  It checks the exact saved research cache against the current request/model, rejects
  downstream/new-review work, reproduces the old incomplete response from the paid-stage
  ledger, and checks settled stages, leases, reservations and remaining original budget
  under a job lock. One migration marker prevents repeated rearming. Controlled pilots
  retain their original workflow. GET/status/artifact inspection never queues work.
- Existing research and paid stage records remain intact. The old monolithic review is
  replaced by the new bounded review, so reviewing can incur new text-model usage.
- Package and installed-wheel checks include the hook and integrity modules as well as
  the new recovery module; source-checkout imports alone were insufficient coverage.

The migration is deliberately a compatibility bridge, not a growing list of automatic
retry exceptions. New review exhaustion does not qualify for another migration.

## Remaining flow defects and priority

The previous script exposed a separate representation problem: `_cold_open` is removed
from scene-one validation by exact prefix matching. Fact-checking can change its spoken
text while leaving that metadata stale, causing the corrected cold open to be judged
against the setup event. The repair's scene-specific evidence can then exclude the
cold-open evidence. This needs a single authoritative narration representation with
explicit hook/cold-open/body spans and evidence provenance preserved through edits;
loosening entailment or adding fuzzy matching is not the fix.

After that, evaluate the whole-script reviewer on accepted paraphrases as well as real
errors. The prior run flagged both the real survival-to-fledging substitution and claims
that may be overly strict (e.g. a species already explicitly described as mainland-only
loss). Do not improve the apparent pass rate by switching these gates off.

Finally, measure the writing separately: actual opening, first 30 seconds, mechanism,
progressive revelations, repetition, answer and callback. Use fixed saved dossiers for
comparisons so research variance does not masquerade as a hook improvement. Only a
complete script can receive this assessment; audience retention requires published data.

## Acceptance tests

Offline tests exercise partial/malformed output, duplicate and unknown IDs, truncated
responses, bounded batches, charged responses, interrupted checkpoints, restoring on a
fresh worker, exhausted budgets surviving restarts, and provider replay when checkpoint
writing fails. Recovery tests reject unrelated content failures, new exhausted reviews,
unsettled/non-script stages, stale checkpoints and changed research requests; reproduce
legacy coverage failure; enforce authentication; and verify duplicate-click behavior.
A production resume remains untested until this change is merged/deployed.
