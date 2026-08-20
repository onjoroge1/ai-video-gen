# Quiz Short Retention V2 — Rapid Reveal

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

## V2 creative contract

- The **first clue is frame zero**. No mascot intro or logo hold.
- Three rounds maximum: **medium → hard → expert**. The opener cannot be trivial.
- Voice and timer run concurrently over the clue; no separate “What is it?” card.
- Guess window: 2.4 seconds. Reveal: 0.8–1.2 seconds, answer only.
- Every card has subtle duration-aware motion; no frozen multi-second PNG.
- The final answer carries “COMMENT SCORE”; there is no outro or subscribe teaser.
- Expected duration is roughly **10–11 seconds**, designed to invite an immediate replay.

## Why this is a creative change, not only a trim

The viewer now receives the product before deciding whether to swipe: a large, legible mystery shape and
a moving timer. Bolt remains the channel identity, but does not occupy the scarce first-frame real estate.
The reveal is a color transformation of the same subject, so every 3–4 seconds contains a visual reward.

## Controlled test

Publish three Rapid Reveal quizzes in one category before drawing conclusions. Keep posting window,
title shape, item count, voice, and music consistent. Compare against the prior quiz baseline.

Primary gates after at least 500 Shorts-feed impressions:

| Metric | Baseline | V2 minimum | Strong result |
|---|---:|---:|---:|
| Stayed to watch | 19% | 30% | 40%+ |
| Average percentage viewed | ~48% | 85% | 110%+ |
| Average view duration | 16s / 33s | 9s / ~11s | 12s+ / ~11s |
| End-of-video retention | ~5% | 50% | 70%+ |

If stayed-to-watch remains below 30%, test the next first-frame mechanic rather than adding more pacing:

1. **Progressive crop:** start on an eye/texture/detail and reveal one larger crop every 0.6 seconds.
2. **Two-shadow choice:** show A/B silhouettes and ask which one matches the named animal.
3. **Odd-one-out:** three visual clues, one does not belong; reveal the causal reason.

Do not restore a standalone host intro, spoken CTA, or post-game subscription card. Those can be tested in
metadata, pinned comments, or a small non-blocking brand mark without delaying gameplay.
