# Spec import: operator research + narration, verified and rendered

`scripts/import_spec.py` (module `spec_import.py`). Operator question, 2026-10-21: *can I give
ReelForge the research and the script, as with the ChatGPT lionfish rewrite, and have it check the
findings and make the video?* The answer is yes. The path is the one jobs/lionfish-v2/hand_build.py
proved: new facts go into the dossier with verbatim quotes and citation records, then the normal
pipeline resumes. Before, that took a bespoke script for each film. Now a spec file does it.

## The flow

```
topics/specs/<slug>.md ──import_spec.py──> jobs/<slug>/verification_report.md   (free: no provider calls)
                                           jobs/<slug>/spec_verification.json
                                           jobs/<slug>/pages/                    (cited pages, cached)
operator reads the report, edits the spec, repeats; when it says Ready to approve: YES
import_spec.py --approve <narration sha256> --max-cost N
        ──> research_dossier.json, _state.json, run_command.txt, spec_approval.json
        ──> run_illustrated_local.py --resume   (claim ledger, storyboard, TTS, images, render)
```

Nothing is spent before the approval. The approval is bound to the SHA-256 of the
whitespace-normalised narration. Changing any word changes the hash, and the old approval is
then refused. `--build-only` writes the state without resuming. `--offline` reads only the cached
pages.

## The spec format

A markdown file with one fenced ```` ```json ```` block. A ```` ```yaml ```` block also works if
PyYAML is installed. Prose outside the block is the operator's notes. The template is
`topics/specs/TEMPLATE.md`, and `topics/specs/lionfish-v2.md` is a full worked example.

| field | meaning |
|---|---|
| `slug`, `title`, `channel` (world \| history \| …), `duration_sec` | the job; `title` is the video's working title |
| `decision` `{what, who, when, kind, cite}` | the past deliberate decision. `kind` ∈ animal_introduced, animal_removed, animal_targeted, invention_adopted, product_adopted, rule_enforced |
| `consequence` `{what, cite}` | the documented consequence |
| `still_unfolding` `{what, as_of, cite}` | the dated present-day sign it continues |
| `central_question`, `ending_answer` | the one question the film asks, and its answer, told from today |
| `human` `{person, want, detail}` | the person, what they want, one concrete sourced detail |
| `forbidden_claims` | claims we cannot make; lines that overlap one are flagged |
| `recurring_image` | optional callback object |
| `render` `{palette, music_mix, music, voice, packaging}` | optional run_illustrated_local flags |
| `sources` `{key: url}` | optional short names for URLs |
| `narration` | the full narration, in order: a list of lines |

A narration line is `{"say": "...", "part": "...", "claims": [...], "cite": [...], "picture": "..."}`:

- `say` is the spoken text, voiced exactly as written. One sentence per line is best: a claim
  binds to its whole line.
- `part` ∈ opening, attempt, complication, development, ending. It carries forward to the next
  lines and only guides the segmenter's scene breaks and picture palette.
- `claims` defines new claims: `{id, source, quote, kind, evidence, claim?}`. `source` is a
  `sources` key or an https URL. `quote` is copied character for character from the page. `kind` is
  the ledger kind (event, outcome, mechanism, context, general_principle). `evidence` is
  documented, model or interpretation. `claim` is the fact in plain words; it defaults to the line.
- `cite` reuses claims defined on earlier lines, by id.
- A line with no claims is framing. If it states a number above ten or an attribution ("said",
  "researchers found"), it is flagged as unsourced.

## What is checked

**Quotes.** Each cited page is fetched with claim_verify's document fetch (PDF and XML included,
for Europe PMC full text), then its page fetch. Each quote is then located on the page:

| mark | status | meaning |
|---|---|---|
| ✅ | exact / normalized | the quote is on the page; typography (curly quotes, dashes, case) normalised |
| ⚠ | recovered | the quote is not on the page as written, but one page sentence carries ≥70% of the quote's own content words and all its numbers. That sentence becomes the ledger quote, and the operator's version is kept beside it |
| ⚠ | number | the line states a number (above ten, within 5%) that none of its quotes carries. A year may come from the cited page itself, e.g. a dateline |
| ❌ | absent | the page does not say it. The report gives the closest page passage |
| 🚫 | unreachable | the page could not be read (403, challenge page, stub). Cite a readable copy |

