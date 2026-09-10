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
