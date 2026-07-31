# Visual Pipeline v2 — Shot Planning, Persistent World State & Enforcement

**Status:** proposal / phased. **Owner decisions locked:** shot density is *format-aware* (Shorts dense, long-form ~5s); the ~1.5s "new info" rule is a **Shorts-only** rule.

## Thesis

Our retention wins came from a *coherent sequence of visual events* — new information every ~1–1.5s, visible state changes, escalating consequences, varied composition — not from prettier individual frames. `_full_prompt` is already good at single images; the ceiling is that **infra treats every scene as one independent illustration.** The leap is a **shot-planning layer with persistent world state, explicit reveal logic, and an enforcement loop** — not a longer prompt.

The pivot: **scene → `shots[]`.** A 5s narration beat currently holds one composition for 5s (the pacing problem). A beat should instead carry multiple timed shots, each delivering *new* visual information.

## Gate −1 — Premise & Payoff Contract (MOST UPSTREAM; highest ROI; cheapest to build)

**Evidence:** the "oxygen subscription" Short got **22% viewed**. Post-mortem: not an image problem — a **promise failure**. It promised "subscribe to oxygen" and delivered a conventional hypoxia explainer decorated with banking metaphors. The first frame ("BRAIN DIES IN SECONDS" + brain + battery + tank) sold generic hypoxia; the premise (a lapsed oxygen *subscription*) was absent from the frame that decides the swipe. *"We had a novel question but answered a more ordinary question."*

**A tighter/faster wrong video still fails.** So a premise gate sits UPSTREAM of both the density work and the shot-planner, and it's the cheapest high-impact fix (prompt/gate work in days, not a rendering subsystem in weeks). **Build this before v2 visuals.**

**`PremiseContract`** — authored/derived before script generation, then every scene scored against it:
```json
{ "viewer_promise":"what physically happens when an oxygen subscription expires",
  "world_rule":"humans breathe through company-controlled oxygen regulators",
  "central_question":"what fails first after the regulator shuts off?",
  "concrete_mechanism":"payment failure closes Bolt's oxygen valve",
  "bolt_objective":"restore oxygen before losing consciousness",
  "failed_workaround":"Bolt tries to stockpile breaths",
  "novel_payoff":"the body has no meaningful internal prepaid oxygen reserve",
  "first_consequence_deadline_ms":2000, "metaphor_budget":2 }
```
The metaphor must become the **literal, visible world-rule** (the valve declines a payment and shuts), not decoration the viewer has to translate back to physiology.

**Gates (implement the semantic ones as an LLM judge, not regex):**
- **Premise-fidelity judge (the killer test):** *"could this script be retitled 'what happens when you stop breathing?' with no major change? → reject."* Highest-value single gate. Per-scene: "how does this advance the exact scenario?" — reject scenes that don't.
- **Payoff-obviousness judge:** could a viewer guess the payoff from the title? Is the climax visually + conceptually stronger than the hook? If not → regenerate the ending.
- **First-consequence timing:** one hook question only (no re-asking); question complete by ~2s; a visible consequence begins by ~2s.
- **Structure:** require ≥1 *failed physical workaround* (try → fail → try harder → reveal) so it escalates instead of listing.
- **Cheap guardrails:** ≤~100 words / ≤~42s; ≤2 metaphor callbacks; ban empty phrases ("here's the part that stays with you").
- **3-second hook dry-run:** render ONLY the first ~3s (or an animatic of it), review muted at phone size — is the premise + threat + visual action instantly readable, and is the world-rule *visible in frame*? If not, kill the job before full generation.

**Note — these gates already have weak cousins that this slipped past:** the hook grader, the Viewer Question Contract, `generate_graded_short` conceit-enforcement. They test hook *mechanics*, not premise fidelity / payoff-obviousness, and they *warn* rather than *veto*. Fix = add the two judges + make them regenerate.

**Anti-blandness / cost discipline:** the contract must make premises *sharper and more literal*, not fewer or safer. Every gate keeps a best-effort escape hatch (ship + `degraded` flag) so a good-but-imperfect script isn't regenerated forever.

## Gate 0 — Prove the density hypothesis before building the machine (IN PROGRESS)

Everything below is justified *only if* "new visual info ~every 1.5s lifts Shorts retention" holds. **Do not build the system until this is confirmed.**

- **Experiment (`scratchpad/density_ab.py`):** one authored Shorts script + one voiceover, two cuts differing ONLY in shot density — CONTROL (1 still/beat, ~3s) vs TREATMENT (2 distinct shots/beat, ~1.5s; shot B a new micro-moment, not a zoom). Stills-only (i2v off) to isolate the lever.
- **Read:** upload both (same title/thumb), compare avg-% viewed + the early-retention curve.
- **Decision:** lift → build v2 with conviction; flat/negative → stop, we saved weeks.

