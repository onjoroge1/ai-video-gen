# Bolt Sequence Compiler — Rebuild Architecture

**Supersedes the bespoke one-off render scripts** (see `BESPOKE_VIDEO_FLOW.md`). Core principle:

> **A narrative beat ≠ a render clip. Optimize for ONE unmistakable causal journey, not the number of
> moving clips.** A 20s Short = ~10 narrative beats but only **3–4 continuous sequence blocks.**

The old system rendered 1 beat → 1 image → 1 independent i2v clip → motion resets, character mutation,
reversed direction, premise-breaking invented actions (Bolt walking on a cloud he's supposed to fall
through). The rebuild replaces the planning + motion layers with a **stateful sequence compiler**;
it **keeps** the parts that worked (continuous TTS, word-level alignment, caption rendering, ffmpeg
assembly, the production-package concept).

---

## 1. Pipeline (data flow)

```
Idea
 → Format selector            (not the universal descent playbook)
 → Fact-validation gate
 → Retention script compiler  → creative_plan.json  (IMMUTABLE once approved; hashed)
 → Beat graph                 (10 beats)
 → Continuity/state graph     (global invariants + per-sequence start/event/end)
 → Sequence block planner     (10 beats → 3–4 continuous blocks)
 → Image preflight            (reject/regenerate contaminated anchors)  → image_preflight_report.json
 → Low-cost animatic          (deterministic; GATE before any paid render)
 → Provider-routed generation (directed-action vs ambient vs deterministic compositing)
 → Best-of-N semantic critic  (frame-sampled VLM + optical-flow; reject hard violations)
 → Event-aligned assembly     (visual events on spoken verbs/nouns; not sentence=clip)
 → Retention + continuity QC   → reports
 → final.mp4 + captions.srt
```

Each arrow is a module with a typed input/output; nothing downstream may silently rewrite an approved
upstream artifact.

## 2. Modules → files

| Module | New/Reuse | File |
|---|---|---|
| Format selector | new | `bolt_seq/format.py` |
| Retention compiler (gates) | new | `bolt_seq/retention.py` |
| Continuity state engine | new | `bolt_seq/continuity.py` |
| Sequence block planner | new | `bolt_seq/planner.py` |
| Image preflight (VLM audit) | new | `bolt_seq/preflight.py` |
| Animatic builder (deterministic) | new | `bolt_seq/animatic.py` |
| Provider router + generators | new wrapper over existing | `bolt_seq/providers.py` |
| Best-of-N semantic critic | new | `bolt_seq/critic.py` |
| Assembly (event-aligned) | refactor of `render_cloud_final.py` | `bolt_seq/assemble.py` |
| QC + reports | new | `bolt_seq/qc.py` |
| Orchestrator | new | `bolt_seq/build.py` |
| **Reuse as-is** | | `ep.generate_tts`, `ep.transcribe_words`, `ep.generate_image`, ffmpeg recipes, package format |

VLM audits (preflight + critic) use **claude-opus-4-8 vision**. Directed-action generation routes to a
directed provider; ambient/cloud to **Kling** (fal); gauges/meters/cutaways to **deterministic
compositing** (PIL/ffmpeg — same tech as `board_pipeline.py`).

## 3. Schemas

### 3.1 `creative_plan.json` (immutable once approved)
```json
{ "format": "physical_experiment", "title": "...", "duration_target_s": 19,
  "narration": "full VO verbatim", "captions": [{"t_hint":"verb/noun","text":"3–6 words"}],
  "hook": "...", "first_payoff_s": 5.5, "second_open_loop": "...", "climax": "...",
  "ending_loop": "final action recreates frame 1", "facts": ["claim + source"],
  "script_hash": "sha256(...)" }
```
Renderer must never alter `narration`/`captions`/`facts`/`ending` without a NEW plan + re-audit.

### 3.2 Global continuity invariants + per-sequence state
```json
{ "global_invariants": {
    "bolt_model": "bolt_v1_hover_base",
    "forbidden_features": ["mouth","boots","legs","extra_limbs","costume_change"],
    "persistent_equipment": [], "screen_direction": "...", "<meter>": "monotonically_decreasing" },
  "sequence": { "start_state": {…}, "events": ["…"], "end_state": {…} } }
```
**Rule: `end_state` of block N is the `start_state` of block N+1** (chained).

