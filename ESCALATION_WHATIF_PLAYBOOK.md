# Escalation "What-If" — Production Playbook (system prompt / bespoke build spec)

> ⚠️ SUPERSEDED (2026-07-21). The canonical creative spec is now `Bolt_High_Retention_Short_Production_Spec_v2_FULL.md`
> (general consequence-machine system) + `BOLT_SPEC_v2_ENGINEERING_APPENDIX.md` (our stack realities).
> This file is retained only for the DESCENT-format specifics — a format we've concluded is virality-capped
> (single location, one repeating question). Use v2 + appendix for new work.

**Purpose.** Load this to hand-produce ONE bespoke escalation-what-if Short to the standard of the ocean
flagship (`renders/drop_ocean_v5/`), without re-deriving the recipe. This is a spec for a *bespoke* build,
not an automated pipeline. Engine = `sim_drop_pipeline.run_drop_pipeline` + `explainer_pipeline` i2v.
Last validated build: "How Deep Can You Go Before the Ocean Crushes You?" (2026-07-21).

> Ground rule this format exists to satisfy: **the footage must dramatize the narration on the beat.**
> A state-change infographic ("meter drops") is a fail; a visible EVENT ("Bolt's visor cracks, he goes limp")
> is the bar. Bolt reacts, on-screen, every scene.

---

## 0. GATE 1 — DATA VALIDATION (run BEFORE any render; non-negotiable)

The flagship shipped with a factual error on its spine ("you die at 200 m" — the real scuba record is
~332 m). That is the single most likely way this channel gets burned. Every number is guilty until verified.

For EVERY numeric or factual claim in the script (narration AND on-screen overlays):
1. **Verify against a real source** (WebSearch / known reference). Write the source + value next to the claim.
2. **Recompute every multiplier** from the *defended* baseline and make the on-screen number equal the
   narrated one (flagship bug: "19×" and "55×" were computed off the wrong 200 m).
3. **Unit consistency** — pick metric or imperial and stay there (flagship mixed "1,000 ft" into a metric script).
4. **Ordering sanity** — claims must be physically ordered (flagship put "steel subs crush" *below* the
   Titanic; subs actually implode ~200–1,000 m, far shallower).
5. **Framing honesty** — don't state a dramatized ceiling as an absolute ("your body gives out at 200 m" →
   "past ~200 m you're beyond almost any human"; note the ~332 m record exists).
6. **YMYL check** — must not read as how-to for a dangerous activity. Framing depth/force as pain→death is
   fine (discourages); giving technique/dosage is not.
7. Only after all claims pass: proceed. Log the source table in the render dir as `facts.md`.

*(When this format is later pipeline-ized, this gate becomes an automated LLM + lookup + numeric-consistency
check inside a `generate_drop_script(topic)` step. For now it is a manual pass I run and show you.)*

---

## 1. Format DNA (what makes it retain)

