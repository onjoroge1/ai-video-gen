# FATAL Thumbnail Playbook: World and History films

> Operator standard, 2026-10-17. It extends `docs/PACKAGING_PLAYBOOK.md` (show-vs-tell, squint
> test, curiosity gap) to the consequence films on Bolt Explains the World and Bolt Explains
> History. Tool: `scripts/make_fatal_thumbnail.py`.

## Why someone cold-clicks

A cold viewer gives a thumbnail under a second, at about 350 px wide, between other videos. Four
triggers earn the click. Design every panel against them:

1. **One salient subject per panel.**
   - The eye needs one large, high-contrast thing to land on.
   - Two busy halves read as noise at feed size.
2. **A person close to the threat, at the moment before.**
   - We are wired to watch danger near a human.
   - Anticipation creates tension the brain wants resolved; aftermath does not.
3. **Recognition plus wrongness.**
   - Show something the audience half-knows, plus one detail that should not be there.
   - Elephant's Foot: the famous black-and-white photo, then the same mass with glowing cracks.
   - Demon Core: a screwdriver, with blue light leaking along its blade.
4. **A curiosity gap the title does not close.**
   - The picture raises the question, the title frames it, and only the film answers it.

## The format

- **Split screen.**
  - The left (about 45%) is circled in red.
  - The right (about 55%) carries the headline.
  - A yellow arrow runs left to right.
  - `backfire_packaging.compose` draws all of this; the image model never draws the ring or the text.
- **Left panel: the act.**
  - The recognizable thing or deliberate fix, with one wrong detail, large and centred in the lower two-thirds.
  - No faces.
- **Right panel: the threat, now.**
  - One person at dominant scale (or a gloved hand), close to the danger.
  - Grounded, realistic fear: wide eyes are fine, but never an open-mouthed cartoon shock face. The operator rejected one on the Chernobyl thumbnail.
  - Keep the top 22% dark for the headline.
- **Photoreal documentary look.** The live Chernobyl FATAL TEST set this.
  - Illustrated thumbnails on the History lane are allowed when the film is illustrated.
  - Read both at feed size before choosing.

## The headline: "FATAL ___"

- Two words: yellow **FATAL**, then a white noun. Examples: FATAL TEST, FATAL FUEL, FATAL SLIP.
- **The noun names the thing visible in the picture.** That is where the mystery comes from.
  - FATAL FUEL over a background of a door and dials pointed at nothing.
  - FATAL FUEL over the Foot itself did.
- **Use FATAL only where the film documents deaths or lethal danger.**
  - The script checks the transcript (`fatal_allowed`) and refuses otherwise.
  - Where FATAL would mislead (an invasive species, plastic, a mine fire nobody died in), keep the same look with a different first word.
- **The headline is thumbnail-only.**
  - Video titles stay search-led: they keep the demand keyword ("Elephant's Foot", "Demon Core").
- **Check for fatigue** after about five FATAL films.

| Film | Headline | Left (circled) | Right |
|---|---|---|---|
| Chernobyl, 40 years later | FATAL TEST | gloved hand on the shutdown button | hazmat figure, dosimeter, the arch |
| Elephant's Foot (arch reframe) | FATAL FUEL | 1996-style black-and-white photo: man beside the Foot | the same mass today, ember cracks, dosimeter pinned red |
| Demon Core | FATAL SLIP | bare fingers, screwdriver in the gap, blue light leaking | physicist's face lit blue, colleagues shielding their eyes |

## The title: a question in words the cold viewer knows

Operator rule, 2026-10-17: question titles drive traffic. Chernobyl, the channel's clearest performer,
is "Why Can't Anyone Live at Chernobyl, 40 Years Later?".

- **Write the title as the film's own question.** The thumbnail shows the danger; the title asks the question.
- **Lead with a term the broad audience already knows.**
  - Explain a niche term or leave it out, even when it is the search keyword.
  - "Elephant's Foot" went live in a statement title and was retitled.
  - The new title is "Why Is Chernobyl's Melted Reactor Fuel Waking Up 40 Years Later?", because most browsers do not know the term.
  - The keyword stays in the tags, the description and the Short.
- **Stakes, then question,** where a known stake exists: "The Demon Core Killed a Scientist. Why Did They Keep Testing It by Hand?"
- **Don't repeat the thumbnail's words,** and keep it to about 70 characters.
- **After retitling a live film,** re-sync its translations with `scripts/localize_video.py <id> --job <job> --langs <existing> --if-changed`.

## Accuracy before upload