### 3.3 `sequence_block.json`
```json
{ "id":"A", "t_start":0.0, "t_end":5.5, "beats":[1,2,3],
  "start_frame":"…", "event_chain":["…"], "end_frame_state":{…},
  "camera":"…", "motion_vector":"downward", "provider":"directed_action",
  "acceptance_tests":["bolt_on_model","vertical_flow_down","touch_then_breakthrough","no_stand"] }
```

## 4. Concrete plan — CLOUD (physical_experiment + reversal)

**Invariants:** `altitude ↓ monotonic · vertical_velocity always_down · bolt_never_stands · cloud_contact=touch_then_immediate_breakthrough · forbidden=[walking,hovering,upward,mouth,boots,legs,landing_pose]`.

| Block | t | Beats | Continuous action | end_state | Provider |
|---|---|---|---|---|---|
| **A** | 0–5.5 | 1–4 | Bolt streaks DOWN fast → cloud grows → brief touch → **immediately breaks through** (no stand) | falling, inside-cloud-entering | directed-action |
| **B** | 5.5–10 | 5–6 | Inside: droplets hit visor, visibility collapses, spins, **still visibly descending**, condition worsens | falling, wet/blind | directed-action (or ambient+overlay) |
| **C** | 10–15.5 | 7–9 | Wide reveal of cloud scale (Bolt tiny but tracked) → droplets shown **sparse across huge volume** = the causal answer, delivered visually | falling, understood | Kling ambient + **deterministic droplet-density overlay** |
| **D** | 15.5–19 | 10 | Exits cloud, another cloud appears below, keeps falling into a composition **matching frame 1** (loop, no fade) | falling → loop | directed-action |

## 5. Concrete plan — OXYGEN (goal_chase + countdown)

**Invariants:** `bubble_visible_after_shutdown=true · oxygen_reserve ↓ monotonic · screen_direction=toward_green_hub · hub_distance ↓ monotonic · hub_screen_size ↑ monotonic · no_reverse_travel · forbidden=[mouth,boots,bubble_flicker]`.

| Block | Beats | Continuous action | Provider |
|---|---|---|---|
| **1** | collapse preview + rewind | flash the near-miss collapse, then rewind to start (cold-open tension) | directed-action |
| **2** | shutdown + chase | valve closes, bubble ON, Bolt runs toward hub, **reserve meter ticks down**, hub grows | directed-action + deterministic meter overlay |
| **3** | failed theft + impairment | tries to steal a neighbour's air → fails → **movement destabilizes, steps shorten, eyes unfocus** | directed-action |
| **4** | final run + collapse | hub visibly close, reserve hits 0, **continuous collapse 3 steps short** (on-screen, not narrated) | directed-action |

No console-exposition dwell; no subscription-ad ending; the meter + impairment carry the "why."

## 6. Provider routing
- **directed physical action / transformation** → directed-action video provider (best-of-N + verify).
- **ambient** (clouds, mist, background drift) → Kling (fal).
- **gauges / meters / maps / cutaways / scale comparisons** → deterministic PIL/ffmpeg compositing.
- **Hero-action fallback = explicit FAILURE**, never a silent Ken-Burns substitute.
- Two modes: **reliable daily** (deterministic-first, 1–2 hero seqs, animatic-gated) · **cinematic flagship** (3–4 directed seqs, best-of-N, higher QC/budget).

## 7. Retention compiler gates (reject before render)
frame-1 visible action · premise+goal+stakes by 2s · first payoff by 5–6s · new open loop right after ·
**semantic** state-change every 1.5–2.5s (event/consequence/transformation/reveal/reversal/resource-loss/
progress — a cut alone does NOT count) · escalation across ≥2 consequence categories · climax stronger
than hook · no static result card · no in-video CTA · final action loops to frame 1.

## 8. Image preflight (per anchor, VLM) → regenerate on any hard fail
Is this exactly Bolt? · prohibited features (mouth/boots/legs)? · persistent equipment present? · pose
physically compatible with the story (no standing during a fall)? · continues the previous state? ·
implies a premise-contradicting event? A failed anchor is **regenerated**, not animated.

