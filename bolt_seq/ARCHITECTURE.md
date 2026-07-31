# Bolt Sequence Compiler — topic-agnostic architecture (Generalization Validation phase)

This phase froze the cloud short as a regression fixture and rebuilt the compiler as a **reusable,
topic-agnostic high-retention Short engine**. The same core now drives three subjects that share no
physics — a robot **falling** through a cloud (vertical), a robot **racing** to refill oxygen
(horizontal goal-chase + countdown), and a **train** that can't stop (config-only). None of them
required topic-specific code in the core.

> Cloud is only the first validation fixture. The system is "generalized" only when cloud **and**
> oxygen render through the same modules and train **compiles** config-only. That bar is the subject
> of this document.

---

## 1. Module tree (generic core vs. per-topic data vs. frozen fixture)

```
bolt_seq/
├── continuity.py        GENERIC  declarative state engine — the 9-constraint vocabulary
├── scene_graph.py       GENERIC  multi-entity graph; per-channel tracks; parent attachment; eval
├── bindings.py          GENERIC  STATE→VISUAL resolver (state drives rendering, not just QC)
├── compiler.py          GENERIC  image gen, VLM preflight, PIL scene-graph compositor, audio, mux
├── orchestrator.py      GENERIC  the ONE build flow (render OR config-only plan) + abstraction audit
├── formats/             GENERIC  retention STRUCTURES (role palette + axis), not topics
│   └── __init__.py               physical_experiment · goal_chase · countdown · mystery_reversal
│                                 escalation · transformation · comparison · quiz
├── effects/             GENERIC  procedural visual adapters, registered by name
│   └── __init__.py               resource_meter · destination_growth · impact · cloud_rupture
│                                 fog_whiteout · visibility_loss · collapse · heat_distortion
│                                 speed_streaks · rising_bubbles · air_bubble
├── providers/           GENERIC  how an entity's pixels are made (routing)
│   └── __init__.py               deterministic_2d✓ · image_generator✓ · manual_asset✓
│                                 ambient_i2v(declared) · directed_video(DEFERRED) · layered_rig(declared)
├── topics/              DATA     pure config — one module per subject, ZERO rendering code
│   ├── cloud_landing.py          vertical fixture (reuses frozen assets → regression)
│   ├── oxygen_subscription.py    horizontal goal-chase + countdown (second fixture, renders)
│   └── train_stopping.py         config-only abstraction test (render=False)
├── fixtures/cloud/      FROZEN   the regression reference (inputs + reports + both animatics + assets)
├── tests/
│   ├── test_state.py             29 checks — legacy invariants + all 9 declarative constraints
│   └── test_regression.py        17 checks — cloud fixture stays valid through the current stack
├── build_cloud.py       LEGACY   Phase-2 cloud orchestrator (superseded by orchestrator.py; kept)
├── build_cloud_v2.py    LEGACY   Phase-2.1 cloud orchestrator (superseded; kept for provenance)
└── gen_poses.py         LEGACY   Phase-2.1 pose generator (superseded by providers.image_generator)
```

Legend: **GENERIC** = topic-agnostic core, reused unchanged by every topic. **DATA** = a topic is a
config module the core consumes. **FROZEN** = the cloud regression reference. **LEGACY** = the older
cloud-only path, retained (nothing depends on it).

---

## 2. The layers (corrected terminology)

Cloud and oxygen and train are **topics**, not formats. Four layers, each independent:

