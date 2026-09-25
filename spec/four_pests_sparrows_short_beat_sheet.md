# Four Pests: The Sparrow — Bolt Explains the World, vertical Short

**Status:** beat sheet, pre-research. Every factual line below is a research candidate until the
claim ledger accepts it. Nothing here is an approved claim, and no clip is authorized until the
operator flips the paid flag for the directed adapter.

**Channel:** Bolt Explains the World · engine hint `removed_keystone` (a predator taken out, the
prey it held down takes over) · banner ANIMAL CONTROL. UNEXPECTED CONSEQUENCES.

**Format:** 9:16, 1080x1920, ~30 s, five clips, Kling 3 Pro on fal.ai via the directed adapter
with start **and** end frame conditioning. Audio off at the provider; narration, music and SFX are
muxed by the pipeline. Frame zero is the hook image, no logo, no host intro. The last frame is
the first frame, so the Short loops.

**Title (working):** China Declared War on Sparrows. The Locusts Noticed.
**Thumbnail:** clip 1 end frame (rooftops, raised pots, a sky with three birds left in it). Baked
text: `1958`. Title carries the words, thumbnail carries the emptiness.

---

## Narration (85 words, target 30–33 s at natural speed)

| Beat | VO | Words |
|---|---|---|
| 1 | In 1958, China went to war with the sparrow. | 9 |
| 2 | Villages banged pots and drums for days, so the birds could never land. They dropped out of the sky, exhausted. | 20 |
| 3 | Sparrows ate grain, so fewer sparrows meant more food. That was the plan. But sparrows also ate insects, and the insects had just lost their only predator. | 28 |
| 4 | Locusts took the fields the sparrows had been blamed for. Harvests fell for years. | 14 |
| 5 | In 1960 the sparrow came off the list. Its replacement: the bed bug. Kill the pest, and find out what it was keeping in check. | 24 |

Every line passes the mute test: the picture states the claim without the words (see the
"reads silent as" column below). Numbers are deliberately absent from the VO. The kill count and
the famine toll are the two figures most likely to be disputed, so they appear on screen only if
the ledger accepts a sourced value, and never as a spoken absolute.

---

## Clips

Style lock, prepended to every still prompt:

> Painted documentary illustration, vertical 9:16 composition, rural northern China 1958, muted
> earth palette with one warm accent, film grain, natural light, no text, no lettering, no logos,
> no modern objects, faces small or turned away.

Negative prompt, every Kling call:

> text, letters, numbers, watermark, logo, cartoon, anime, modern clothing, cars, power lines,
> extra limbs, deformed birds, duplicate people, camera shake, flicker, cuts

Kling 3 Pro settings, every clip: `model: kling-v3-pro`, `generate_audio: false`,
`duration: 5` (clip 3 is `10`), `cfg_scale: 0.5`, `use_elements: false` (no mascot in frame on
this channel, so nothing to lock).

| # | Time | Role | Start frame (still prompt) | End frame (still prompt) | Kling motion prompt | Caption (safe zone) | Reads silent as |
|---|---|---|---|---|---|---|---|
| 1 | 0:00–0:05 | hook / setup | Low-angle view up past clay rooftops at dusk. The whole sky is dense with small brown sparrows in flight, thousands of them. On the rooftops, villagers in 1950s cotton jackets stand with pots, gongs and bamboo poles raised overhead, faces up. | Identical framing and figures, pots still raised. The sky is almost empty: three sparrows left, one mid-fall with wings folded. | Locked camera. The sky full of sparrows thins out over five seconds as birds scatter and drop, until only three remain. The people on the rooftops keep their pots raised and do not move. No cuts. | `1958 · WAR ON THE SPARROW` | People drove the birds out of the sky |
| 2 | 0:05–0:10 | intervention | A walled courtyard, midday. A boy of about ten beats a tin pot with a stick, mouth open. One sparrow circles above him, wings ragged, low. | Same courtyard. The sparrow lies on the packed earth at his feet. Against the wall behind him, a heap of small brown birds. The boy's arm is still raised. | Locked camera. The sparrow's circles get lower and slower until it falls at the boy's feet. The boy keeps beating the pot throughout. No cuts. | `NO PLACE TO LAND` | Exhaustion, not shooting, killed them |
| 3 | 0:10–0:20 | mechanism (10 s) | Macro, a single wheat stalk against soft green field bokeh. A sparrow grips the stalk and holds a green locust nymph in its beak. | The same stalk, same light, no sparrow. The stalk is crowded with locusts, a dozen or more, and the field behind is speckled with them. | Locked macro. The sparrow swallows the nymph, looks up, and flies out of frame. Locusts then climb the empty stalk one after another until it is covered. Slow, continuous, no cuts. | `WHAT THE SPARROW ATE` | The bird was the insect's predator |
| 4 | 0:20–0:25 | consequence | Wide, a green millet field at morning. A farmer in a straw hat stands at the field edge with his back to camera, a hoe on his shoulder. Clear sky. | Same field, same farmer, now holding his hat against his chest. The crop is stripped to stubble and the sky is a dark moving cloud of locusts. | Locked camera. A locust swarm rolls in from the top of frame like weather, the green field goes to brown stubble beneath it, the farmer takes off his hat. No cuts. | `THE FIELDS` | The harvest was lost to insects |
| 5 | 0:25–0:30 | reversal / verdict | A wooden notice board in a village square. Four painted pest icons in a column: a rat, a fly, a mosquito, a sparrow. A hand with a brush hangs at the edge of frame. | The same board. The sparrow icon has a wet red cross through it and a bed bug is painted below. Above the board, the dusk sky is filling with sparrows again. | Locked camera. The brush crosses out the sparrow and paints a bed bug beneath it. The sky above the board fills with returning sparrows until it matches the opening shot. No cuts. | `1960 · REPLACED BY THE BED BUG` | The sparrow was reinstated; something else took its place on the list |

