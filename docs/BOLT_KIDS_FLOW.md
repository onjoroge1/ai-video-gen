# Bolt Kids v1 — dedicated gated episode production

## Scope and entry points

`bolt_kids_v1` is a separate, landscape, approximately two-minute preschool animal-adventure flow.
It is **not** a Nature Story, Rapid Quiz, illustrated explainer, TV board, or directed-first-45 preset.
The initial template is an original three-round backyard hide-and-seek story with spoken character
turns, explicit answer pauses, a recurring song recording and an action-song payoff.

- Studio: `/bolt-kids` (existing studio authentication).
- Schema/template: `GET /api/kids/schema`, `GET /api/kids/template`.
- Provider-free structure validation: `POST /api/kids/validate` with `{"spec": {...}}`.
- Proposal: `POST /api/agent/actions` with `operation: "bolt_kids_episode"`, a complete `spec`,
  and `cost_ceiling_usd`. Do not submit fields from another format.
- Approval/execution: existing `/agent/actions` card and exact-hash/cost approval.
- MCP: `propose_bolt_kids_episode(spec, cost_ceiling_usd)`; existing status/dispatch/artifacts tools.
- Saved diagnostics: `kids-gates`, `kids-episode`, `kids-quality`, `kids-timeline`.
- Final human review: `/api/kids/jobs/{job_id}/review`, also exposed in the Kids studio.

**The template's unresolved references intentionally fail validation.** Upload and review the actual
robot and set assets first. Do not invent a checksum, mark unknown rights as resolved, or bypass
validation to start an inexpensive test.

## What is shared, what is isolated

Shared: studio session authentication, `agent_actions`, immutable approvals, the existing durable
queue/leases/reservations, Blob/Postgres, stage cache, the raw image provider helper, an explicitly
directed raw motion call, media binary discovery, and Finished Videos finalization.

Isolated: episode schema, story family, character/voice casting, song generation, audio timeline,
response pauses, storyboard/animatic, mandatory action semantics, frame layout, and all Kids gates.
No existing flow's default model, thresholds, creative prompts, or old approval bytes are replaced.

The queued request carries an internal `kids_authorization` envelope. Public generic generation
rejects that field. The worker verifies that the reconstructed request, policy version, provider
manifest and cost ceiling are unchanged before entering `bolt_video.kids.pipeline.render_episode`.
An approved action binds one deterministic job ID, including crash/reconnect between enqueue and
mark-queued. The MCP adapter does not render, approve, or hold provider credentials.

## Gate sequence

| Stage | Required evidence | Failure behavior |
| --- | --- | --- |
| Contract | Valid graph/IDs, exactly three ordered matching question/reveal rounds, a musical payoff and recap, robot Bolt, explicit 2–4 second answer pauses | Reject before provider imports/calls |
| Configuration and references | Required provider configuration, FFmpeg/ffprobe, durable storage; actual decoded reference bytes, MIME and SHA-256 | No script/audio/visual spend |
| Script | Independent critic of exact script, fair clues, learning accuracy, kindness, safe actions, original lyrics, complete ending | No speech/song generation |
| Songs and speech | Actual audio, transcribed words compared to authored words; saved song duration within one second of its declared length | No image/motion generation; required music cannot become silence |
| Measured timing | 110–130 second actual timeline; no audio time-stretch; preserved response intervals; shot/action feasibility | Save timing report, stop before images |
| Animatic | Actual soundtrack over timed storyboard cards; decode, A/V timing, loudness and dimensions | No image/motion generation |
| Source visuals | Actual generated/reused first frame compared to character and set references; expected first state and no premature answer | No motion generation until **all** source assets pass |
| Provider motion | Actual ordered frame samples, stable identity, visible complete action, valid endpoint and explicitly authorized looping | No still-image or frozen-tail substitute |
| Encoded actions | Samples of each required action after actual trimming/looping and encoding | Prevent a source clip passing while its delivered action is cut off |
| Encoded delivery | H.264/AAC, dimensions, full decode, measured A/V/timeline agreement, loudness, true peak; one actual encoded sample per beat | Failed output is not finalized as an accepted episode |
| Human release | Full viewing/listening checklist bound to the exact finished MP4 hash | Technical completion remains non-publishable until explicit approval |

There is **no weighted score that can average away a failed required check**. An absent, truncated,
malformed or incomplete critic result is `unscored_unavailable`, not zero out of 100. Reports name
the stage, checks, actual input hashes and evidence. These are production checks, **not validated
predictions of retention, developmental benefit or educational efficacy**.

Initial engineering thresholds are versioned in `POLICY_VERSION`, not exposed as author overrides.
They require calibration with real reviewed episodes. Model visual review is sampled, not exhaustive.
ASR agreement does not prove pleasant singing, pronunciation quality or a good mix; the full human
listening review remains mandatory. SFX must be supplied as reviewed audio, not fake TTS animal calls.

## Audio first

A cue is exactly one of speech, song, explicit pause, or saved sound effect. Spoken turns name a
character, not a speaker prefix in a long narration string. Each character has a pinned voice and
acting instructions. The OpenAI adapter requests `gpt-4o-mini-tts-2025-12-15`; songs use an independent
Eleven Music `music_v2_5` composition plan with explicit lyrics and a declared duration.