| Layer | What it is | Contract |
|---|---|---|
| **formats/** | retention STRUCTURES | a role palette + which roles are mandatory + a default motion axis |
| **topics/** | SUBJECTS (config) | names formats, declares state vars + constraints, an entity graph, bindings, blocks |
| **effects/** | procedural VISUALS | `fx(params,size)->RGBA`, driven by state-bound params; registered by name |
| **providers/** | pixel ROUTING | resolves an entity's asset (composite / generate / manual / …) — a config choice, not code |

A topic composes formats (`cloud = physical_experiment + mystery_reversal`,
`oxygen = goal_chase + countdown`, `train = physical_experiment + countdown`) and the orchestrator
checks its blocks against the composed role palette.

---

## 3. The one build flow (orchestrator.py) — no per-topic renderer

```
topic load → format select → plan compile (whisper/word timing) → STATE validate (continuity)
→ STRUCTURE validate (formats) → abstraction audit → asset resolve (providers) → preflight (VLM)
→ per-block: entity overrides → bindings(state→tracks) → overlays → render_scene_block (PIL)
→ concat → captions (whisper-aligned) → audio (ambient+SFX+VO, 2-pass loudnorm) → mux
→ continuity QC + perceptual QC (VLM) + reports
```

`render=False` (train) runs the identical path up to rendering, then emits `animatic_spec.json`
(per-block resolved tracks) instead of pixels — **no** model/ffmpeg I/O.

### State DRIVES rendering (the key upgrade)
`bindings.py` reads each block's `start_state`/`end_state` and writes the entities' animation tracks.
Examples actually used by the fixtures:

| state variable | → entity.channel | effect on screen |
|---|---|---|
| `altitude` (cloud) | `bolt.y`, `env.y` | robot falls; sky pans up |
| `oxygen_reserve` | `meter.fill`, `bubble.scale`, `vignette.intensity` | bar drains; bubble shrinks; view tunnels |
| `distance_to_hub` | `hub.scale`, `hub.x`, `tunnel.x`, `beacon.progress` | goal grows & slides in; world scrolls |
| `bolt_condition` | `bolt.pose` | pose swaps fresh→strained→failing→collapsed |
| `bubble_present` | `bubble.visible` | air reserve disappears at collapse |
| `brake_temp` (train) | `heat.intensity` | brake shimmer intensifies |

Because the visuals are *computed from* the validated state, a value that passes continuity is the
same value that renders — the two can't diverge.

---

## 4. Generic-vs-topic-specific code audit  *(explicit deliverable)*

**Every line of rendering/validation logic is generic.** A topic contributes **only data**. The
orchestrator's `_abstraction_audit()` proves this mechanically: it confirms every format, constraint
kind, provider, and effect a topic names is in the generic registries. All three topics return
`GENERIC (no topic-specific core code)`, `missing_or_unregistered: []`.

| Component | Generic? | Notes |
|---|---|---|
| continuity.py (9 constraints) | ✅ generic | no topic literals; dispatch over declared constraints |
| scene_graph.py (entities/tracks/attachment) | ✅ generic | channels + easing only; no cloud/oxygen terms |
| bindings.py (state→visual) | ✅ generic | linear remap + categorical map; pure data transforms |
| compiler.render_scene_block (PIL compositor) | ✅ generic | env-pan / sprite / procedural draw / ghosting — axis-free |
| compiler.build_audio | ✅ generic | ambient presets (wind/water/room) + SFX kinds |
| orchestrator.py | ✅ generic | one flow; render vs plan is a flag |
| formats/* | ✅ generic | retention structures; no subject knowledge |
| effects/* | ✅ generic | `fx(params,size)`; params come from state bindings |
| providers/* | ✅ generic | routing; asset spec lives on the entity (data) |
| topics/cloud_landing.py | 🟡 data only | cloud facts: plates, poses, altitude, "1,000,000 LBS" |
| topics/oxygen_subscription.py | 🟡 data only | oxygen facts: bubble, hub, reserve, pose prompts |
| topics/train_stopping.py | 🟡 data only | train facts: rails, brakes, momentum |

**No cloud-specific logic leaked into the core.** The old `compiler.render_block`
(downward-only, single-plate/single-pose, `assert y1f >= y0f`) is retained but **unused** by the
generic path; the generic renderer is `render_scene_block`.

---

## 5. The three fixtures

### Cloud (vertical) — REGRESSION, reuses frozen assets
Runs through the generic orchestrator using `fixtures/cloud/` assets (no regeneration). Reproduces the
frozen ceiling: continuity ✓, structure ✓, abstraction GENERIC, and `sticker_slide_appearance` ≈ the
frozen v2 value — i.e. the generalized stack renders cloud identically in behaviour.

### Oxygen (horizontal goal-chase + countdown) — SECOND FIXTURE, renders
9 synchronized entities (tunnel, streaks, bubbles, beacon, hub, bolt, attached air-bubble, vignette,
meter), all state-driven. **Rendered: 23.2s · stereo · −15.59 LUFS · 0 silence gaps · continuity ✓ ·
structure ✓ · abstraction GENERIC · ~$0.4 (assets+VLM, no paid video).** Continuity enforces: oxygen
only drains, distance only shrinks, hub only grows, condition only worsens, bubble persists until
collapse, collapse fires inside the distance threshold (≤0.15), no reversal — all pass.

Every binding is **visibly** working in the render: the meter drains green→red, the air bubble shrinks
then vanishes at collapse, the hub grows and slides in from the right, beacon rings expand, Bolt's pose
swaps swim→push→reach→collapse, the red collapse wash lands at the end. Topology is entirely unlike
cloud (horizontal chase, HUD meter, growing goal, parent-attached prop) yet uses the same modules.

**Perceptual (VLM):** `active_hook 5 · motion_realism 4 · urgency 6 · escalation 6 · comprehension 4 ·
sticker_slide_appearance 6 · loop 4`. This is the **same deterministic ceiling as cloud** (sticker≈6):
proof the ceiling is a property of flat-cutout deterministic-2D, **not** of the cloud topic. Comprehension
is lower than cloud (4 vs 7) — the scene is busier and the hub can read as a second character; a cheap
fix (distinct hub art / clearer captions), but out of scope for a validation fixture.

### Train (config-only) — ABSTRACTION TEST
A brand-new subject with new physics compiled with **zero** new core code:
`continuity ok · structure ok · abstraction GENERIC · missing []`. Expected states verified in the
plan: speed↓, distance↓, brake_temp↑, stopping_distance_used↑; `stopped` fires within
`distance ≤ 0.1`. Emits `animatic_spec.json` (state-driven tracks for rails/obstacle/heat/meters).

---

## 6. Remaining architecture gaps (honest)

1. **Deterministic visual ceiling stands.** The generic renderer is a better *sticker* — parent
   attachment, scale/pose animation, ghosting, tunnel scroll — but a single flat cutout still can't
   deform. `layered_rig` (segmented limbs / squash-stretch) is **declared, not built**; `directed_video`
   is **DEFERRED**. Crossing the perceptual bar needs one of those.
2. **Perceptual critic is pass/measure, not repair.** It scores the final; it doesn't yet drive
   automatic best-of-N regeneration of a weak block. (The hook to do so exists — it's a loop away.)
3. **Timing model is line-based.** Block duration = whisper span of its lines. Fine for these Shorts;
   a beat that needs to hold on a visual longer than its narration has no "dwell" control yet.
4. **Bindings are linear/categorical.** `remap` + `map` cover the fixtures; no easing *per binding*
   beyond the track curve, and no derived/compound bindings (e.g. velocity = d(distance)/dt).
5. **Effects are 2D procedural.** `heat_distortion` is a tint stub (no real refraction);
   `destination_growth`/meters are clean but simple. Good enough for animatics, not final polish.
6. **One character identity.** `POSE_IDENTITY`/topic `IDENT` are per-topic strings; there's no shared
   character library or cross-topic identity lock beyond the `immutable` constraint on the state var.

---

## 6.5 Phase 2.5 — Generalization Hardening (correctness gates + idea compiler)

The train animatic exposed that registry-compatibility ≠ semantic correctness (axis said "vertical" for a
horizontal scene; continuity reported `ok:true` with an empty `by_kind`). Phase 2.5 closed those gaps.

**New modules:** `semantics.py` (semantic audit), `facts.py` (fact gate), `retention.py` (retention gate +
per-block repair), `idea_compiler.py` (plain-language idea → topic), `run_idea.py` (E2E entry),
`providers/directed_video.py` (Phase-3 scaffold, disabled).

1. **Non-vacuous continuity** — `continuity.validate_all` now fails when a topic declares stateful
   behaviour but doesn't exercise it: empty trace, a declared state var absent from the trace, a
   constraint whose var/event never appears (`not_evaluated`), or state_vars with no constraints. Every
   constraint emits an evaluation ledger (`{kind,target,evaluated,points,result}`) — a pass is now
   provable, not implied by an empty violation list.
2. **Axis from the scene, not the format** — `scene_graph.infer_axis` derives the motion axis from which
   channels actually move (`horizontal/vertical/radial/depth/stationary/mixed`, plus per-entity axes). A
   topic may also declare `axis`. Train is now **horizontal**, oxygen **mixed**, gravity **stationary**.
3. **State/binding provenance** — `bindings.provenance` records, per block, `{source_state, constraint,
   binding, target, state_from, state_to, visual_from, visual_to}` → every visible change traces to
   validated state (`provenance_report.json`, and embedded per block in `animatic_spec.json`).
4. **Semantic audit** (`semantics.audit`) — the registry check is renamed `registry_compatible`; the new
   `semantically_valid` (hard) checks: required vars/entities exist, every changing state is visualised,
   no orphaned entity, no unused state, no spatial track animated without provenance, threshold events in
   the right block; (soft) axis matches scene, climax is the strongest transition. This caught a real
   oxygen defect (`hub_screen_size` increased but drove nothing) — fixed.
5. **Fact gate** (`facts.validate_and_resolve`) — extracts every claim, qualifies unsupported absolutes,
   recomputes derived numbers, checks units, re-validates after rewriting. **No pass → no render.** On the
   train it qualified "almost no grip"/"a kilometre later"; on gravity it caught a mass/weight unit error
   and the false "gray-out at 2g" (needs ~3–4g). Sources are labelled honestly — no fabricated citations.
6. **Retention gate + repair** (`retention.py`) — scores 11 axes → `PASS/REPAIRABLE/FAIL`; a FAIL is
   reported as **DEGRADED**, never "success". `REPAIRABLE` triggers a bounded per-block repair (raise
   subject prominence / declutter / caption / re-render motion) that re-renders **only the failed block**.
7. **Idea compiler** (`idea_compiler.compile`) — plain-language idea → research → facts → format select →
   state graph → entity graph → blocks → bindings → asset plan → topic config, using the orchestrator's
   OWN gates as the validation oracle in a compile→validate→repair loop. Emits `facts.md`, `sources.json`,
   `creative_plan.json`, `retention_plan.json`, `topic_config.json`, `state_graph.json`,
   `entity_graph.json`, `asset_plan.json`, `acceptance_gates.json`.
8. **Unseen gravity topic** — from only *"What if gravity doubled for ten seconds?"* the compiler produced
   a gate-valid topic in 3 repair attempts with **zero gravity-specific core code**: format `countdown`,
   axis `stationary`, poses brace→strain→grayout→relief, a gravity meter + countdown clock + crush effect,
   all state-driven. Rendered deterministically. *(numbers in `run_idea` output / build_report.)*
9. **directed_video scaffold** (`providers/directed_video.py`) — the Phase-3 interface: identity ref,
   required start/end frames, motion direction, prohibited events, best-of-N, sampled-frame semantic gate,
   optical-flow direction check, explicit failure. `ALLOW_PAID=False`; `generate`/`resolve` raise — **no
   silent deterministic fallback on hero blocks**. Deterministic stays the provider for meters/captions/
   UI/persistent state. Not enabled — awaiting sign-off.

## 6.6 Phase 3A — directed_video provider (hardened gate, validated offline, NOT enabled)

Paid directed motion for hero-action blocks is now *ready to authorize* but **not enabled**
(`ALLOW_PAID=False`). The provider (`providers/directed_video.py`) fixes every gate weakness that made
best-of-N unsafe, and the gate is validated offline before any spend.

**Gate hardening (9):** zero-delta direction → `stationary` (no phantom left/up/away); enforce
`start_end_match` + `start_frame_match`/`end_frame_match`/`entry_cut`/`exit_cut` vs deterministic
boundary frames; reject insufficient motion (min displacement + path length; a directional block cannot
accept optical-flow `none`); **VLM per-frame bounding-box tracking of the hero as the PRIMARY direction
signal** (centroid/scale trajectory, reversals, disappearances) with global optical flow only secondary;
≥8 frames + action-centered sampling; **scoped prohibitions** (global + block + entity + state-window,
not every topic `must_not_occur` applied blindly); **technical media gate** (aspect, duration, fps,
decode, resolution, black/frozen); **budget controls** (max_candidates, per-block/per-video USD caps,
timeout, retry ceiling, cached reuse, stop-after-first-pass, cost report). Mutation is caught by a pointed
"was the hero replaced?" question + a per-frame identity floor.

**Lifecycle:** prompt build → identity ref + start/end frame inputs → adapter submit/poll/download →
media normalize → gate → store accepted / rejection report / **explicit failure**. `FalKlingAdapter`
carries the request shape but refuses without `ALLOW_PAID` + `FAL_KEY`. **No silent deterministic
fallback on hero blocks.**

**Offline validation** (`eval_directed_gate.py` → `_directed_gate_eval/confusion_matrix.{json,md}`): 14
clips — 9 synthetic motion controls, 4 known-bad real animatics (cloud sticker, oxygen, gravity + a real
landscape Kling i2v), 1 positive control. Result: **13/13 known-bad rejected, 0 false positives, 0 false
negatives → FP rate 0.0 → SAFE_TO_ENABLE_PAID: True.** Notably the moving-background/static-subject clip
was rejected because PRIMARY entity tracking saw the hero wasn't moving (global optical flow alone would
have false-passed it). A first invalid mutation control (oxygen `hub.png` contained a Bolt-like figure)
was corrected to an unambiguous non-Bolt blob before certification.

**Caveat (honest):** FP=0 on this curated set is necessary, not sufficient — real generated candidates may
present novel failure modes. That is why the first pilot is capped (3 candidates, $5, stop-after-first-
pass), every candidate is gated, and a human reviews before wider use.

**Pilot (prepared, not run):** `pilot_oxygen_spec.py` → `_oxygen_pilot/{pilot_spec,spend_estimate}.json`
for the oxygen *final-sprint-and-collapse* hero block only (meters/hub/captions/effects/audio stay
deterministic). Spend estimate: v2.1-standard ~$0.28 first-pass / $0.84 worst-case; v3-pro ~$0.56 /
$1.68; hard cap $5. **Awaiting explicit authorization before the first paid API call.**

## 7. Exact commands

```bash
# state engine + declarative vocabulary (29 checks)
PYTHONPATH=$PWD python3 bolt_seq/tests/test_state.py

# cloud regression fixture (17 checks; no spend)
PYTHONPATH=$PWD python3 bolt_seq/tests/test_regression.py

# cloud through the generic orchestrator (regression render; reuses frozen assets, ~$0.01)
python3 -m bolt_seq.orchestrator cloud_landing

# oxygen — the second fixture (generates assets + renders; deterministic, no paid video)
python3 -m bolt_seq.orchestrator oxygen_subscription

# train — config-only planning (no assets, no render, no spend)
python3 -m bolt_seq.orchestrator train_stopping
#   or:  python3 -c "from bolt_seq import orchestrator as O; O.build('train_stopping')"

# Phase 2.5: compile a PLAIN-LANGUAGE idea → validated topic → deterministic animatic (no gravity code)
python3 -m bolt_seq.run_idea "What if gravity doubled for ten seconds?"            # compile + render
python3 -m bolt_seq.run_idea "What if gravity doubled for ten seconds?" --plan-only  # compile + gates only

# hardening + regression tests
PYTHONPATH=$PWD python3 bolt_seq/tests/test_state.py         # 34 checks (incl. non-vacuous continuity)
PYTHONPATH=$PWD python3 bolt_seq/tests/test_regression.py    # 38 checks (incl. Phase 2.5 + 3A gate logic)

# Phase 3A: offline directed_video gate validation (VLM+ffmpeg, NO video generation) → confusion matrix
python3 -m bolt_seq.eval_directed_gate      # → _directed_gate_eval/confusion_matrix.md (must be FP=0)
python3 -m bolt_seq.pilot_oxygen_spec       # → _oxygen_pilot/{pilot_spec,spend_estimate}.json (no spend)

# add a new topic: drop a module in topics/ and register it in topics/__init__._TOPICS,
#   OR just: python3 -m bolt_seq.run_idea "<your idea>"
```

Outputs land in `renders/bolt_seq/<topic>/`: `plan.json`, `continuity_report.json`,
`structure_report.json`, `abstraction_audit.json`, `entity_graph.json`, `motion_report.json`,
`state_trace.json`, and (render topics) `<topic>_animatic.mp4/.srt`, `audio_report.json`,
`asset_report.json`, `perceptual_quality_report.json`, `contact_sheet.jpg`, `build_report.md`;
(config-only) `animatic_spec.json`.