Clip 5's end frame is drawn from clip 5's own start frame (the board stays, the sky band above it
fills with sparrows), and the loop closes with a cross-dissolve from that frame to clip 1's start
frame, absorbed by clip 5. A first attempt drew the loop frame from clip 1's start image so the
closing sky would be the opening sky rendered again; the edit model kept clip 1's rooftops and
dropped the board, which would have left Kling two unrelated compositions to morph between.
Rule learned: an end frame references its own start frame, never another clip's.

Camera is locked in every clip on purpose. The continuity gate measures global drift, and on this
format the before-and-after *is* the content, so a moving camera would hide the change it is
meant to show.

---

## Claim ledger (verify before narration; none is accepted yet)

| # | Claim | Where it appears | Notes for research |
|---|---|---|---|
| C1 | The Four Pests campaign began in 1958 as part of the Great Leap Forward and named rats, flies, mosquitoes and sparrows. | VO 1, caption 1, clip 5 board | Primary: campaign directives, 1958. Secondary: Shapiro, *Mao's War Against Nature*. |
| C2 | Sparrows were killed mainly by exhaustion: coordinated noise kept them airborne until they dropped, plus nest destruction and shooting. | VO 2, clips 1–2 | Do not claim noise was the only method. |
| C3 | The stated rationale was that sparrows ate grain. | VO 3 | Needs the campaign's own wording. |
| C4 | Sparrows eat large numbers of insects, including locusts, and ornithologist Tso-hsin Cheng's work established this in the campaign's context. | VO 3, clip 3 | Cheng is the named scientist; keep him out of VO unless the source is exact. |
| C5 | Locust and other insect populations rose sharply after the sparrow decline and damaged crops. | VO 4, clip 4 | Strength of the causal link matters: "no predator left" in VO is an inference and must be supported or softened to "one fewer predator". |
| C6 | Harvests fell in the following years; yields recovered only in the mid-1960s. | VO 4 | Do NOT let the Short attribute the Great Famine to sparrows alone. The famine had several causes. The current VO says "harvests fell for years", not "famine". Any famine reference on screen needs its own accepted claim and hedged wording. |
| C7 | In 1960 the sparrow was removed from the list and replaced by the bed bug. | VO 5, caption 5, clip 5 | Widely reported; find the directive or a primary-source account. |
| C8 | China later imported sparrows, reportedly from the Soviet Union, to restore the population. | Clip 5 end frame only (returning sky) | Not in VO. If unsupported, the returning sky is still honest as "the sparrow was reinstated". |
| C9 | Kill count ("hundreds of millions", "nearly a billion") | Nowhere | Figures vary by an order of magnitude across sources. Excluded from VO and screen unless the ledger accepts one sourced number. |

Sources to start from: [Wikipedia, Four Pests campaign](https://en.wikipedia.org/wiki/Four_Pests_campaign)
(for the citation trail, not as a citation); [a Soviet scientist's 1964 account](https://alphahistory.com/chineserevolution/a-soviet-scientist-on-the-four-pests-campaign-1964/);
[University of Chicago, "How the persecution of sparrows..."](https://climate.uchicago.edu/news/how-the-persecution-of-sparrows-killed-2m-people/)
(note its title asserts a death toll the ledger should treat as contested).

---

## Cost and budget

| Item | Count | Unit | Subtotal |
|---|---|---|---|
| Kling 3 Pro, 5 s clips | 4 | $0.56 | $2.24 |
| Kling 3 Pro, 10 s clip | 1 | $1.12 | $1.12 |
| Stills (start + end per clip, one loop frame) | 10 | ~$0.04 | ~$0.40 |
| Narration + word timestamps | 1 | ~$0.05 | ~$0.05 |
| **Accepted-clip total** | | | **~$3.80** |

Budget for the directed adapter: `budget_for("kling-v3-pro", seconds=5)` per 5 s block, and
`budget_for("kling-v3-pro", seconds=10)` for clip 3, with `max_candidates: 2`. Worst case, every
block needs its second candidate: ~$7.20. Hard cap for the whole Short: **$8.00**.

## Gates that apply

1. Research handoff accepts C1–C7 (C8 optional, C9 excluded) before any still is bought.
2. Narration is measured, not declared: real TTS first, then the clip plan is fitted to it.
3. Each still pair passes a quick check that start and end share framing, palette and figure
   placement, or the end still is regenerated before Kling is called.
4. Each Kling candidate passes the motion and continuity gates (real change between first and
   last frame, no camera drift, no anatomy mutation) or the next candidate is bought, up to two.
5. The first frame is graded for the swipe test at phone size: is the sky legibly *full* of birds
   at 160 px?

## What to decide before the run

- Confirm the VO wording for C5 and C6 after research. Both may need softening.
- Confirm whether the bed bug on the board should be an icon (safer with image models) or a
  painted word (riskier; models garble text).
