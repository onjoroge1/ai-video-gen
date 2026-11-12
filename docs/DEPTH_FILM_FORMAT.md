# Depth film format

On 2026-11-08 the operator made this format the standard look for films. It was first used in the Chernobyl horses 60-second pilot.

The narration and music stay exactly as they are; only the pictures are rebuilt:

- **A recurring "you":** an anonymous person whose face is never shown.
- **Text cards on the key lines:**
  - a green ✓ marks what everyone believes;
  - a red ✗ marks a wrong belief;
  - a red box marks the turn.
- **Explainer graphics:** maps, callouts, split screens, icon counts and inset pictures.
- **Constant motion:** image-to-video (I2V) clips, or a camera move on a still.

**Rule:** a card may only use words the narrator speaks within 8 s of it. `check` enforces this, and `frames` and `render` refuse a spec that breaks it. The `--allow-unspoken` flag is for the operator only.

## Workflow

```bash
S=jobs/<job>/<cut>/depth.json
python scripts/make_depth_film.py $S check     # shot table + card rule, $0
python scripts/make_depth_film.py $S plan      # missing stills/clips and their cost against cap_usd, $0
python scripts/make_depth_film.py $S stills    # gpt-image-2 high (~$0.21 each); stills that reference stills wait for them
python scripts/make_depth_film.py $S frames    # contact_sheet.jpg, $0 — review before buying clips
python scripts/make_depth_film.py $S clips     # Kling v3 pro 5 s (~$0.56 each)
python scripts/make_depth_film.py $S render --sbs   # <name>.mp4 at 1440p + side_by_side.mp4 against audio.source
```

**Spend:**
- Paid steps log to `ledger.jsonl` next to the spec.
- They refuse to start if the logged spend plus the planned purchases would pass `cap_usd`.
- Nothing already bought is bought again unless it is passed to `--force`.

**Clips are optional.** A clip background whose `clips/<name>.mp4` is missing renders as a camera move on its still. Without clips, a film still works as a $0 preview.

## Spec

| Key | Meaning |
|---|---|
| `name` | Output file stem. |
| `job` | The job directory, relative to the spec's own folder (usually `..`). Paths like `images/x.jpg` resolve inside it. |
| `cap_usd` | Hard cap on what the paid steps may spend. |
| `audio` | `{source, start, end}`. Audio is cut from `source` (normally the finished `explainer.mp4`). Times use the time syntax below. |
| `vars` | Text substituted into prompts as `{NAME}`, for example STYLE, YOU and the animal. |
| `points` | Named points on pictures, as 0–1 fractions of that picture. |
| `stills` | `{name: {prompt, refs?}}`, saved as `stills/<name>.png`. Elsewhere in the spec, refer to one as `@name`. |
| `clips` | `{name: {image, prompt, seconds?, model?, negative?}}`, saved as `clips/<name>.mp4`. |
| `shots` | The list of shots, back to back. Each shot ends where the next one starts, and the last ends at `audio.end`. |

**Narration timeline:** word timings come from `audio/scene_NN.mp3.word_times.json`, offset by the scene durations.

### Time syntax

| Form | Meaning |
|---|---|
| `12.3` | Seconds. |
| `"Poison"` | The start of the first time that word is spoken. |
| `"This is"` | A phrase. Use one when a single word comes earlier, as "this" does in "Picture this.". |
| `"farm#2"` | The second occurrence. |
| `"barn+0.3"`, `"Slowly-0.12"` | A word plus or minus an offset in seconds. |
| `"+0.5"` | Seconds after the start of the shot or segment. |

### Shot

```json
{"name": "zone map", "start": "This is", "vignette": 0.35,
 "bg": {...} | [{...}, {...}],
 "overlays": [...]}
```

**Background segments** (`bg`): a list plays in order. A later segment starts at `from` and fades in over `xfade` seconds.