Recovery is deliberately stricter than research's `repair_quote` default. That default accepts
half of the claim and quote words together, and it let a fabricated "pythons have eaten every
raccoon" match a page sentence about fur-bearing animals (the 403-wall lesson).

**The pipeline's dossier check.** The dossier that approval would build goes through
`longform_research.validate_research_dossier` during the check. A claim it would refuse, such as
a quote whose negation disagrees with the claim or a weak domain, shows in the report, so the
operator does not first meet it at approval.

**The World consequence model** (channel world or unset; other channels are reported as not
applicable). It is the story-contract lane's rule (PR #217,
`story_contract.validate_consequence_model`). That function is used when it can be imported.
Until the PR merges, a mirror in spec_import with the same codes runs instead:

- `DECISION_MISSING` / `DECISION_NOT_DELIBERATE` / `DECISION_UNDATED`, plus spec_import's
  `DECISION_UNNAMED` (no `who`)
- `CONSEQUENCE_MISSING` / `CONSEQUENCE_NOT_DOCUMENTED`: the consequence must cite a documented
  event or outcome. A quote that reports a model ("models projected", "simulated", "predicted") is
  a model, and a hedged quote ("may", "could", "can", "suggests") is an interpretation, whatever
  the spec labels it.
- `STILL_UNFOLDING_MISSING` / `STILL_UNFOLDING_NOT_PRESENT`: a documented claim dated within five
  years
- `QUESTION_HYPOTHETICAL` ("What happens when …?"), `QUESTION_NOT_CONSEQUENCE` (the question
  shares no word with the decision or the consequence), `QUESTION_MISSING`, `ENDING_MISSING`
- `<PART>_UNVERIFIED`: a binding claim that is ❌ or 🚫

**Voice.** Words against the duration target (2.588 words per second, the slowest measured
rate), sentence count, mean sentence length, sentences over 25 words, numbers per 100 words and
attributions per 100 words. These are reported only and never block.

**Never rewritten.** spec_import does not change a word of the narration. Unsupported lines get a
suggestion in the report's "Suggested rewording" section. The operator edits the spec and runs the
check again, which produces a new hash.

## The approved build

`--approve <sha>` re-runs the check against the cached pages. It refuses if the hash differs, if
anything is ❌ or 🚫, or if a spec problem, dossier error or consequence failure remains. Otherwise it:

1. builds `research_dossier.json` in hand_build's claim shape: verbatim quote, a citation record
   per claim, `support_provenance` `operator_spec` or `page_recovered`, `story_kind`, and the
   spec's URLs as `operator_source_urls`. It must pass `validate_research_dossier`.
2. builds `_state.json` with the story-contract lane's word-preserving segmenter
   (`story_contract_segment.build_state`). Scenes come from the lines, claim refs from each line's
   claims, and pictures from each line's `picture` or the segmenter's defaults. The state carries
   `_spec_import` (spec and narration hashes). The words are checked unchanged once more.
3. writes `run_command.txt`, which rescue_script reads, and `spec_approval.json`, then runs
   `run_illustrated_local.py --resume` with the ceiling and the spec's render flags.

The segmenter is PR #217's. Until it merges, step 2 stops with a message naming the PR, after the
dossier has been written. No segmenter is guessed at. Once the PR merges, the lane policy
(`_lane = story_contract`) also governs the resumed run: its gate table and the narration hash
check before media.

## Worked case: lionfish v2

`topics/specs/lionfish-v2.md` is the ChatGPT-revised narration from jobs/lionfish-v2 (76 lines, 29
claims, including hand_build's c70–c86), with evidence labels from the lane's
lionfish_v2_story_kinds fixture. Dry run, 2026-10-21 (jobs/lionfish-v2-spec, no render, no upload):

- all 29 quotes exact on their pages; 0 ❌, 0 🚫; one unsourced repeat ("Seventy-three trips, and a
  full freezer.")
- consequence **FAIL**: `CONSEQUENCE_NOT_DOCUMENTED` (c77 and c80 are interpretations, c78 is a model)
  and `QUESTION_HYPOTHETICAL`. This is the operator's ruling ("not a consequence video"), now caught
  before any spend.
- 731 words against a 776-word target (5:00), mean 9.6 words per sentence, 2 sentences over 25
  words, 1.78 numbers and 0.68 attributions per 100 words.

The tests (tests/test_spec_import.py) use trimmed copies of those real pages
(tests/fixtures/spec_import/pages). They need no network and make no provider calls.
