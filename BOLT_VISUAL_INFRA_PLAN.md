# Bolt Visual Infrastructure — Phased Plan

**Owner:** channel owner · **Status legend:** ✅ shipped · 🔵 next · ⚪ planned · 🧪 experiment/gated
**Last updated:** 2026-07-25

> The next retention leap does **not** come from a longer image prompt. It comes from giving the
> pipeline a **shot plan, persistent world state, explicit reveal logic, and an enforcement loop** —
> and from guaranteeing the video **delivers the promise its title makes.**

---

## 1. Why (the two root causes)

Two independent failures, from real data:

- **A — "Novel question, ordinary answer" (promise failure).** The *"Subscribe to Oxygen?"* short got
  **22% viewed**. Root cause was not image quality — it promised a paywalled-air scenario, then delivered a
  generic hypoxia list decorated with banking metaphors. The viewer was sold one video and shown another.
- **B — "Poster sequence, not a continuous event" (visual rhythm/continuity).** Scenes are treated as
  independent illustrations: one composition per ~3–5s narration beat, Bolt teleporting between disconnected
  settings, his problem resetting each scene, novelty too slow. Attractive frames, no compounding event.

The whole plan is: **fix A upstream (premise/payoff gate), fix B with a shot-planning + continuity + QA layer** —
in that order of leverage, because a beautiful shot plan for the *wrong* script still fails.

## 2. Retention thesis (what we're optimizing)