The same song ID is generated/checked once and the approved recording is reused for every occurrence.
A seed or similar prompt is not a guarantee of the same melody or singer. OpenAI speech and Eleven
singing do not share a portable voice identity. The robot's performance is expressed through its
screen, antenna, hands and body, not an invented lip-sync mouth.

Speech and songs are sequential in v1. There is deliberately no background bed masking words, and
no song-vocal/spoken-dialogue overlap. Audio is normalized without speed changes and concatenated
with real silence intervals. Sidecar SRT captions preserve authored words; this version does not
claim karaoke-word animation or forced phoneme-level song alignment.

The generated animatic is a diagnostic, not proof of the finished images. V1 uses one full-episode
paid approval with automatic intermediate gates and a separate final **non-spending** human release
review. It does not silently promote a first-45 pilot or ask another API to approve purchases.

## Reusable assets and storage

`kids_assets` stores immutable library metadata in the existing Postgres connection. Media stays in
existing Blob storage, not GitHub or database byte columns. `kids_editorial_reviews` is append-only;
reviewing a final does not rewrite the original automated report or pretend it was previously passed.
Tables are created lazily on first catalog/review use and fail closed when persistence is unavailable.

An authenticated operator uploads an image, WAV/MP3, or MP4, supplies origin/rights information and
explicitly confirms source review. Bytes are bounded to 32 MiB and decoded before registration.
References resolve only `asset://` paths below the repository asset root or `library://` IDs owned by
this studio. No arbitrary input URLs, filesystem paths or provider options are accepted.

Each episode names a brand-pack ID/version and frozen reference hashes. Start with the real robot,
backyard reference, chick, bunny and elephant. Generated assets are driven by those references;
identities are not re-invented from a mascot name. New versions require new references/approval.

The renderer supports approved full-frame stills and motion clips, not an already-built skeletal
3D rig. A full-frame clip is reusable in its fixed set; it is not automatically a transparent
character layer transferable to any environment. One-time reveals cannot loop. Only explicitly
loopable cyclic movement can repeat, and both source and delivered action samples are reviewed.

Finished jobs export the episode, storyboard, timing, gate/quality reports, manifest, soundtrack,
individual normalized audio/song files and final visual sources. Review exported assets before
registering them for later episodes. Cross-episode reuse uses the catalog; worker-resume cache is
job-scoped and is not a general cross-project media library.

## Failure, repair and recovery

Completed paid stages retain the exact requests and bytes under the existing durable stage ledger.
A worker restart restores them; deterministic local audio/shot/mux stages are cached too. No second
scheduler, mutable global per-user draft, or browser-memory job state is used.

V1 does **not** perform automatic best-of-N/content repairs. An unchanged content failure stays a
failure. The operator inspects the saved diagnostic, repairs only the relevant contract/assets, and
creates a new approval. Approved catalog assets can then be reused. This is different from retrying
an unchanged provider outage or resuming a worker checkpoint. Ambiguous in-flight purchases are
reconciled by the existing runtime, never blindly repurchased by this adapter.

Changing the spec, source hash, acting direction, model, policy or price allowance invalidates the
approval. Do not raise cost/per-call limits automatically, disable gates to hit a score, replace
failed artifacts in place, or use a human release record to override a failed automated prerequisite.
Bump the relevant policy/render version whenever pixel, timing, or gate semantics change.

## Configuration and cost accounting

Reuse `OPENAI_API_KEY`, `DATABASE_URL`, Blob configuration, `FAL_KEY`, and the current worker setup.
Add `ELEVENLABS_API_KEY` only when generating new songs. Reused saved songs need no music-provider key.
`KIDS_MAX_COST_USD` defaults to 10 and is also bounded by the existing durable job cap. The effective
per-call reservation ceiling is frozen from `DURABLE_MAX_INFLIGHT_CALL_USD`; incompatible motion
models are rejected at proposal time rather than after buying earlier assets.

The rate/allowance manifest is conservative planning data, **not an invoice or a fixed per-episode
price promise**. Speech/music/critic entries explicitly record reserved allowances; image billing
uses the existing helper. The ledger's displayed spend can therefore differ from provider invoices.
Hosting, storage, bandwidth, initial asset creation and manual editorial work are separate.
Configuration readiness is not proof of quota, account entitlement, commercial music rights or live
provider quality. Review current provider terms and actually audition the selected voices/songs.

## Verification and remaining production proof

Run the focused checks using the normal project dependencies:

```sh
python -m pytest tests/test_bolt_kids_*.py
```

Tests cover invalid schemas, missing source rights/checksums, path/URL rejection, response pause
preservation, immutable voice/model/budget requests, missing lyric stops, absent critic stops, the
actual shared durable TTS cache across workers, private routes, exact paid approval and duplicate
submission handling, real FFmpeg encode/decode, and synthetic full-duration orchestration.

The full-duration test uses a **320×180 synthetic test pattern/tone and test critics**, not generated
Bolt art, real singing or a real editorial assessment. A separate real-media smoke checks the 720p
codec/dimensions path. Neither test establishes a publishable episode. Tests do not call paid providers.

Before launch: provision reviewed robot/set/animal assets, validate credentials and current music
rights, run one explicitly approved live episode, inspect its full soundtrack and action continuity,
complete the human release checklist, and measure actual audience behavior after manual publishing.
No automatic YouTube publishing or scheduling is implemented by this flow. Optional-engine PRs
#124/#125 and a Motion Canvas/Blender rig are not dependencies of this v1.
