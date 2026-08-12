"""Generate a simulation's source plates, with continuity enforced by construction.

THE GAP THIS CLOSES
The first simulation shipped with a hand-made asset pack, so nothing in sim/ knew how to make one.
It also inherited that pack's defect: the recurring character was differently proportioned on
Mercury and absent on Jupiter, because ten images were generated independently with nothing holding
them together. The audit called that "identity drift"; the cause is simply that continuity was never
stated as a constraint.

So a plate prompt here is assembled, never free-written:

    CONTINUITY   identical every scene -- who the person is, what they wear, where they are, the
                 recurring object, the guide, the look. Verbatim repetition is the point.
    ACTION       the one thing different about this beat.
    PROHIBIT     the failure modes of the format (style resets, magic, anatomy, text).

A caller supplies only the ACTION. It cannot accidentally re-describe the protagonist, which is how
drift gets in.
"""
from __future__ import annotations
import os
import threading

PROHIBIT = ("No text, no letters, no numbers, no words, no logos, no watermark, no subtitles. "
            "No magic, no glowing energy, no lasers, no force fields, no fantasy effects. "
            "No extra people appearing, no duplicated person, no deformed hands, no malformed "
            "anatomy, no extra limbs. Do not change the art style between images. "
            "Photoreal cinematic frame, natural light, believable real-world environment.")


def _as_text(continuity):
    """`Simulation.locked` is a str in one topic and a dict in another -- the type fork the council
    identified. Accept both here rather than making every caller remember which topic it is in."""
    if isinstance(continuity, dict):
        return ". ".join(f"{k}: {v}" for k, v in continuity.items())
    return str(continuity or "")


def build_prompt(continuity, action, shot=""):
    """CONTINUITY (verbatim, every scene) + ACTION (this beat only) + PROHIBIT."""
    parts = [_as_text(continuity).strip(), action.strip()]
    if shot:
        parts.append(shot.strip())
    parts.append(PROHIBIT)
    return " ".join(p.rstrip(".") + "." for p in parts if p)


def generate(scenes, out_dir, continuity, size="1024x1536", cap_usd=3.0, price=0.042,
             workers=3, references=None, progress=print):
    """scenes: list of (stem, action, shot). Returns (manifest, failures). Never raises.

    `references` are character reference images. When given, generate_image switches to image-edit
    mode so the SAME person appears in every plate. Text pins wardrobe and setting well -- the coat,
    satchel and street held across seven plates -- but it cannot pin a face or body proportion, which
    is exactly how the previous pack ended up with a differently-proportioned character on one plate
    and none at all on another. A reference makes identity a pixel constraint instead of a promise.
    """
    import explainer_pipeline as epl

    os.makedirs(out_dir, exist_ok=True)
    manifest, failures, costs = {}, [], []
    spent = 0.0
    lock = threading.Lock()

    def one(stem, action, shot):
        nonlocal spent
        p = os.path.join(out_dir, f"{stem}.png")
        if os.path.exists(p) and os.path.getsize(p) > 10000:
            with lock:
                manifest[stem] = p
            progress(f"  {stem[:28]:28s} reuse")
            return
        with lock:
            if spent + price > cap_usd:
                failures.append((stem, f"cap ${cap_usd:.2f} reached"))
                progress(f"  {stem[:28]:28s} SKIP (cap)")
                return
            spent += price
        try:
            epl.generate_image(build_prompt(continuity, action, shot), p,
                               reference_paths=references, cost_sink=costs, size=size)
        except Exception as e:
            with lock:
                spent -= price
                failures.append((stem, f"{type(e).__name__}: {e}"))
            progress(f"  {stem[:28]:28s} FAIL {str(e)[:60]}")
            return
        with lock:
            manifest[stem] = p
        progress(f"  {stem[:28]:28s} ok")

    ts = [threading.Thread(target=one, args=s) for s in scenes]
    for i in range(0, len(ts), workers):
        b = ts[i:i + workers]
        for t in b: t.start()
        for t in b: t.join()
    progress(f"  plates {len(manifest)}/{len(scenes)}, ${sum(costs) or spent:.2f}")
    return manifest, failures
