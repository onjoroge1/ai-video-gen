# Bolt Spec v2 — Engineering Appendix (our production stack)

Companion to `Bolt_High_Retention_Short_Production_Spec_v2_FULL.md`. That spec is the CREATIVE/retention
system (topic gate → hook → ladder → animatic → scorecards). This appendix is the ENGINEERING layer it
omits — the hard-won realities of actually rendering a Short on OUR stack. **Both are required.**
(Supersedes `ESCALATION_WHATIF_PLAYBOOK.md`, which was the narrower descent-format predecessor.)

---

## A. Where the spec's gates map to our tooling

| Spec gate | How we run it on this stack | Catches | Does NOT catch |
|---|---|---|---|
| Topic gate (§4) | Manual score before writing | Structurally viral-capped topics (ocean/Jupiter fail) | — |
| Hook variants (§6) | gpt-image 3 hook stills + score | Weak opening frame | Whether the hook *animates* well |
| **Animatic gate (§15, score ≥82)** | **gpt-image stills + temp TTS + burned captions + sfx cues → assemble → adversarial workflow score** | **weak STRUCTURE, cheaply, BEFORE Veo spend** | **MOTION quality (stills can't)** |
| Final render (score ≥88) | Full render + per-shot motion/res verify + silent test | execution defects | — |

**The animatic gate is our single highest-leverage adoption** — it's the fix for our repeated "spent a day's
Veo quota, then found the structure was 69/100" failure. Build the animatic from the SAME stills the final
render will start from (they double as Veo start-images), so it's near-zero extra cost.

**Critical caveat the spec misses:** the animatic proves STRUCTURE, not MOTION. A shot can pass the animatic
and Veo still return a static/wrong clip. So the final-render gate MUST still run per-shot motion+resolution
verification (below). Two gates, two different failure modes.

## B. Character consistency (the spec's "continuity anchor" §11 is not enough)

- Prompts alone DRIFT (probe: Bolt grew humanoid legs for an action pose, eyes went dark). `MASCOT_REF`
  locks face/palette/antenna but NOT body-plan/eye-state.
- **Mandatory continuity-anchor text in EVERY start-image prompt:** *"legless rounded pedestal base (NO
  legs/feet), two short stub arms, BOTH eyes glowing cyan, mint-tipped antenna, matte white + mint."* Plus
  `reference_paths=[MASCOT_REF]` (assets/mascot/bolt.png).
- Budget **~1-in-5 re-rolls** to cull legs/eyes-off/scale-ambiguity. Residual cosmetic drift (pedestal shape,
  hands) is acceptable — viewers don't read it as "changing."
- Props REUSED across shots drift badly (Jupiter capsule) — avoid reusing a prop, or accept drift. The
  consequence-machine format sidesteps this (different object each scene).

## C. Motion delivery (Veo is stochastic — verify, never assume)

- A 720p Veo clip can still be near-static (ocean ending motion 0.8). **Verify every hero shot by MOTION
  (frame-diff) AND resolution**, never a still: real Veo = **720x1280**; Ken-Burns fallback = **1080x1920**
  (silently ships as status:ok — treat 1080 as FAIL).
- **Best-of-N** for hero shots: render up to 3, keep highest frame-diff motion (require > ~12).
- Veo duration accepts **ONLY 4/6/8s** (5/7 → 400 → silent fallback); snap up to nearest valid ≥ needed.

## D. Cost mix (what makes a 12-25 shot consequence machine affordable)

- **~8 Veo shots ≈ a day's quota** — an all-Veo consequence machine is infeasible.
- **Kling (fal) for the BULK** — ambient reaction motion (cower, flinch, teeter, sniff) is enough for most
  everyday beats, and it's a separate/cheaper quota.
- **Veo only for HERO beats** — directed action/physics/destruction (predator lunge, stomp, transformation).
- Veo variants share ~one project quota but have separate model buckets; `VEO_CHAIN` = fast→standard→lite.

## E. Audio (bake the spec's §13 rules into the mix)

- narration TTS runs slow (~155 wpm) → speed ~1.2x (atempo) to hit the spec's pace.
- SFX side-chain ducked ~8 dB under narration; TP limiter −1.5 dBTP; soft (non-harsh) transients; NO end
  crack before a loop; 80 ms fade-in + loop fade.
- Master to −14 LUFS but **target loudnorm I=-13** (linear mode undershoots ~1–1.5 LU → lands ~-14).

## F. Standalone-run traps (every scratchpad build)

- `os.chdir(project)` + `sys.path.insert(0, project)` at top, or background tasks `ModuleNotFoundError`.
- `load_dotenv(dotenv_path=os.path.join(os.getcwd(),".env"), override=True)` or image/TTS silently fall back
  to blank frames (cost $0.000 = the tell).
- `subprocess.run(..., capture_output=True)` swallows ffmpeg errors — check returncodes on new steps.
- `~/Downloads` is TCC-blocked — user must move files into the project.

## G. Verification discipline (hard-won)

- Never mark my own homework on a greenlight — run the independent adversarial workflow (it caught the
  legs/eyes/passive defects my direct read missed; it also sometimes returns placeholder junk — spot-check it).
- Verify against the live artifact (frames/ffprobe), not memory. Report failures plainly.
