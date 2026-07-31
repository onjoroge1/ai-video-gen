"""Character bible (GENERIC location; Bolt is the first character). Identity text, IMMUTABLE anatomy
invariants, and the approved clean reference image live here — NOT hard-coded in the provider. The
directed_video anatomy gate reads these from the spec, so a different character = a different bible,
not a code change. A topic attaches this via its directed-hero contract."""
from __future__ import annotations
import os

_OXY = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "renders", "bolt_seq", "oxygen_subscription")

BOLT = {
    "id": "bolt_v1",
    "identity": ("the mascot robot Bolt: a rounded matte-white body with mint-green accents, a glossy "
                 "black visor with exactly two glowing cyan eyes and NO mouth, a cyan chest panel, two "
                 "stubby rounded arms, a thin antenna with a cyan tip, and a SINGLE rounded hover-base "
                 "(no legs, no feet)"),
    # approved CLEAN reference (single hover-base, no legs) used for direct per-frame anatomy comparison
    "reference": os.path.normpath(os.path.join(_OXY, "bolt_swim.png")),
    "anatomy": {
        # required in every frame where the lower/upper body is visible (occlusion is allowed; replacement is not)
        "required": {"hover_base": 1, "antenna": 1, "visor": 1, "eyes": 2, "chest_panel": 1, "arms": 2},
        # must NEVER appear in any frame — presence in even one frame is a hard identity failure
        "prohibited": ["legs", "feet", "boots", "shoes", "separate lower limbs", "mouth",
                       "extra limbs", "altered pelvis", "duplicated Bolt"],
    },
}
