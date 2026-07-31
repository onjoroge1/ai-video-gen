# Bolt Packaging Playbook — What-If Science Explainer Channel

> Source: multi-agent research (2026-07-11) on high-CTR science/"what-if" thumbnail + title
> packaging, cross-referenced with this channel's own metrics (Water short 73% viewed with
> real-life imagery; Light long-form 2.4% CTR with symbolic imagery).
>
> **Confidence:** every *structural principle* below is high–medium confidence from multiple
> sources or primary creator/academic grounding. The exact CTR-lift percentages that circulate
> online (37.4% group penalty, 39% contrast, 20-30% emotion, 38% consistency, 36% numbers, "2%
> doubles views") are single-SEO-source and **not verified** — treat as directional and A/B test.

## The #1 principle most small science channels get wrong
**Thumbnail and title are ONE show-vs-tell unit, not two labels.** The **thumbnail SHOWS** the
surprising, impossible-looking visual; the **title TELLS** the specific verbal setup + keyword +
number — and *neither resolves the gap the other opens.* Redundancy throws away half your
packaging. For a faceless/mascot channel the thumbnail carries 100% of the click, so it can't
waste words echoing the title. [high]

## Thumbnail checklist — DO
1. **One focal subject — pass the squint test** (identifiable in <1s at ~160px). Bolt OR one anomalous object/scene, not both + a prop. [high]
2. **Render the "what if" as a LITERAL image of the actual thing, not a symbol.** Show the premise made real (a sunbeam crawling, a frozen ocean, a second moon) — never a metaphor (an hourglass for "time," a glowing vortex for "energy"). The eye resolves an image faster than text, and it dodges garbled AI-text. [medium]
3. **0–3 words of baked text, only as a curiosity trigger** (a number, "WHY?", a superlative) — never a description, never the title repeated. [high]
4. **Keep a curiosity gap the title does NOT answer** (thumbnail shows the anomaly; title frames it; neither resolves it). [high]
5. **High LOCAL contrast** — 2–3 bold colors, subject ~30%+ separated from background, text ≥4.5:1 (WCAG AA). [high]
6. **One glowing, saturated focal color on a darker/neutral field** (the neon-on-deep-space move). [medium]
7. **Bolt = genuine awe/wonder, not the cliché open-mouth shock face** (the shock face is decaying). [medium]
8. **Design mobile-first** — compose and QA at ~160px next to real competitor thumbnails (70%+ of views are mobile). [high]
9. **Lock a house style eventually — but early, prioritize raw stopping-power over brand consistency.** [medium]

## Thumbnail checklist — DON'T
1. **Clutter** (multiple subjects/logos/arrows/text) — the most-cited CTR killer. [high]
2. **Repeat the title** in the thumbnail — wastes the second slot. [medium]
3. **Overpromise** — clickbait wins the click, loses the Test & Compare on watch-time share. [high on mechanism]
4. **Ship a generic "looks-AI" thumbnail** (garbled text, uncanny render, stock-generic). [medium]

## Title checklist
**Formula:** reveal the SETUP, withhold the OUTCOME; front-load a specific concrete subject in the
first ~4–5 words; a number only to quantify stakes; ~60–70 chars / ~10–11 words long-form (Shorts
declarative, <~40 chars); imply a visceral consequence; complement — never repeat — the thumbnail.
- **Curiosity gap is the core driver** — name the scenario, hide the consequence. [high]
- **Second-person "you"** makes stakes personal. [high]
- **Specificity beats vagueness, hard** ("Black hole through your body" > "space is dangerous"). [high]
- **Number only to quantify stakes** ("1,000 mph faster" ✓; "5 what-if scenarios" ✗). [medium]
- **Front-load the keyword** in the first ~60 chars. [high]
- **Question mark optional** — works in Science/Tech (answer-seeking mode), but top long-form skews declarative; test both. [medium]
- **Bracket hook** for a second curiosity layer: "(It's Worse Than You Think)." [medium]
- **Benchmark:** ~8–15% CTR is strong for optimized science; below ~4% signals a packaging problem. [medium]

**Example titles:** *What If a Black Hole Passed Through Your Body?* · *This Is What Happens If Earth
Stops Spinning for 10 Seconds* · *What If You Fell Into Jupiter? (It's Worse Than You Think)*

## Scoring rubric (rate each 0–2; total 0–10)
1. **Single focal point** — one subject passes the 1-second squint test at 160px, no clutter.
2. **Curiosity gap, unresolved & honest** — the pair opens a loop neither half closes, and the video can pay it off.
3. **Show-vs-tell split** — thumbnail shows the visual; title carries the verbal setup + keyword; no repeated words.
4. **Specificity + stakes** — concrete subject front-loaded; number only if it quantifies; consequence visceral/second-person.
5. **Mobile legibility + contrast** — ≤3 words baked, high contrast, reads clean at 160px, doesn't look AI-generic.

**Interpretation:** 9–10 ship + A/B test; 6–8 fix the lowest dimension first; ≤5 rebuild. Whatever the
score, still run Studio **Test & Compare** (up to 3 variants, ~7–14 days / 10k+ impressions) —
packaging is empirical, and the winner is chosen on watch-time share, not raw CTR.

## How this maps to the pipeline (implemented 2026-07-11)
- **`_thumbnail_caption` / `_bg_prompt`** — steer to the LITERAL subject + show-vs-tell text (not the title), gated on `LITERAL_IMAGERY` (default on).
- **Scene image direction** — real-life / lab / documentary default; symbolic-metaphor imagery demoted; same `LITERAL_IMAGERY` toggle so grounded-vs-current can be A/B'd.
- **`grade_thumbnail`** — checklist upgraded to the researched dimensions (single focal · literal subject · show-vs-tell · curiosity gap · Bolt wonder · mobile contrast).
- **Validation** — log CTR + retention per video in the Metrics tab; the tags/CTR fields exist to prove packaging changes on real data, not vibes.
