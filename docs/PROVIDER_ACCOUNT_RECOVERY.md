# Provider account recovery

An account rejection is an operational pause, not an unsupported story. The shared
Anthropic adapter recognizes explicit insufficient-credit, authentication and permission
HTTP responses. It raises `ProviderBlocked` through the evidence and writing layers.

The durable worker saves its checkpoint and enters `provider_blocked`. Scheduled worker
polling does not claim this state. The console explains the problem and offers **Resume
this video** after account access is restored. Resume uses the existing approved action's
dispatch endpoint; it does not create a proposal or ask for spending approval again.

The resume transaction verifies the checkpoint, one rejected Anthropic stage, its existing
reservation, and the original job budget. It grants one explicit attempt. The same request
hash and idempotency key are retained. Completed research, writing and media are restored;
they are not repurchased. A second account rejection pauses again.

The reservation remains held for the rejected request until that exact call eventually
settles. Reserved allowance is not recorded provider spend. No code assumes that setting an
idempotency header by itself guarantees provider-side deduplication of ambiguous requests.

Timeouts, server errors, malformed model output, evidence rejection and budget exhaustion
do not qualify for this account-resume path. Existing retry and evidence rules still apply.
The compatibility reader handles older saved SDK account errors, including the cane-toad
run, without topic names, action IDs or per-PR recovery markers.

Reusable units:

- `provider_blocks.py`: rejection classification, safe messages and worker control signal.
- Anthropic durable adapter: records the blocked stage while preserving its reservation.
- `PostgresStore.resume_provider_block`: atomic eligibility and explicit resume.
- Durable worker and action console: pause, display, authenticated dispatch and continuation.

Validation covers three unrelated topic inputs, rejected and restored credentials, saved
legacy errors, ambiguous reservations, exhausted budgets, and duplicate resume requests.
The delivery integration test simulates credit rejection twice, restores access, and then
uses real FFmpeg and download/hash verification to deliver an MP4. Provider responses and
database/Blob adapters are simulated; this does not prove a fresh live story's quality.

## What a resumed worker saves and reuses

The worker may enter the pipeline from its beginning, but completed provider requests are
replayed by request hash. A changed prompt is a new request. Research and draft factual
beats can therefore be saved even while evidence validation still prevents a full script.
The complete script is saved before narration and images; completed media has its own
immutable per-stage artifact and is restored separately from the control checkpoint.

Evidence coverage now also checkpoints the work between provider calls:

- The bounded set of exact passages selected from verified primary sources, before judging.
- Each decided entailment result, including rejections and its usage subtotal.
- The returned focused supplement, before its source validation and claim judgments.

These records live in the private `evidence_coverage_v2.json` checkpoint. The repair identity
binds them to the same topic, engine, gaps and original claims; judgment keys additionally
bind the source text, assertion and entailment contract. Restoring a partial repair avoids
re-fetching pages and changing passage selection merely because a worker restarted. A
completed judgment's usage is included once in the attempt report; replay is not a new
provider charge. Account outages and unavailable judgments are never saved as decisions.

Restart tests restore actual checkpoint archives into separate worker directories and
verify passage reuse, interrupted supplement validation, unchanged evidence rejection and
cost reporting. This does not relax evidence gates or grant an extra attempt to a terminal
research failure. Nor does it establish a speed improvement for a complete live video.
