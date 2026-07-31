# Bolt Bespoke Video Flow — Full Map (for audit before rebuild)

**Purpose:** document *everything* in the current "bespoke" video path — inputs, scripts, prompts, models,
ffmpeg recipes, costs, version history, and where it over-engineered into bad output — so we can strip it
down and rebuild deliberately. This is the **package → standalone-script → MP4** path (oxygen + cloud
lineage), which is SEPARATE from the repeatable UI shorts pipeline (`explainer_pipeline.py` etc.).

> Bottom line up front: the bespoke flow grew into ~40 one-off scratchpad scripts and a 6-layer assembly
> (TTS → whisper-align → Ken-Burns/Kling hybrid → captions → synth wind → loudnorm → concat/mux). The
> **inputs and audio path are fine; the motion layer is where it breaks** — 10 independent i2v clips can't
> form one continuous action, and the source frames themselves fight the premise. That's the crap.

---

## 1. What "bespoke" means here

| | UI shorts pipeline | Bespoke flow (this doc) |
|---|---|---|
| Trigger | Topic prompt in the UI | A hand-authored **production package** (images + script + spec) |
| Script | LLM-generated + graded | Pre-written (recipe `voiceover` / `narration.txt`) |
| Images | Generated per scene | **Pre-made frames supplied in the package** |
| Assembly | `run_explainer_pipeline` | **One-off scratchpad Python script per video** |
| Repeatable? | Yes (one-click) | **No** — every video is a bespoke script |
| Output | 9:16 / 16:9 short | 9:16 short (~16–21s) |

Two packages exist: `renders/bolt_cloud_experiment_package/` and
`renders/Bolt_Oxygen_Subscription_V3_Production_Package/`.

---

## 2. Production package format (the INPUT)

A package is a folder the assembly script reads. Cloud package contents:

```
images/            10 master frames, 9:16 (941×1672), numbered 01..10 in causal order
reference/         bolt_original_reference.jpeg  (character identity)
prompts/           MASTER_VIDEO_CREATION_PROMPT.md, individual_image_prompts.{md,json}
spec/              video_spec.md, render_qa_checklist.md, voiceover_script.txt
metadata/          video_recipe.json (timing/captions/motion/sfx), asset_manifest.json
contact_sheet.jpg  overview of all frames
```

**`metadata/video_recipe.json`** is the machine-readable heart: `target_duration_seconds`, the full
`voiceover` string, and a `shots[]` array where each shot has `{shot, file, start, end, narration,
caption, motion, sfx}` plus `global_constraints` (images in order, downward-only, no static >2.3s, loop
final→first, no CTA). The oxygen package uses `shot_manifest.json` + `motion_prompts.md` + `continuity_bible.md`
+ `qa_checklist.md` + `baseline_lessons.md` for the same purpose (heavier).

The assembly script's job: **turn these fixed frames + fixed narration into a timed, captioned, voiced,
motion'd MP4.**

---

## 3. The assembly pipeline (the FLOW)

Current best version = `scratchpad/render_cloud_final.py` (stills) and `render_cloud_i2v.py` (motion).
Six layers:

### 3.1 Narration → continuous TTS
- `ep.generate_tts(VO_TEXT, path, voice="onyx")` → OpenAI **tts-1-hd**, one continuous take of the full
  voiceover (NOT per-line — per-line placement caused the v1 "skip"; see §6).

### 3.2 Whisper alignment → per-shot timing (the good part)
- `ep.transcribe_words(vo)` → OpenAI **whisper-1** word timestamps `[(word,start,end),...]`.
- Each shot's narration fragment is mapped to its **last word's end time** by cumulative word count;
  shot window = `[prev_end, this_end + 0.10]` (last shot +0.6s tail). Proportional fallback if the whisper
  word count is off by >~4. → **each shot stays on screen exactly as long as its line** (no gaps, no dead
  tail, no desync). This is the UI-pipeline-quality trick and it works.

### 3.3 Per-shot visual clip (the BROKEN part)
Two modes, chosen per shot:
- **Ken Burns still** (deterministic, safe): ffmpeg `zoompan` on the frame.
  - push-in: `z='min(1.0+0.0016*on,1.14)'` · pull-out: `z='if(lte(on,1),1.14,max(1.14-0.0016*on,1.0))'`
    · near-static: `z='min(1.0+0.0006*on,1.035)'`
  - Supersample 2× (`scale=2160:3840,crop=2160:3840`) before zoompan → smooth sub-pixel pans; output `s=1080x1920:fps=30`.
