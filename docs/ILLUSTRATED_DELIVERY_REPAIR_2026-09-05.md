# Illustrated delivery repair — September 5, 2026

Baseline: PR #77, main `82080e3`. The local baseline tree is identical to main.
This change incorporates the pending delivery repairs in an isolated checkout and adds
approval-boundary, installed-wheel, OpenAI accounting and encoder-restart verification.

## Changes

- A public, non-spending `generic_illustrated` proposal freezes a 60–90-second landscape
  still-image recipe, creative direction, provider/model manifest and spending ceiling.
  Approval stays on the authenticated operator page. Claim transaction binds the job ID,
  allowing queue recovery without creating a second paid job. Missing provider configuration
  leaves an approved action recoverable. Modified recipes/provider choices are rejected.
- Directed pilot approvals reject any window other than the first 45 seconds. The malformed
  208-second Hippo pilot cannot execute under a 45-second approval; its source spec is retained
  for repair rather than silently reinterpreted as an approved continuation.
- Readiness checks actual selected providers, including native Anthropic research when plain
  script generation uses OpenAI. It explicitly reports model access and quota as not checked.
- Workers yield at safe stage boundaries after 480 seconds, checkpoint, release their lease,
  and continue under the same job/budget. Cooperative continuations have a separate bounded
  count and do not consume error retries. Existing minute cron/dispatch claims queued work.
- Illustrated FFmpeg segments and assembly outputs use content-based durable stage identities,
  allowing completed encoding to survive temporary-directory replacement. Finished metadata
  takes cumulative spend from the durable ledger, including previous worker windows.
- Research retains paused server-search turns, original tool blocks and citations, continuing
  at most three times. Truncated/malformed evidence is not sent to a text repair model that
  could fabricate missing claims. Durable SDK retries/timeouts are bounded.
- Anthropic accounting includes cache/search usage and removes clipped reservations. OpenAI
  script fallback now reserves, settles and replays through the durable ledger too.
- Progress streams emit event IDs, resume from Last-Event-ID and remain connected on retries.
  The illustrated UI defaults to 90 seconds; unknown media totals are displayed as unknown.
- Wheel packaging includes required root modules, six corpus references, approval pages and
  bundled specs. CI smoke-tests the installed wheel outside the source checkout.

## Validation

The provider-fake delivery test exercises HTTP proposal/approval/execute, real orchestration,
claim/storyboard/evidence gates, media SDK adapters, word timing, real FFmpeg, checkpoint restore,
Finished Videos listing and SHA-256-verified MP4 download. Two runs force a fresh worker after
(a) the first committed image and (b) the first committed encoded segment. Completed provider
calls are not repeated; the encoder case verifies a reused FFmpeg stage.

This fixture is synthetic: narration is a generated tone, images are test drawings, and research,
script generation, fact-checking and visual/editorial model responses are supplied by fixtures.
The database and Blob boundary use memory/filesystem adapters. This is delivery validation,
not a Claude-quality result, a production database concurrency test, or a publishable video.

The built wheel imports the application and illustrated modules and loads all six references
from a clean temporary directory. No source-checkout imports are permitted in the CI smoke.
Full-suite result is recorded in the PR after completion. No paid provider calls were made.

## What remains unverified

1. Live Claude research/story pass rate after PR #77, including actual narration timing.
2. Production model access/quota, real Postgres locking, remote Blob behavior and worker handoff.
3. Editorial quality and delivery of one approved production canary. Use the recipe in AGENTS.md
   only after this repair deploys. Do not automatically escalate the budget or rerender a failure.
4. Multi-minute throughput. Cooperative checkpoints reduce wasted work but do not guarantee a
   single slow provider call/encode finishes inside the hosting limit. The canary is 60–90 seconds.
5. Provider reservations estimate input/search token usage; actual billed usage can differ.
   Committed outputs replay without repurchasing. A process killed after a provider accepts work
   but before ledger settlement still has the existing bounded in-flight duplicate risk.

No story quality gates or mechanism deadlines were lowered. Shared creative-corpus expansion
and new engines remain separate from establishing dependable illustrated delivery.
