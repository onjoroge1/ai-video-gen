# Quiz Short Retention V2.3 — Three-Round Rapid Reveal

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

## V2.3 creative contract

- The **first clue is frame zero**. No mascot intro or logo hold.
- Three rounds maximum: **warm-up → no hints → final boss**. The opener cannot be trivial.
- Voice and timer run concurrently over the clue; no separate “What is it?” card.
- Each 2.4-second guess progressively widens from a tight detail to the complete clue every 0.8 seconds.
- Reveal: 0.8–1.2 seconds; the final reveal may run up to 3.6 seconds for the integrated replay CTA.
- A vision QA pass grades first-crop difficulty, full-clue fairness, answer identity, anatomy, pose,
  subject occupancy and clue/background contrast at phone size.
- Overly easy openings are cropped tighter; incorrect/anatomically weak reveals regenerate once.
- Critical headers, timers, answers, and CTA remain inside the Shorts safe zone.
- Every card has subtle duration-aware motion; no frozen multi-second PNG.
- Optional `QUIZ_FAL_OPENER=1` uses one fal/Kling clip behind the first countdown only. This isolates
  the value of generative motion at the swipe/stay decision without paying to animate every card. It is
  not combined with progressive crops because generative silhouette morphing can make a clue unfair.
- The shipping quiz has **no mascot overlay**. Search and reveal frames stay focused on the animal,
  timer, answer typography, and same-frame colour transformation; off-model character art cannot cover clues.
- The final answer carries “GOT ALL 3? · SUBSCRIBE” on screen. The spoken line asks for the replay
  instead — “Missed one? Go again.” — so the two channels complement rather than repeat, and the ask
  names an action the loop has already made free. There is no separate outro or subscription card.
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
a moving timer. Typography, difficulty labels, sound, and reveal choreography carry the format identity
without a character competing for the frame. The reveal is a color transformation of the same subject,
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
sitting against dark rainforest foliage.

If stayed-to-watch remains below 30%, test the next first-frame mechanic rather than adding more length:

1. **Two-shadow choice:** show A/B silhouettes and ask which one matches the named animal.
2. **Odd-one-out:** three visual clues, one does not belong; reveal the causal reason.
3. **Texture/detail:** replace the shadow with fur, skin, feather, eye, or footprint crops.

Do not restore a standalone host intro, mascot overlay, or post-game subscription card. The CTA belongs
inside the final answer reward; the animal and the game remain the visual focus.