## Non-negotiable constraints (things the proposal under-weighted)

1. **Cost is format-gated.** At ~$0.045/image: a 50s Short @1.25s/shot ≈ 40 shots ≈ $2.50–3.50 (fine if retention pays). A 10-min long-form @1.5s ≈ 400 shots ≈ **$25–40/video (not viable).** Therefore:
   - Shorts: dense shots (target ~1.25–1.5s of *new info*).
   - Long-form: keep ~5s scenes; only split **hero beats** (hook / reversal / climax) into shots.
   - **Hard per-video budget cap** with graceful degradation: when the cap is hit, the planner drops shot count rather than failing.
2. **Novelty isn't free.** Caption swaps, zooms, particles do NOT count as new info (per spec). Real novelty = real new images = real cost. Env packs improve cohesion-per-dollar but do **not** cut image count (an edit-mode call costs the same). The density target must be budget-bounded, never absolute.
3. **Animatic is the cost gate, not a UI nicety.** Render the shot plan as cheap placeholder frames + captions + real timing FIRST; gate all paid generation (images, i2v, vision-QA) behind approval of that animatic (by the operator or a grader). This validates rhythm/continuity/reveal at ~zero cost and enforces the "no unchanged composition >1.5s" and "compounding not resetting" rules *on the plan, before spend*.
4. **Resumability + latency.** Renders checkpoint and resume; the shot planner + QA-regeneration layer must stay **resume-stable** (a failed $3 short can't restart from zero) and must generate shots in **parallel** (as images already do).

## Revised pipeline

```
Script + retention map
  → Visual Director (separate LLM call: scenes → shots[])
  → Look Bible + Continuity Registry (per-video art seed; environment_id state)
  → Reference Resolver (Bolt + env pack + prior-frame, conditionally)
  → Animatic (cheap placeholder cut)  ── GATE (approve before paid gen) ──
  → Prompt Compiler + Generation (budget-capped, parallel)
  → Visual QA + targeted regeneration (named failure → targeted change, not blind retry)
  → i2v + captions + final render
  → Retention telemetry (visual metadata ↔ retention timecodes)
```

Key architectural call: a **separate "Visual Director" pass** after the script exists. Don't make one call solve narration + shot rhythm + continuity + camera + prompting — different jobs.

## Data model (target)

**Scene → shots[]** (timed):
```json
{ "scene_id":"s03","narration_start_ms":4800,"narration_end_ms":9200,
  "shots":[ {"start_ms":4800,"duration_ms":1400,"visual_role":"mechanism","asset_mode":"image"},
            {"start_ms":6200,"duration_ms":1500,"visual_role":"threshold","asset_mode":"i2v_open"},
            {"start_ms":7700,"duration_ms":1500,"visual_role":"mini_payoff","asset_mode":"image"} ] }
```
Rule: deliver new info every ~1–1.5s (Shorts); no unchanged composition > ~1.5s; a longer i2v shot is OK **iff** something meaningfully changes inside it.

**Per-shot state (makes escalation verifiable — compounding, not resetting):**
```json
{ "state_in":{...}, "state_delta":{...}, "state_out":{...},
  "bolt":{"goal":"stop the train","state_in":"confident","action":"pulling the brake with both hands",
          "state_out":"alarmed — barely slows","gaze_target":"track ahead"} }
```

**Focal hierarchy + reveal control (fix two real defects: Bolt vs subject; surprise-first spoiling the payoff):**
```json
{ "focal_hierarchy":["steel wheel on rail","sparks","Bolt reacting behind"],
  "bolt_screen_occupancy_pct":15, "visual_priority":"proof_primary",
  "reveal_level":"tease", "surprise_focus":"the huge remaining stopping distance", "open_loop_id":"why_train_keeps_moving" }
```
`visual_priority` ∈ {proof_primary, bolt_primary, environment_primary, consequence_primary}. `reveal_level` ∈ {hidden, tease, partial, full_payoff}.

**Conditional realism (real bug fix):** our GROUNDED REALISM rule is currently unconditional — wrong for microscopic/astronomical/internal-body topics. Add `visual_mode` ∈ {grounded_real_world, physically_plausible_macro, cross_section, scale_comparison, literal_surreal_consequence}.

**Environment: type vs id + pack.** `environment_type` = category (kitchen); `environment_id` = an actual place (kitchen_A) with `immutable_features[]` + `mutable_state{}`. Build an **environment_pack** (wide plate / three-quarter medium / close detail / immutable landmarks / mutable state) **only** when the env appears in ≥3 shots, a physical experiment continues across scenes, or it's a recurring branded location (Bolt's lab). One-offs skip it.