Coherent visual **events**, not prettier frames: new visual information every ~1–1.5s (Shorts), visible
**state changes**, escalation that **compounds** (failures don't reset), varied composition, and a payoff the
viewer can't already guess. Caption changes, zooms, and particles **do not count** as new information.

## 3. Guardrails (constraints that shape every phase)

These are non-negotiable and were the main corrections to the original proposal:

1. **Format-aware density.** The ~1.5s rule is a **Shorts rule**. Long-form stays ~5s/scene and only splits
   *hero beats* (hook / reversal / climax). Applying 1.5s to a 10-min video is a cost bomb (see §7).
2. **Budget-bounded novelty.** Density is a *target the budget can veto*, not an absolute. Every render has a
   hard per-video USD cap; when hit, the planner **degrades to fewer shots** rather than failing.
3. **Animatic gate before spend.** Render the shot plan as cheap placeholder frames + captions + real timing
   **first**; gate all paid generation (images, i2v, vision-QA) behind approval of that animatic.
4. **Prove before build.** The density hypothesis (§Phase 1) is validated on real uploads **before** the
   expensive shot-planning system is built. If density doesn't lift retention, we don't build the machine.
5. **Resumability / determinism preserved.** Renders checkpoint and resume; the shot-planner + QA-regeneration
   layer must stay resume-stable, or a failed render restarts from zero.
6. **No synthetic data.** State boards, environment state, and any on-screen "fact" derive from the actual
   script/narration; unknowns are shown as unknown, never invented to fill a diagram.
7. **IP boundaries.** No real people/actor likenesses, no reproduction of copyrighted character/brand designs,
   no real footage; original art only. (See the State Board work for the compliant pattern.)

---

## 4. Phases

### Phase 0 — Foundations ✅ (shipped 2026-07-25)
- ✅ **Format-aware shot density.** `scene_count_for`: social plans toward the still tempo (`SECS_PER_STILL=2.5`);
  long-form unchanged (~5s). `_select_i2v_indices` now biases motion onto the **longest** beats, so stills (short
  beats) stay snappy and animated clips hold longer — the stills-vs-motion split with no timing hacks.
- ✅ **Gate −1 premise contract (social).** `build_premise_contract` → `_premise_block` (into `generate_script`)
  → `grade_premise` veto riding the `generate_graded_short` regen loop, all **before** image/TTS/Veo spend.
  Flags: `answers_generic_question` (the #1 killer), `hook_repeats_question`, `consequence_after_2s`,
  `no_failed_workaround`, `payoff_obvious_or_weak`, `metaphor_over_budget`, `over_length`, `empty_phrases`.
  Validated on the oxygen case: bad **16** / mismatched **40** / aligned **85** — discriminates, ~$0.02/short.
- ✅ **Density A/B assets** built (`moon_control` 8 shots vs `moon_treatment` 16 shots, same script/VO).

**Done-criteria:** all shipped and import-verified. ✔

### Phase 1 — Validate the density hypothesis + cheap opening gate 🧪🔵
The gate on everything below. Cheap, fast, high-information.
- 🧪 **Density A/B upload.** Post `moon_control` and `moon_treatment` (same title + thumbnail, spaced a day+
  apart). Read **avg % viewed + the first 3–5s curve**. Success bar: treatment wins **enough to justify ~2×
  image spend** on Shorts. Confirm on 2–3 more topics before committing Phase 2 (n=1 is directional only).
- 🔵 **3-second muted hook dry-run.** Render only the opening (~3s) before full generation; auto-check (or
  human-glance) that premise + threat + visible action read at phone size, muted. If not, stop the job.
  Render-side companion to Gate −1.

**Done-criteria:** a real retention delta (or null) recorded; dry-run aborts a bad opening in a test run.

### Phase 2 — The shot-planning core (Shorts first) ⚪
The retention-critical 80%. **Gated on Phase 1 showing a lift.** A separate **visual-director** LLM pass runs
*after* the script (don't make one call solve narration + rhythm + continuity + prompting).
- Scene → **`shots[]`** with per-shot: `visual_role`, `asset_mode` (image / i2v_open), `duration_ms`,
  `state_in` / `state_delta` / `state_out`, `reveal_level` (hidden/tease/partial/full_payoff),
  `focal_hierarchy` + `bolt_screen_occupancy_pct`, `visual_mode` (grounded_real_world / physically_plausible_macro /
  cross_section / scale_comparison / literal_surreal_consequence — **conditional grounded-realism** fixes the
  current bug that forces micro/astro topics into a literal camera).
- **Prompt compiler v2:** lead with the communication job (`INSTANT READ`) + the real `surprise_focus` (not the
  generic "the most surprising element"); then proof, state change, focal hierarchy, continuity, camera, Bolt,
  art direction, safe-area, excludes, final priority.
- **Cheap deterministic QA + targeted regen** (every image): OCR unwanted text, subject over caption box,
  wrong aspect/res, near-duplicate adjacency, Bolt missing when required, reference not applied → **named
  failure → targeted prompt change** (never a blind retry).
- **Budget cap + animatic gate** wired here (guardrails 2–3).

**Done-criteria:** a Shorts render driven by `shots[]` at ~1.5s density, within a budget cap, with the animatic
gate and deterministic QA active; hero-beat state changes visibly compound.

### Phase 3 — Environment system (continuity) ⚪
Kills the disconnected-poster look. **`environment_type` (category) vs `environment_id` (an actual place)**, with
**environment packs** generated only when a place appears in ≥3 shots, a continuing experiment spans scenes, or
it's a recurring branded location (Bolt's lab):
- Pack = wide clean plate + three-quarter medium + close/detail + `immutable_features` + `mutable_state`.
- **Reference resolver (anti-drift):** reuse the previous image only for same-camera / direct before-after /
  exact-placement shots; otherwise return to the immutable pack + current state (prevents progressive mutation of
  Bolt/props/architecture and camera lock-in).

**Done-criteria:** a multi-scene short set in one evolving place reads as one location with a changing state.

### Phase 4 — Purposeful motion + identity/scale ⚪
- **i2v start/end contracts:** `start_state`, `primary_motion`, `camera_motion`, `end_state`, `motion_budget`,
  `reveal_level` — kills generic swaying / camera-motion soup; an i2v open frame shows pre-action tension, not the
  completed payoff.
- **Multi-angle Bolt + recurring-prop references** for identity, interaction and scale continuity.
- **Vision-QA on hero shots only** (hook, reversals, climax, i2v opens): claim readable without captions?
  intended action visible? reveals too much/little? focal subject dominant? continuity matches state? climax
  visually strongest? → the enforcement table (regenerate with a reason, not blind).

**Done-criteria:** i2v clips depict the intended transformation; hero shots pass vision-QA; Bolt stays on-model.

### Phase 5 — Retention learning loop ⚪
Log `shot_duration`, `shot_scale`, `asset_mode`, Bolt presence, environment continuity, `reveal_level`, QA
failures, regeneration count **against retention timecodes** (via the Metrics tab). Turns the experiments into a
system that learns which visual decisions actually work, instead of a growing pile of prompt rules.

**Done-criteria:** a dashboard/query linking visual metadata to per-video retention curves.

### Phase 6 — UI controls ⚪
Surface the machine: shot timeline per scene · Video Look Bible card (lock/unlock) · environment cards + packs ·
environment-state timeline · reference mode (new location / same place-new angle / continuous edit) · reveal
control · focal-hierarchy editor · Bolt size/position/action/gaze · QA badge with exact failure + "repair" ·
"regenerate shot preserving env/Bolt/prop" toggles · side-by-side muted animatic preview.

---

## 5. Reconciled priority (proposal ranking → phases)

| Original priority | Item | Lands in |
|---|---|---|
| (new #1) | Prove density on a hand-cut short | Phase 1 |
| P0 | Scenes → timed `shots[]` | Phase 2 |
| P0 | Visual proof, focal hierarchy, reveal state | Phase 2 |
| P0 | Per-video look bible + semantic shot rhythm | Phase 2 (compiler v2) |
| P0 | QA triggers targeted regeneration | Phase 2 (cheap) / Phase 4 (vision) |
| P0 (shipped) | Premise & payoff gate | **Phase 0 ✅** |
| P1 | Environment manifests / packs / state evolution | Phase 3 |
| P1 | Multi-angle Bolt + recurring-prop refs | Phase 4 |
| P1 | i2v start/end contracts | Phase 4 |
| P2 | Visual metadata ↔ retention analytics | Phase 5 |

## 6. What the proposal got right / what changed

**Right (adopted):** shots[] as the real unlock; a separate visual director; `state_in/delta/out`;
reveal-control; focal-hierarchy; conditional grounded-realism (`visual_mode`); QA with named failures;
`environment_id` vs `environment_type`; multi-view packs over one canonical plate; anti-drift reference rule.
**Changed (guardrails):** density is Shorts-only + budget-capped; the animatic is promoted from a UI nicety to
the **cost gate**; the density hypothesis must be **proven before** the system is built; resumability/determinism
must be preserved; env packs improve cohesion-per-dollar but **do not** cut image count.

## 7. Cost model (why format-aware + caps are mandatory)

At ~$0.045/image (gpt-image-2):

| | Now | With density |
|---|---|---|
| Short (~50s) | ~20 img ≈ $1 | ~40 shots ≈ $1.80 img + i2v + QA/regen ≈ **$2.50–3.50** |
| Long-form (10min) @ 1.5s | — | ~400 shots ≈ **$18 img alone**, $25–40 all-in — **not viable** |

→ Shorts go dense (with a per-video cap); long-form keeps ~5s and splits only hero beats. The animatic gate
prevents paying for a plan that isn't good yet.

## 8. Open decisions
- Density success threshold (what % lift justifies ~2× Shorts image spend?).
- Shots per beat cap for Shorts (2 vs 3) and hero-beat count for long-form.
- Vision-QA model/budget (which shots, how many verifier calls).
- Where `shots[]` lives in the checkpoint schema (resume-stability).

## 9. Appendix — data schemas (concrete)

**PremiseContract** (✅ shipped): `viewer_promise, world_rule, central_question, concrete_mechanism,
bolt_objective, failed_workaround, novel_payoff, first_consequence_deadline_ms, metaphor_budget`.

**Shot** (Phase 2):
```json
{ "start_ms": 6200, "duration_ms": 1500, "visual_role": "threshold", "asset_mode": "i2v_open",
  "visual_mode": "cross_section", "reveal_level": "partial", "surprise_focus": "…",
  "state_in": {…}, "state_delta": {…}, "state_out": {…},
  "focal_hierarchy": ["proof","consequence","bolt"], "bolt_screen_occupancy_pct": 15 }
```

**EnvironmentPack** (Phase 3): `environment_type, environment_id, plates{wide,medium,detail},
immutable_features[], mutable_state{}`.

**i2v contract** (Phase 4): `start_state, primary_motion, camera_motion, end_state, motion_budget, reveal_level`.
