# PR 2 Validation — Research, Claims, and Measured Audio

This document is the merge disposition for PR 2 of `LONGFORM_BOLT_EXPLAINER_ROADMAP.md`.

## Requirement disposition

| Roadmap requirement | Disposition | Evidence |
|---|---|---|
| Pre-script research dossier | PASS — fail-closed implementation and tests | Long-form calls bounded Anthropic server-side search before story planning; invalid or uncited output stops before scripting and media generation |
| Claim ledger and source validation | PASS — adversarial tests | Unique claim IDs, HTTPS provider-observed URLs, provider-observed support excerpts, source class, confidence, scope, timescale, and exaggeration policy are validated |
| Scope, timescale, and confidence checks | PASS — seeded failures | Local-to-global inflation, instant treatment of long-timescale claims, and unhedged speculation fail deterministically |
| Unsupported claims fail | PASS — seeded failures | Factual/numeric/causal scenes without claim references fail; unknown claims, invented URLs, invented support excerpts, and weak community sources fail |
| Fact-check cannot silently break story or claims | PASS — post-mutation gate | Fact-check output is revalidated against exact final narration phrases, evidence IDs, and the story contract before media purchase |
| Claim-to-narration joins complete | PASS — deterministic test | Every reference requires an exact final-narration substring and a dossier claim ID |
| Claim-to-evidence joins complete | PASS — deterministic test | Every claimed scene and reference must share a stable non-empty evidence ID |
| Final-speed TTS precedes main visual purchase | PASS — orchestration test and source audit | All long-form scene audio is generated and transcribed before the first image call; timing failure raises before visual generation |
| Phrase timestamps use measured audio | PASS — deterministic tests | Visual anchor phrases resolve against real word timestamps with global offsets; only exact or unambiguous high-confidence fuzzy matches pass |
| Natural-speed 90-second runtime is 87.3–92.7 seconds | PASS — exact boundary tests | 87.30, 90.00, and 92.70 pass; 87.29 and 92.71 fail; report declares natural speed and no post-stretch |
| Runtime refit uses measured duration | PASS — retry integration test | Up to two rewrites use observed per-scene duration, rerender TTS, and revalidate story/claims; third miss fails closed |
| Cached audio cannot validate changed narration | PASS — regression test | Cache identity includes TTS model, voice, and narration hash; stale or legacy cache is regenerated |
| Reports are downloadable and durable-ready | PASS — API/UI tests | Research dossier, claim ledger report, and audio timing report have job routes, UI controls, and finished-artifact persistence hooks |
| Deployment SDK and proxied local runtime support the implementation | PASS — lockfile reconciliation | `requirements.txt` and `uv.lock` agree on Anthropic 0.125.0 and OpenAI 2.54.0; HTTPX SOCKS support is explicit for the workspace proxy path |

## Test result

Run:

```text
.venv/bin/python -m pytest -q
```

Result at completion: **101 passed**.

Controlled live provider check (no visual assets):

- 240 words at unmodified `echo` TTS speed measured 124.344 seconds, demonstrating that the legacy word-rate estimate was materially wrong for this sample.
- A measured 176-word refit at the same unmodified voice speed measured 91.920 seconds.
- Whisper returned 176 timed words, the evidence anchor resolved to measured timestamps, and the complete 90-second timing report passed with no post-stretch.

## Fail-closed order

1. Provider search produces a dossier and citation evidence.
2. The dossier fails if a material claim lacks a provider-observed URL and support excerpt.
3. The script may use only dossier claim IDs.
4. Fact-check and estimated-runtime rewrites are revalidated.
5. Natural-speed TTS is generated and measured for the complete narration.
6. Any timing, phrase, story, or claim failure stops before image purchase.
7. The final MP4 is measured again and rejected outside ±3%.

## Known limitations and non-goals

- Provider-observed support proves provenance and an exact cited excerpt, but deterministic code cannot prove full semantic entailment for every paraphrase. Controlled pilot review remains mandatory.
- Evidence IDs prove planned joins in PR 2; they do not prove the generated pixels contain the required evidence. Required/forbidden object-state compilation and continuity verification belong to PR 3.
- This PR does not fix slideshow pacing, Bolt placement in rendered pixels, or motion semantics. Those belong to PRs 3–5.
- The current opening render gate is not the final blind 45-second rendered-story judge. That belongs to PR 5.
- Production Blob/Postgres durability, `/finished`, cross-worker recovery, and queue/workflow execution belong to PR 6.
- Paid 45-second and 90-second acceptance pilots belong to PRs 7 and 8; no rendered-video quality claim is made by this PR.

## Rollback

- Pre-PR 2 production baseline: `checkpoint/pre-pr2-main-c8a035b`

PR 2 can be reverted as one commit without reverting PR 1 or the roadmap.