- **Kling i2v** (fal, motion): see §4. Clip trimmed to the shot's window and `scale=1080:1920:force_original_aspect_ratio=increase,crop`.

### 3.4 Captions (PIL)
- `Arial Bold` ~84px, white with black stroke(5), on a `rounded_rectangle` dark pill (`fill=(0,0,0,150)`),
  centered, lower third (`y ≈ 0.70·H`), wrapped at ~17 chars/line. Rendered to a transparent PNG per shot,
  overlaid via ffmpeg `overlay=0:0`.

### 3.5 Synthesized wind bed (added for the cloud short)
- ffmpeg `anoisesrc=color=brown:amplitude=0.6`, `lowpass=f=650`, `highpass=f=90`, `volume=0.15`, 1s fades.
- Mixed under the VO: `amix=inputs=2:weights=6 1:normalize=0` (VO 6×, wind 1×).

### 3.6 Assemble + master
- Per-shot clips → `ffmpeg -f concat -c copy` → `_body.mp4` (video-only).
- Final mux: `[body][vo+wind]` → `loudnorm=I=-14:TP=-1.5:LRA=11` + global `fade` in 0.3s / out 0.5s →
  `-c:v libx264 -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart`.
- Verify: ffprobe duration/streams, `loudnorm print_format=json` (lands ~−16, single-pass undershoot),
  `silencedetect=n=-35dB:d=0.4` (gap check).

---

## 4. Kling i2v layer (fal) — the motion engine

- **Endpoint:** `POST https://queue.fal.run/{MODEL}` with header `Authorization: Key $FAL_KEY`; poll
  `status_url` until `COMPLETED`; download `response.video.url`. JSON body: `{prompt, image_url (data-URI
  of the frame), duration: "5"}`. `image_url` = the package frame → Kling animates *from* it (keeps Bolt on-model).
- **Models (env `I2V_PROVIDER=fal`, `FAL_MODEL` default v2.1 standard):**
  - `fal-ai/kling-video/v2.1/standard/image-to-video` — $0.28 / 5s
  - `fal-ai/kling-video/v2.1/pro/image-to-video`
  - `fal-ai/kling-video/v3/pro/image-to-video` — $0.56 / 5s (2×), more natural motion (used for cloud i2v)
- **Motion-prompt template** (from `render_cloud_i2v.py`), two guard constants appended to every prompt:
  - `KEEP = "Keep the character EXACTLY as in the image — same design, colors, proportions; do not redesign or add limbs."`
  - `DOWN = "Strong continuous DOWNWARD motion, camera moves down with him; NO upward, NO reverse, NO looping-back motion."`
  - Per-beat example (shot 4): *"The cloud surface suddenly breaks apart and the small white-and-mint toy
    robot drops straight down through it fast, arms flung upward, alarmed and scared, cloud wisps bursting
    upward past him. {DOWN} {KEEP}"*
- **Hybrid selection:** hero beats (hook, false-landing, fall-through, tumbling, scale, fog payoff, loop)
  → Kling; transitional beats → Ken Burns. Parallelized with a 7-wide `ThreadPoolExecutor`.

---

## 5. Infra / models / APIs used

| Role | Model / tool | Where |
|---|---|---|
| Voiceover | OpenAI **tts-1-hd**, voice `onyx` | `ep.generate_tts` |
| Word timing | OpenAI **whisper-1** | `ep.transcribe_words` |
| i2v motion | **Kling** v2.1 std/pro, **v3 pro** via **fal** | direct `requests` to `queue.fal.run` |
| Still images | **gpt-image-2** (locations/cards) | `ep.generate_image` |
| Script/premise/extraction | **claude-opus-4-8** | `ep`, `board_pipeline` |
| Assembly | **ffmpeg** (zoompan, overlay, amix, loudnorm, concat, anoisesrc) | scratchpad scripts |
| Character ref | `reference/bolt_original_reference.jpeg`, `assets/mascot/bolt.png` | image-edit + Kling seed |