- **Open-loop hook (0–~6 s):** cold-open on the strangest *visible* catastrophe (Bolt's suit imploding),
  withhold the payoff. Title question on screen. NOT a definition.
- **Escalation ladder:** one familiar subject + an increasing variable, each step a bigger visible
  consequence. Order strictly by intensity. `me → my body → my gear → the world → the extreme`.
- **Two-bar meter arc:** a persistent gauge that tells a story — e.g. `SURVIVAL 100→0%` then flips to
  `CRUSH FORCE 0→100%`. No dead/flat meter.
- **Death/turn beat:** the protagonist fails mid-way; camera continues without him (raises stakes, breaks
  the "he's fine" safety).
- **Scale payoff → cinematic VERDICT ending:** end on the gut-punch comparison over a MOVING shot with an
  open-loop kicker ("and we've barely seen it") — never a static results card.
- **Accelerating cadence + anticipation audio** (riser into the climax, boom on it).

## 2. Scene architecture (9 beats ≈ 30–40 s)

1. Cold catastrophe hook (meter 100%)  2–4. Escalation steps (meter falling, each a visible reaction)
5. Death/turn (protagonist gives out; fade)  6–7. Scale escalation without protagonist (meter = second bar)
8. Cinematic VERDICT reveal (comparison + kicker).  Keep <60 s; Shorts.

## 3. Technical recipe (the hard-won settings)

- **i2v = Veo for directed action.** `provider:"veo"` per scene (Kling/fal = ambient motion only, cannot
  direct action). `_i2v_clip` already snaps Veo duration to {4,6,8}s and drives `VEO_CHAIN` model fallback.
- **Best-of-N motion (CRITICAL, not yet in pipeline).** A 720p Veo clip can still come back near-static
  (motion 0.8). For every hero shot: render up to 3×, keep the highest frame-diff motion, require > ~10;
  see `scratchpad reroll_end.py motion()`. Verify MOTION, never a still frame.
- **Veo success check:** raw width 720 = real Veo; 1080 = Ken-Burns fallback (silent — treat as FAIL and
  re-roll or flag `degraded`).
- **Events** (`_event_vf`): map each narrated consequence to a footage filter (narcosis rgba-shift+roll,
  flatline fade, implosion flash, pressure_rings shake, lung_crush zoom). For a visible death, use a
  **fade-only** treatment (the built-in `flatline` vignette=PI/4 over-darkens and hides the character).
- **HUD overlay** (`_drop_overlay`): neon frame + two-bar meter + per-scene chip/cue + bloom. NOTE the
  telemetry strings ("SECTOR SOL-3", space chrome) are HARDCODED — override for non-space topics.
- **Verdict ending overlay** = the custom `build_end_overlay` recipe (soft top/bottom gradient scrims +
  panels behind big numbers over live footage; headline chip → up-to-3 labeled number panels → red marker
  line → cyan kicker). Not the pipeline's game-show "FINAL RESULTS" card.
- **Audio:** per-scene ambience bed + impact sfx (make impact per-scene optional), riser+boom anticipation,
  music bed. **Master to −14 LUFS** (`loudnorm=I=-14:TP=-1:LRA=11`, two-pass) and mux with **`-c:a` at
  192k stereo** (never let ffmpeg pick a low mono default). See `scratchpad/fix_loudness.py`.
- **Disclosure:** description carries the AI/synthetic line AND the uploader ticks YouTube Studio's
  **"Altered content"** toggle (text alone is not compliant).

## 4. Known traps (all bit us at least once)

- Standalone runs MUST `load_dotenv(dotenv_path=os.path.join(os.getcwd(),".env"), override=True)` and
  `os.chdir` to the project, or image/TTS silently fall back to blank frames (cost $0.000 = the tell).
- Background tasks lose cwd → `ModuleNotFoundError` unless you `os.chdir` + `sys.path.insert` in-script.
- Veo durations: ONLY 4/6/8 (5/7 → HTTP 400 → silent Ken-Burns).
- **Veo quota model is UNRESOLVED.** A repo comment (`explainer_pipeline.py:2266`, "probed") says Veo 3.x
  **share ONE project quota**; this session the model-fallback chain *empirically* helped (standard rendered
  after fast 429'd), but that may have been a rate-limit window. Treat `VEO_CHAIN` as "might help," not
  "3× capacity." The only *proven* cross-quota fallback is a different PROVIDER (Sora). Probe deliberately
  before promising scale.
- Economics: one Veo destruction Short (+ re-rolls) can exhaust a month's spend cap and a day's quota.
  This is a **flagship/occasional** format, not a daily-volume one.
- `subprocess.run(..., capture_output=True)` swallows ffmpeg errors — check returncodes on new steps.

## 5. Build workflow (bench pattern)

1. Pick topic → draft script (hook + ladder + verdict). 2. **GATE 1 data validation** (§0) → `facts.md`.
3. Adversarial retention audit (multi-lens) → apply fixes. 4. Render via `run_drop_pipeline` (or scripted
   checkpoint), Veo per scene, best-of-N motion. 5. Verify MOTION + content per scene (frames), meter arc,
   captions, sync. 6. **QC gate:** loudness −14, stereo 192k, 720p-real-Veo on every hero, no silent
   fallbacks, filename canonical. 7. Deliver mp4 + captions.srt + description.txt + facts.md.

## 6. Topic shortlist (catastrophe/escalation format)

Neutron-star moon; nuke in the Mariana Trench; falling into Jupiter; standing on each planet; the coldest→
hottest places you could survive; how fast until your body can't take it. Each: familiar subject + rising
variable + visible consequence + scale verdict.
