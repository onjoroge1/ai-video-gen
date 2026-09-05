# Quiz Short Retention V2.4 — Three-Round Rapid Reveal

## Measured failure

The animal quiz reference (`uOSTBH8cjUw`) received 589 views and 2 subscribers, but only **19% stayed
to watch** while **81% swiped away**. Average view duration was **16 seconds on a 33-second Short**.

The retention curve has two different problems:

1. **Feed decision failure:** the first frame is a generic Bolt game-show stage and question mark. It
   announces a quiz but does not let the viewer play. Most viewers reject it before engagement.
2. **Post-game cliff:** the curve falls sharply around 26–29 seconds. The old renderer appends a host
   outro and then a second subscribe/next-quiz teaser after the third answer. The reward is over, so the
   viewer leaves.

The middle declines steadily because each round serializes “Number N. What is it?”, a 2.4-second timer,
and a reaction reveal. Easy-first clues plus repeated setup make the interaction feel slower than it is.

## V2.4 creative contract

- The **first clue is frame zero**. No mascot intro or logo hold.
- Three rounds maximum: **warm-up → no hints → final boss**. The opener cannot be trivial.
- Voice and timer run concurrently over the clue; no separate “What is it?” card.
- Each 2.4-second guess progressively widens from a tight detail to the complete clue every 0.8 seconds.
- Reveal: 0.8–1.2 seconds; the final reveal may run up to 3.6 seconds for the integrated score CTA.
- A vision QA pass grades first-crop difficulty, full-clue fairness, answer identity, anatomy, pose,
  subject occupancy and clue/background contrast at phone size.
- **Frame-zero contrast is a gate, not a note.** Contrast is scored twice — once on the full clue and
  once on the opening crop alone, because a silhouette can separate cleanly in the wide shot and
  vanish inside the crop the viewer actually decides on. A habitat round that misses the bar is
  regenerated once against an explicitly bright, open background rather than reported as a
  degradation on a video that ships anyway. An unmeasured score counts as a failure: absence is the
  state the gate lived in when frame-zero contrast was never requested at all.