**Reference discipline (avoid drift):** do NOT auto-pass the previous frame into every scene (it mutates Bolt/props/architecture and locks the camera). Use prior-frame reference ONLY for: same camera position, direct before/after transformation, or exact object placement. New angle in the same place → return to the env pack + current state. Reference mode ∈ {new_location, same_place_new_angle, continuous_edit}.

## Prompt compiler v2

Lead with the *communication job*, not environment/style:
```
FORMAT: vertical cinematic Short frame.
INSTANT READ: <the one thing the viewer must grasp instantly>
PRIMARY VISUAL PROOF: <surface_focus / the real proof>
STATE CHANGE: <state_delta in words>
FOCAL HIERARCHY: <ordered>   BOLT: <occupancy%, action, gaze>
CONTINUITY: <environment_id immutable features + current state>
CAMERA: <shot scale + angle + composition>
ART DIRECTION: <compact look-bible fields>
MOTION READINESS: <for i2v: keep subject fully in frame with room to move>
SAFE AREA: keep the real caption bounding box quiet.
EXCLUDE: illegible text/labels/UI/watermark, empty centered comp, unrelated glow.
FINAL PRIORITY: <one sentence — the frame's job>
```
Two changes vs today: replace "the most surprising element" with the actual `surprise_focus`; make grounded-realism conditional on `visual_mode`.

**i2v start/end contract** (kills generic swaying / camera-soup):
```json
{ "asset_mode":"i2v_open","start_state":"wheel spinning, brake just touching",
  "primary_motion":"wheel keeps sliding, sparks rapidly increase","camera_motion":"low tracking beside the wheel",
  "end_state":"wheel glowing hot, train still moving","motion_budget":"1 subject action + 1 camera move","reveal_level":"partial" }
```

## QA — two layers, and it must ACT

**Cheap deterministic (every image):** OCR finds text/numbers; subject overlaps the real caption box; wrong aspect/resolution; near-duplicate adjacent frames; Bolt missing when required; reference assets not applied.
**Vision QA (hook, reversals, climax, i2v opens only — cost-scoped):** claim readable without captions? intended action visible? reveals too much/little? focal subject dominant? continuity matches env state? i2v motion unobstructed? climax visually strongest?

**Enforcement (named failure → targeted change, never blind retry):**
| Result | Action |
|---|---|
| Repetition expected but env changed | Regenerate from env pack |
| Novelty expected but adjacent too similar | Re-plan camera/comp, regenerate |
| Visual proof missing | Rewrite action/proof block |
| Bolt blocks subject | Reduce occupancy / reposition |
| Hook unreadable at phone size | Simplify to fewer focal elements |
| Text detected | Targeted regen with OCR location |
| i2v frame shows completed payoff | Return to pre-action state |

## Phases

**P0 — Slice 1 (Shorts only; the retention-critical 80%).** Ship one thin vertical:
Visual Director → `shots[]` with `state_delta` + `reveal_level` + `focal_hierarchy` + `visual_mode`; **prompt compiler v2** (INSTANT READ + real surprise_focus + conditional realism); **cheap deterministic QA + targeted regen**; **animatic gate**; **budget cap + resume-stable**. No env packs, no vision-QA, no telemetry, no full UI yet.
*Also already shipped:* format-aware cadence (`SECS_PER_STILL=2.5`/`SECS_PER_MOTION=3.5`) + i2v selection biased to the longest beats.

**P1 — Cohesion + purposeful motion.** Environment manifests / reference packs / state evolution; multi-angle Bolt + recurring-prop references; i2v start/end contracts; vision-QA on hero shots.

**P2 — Learning loop.** Connect visual metadata (shot_duration, shot_scale, asset_mode, Bolt presence, env continuity, reveal_level, QA failures, regen count) to retention timecodes in the Metrics tab — so the system learns which visual decisions actually work, instead of accreting prompt rules.

## UI additions (P1+)
Shot timeline per scene · Look Bible card (lock/unlock) · Environment cards + reference packs · Environment state timeline · Reference mode selector · Reveal control · Focal-hierarchy editor · Bolt size/position/action/gaze · QA badge with failure + one-click repair · "regenerate shot preserving env/Bolt/prop" toggles · side-by-side muted animatic preview.

## Sequencing discipline
Build P0 as one shippable slice, Shorts-only, validate retention on real uploads, *then* generalize. Guard against the classic stalled grand-rewrite: every phase must ship and be measurable on its own.