The pipeline's packaging is written from the run question. On 2026-10-17 it drew two failures:

- **Elephant's Foot:** it crossed out "sand and lead", which the reframed film no longer covers.
- **Demon Core:** it drew protective gloves on a story about bare hands.

Before setting a thumbnail, check:

- The circled act is the film's actual fix or act, as narrated.
- No detail contradicts the film (gloves, the wrong era, an object that is not there).
- Metaphor is labelled to yourself.
  - The Foot's ember glow stands for "waking up"; the mass gives off heat but does not visibly glow.
  - A metaphor that shows the film's claim is acceptable.
  - One that invents a new claim is not.
- The thumbnail does not answer the title, and the title does not repeat the thumbnail.

## Process

1. **Write the two panels against the four triggers.** Pick the noun.
2. **Generate two candidates per film:**

   ```bash
   python3 scripts/make_fatal_thumbnail.py jobs/<job> --word FUEL --name v2 \
     --left "..." --right "..."
   ```

   This writes `<job>/thumbs/<name>_bg.png`, the composed `<name>_fatal_fuel.jpg` and a JSON record
   holding the prompt and the transcript evidence for FATAL.
3. **Run the feed test.** Put every candidate at 360 px beside the live reference:

   ```bash
   python3 scripts/make_fatal_thumbnail.py jobs/<job> --feed-test a.jpg b.jpg
   ```

   Choose on what reads in under a second, not on the full-size image.
4. **Install it.** `--set <path>` copies it to `<job>/thumbnail.jpg`, which `upload_job.py`
   uploads. The pipeline's own thumbnail is kept as `thumbnail_pipeline.jpg`.
5. **After publishing, use Studio Test & Compare.** Choose on watch-time share, not raw CTR, as
   `PACKAGING_PLAYBOOK.md` says.

## What failed first (2026-10-17, v1)

- **FATAL FUEL v1:** the circled half was the New Safe Confinement. It is a grey building nobody recognizes at feed size, and it shows no threat. The interesting object, the Foot, was a murky blob behind a hazmat figure turned away from the camera. Nothing looked wrong, so it raised no question.
- **FATAL SLIP v1:** the left read as "a man prying a metal ball", because nothing signalled a bomb core. The scare on the right was small figures in aftermath.

In the feed test, v2 of each read instantly and v1 did not.

## Experiments: three thumbnails per film, one hypothesis each

Operator, 2026-10-18. Each new film ships with three thumbnails: the playbook control plus two variants
that each change ONE thing. The test runs in Studio's Test & Compare, which splits impressions at random
on the same video and picks the winner by watch-time share. One hypothesis per film, and no title change
while it runs.

The ladder (`HYPOTHESES` in the script; `--next-hypothesis` prints the first one the log hasn't started):

| Id | Variable | Hypothesis |
|---|---|---|
| H1 | picture | The thumbnail shows what the title asks, not the backstory (Chernobyl, started 10-18) |
| H2 | picture | A human face in danger beats an object, or a figure seen from behind |
| H3 | headline | The word matters: FATAL vs. a word from the film vs. no text |
| H4 | picture | A famous icon beats a new scene |
| H5 | picture | A split (cause → consequence) beats one hero image |
| H6 | style | Illustrated, matching the film, beats photoreal |

A spec names the control and the overrides. A variant that keeps the control's picture reuses its
background, so a headline test costs one image:

```json
{"hypothesis_id": "H2", "hypothesis": "A face in danger beats an object or a figure from behind.",
 "variable": "picture",
 "control": {"name": "A", "first": "FATAL", "word": "COIL", "left": "...", "right": "<a face, close to the threat>"},
 "variants": [{"name": "B", "right": "<the threat alone, no person>", "note": "object only"},
              {"name": "C", "right": "<the person seen from behind>", "note": "figure from behind"}]}
```

```bash
python3 scripts/make_fatal_thumbnail.py jobs/<job> --variants spec.json --set-control
python3 scripts/make_fatal_thumbnail.py jobs/<job> --record-result H2 --verdict winner --winner B --shares A=31,B=44,C=25
```

Outputs:
- `thumbs/<test>_A|B|C.jpg`
- the feed sheet beside the live reference
- `thumbs/<test>.json`
- an entry in `jobs/yt/experiments/THUMBNAIL_LOG.md` (git-ignored: analytics stay out of the public repo)

The FATAL guardrail applies to every variant. YouTube doesn't expose Test & Compare results through the
API: record them from Studio. Many small-channel tests will end "inconclusive". That is a result too: the
variable isn't the bottleneck.