- Overly easy openings are cropped tighter; incorrect/anatomically weak reveals regenerate once.
- Critical headers, timers, answers, and CTA remain inside the Shorts safe zone.
- Every card has subtle duration-aware motion; no frozen multi-second PNG.
- **One voice.** The narrator runs the game (“Okay… lock in.” / “Nah… final boss.”) and the screen
  reacts where the narration does not (“IF YOU MISSED THAT 💀” on round one's reveal). A second TTS
  voice was tried on the second reveal — “Let him cook!” — and removed: a synthesized voice
  delivering a meme has neither the timing nor the texture the joke depends on, and it read as
  exactly the thing the format set out to avoid, someone imitating slang rather than reacting.
  A reaction belongs on the screen or nowhere; it does not belong in a second synthetic voice.
- The opener promises the round the viewer has to stay for — “Three animals. Last one's brutal.” —
  rather than describing round one. Each line is hard-bounded by its own countdown, so the opener is
  built longest-first and drops the threat, never the timing, when a long category crowds it out.
- Optional `QUIZ_FAL_OPENER=1` uses one fal/Kling clip behind the first countdown only. This isolates
  the value of generative motion at the swipe/stay decision without paying to animate every card. It is
  not combined with progressive crops because generative silhouette morphing can make a clue unfair.
- No mascot is composited on clue, reveal, answer, CTA, or loop frames. The animal transformation,
  display typography, difficulty ladder, timer, and sound design carry the complete quiz experience.
- The final answer carries a score ladder — “0/3 😭 · 1/3 🤨 · 2/3 🔥 · 3/3 🐐” — over a
  “ROUND 2 · FOLLOW” chip. The spoken line asks the question that earns the comment instead:
  “Be honest… what'd you get?” There is no separate outro or subscription card, and **“subscribe” is
  never spoken.** A spoken subscribe is a chore where a promised round two is an offer.
- The replay ask was retired, not lost. “Missed one? Go again.” worked — average percentage viewed
  sits above 100% — which is the argument against keeping it: the longest slot in the Short was
  buying more of a saturated metric while comments, the one signal this format has never asked for,
  stayed flat. The closing beat still dissolves into the opening frame, so the replay stays free
  whether or not anybody names it.
- Emoji are drawn through a separate colour-emoji pass. The display face carries no emoji glyph and
  PIL performs no font fallback, so an emoji sent through the normal text path is drawn as nothing
  at all — no tofu box, no exception. Without an emoji face the score ladder is skipped whole rather
  than rendered as bare numbers: half of “0/3 😭” is the half that would silently disappear.
- **The video closes on the frame it opens on.** The last beat cross-dissolves into round one's first
  countdown card — same base image, same overlay, same zoom, rendered through the same path, so it is
  that frame rather than a copy of it. The dissolve is absorbed by the closing card and costs no
  runtime. Habitat pairs make this honest at the content level: round one and the final round share a
  habitat, and the final animal is chosen to genuinely live there rather than relocated to fit.
- The music has no tail fade. A fade to silence is an ending cue, and it played over the one beat
  built to hide the ending.
- Expected duration is roughly **11 seconds**, designed to invite an immediate replay.

## Why this is a creative change, not only a trim

The viewer now receives the product before deciding whether to swipe: a large, legible mystery shape and
a moving timer. The retained display font and difficulty system provide a consistent channel identity
without placing a character over the habitat. The reveal is a color transformation of the same subject,
so every 3–4 seconds contains a visual reward.

## Controlled test

Publish three Rapid Reveal quizzes in one category before drawing conclusions. Keep posting window,
title shape, item count, voice, and music consistent. Compare against the prior quiz baseline.

Primary gates after at least 500 Shorts-feed impressions:

| Metric | Baseline | V2 minimum | Strong result |
|---|---:|---:|---:|
| Stayed to watch | 19% | 30% | 50%+ |
| Average percentage viewed | ~48% | 85% | 110%+ |
| Average view duration | 16s / 33s | 9s / ~11s | 12s+ / ~11s |
| End-of-video retention | ~5% | 50% | 70%+ |

Measured after the first three published Rapid Reveal quizzes: **46.0%** and **35.5%** stayed to
watch at 100%+ APV, on ~1.2K views each. The format clears its minimum gate, so the fallback
mechanics below are not the next move — the remaining retention is at the two joins, frame zero and
the ending, and both are addressed above. The 10.5-point spread between those two videos tracked
first-frame silhouette contrast: a black shape spanning a bright savanna held far better than one
sitting against dark rainforest foliage. That is the only variable this format has measured against
retention, which is why V2.4 turns it into a gate that regenerates rather than a line in a report.

## Bolt's reaction library — built, not adopted

`bolt_seq/gen_quiz_reactions.py` generates keyed, animated Bolt cutouts into
`assets/mascot/reactions/`. They are **library assets**: Kling bills a five-second minimum, so a
clip costs ~$0.28 whatever is used of it, but it is bought once and composited into every quiz
afterwards. The marginal cost per video is zero. A finished clip is never regenerated without
`--regenerate`, and `--force` re-keys from the clip already bought so beat length, despill and crop
can be tuned for free.

The asset is an H.264 `.mp4` carrying colour stacked over its own matte, unpacked through
`unpack_filter()`. Lossless RGBA runs 12–20 MB per 1.4s clip; both WebM encoders in this build
accept `yuva420p`, write `yuv420p` and exit 0, losing the alpha with no error at all. The stacked
form is ~0.5 MB and reconstructs the matte to within 0.08/255.

**None of it is composited into the shipping render.** V2.4 changes narration and the closing card;
bundling a mascot into the same batch would produce one number for two changes. The mascot-free
rule above still governs what actually renders — when Bolt is wired in, it should be as a named
exception naming the exact beats, not by loosening a rule that currently reads as absolute.

**All five generate cleanly, but only on the pro i2v tier for three of them.** The standard tier
honours the flat magenta for roughly 0.45s on poses that lean, tip or recede, then starts rendering
the depth the motion implies — and depth means a background. The key removes the magenta it still
recognises and leaves the rest, so the cutout grows an opaque halo that composites as a dark
rectangle over the scene.

`smug`, `shock` and `dead` all failed that way at 0.43-0.47s and were rejected. Regenerated through
`--hero --reclip` — the pro tier, same seed, so the model was the only variable — they held the flat
background to 1.1s, 1.4s and 1.8s respectively. `hyped` and `clap` never leaked on the standard
tier. The rule of thumb: **a pose that leans, tips or recedes needs `--hero`; a pose that stays
planted does not.**

The vision audit passed all three. It was right to: asked whether the robot is on-model it said yes,
because it was. The halo is a pixel fact, so the gate that catches it measures corner opacity rather
than asking a model — a limb reaches an edge routinely, and nothing about the character reaches all
four corners.

**The mascot was tried against a real render and dropped.** Three placements were prototyped as
overlays on finished output, none of it wired into the pipeline:

| Placement | Result |
|---|---|
| Complete figure standing on the answer card | reads as a sticker pasted on the video |
| Bottom-anchored, cropped by the frame edge | reads correctly — a character leaning into the shot |
| Bottom-anchored, larger | same, with more presence |

The cropping is what separates the two: a whole figure sitting on a UI element reads as an overlay,
where a figure cut off by the frame edge reads as being in the scene. Same asset, different
impression. Bottom-anchoring also frees the answer card and the animal entirely, because it fills
the dead space below the answer rather than competing for the space above it.

Even done correctly it was not what the format wanted, so no mascot ships. Two findings are worth
keeping for any future attempt:

- `hyped` survives cropping because its motion is in the arms and head. `dead` does not — the
  keel-over happens in the body, which is exactly what the frame edge removes.
- A bottom-anchored mascot collides with the closing card's score ladder at y1474. The ladder is
  the ask, so it wins that frame; a mascot on the CTA has to be clamped to the answer beat.

The generator and its five audited clips stay in the tree. They cost $2.80, nothing imports them,
and the tooling — magenta keying, leak detection, identity audit — is reusable for any character
work later.

## What V2.4 does not claim to fix

Retention is not what caps these videos at ~1500 views, and the V2.4 changes should not be read as an
attempt on that ceiling. The V2.3 rewrite roughly tripled stayed-to-watch against the 31–32s quizzes
it replaced (15.8% → 46.0%) and views did not move: the dinosaur quiz at **15.76%** stayed-to-watch
took **1568** views, while the V2.3 replacements at 35–46% took ~1.2K each.

The watch-time arithmetic is the likelier explanation, and it points the other way:

| Format | Duration | APV | Watch time per view |
|---|---:|---:|---:|
| Pre-V2.3 quiz | 32s | ~48% | **~15.4s** |
| V2.3 / V2.4 | ~11s | ~110% | **~12.1s** |

Cutting 32s to 11s traded ~21% of absolute watch time per view for a percentage that was already
winning. V2.4 changes what happens *after* the swipe decision — frame zero is unchanged apart from
the contrast gate — so the honest expectation is better mid-roll retention and more comments, not a
broken view ceiling. The experiment aimed at the ceiling is a **longer** quiz: 5 rounds at ~18.6s
would deliver ~16.7s per view at a plausible 40% stayed / 90% APV, above both formats, and widens the
score ladder the closing card now offers. That requires raising `max_items` and is deliberately not
bundled with this change, so the two can be told apart in the data.

If stayed-to-watch remains below 30%, test the next first-frame mechanic rather than adding more length:

1. **Two-shadow choice:** show A/B silhouettes and ask which one matches the named animal.
2. **Odd-one-out:** three visual clues, one does not belong; reveal the causal reason.
3. **Texture/detail:** replace the shadow with fur, skin, feather, eye, or footprint crops.

Do not restore a standalone host intro or post-game subscription card. The CTA belongs inside the final
answer reward; branding stays in the typography and repeatable game structure.