Keys in `.env`: `FAL_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` (Google TTS / Pexels NOT configured).

---

## 6. Version history (cloud short) — what each fixed / broke

| Ver | Script | Change | Result |
|---|---|---|---|
| v1 | `render_cloud.py` | per-line TTS placed at each shot's start | **Audio SKIPPED** — silent gaps between lines |
| v2 | `render_cloud_audio.py` | one continuous VO + wind bed | skip gone, but VO(16s) < video(20s) → **4s dead tail + desync** |
| v3/final | `render_cloud_v3.py` / `render_cloud_final.py` | whisper-align, video length = VO | **audio fixed** (synced, no tail); payoff reworked (fog + loop); shot-9 tightened 6.9s→4.2s |
| i2v | `render_cloud_i2v.py` | Kling **V3** on 7 hero beats | **motion looks bad** — see §7 |

(Oxygen lineage ran the same arc: `redo_oxygen`→`render_cleared_oxygen`→`render_oxygen_v3_pkg`→`rebuild_oxygen_v4`→`reexport_v4`.)

---

## 7. Why the current output is bad (honest failure modes)

1. **10 independent i2v clips ≠ one continuous action.** Each Kling clip invents its own motion from a
   static frame with no knowledge of the previous clip → motion **resets/jumps between shots** = the "skip",
   and it's the opposite of a linear fall.
2. **Trimming 5s Kling clips to ~1s beats** chops motion off mid-move → judder.
3. **Kling invents premise-breaking action.** Shot 3 → Bolt *walks on the cloud* (he's supposed to be unable
   to land). The model doesn't know the story's rules.
4. **Source frames fight the concept:** frame 03 is a *landing/standing* pose (contradicts "can't land");
   frames give Bolt **legs + white boots** (off-model — his real design is a hover-base).
5. **Motion direction is per-clip stochastic** — hook dives beautifully; fall-through "recedes" instead of
   plunging. No control.
6. **Loudness** single-pass loudnorm lands ~−16 (YouTube normalizes, so cosmetic).

**Over-engineering symptoms:** ~40 one-off scripts; a 6-layer assembly; a hybrid Ken-Burns/Kling motion
system; synthesized wind; a premise gate + hook dry-run + whisper align — lots of machinery, yet the core
deliverable (a continuous, on-model, urgent fall) is unreachable because the *approach* (independent i2v on
a fixed, off-model, premise-breaking storyboard) is wrong.

---

## 8. What a rebuild needs (the fix, not built yet)

- **Continuity over count:** a few LONG continuous shots (one ~10s "plummet + crash through cloud" as a
  single Kling generation), not 10 short chops. Or **chained i2v** (last frame of clip N = first frame of N+1).
- **On-model, always-falling source frames:** Bolt hover-base (no boots), never standing/landing, consistent
  downward line, fear/urgency in the body.
- **Premise-safe storyboard:** the false-landing beat must be a split-second *touch-and-break-through while
  still falling*, never a stand/walk.
- **Keep** the whisper-aligned audio path (§3.2) and captions (§3.4) — those work.
- **Strategic note:** this is the bespoke rabbit hole flagged in `BOLT_VISUAL_INFRA_PLAN.md`; Kling-from-stills
  can't do directed continuous action (that was Veo's job, dropped for slop). Decide if the action-movie
  treatment is worth bespoke effort vs. the repeatable pipeline.

---

## 9. File index (bespoke scratchpad scripts)

`render_cloud.py` (v1) · `render_cloud_audio.py` (v2) · `render_cloud_v3.py` / `render_cloud_final.py` (v3) ·
`render_cloud_i2v.py` (Kling V3 motion) · `kling_model_compare.py` (v2.1/v3 A/B) · `density_ab.py` (shot-density A/B) ·
`extract_narration.py` (beat-sheet → narration) · oxygen: `redo_oxygen.py`, `render_cleared_oxygen.py`,
`render_oxygen_v3_pkg.py`, `rebuild_oxygen_v4.py`, `reexport_v4.py` · state-board: `render_board_video.py`,
`gen_board_mockup.py` · single-card: `render_video.py`, `render_audio.py`, `gen_card.py`, `gen_locations.py`.
Reusable modules in project root: `board_pipeline.py`, `stateboard_pipeline.py` (long-form, isolated).
