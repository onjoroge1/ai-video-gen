"""Build Kling V3 prompts for simulation scenes.

WHY THE STRUCTURE IS FIXED
A simulation only works if the controls really are controlled. The viewer is holding one variable in
their head, so a shot where the camera drifts or the launcher changes silently destroys the
comparison the whole video rests on. So a prompt is assembled from four ordered parts, and three of
them are IDENTICAL in every scene:

  1. ACTION     -- the one thing that moves, per scene. The only part that varies.
  2. CAMERA     -- locked, from the spec's §6. Same words every time.
  3. CONTINUITY -- the locked experiment parameters, verbatim. Same words every time.
  4. LOOK       -- the house style. Same words every time.

The negative prompt carries the spec's per-scene Prohibited list plus the standing bans.

BUDGET
explainer_pipeline._animate_one prepends a ~200-char action directive and truncates the whole thing
at 900 characters, so the assembled prompt is kept near 640 to survive intact. Parts are ordered
most-important-first: if anything is ever cut, it is the style tail, not the action.
"""
from __future__ import annotations

# Standing negatives. The first group protects the comparison, the second the IP posture, the third
# is generator hygiene: gpt-image/Kling both invent lettering if not told otherwise.
STANDING_NEGATIVE = (
    "camera pan, camera tilt, camera zoom, camera shake, camera tracking, moving camera, "
    "changing camera angle, different launcher, second launcher, extra projectile, "
    "projectile changing size, projectile reversing direction, "
    "new characters, human beings, faces, crowds, "
    "text, letters, numbers, captions, watermark, logo, subtitles, "
    "cuts, scene change, montage, split screen, morphing, warping, flicker")


def build(scene, locked, style, extra_negative=""):
    """-> (prompt, negative). Deterministic: same scene in, same prompt out."""
    action = (scene.motion or "").strip().rstrip(".")
    # A scene with a deterministic hero subject (sim/drop.py) must stop the provider drawing its
    # own version of it -- otherwise the frame carries two: ours at the physics scale and the
    # model's cartoon one at icon scale. The prompt takes the exclusion; the negative reinforces.
    if getattr(scene, "hero", None):
        action += (". Background precipitation only, far behind the subject; no large foreground "
                   "raindrop, no close-up drop")
    camera = ("The camera is completely locked off and does not move, pan, tilt or zoom at any "
              "point; a single continuous shot with no cuts")
    cont = ", ".join(f"{k}: {v}" for k, v in locked.items())
    prompt = f"{action}. {camera}. Unchanged: {cont}. {style}".strip()
    if len(prompt) > 700:                 # never truncate mid-sentence; drop the style tail first
        prompt = f"{action}. {camera}. Unchanged: {cont}."[:700]
    neg = STANDING_NEGATIVE
    if getattr(scene, "hero", None):
        neg = "giant raindrop, large foreground drop, teardrop, close-up water drop, " + neg
    if scene.prohibited:
        neg = ", ".join(scene.prohibited) + ", " + neg
    if extra_negative:
        neg = extra_negative + ", " + neg
    return prompt[:700], neg[:600]


def report(sim):
    """Print every prompt for review BEFORE spending. Prompt quality is the whole ball game here."""
    rows = []
    for s in sim.scenes:
        if not s.animate:
            rows.append((s.id, "STILL", "", 0))
            continue
        p, n = build(s, sim.locked, sim.style)
        rows.append((s.id, p, n, len(p)))
    for sid, p, n, ln in rows:
        print(f"\n--- {sid}  ({ln} chars)")
        print(f"    {p}")
    return rows
