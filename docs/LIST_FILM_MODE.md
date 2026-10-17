# List Film Mode

A list film answers one umbrella question with a countdown of short, sourced stories. The format
pools are where the demand sits: the 2026-10-16 scout measured typical views of 1.06M for "worst
nuclear accidents", 765K for "forbidden places" and 398K for "invasive animals". A single-story
film can't reach those pools.

- Code: `list_film.py` (spec, checks, picture matching, timeline) and `scripts/make_list_film.py` (the build).
- Example: `docs/examples/list_animals_nobody_can_stop.json`.

## How a list film is built

1. **Entries come from films we already researched.**
   - Each entry names a finished job. Its sentences cite that job's verified claims (`claim_id`s from its dossier).
   - An entry whose research has no pictures (e.g. `canetoad01`) gets an `image` prompt on each beat.
2. **The sourcing gate runs before any media spend.**
   - `--check-only` runs the same fidelity judge as the single-story pipeline on every factual sentence. Each sentence is judged against the claims it cites, quotes included.
   - An unsupported detail stops the build, and `fidelity.json` names it.
   - A provider outage stops the build as an outage; it is never recorded as a verdict.
3. **Pictures follow the claims.**
   - A sentence gets the pictures of the scenes that cited the same claims, unused ones first.
   - `scene` names a scene outright; `image` draws a new one.
4. **The render:**
   - a countdown card before each entry;
   - 16:9 Ken Burns shots, none longer than 3.4 s (the rendered gate's ceiling is 3.5 s);
   - the chamber bed ducked under the voice, dipping at each card;
   - `captions.srt`;
   - `description.txt` with chapters and the cited sources;
   - `run_result.json`, so `upload_job.py` can upload it.

## Writing rules

The story playbook (`docs/STORY_PLAYBOOK.md`) applies, adapted to a countdown:

- **One umbrella question, held open.** The countdown is the loop. The intro plants the #1 entry's
  moment and the outro returns to it.
- **The human story in every entry.** Open each entry on its documented person's moment, then the fix, the consequence, and why it can't be undone now.
- **Count up the stakes.** #1 is the entry with the widest reach or the documented deaths.
- **Give explicit dates.** Every sentence is judged alone, so "a year earlier" or "three years later"
  has no anchor and fails. Say "in 1956" or "in 1993".
- **One number per sentence,** said at human scale.
- **The outro answers the umbrella question in one plain sentence,** returns to the opening moment, and stops.
- **A rhetorical line asserts nothing new.** Mark it `"rhetorical": true` only when it is a question, a joint, or a summary of facts the film has already told.

## Commands

```bash
python3 scripts/make_list_film.py <spec.json> --out jobs/<slug> --check-only
python3 scripts/make_list_film.py <spec.json> --out jobs/<slug>
python3 scripts/upload_job.py jobs/<slug> --title "<question title>"
```

Packaging follows `docs/FATAL_THUMBNAIL_PLAYBOOK.md`: a question title in words a cold viewer knows,
and a split thumbnail. FATAL is allowed only when the transcript documents a death.

## The pilot (2026-10-17)

"Why Can't Anyone Stop These 4 Animals People Brought In?": #4 Escobar's hippos, #3 Asian carp, #2
cane toads, #1 African bees.

- **Result:** 3:29, 84 shots from 42 pictures, longest shot 3.3 s, −18.5 LUFS.
- **Gate:** 27 factual sentences passed the judge after five rewrites (relative dates, an unnamed actor, a place not in the cited claim).
- **Cost:** about $0.31 of judging, six new pictures and narration. The other pictures were reused from the films.
