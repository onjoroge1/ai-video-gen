# Cut layer: why every video graded 69

Two finished videos on different engines, different topics and different runtimes
(macquarie 74.8s, nile_perch 176.6s) scored an identical 65/100 with identical component
scores. Two independent videos do not grade identically by chance — the rubric was reading
the lane that produced them, not the videos.

## Diagnosis

Three joins where two halves of the pipeline disagreed. None was a story problem.

| # | join | effect |
|---|---|---|
| 1 | `validate_longform_story` returns early for the compiled causal lane, before the timing checks | `checks` reached the scorer empty; absent `max_attention_gap_sec` defaults to the sentinel 999 (−8) while absent `max_exposition_block_sec` defaults to 0.0 (+5) — the same missing measurement scored as catastrophe or as a pass depending on its default |
| 2 | `ATTENTION_ROLES`/`EXPOSITION_ROLES` were written for the cinematic lane | one word (`reversal`) in common with the causal vocabulary, and `mechanism` — the beat that answers the question — counted as exposition to be penalised |
| 3 | scene-wide `valid` flag in `compile_scene_shots` | one unplaceable anchor discarded every measured start in its scene; five of macquarie's seven scenes threw away confidence-1.0 measurements |

`same_source_hard_cut_count` was the second hard cap, and it was not accidental image reuse:
the counts track the `detail_reframe` counts almost exactly (nile_perch 9 against 10,
macquarie 1 against 1). A punch-in is the right device; rendering it as two segments
concatenated with `-c copy` cut from an image straight back to itself.

## Result — macquarie, same story, $1.53

| | before | after |
|---|---|---|
| grade | 65 (D) | **91 (A)** |
| hard failures | `semantic_sync`, `same_source_jump_cuts` | none |
| semantic_sync | 0.077 | 0.90 |
| same-source jump cuts | 1 | 0 (2 reframes absorbed) |
| opening contract | 10/25 | 20/25 |
| narrative propulsion | 17/25 | 25/25 |
| visual continuity | 10/20 | 18/20 |

`macquarie_before.json` is recomputed, not the original file: the pre-fix report was
regenerated in place before it was backed up. It is the scorer run with the empty `checks`
the lane used to emit, against unchanged shot metrics, and it reproduces 65 D and both hard
failures exactly. `macquarie_after.json` / `.txt` are the real artifacts from
`renders/macquarie_v2` (7 scenes, 76.1s).

## What the remaining 9 points are

Real editorial findings, now that the rubric can see the video: the causal lane opens on
`setup` where the corpus references open on a visible consequence (−5), no clause-specific
B-roll (−2), audio cue palette lacks contrast (−2).

Commits: 3ac2c6a, 5f95230, 4ad6687, 31b1d2d.