| Kind | Fields |
|---|---|
| Still | `{"still": "@map", "z": [z0, z1], "c": [c0, c1], "ease": true, "window": [t0, t1], "color": 0.25, "bright": 0.8, "blur": 18}` |
| Clip | `{"clip": "c04_barn", "still": "@barn", ...}`. Plays the clip, retimed to fit the segment, and falls back to the still's camera move. |
| Split | `{"type": "split", "from": "isn't#2", "wipe": 0.35, "left": {"still", "centering"}, "right": {...}}`. The left picture wipes in over the previous segment. |

How a still's camera move works:
- `z` is the zoom; 1 is the widest 16:9 crop.
- `c` is the centre, given as fractions or a point name.
- The move runs over the segment, or over `window` if one is given.

**Overlays.** Every overlay takes `at`, and may take `until`.

**Positions:** use `pos` (pixels on the 1920×1080 canvas), or `pt` (a point on the current still) plus `offset`.

| Type | Fields |
|---|---|
| `card` (the default) | `text`, `size`, `style` (`dark` \| `red` \| `tag`), `mark` (`check` \| `x`), `anchor` (`lt`, `ct`, `cc`, `rc`, …). |
| `callout` | `pt`, `label: [dx, dy]`, `text`. A line runs from the point to the label. |
| `pin` | `pt`, `color`, `r`. |
| `ring` | `pt`, `radius`, `dur`. |
| `glow` | `pt`, `rx`, `ry`. |
| `inset` | `still`, plus `pt` + `offset` or `pos`, and `radius`. A circular picture. |
| `path` | `from`, `to`, `lift`, `dur`, `label: {text, at}`. A dashed arc; the label sits at its midpoint. |
| `icon_rows` | `rows: [{label, at, build: [t0, t1], n, y, count, count_at, count_style, highlight_last}]`. 16 icons per row, so "33" puts its odd pair alone, in red. |
| `statement` | `text`, `color`, `size` (230), `dim` (0.78). One or two spoken words fill the frame over the darkened picture. Use it for the answer to a question the narration just asked ("SQUID.", "YES."). |
| `bars` | `rows: [{label, v, at, value, color, style}]`, `vmax`, `x`, `y`, `w`. Bars on one scale, each filling when its number is spoken. Use it to put the viewer next to the animal (your speed against its speed). |

**Who is in the picture** (`shows`). Give every shot `"shows": ["animal", "you"]`, or `[]` when neither is visible. `check` then reports every stretch where the animal is off screen for more than 20 s or YOU for more than 90 s, and names the shots to repaint. Set other limits with a top-level `"presence": {"animal": 20, "you": 90}`; 0 switches one off. A spec with no `shows` at all is not checked. `render` is not blocked.

## Making a new film in this format

1. **Copy a spec.** The reference is `jobs/chernobyl-horses/pilot60/depth.json`; a copy is kept in `docs/examples/depth_chernobyl_horses_pilot60.json`. Keep its `vars.YOU`, so the same character appears in every film.
2. **Keep the animal and YOU on screen.** In the Chernobyl horses film the horse was off screen for 74 s during the war section and YOU for 179 s in the middle; the reference film this format comes from almost never loses its animal. A shot about soldiers, fire or a document still shows the animal or YOU in the frame. Tag `shows` on every shot and run `check`.
3. **Write one shot every 2–6 s.** Put a card on every belief, every turn and every number. Prefer a graphic to scenery wherever the line explains something.
4. **Reuse the film's existing pictures** in `images/`. Buy stills only where the "you" character or a new composition is needed. Generate the "you" stills from the first "you" still (`refs: ["@you_road", ...]`) so the person stays the same.
5. **Run `check` → `plan` → `stills` → `frames`.** Review the contact sheet. Then run `clips` → `render --sbs`.
6. **Check the result:** `render` writes a 1440p film with the source audio. Before uploading, compare it against the old cut in `side_by_side.mp4`.