## 9. Best-of-N semantic critic (per hero sequence)
Render ≤3 candidates. Sample frames at **0/20/40/60/80/100%**. VLM checks: Bolt on-model every frame ·
persistent objects kept · **direction not reversed** · no object vanished · action matches narrated event ·
start-state + end-state compliance · prohibited actions · sufficient motion · narrated event actually
occurs. **Optical-flow** checks on direction-sensitive seqs (down-fall = downward flow; chase = one screen
direction; destination grows). **Reject hard violations — do NOT accept least-bad. Rerender or fail loudly.**

## 10. Animatic gate (before ANY paid hero render)
Full narration + approximate captions + deterministic camera motion over preflighted anchors → audit hook/
pacing/causality/escalation/climax/loop. Requires pass/approval before spending on generation.

## 11. Assembly / audio / captions
Event-aligned (visual events on spoken verbs, a sequence spans several narration lines) · **no global
fade for looping Shorts** · no unplanned silence >0.3s (mark intentional pauses) · **2-pass loudnorm ≈
−14 LUFS** · **stereo** AAC 192k · no transient at 0:00 · SFX only at causal moments · captions = 3–6 word
phrases with selective highlight, changing on emphasis, never obscuring Bolt/threat · final frame loop-compatible.

## 12. Final QC — fail LOUDLY when
hero action silently fell back to a still · Bolt changed model · equipment disappeared · movement reversed ·
a progress variable went backward · climax not visible · output ≠ approved script · final frame can't loop.
Emit: `contact_sheet.jpg`, `continuity_report.json`, `motion_report.json`, `semantic_compliance_report.json`,
`audio_report.json`, `retention_audit.md`, `degraded_or_failed_shots.json`, `final.mp4`, `captions.srt`.

## 13. Deprecate vs keep
**Deprecate** (fold into the compiler): `render_cloud.py`, `render_cloud_audio.py`, `render_cloud_v3.py`,
`render_cloud_final.py`, `render_cloud_i2v.py`, `render_oxygen_v3_pkg.py`, `rebuild_oxygen_v4.py`,
`reexport_v4.py`, `redo_oxygen.py`, `render_cleared_oxygen.py` — the ~10 one-off render scripts.
**Keep/reuse:** `ep.generate_tts`, `ep.transcribe_words`, `ep.generate_image`, `board_pipeline.py`
(deterministic-overlay tech), the package format, the caption/wind ffmpeg recipes.
**Do NOT touch:** the repeatable UI shorts pipeline (`explainer_pipeline.py`) — separate, working.

## 14. Phased implementation (cost-gated)
- **Phase 1 (this doc):** architecture + schemas + concrete cloud/oxygen plans + deprecation. ✅
- **Phase 2 (next, cheap):** implement `continuity.py`, `planner.py`, `preflight.py`, `animatic.py`;
  preflight → **regenerate clean anchors** (on-model, always-falling, no boots/mouth/stand); build the
  **cloud + oxygen deterministic animatics** (no paid video). ~$0.5–1 in image gen. **GATE.**
- **Phase 3 (after animatic approval):** `providers.py` routing + `critic.py` best-of-N + chained
  directed-action generation for hero sequences; event-aligned assembly; QC reports. Real render budget.
- **Phase 4:** wire into a UI tab OR keep as a CLI flagship path (decide later).

## 15. Automated tests (Phase 2+)
- schema validation (creative_plan/continuity/sequence) · continuity chaining (end_state N == start_state N+1) ·
  invariant monotonicity (meter/altitude never increases) · retention-gate unit tests (a bad script fails
  each gate) · preflight rejects a known-bad frame (boots/mouth/stand) · critic rejects a reversed-flow clip
  (optical-flow fixture) · assembly: no silence >0.3s, no global fade, loudness in band, final≈first frame diff.

---

**Most important line, per your instruction:** *do not optimize for the number of moving clips — optimize
for one unmistakable causal journey.* Three coherent, state-chained sequence blocks beat ten beautiful
clips that contradict each other.
