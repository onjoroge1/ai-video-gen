"""fal.ai image-to-video model registry, shared by the explainer pipeline and the directed-motion
toolchain.

One table names every fal endpoint the pipeline may call, which request *family* it speaks, what a
second of it costs, and what it can condition on. Both callers used to carry Kling's field names
inline (``image_url`` + ``duration: "5"``), so pointing ``FAL_MODEL`` at a Seedance or Wan endpoint
would have sent a Kling body to a model that ignores half of it and bills for audio nobody wanted.

Field names, enums and prices below were read from fal's OpenAPI schemas and model pages on
2026-09-22. They are configured request identifiers, not a claim that fal keeps them stable: a
schema change shows up as a 4xx at submit, never as silent degradation, because every family sends
only fields its schema names.

Terminology guard: ``wan`` as an *I2V provider name* in explainer_pipeline still means the
self-hosted RunPod server. The fal-hosted Wan endpoints here are reached through provider ``fal``
with ``FAL_MODEL`` set to one of the ``wan/...`` ids.
"""
from __future__ import annotations
import math

KLING_V3 = "kling_v3"        # start_image_url / end_image_url / generate_audio / cfg_scale / elements
KLING_V2 = "kling_v2"        # image_url / tail_image_url / negative_prompt
SEEDANCE = "seedance"        # image_url / end_image_url / resolution / aspect_ratio / generate_audio
WAN_26 = "wan_26"            # image_url / resolution / negative_prompt / multi_shots; no end frame
WAN_22 = "wan_22"            # image_url / end_image_url / num_frames @ 16 fps / resolution / aspect_ratio

# usd_per_sec is keyed by output resolution; None means the endpoint has no resolution field and
# bills one rate. Values marked "conservative" were not read from a price page and are set to the
# most expensive verified Kling rate so a spend cap can only overestimate.
MODELS = {
    # ── Kling (fal-ai/kling-video) ─────────────────────────────────────────────────────────────
    "fal-ai/kling-video/v2.1/standard/image-to-video": {
        "label": "kling-2.1-standard", "family": KLING_V2, "durations": (5, 10),
        "end_frame": False, "negative_prompt": True, "audio_flag": False,
        "resolutions": (), "default_resolution": None,
        "usd_per_sec": {None: 0.056},                      # $0.28 / 5 s, verified 2026-07
    },
    "fal-ai/kling-video/v2.1/pro/image-to-video": {
        "label": "kling-2.1-pro", "family": KLING_V2, "durations": (5, 10),
        "end_frame": True, "negative_prompt": True, "audio_flag": False,
        "resolutions": (), "default_resolution": None,
        "usd_per_sec": {None: 0.112},                      # conservative
    },
    "fal-ai/kling-video/v1.6/pro/image-to-video": {
        "label": "kling-1.6-pro", "family": KLING_V2, "durations": (5, 10),
        "end_frame": True, "negative_prompt": True, "audio_flag": False,
        "resolutions": (), "default_resolution": None,
        "usd_per_sec": {None: 0.112},                      # conservative
    },
    "fal-ai/kling-video/v2.5-turbo/pro/image-to-video": {
        "label": "kling-2.5-turbo-pro", "family": KLING_V2, "durations": (5, 10),
        "end_frame": True, "negative_prompt": True, "audio_flag": False,
        "resolutions": (), "default_resolution": None,
        "usd_per_sec": {None: 0.112},                      # conservative
    },
    "fal-ai/kling-video/v3/pro/image-to-video": {
        "label": "kling-3-pro", "family": KLING_V3, "durations": (5, 10),
        "end_frame": True, "negative_prompt": True, "audio_flag": True,
        "resolutions": (), "default_resolution": None,
        "usd_per_sec": {None: 0.112},                      # audio-off, verified 2026-07
    },
    # ── Seedance (ByteDance) ───────────────────────────────────────────────────────────────────
    # Token billing: height x width x seconds x 24 / 1024 tokens. Per-second rates below are that
    # formula at each resolution's 16:9 frame; vertical frames have the same pixel count.
    "bytedance/seedance-2.0/image-to-video": {
        "label": "seedance-2.0", "family": SEEDANCE, "durations": (4, 15),
        "end_frame": True, "negative_prompt": False, "audio_flag": True,
        "resolutions": ("480p", "720p", "1080p", "4k"), "default_resolution": "720p",
        "aspect_ratios": ("auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"),
        "usd_per_sec": {"480p": 0.141, "720p": 0.3024, "1080p": 0.680},   # $0.014 / 1k tokens
    },
    "bytedance/seedance-2.0/fast/image-to-video": {
        "label": "seedance-2.0-fast", "family": SEEDANCE, "durations": (4, 15),
        "end_frame": True, "negative_prompt": False, "audio_flag": True,
        "resolutions": ("480p", "720p"), "default_resolution": "720p",
        "aspect_ratios": ("auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"),
        "usd_per_sec": {"480p": 0.113, "720p": 0.2419},
    },
    "bytedance/seedance-2.5/image-to-video": {
        "label": "seedance-2.5", "family": SEEDANCE, "durations": (4, 30),
        "end_frame": True, "negative_prompt": False, "audio_flag": True,
        "resolutions": ("480p", "720p", "1080p"), "default_resolution": "720p",
        "aspect_ratios": ("auto",),                        # schema: const "auto"; follows the image
        "usd_per_sec": {"480p": 0.2205, "720p": 0.4730, "1080p": 1.164},
    },
    "fal-ai/bytedance/seedance/v1/pro/image-to-video": {
        "label": "seedance-1-pro", "family": SEEDANCE, "durations": (2, 12),
        "end_frame": True, "negative_prompt": False, "audio_flag": False,
        "resolutions": ("480p", "720p", "1080p"), "default_resolution": "720p",
        "aspect_ratios": ("auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"),
        "camera_fixed": True,
        "usd_per_sec": {"480p": 0.029, "720p": 0.0648, "1080p": 0.146},   # $3 / 1M tokens
    },
    # ── Wan (Alibaba) ──────────────────────────────────────────────────────────────────────────
    "wan/v2.6/image-to-video": {
        "label": "wan-2.6", "family": WAN_26, "durations": (5, 10, 15),
        "end_frame": False, "negative_prompt": True, "audio_flag": False,
        "resolutions": ("720p", "1080p"), "default_resolution": "720p",
        "usd_per_sec": {"720p": 0.10, "1080p": 0.15},
    },
    "fal-ai/wan/v2.2-a14b/image-to-video": {
        "label": "wan-2.2-a14b", "family": WAN_22, "durations": (1, 10),   # 17..161 frames @ 16 fps
        "end_frame": True, "negative_prompt": True, "audio_flag": False,
        "resolutions": ("480p", "580p", "720p"), "default_resolution": "720p",
        "aspect_ratios": ("auto", "16:9", "9:16", "1:1"),
        "usd_per_sec": {"480p": 0.04, "580p": 0.06, "720p": 0.08},
    },
}

# Short names for operators and directed specs. The explainer pipeline's FAL_MODEL env accepts
# either the short name or the full endpoint id.
ALIASES = {m["label"]: endpoint for endpoint, m in MODELS.items()}
# The directed-motion toolchain's historical Kling spellings. Without these, a caller pricing
# "kling-v3-pro" straight through this module got the unregistered fallback rate, half the truth.
ALIASES.update({
    "kling-v3-pro": "fal-ai/kling-video/v3/pro/image-to-video",
    "kling-v2.5-turbo-pro": "fal-ai/kling-video/v2.5-turbo/pro/image-to-video",
    "kling-v2.1-pro": "fal-ai/kling-video/v2.1/pro/image-to-video",
    "kling-v1.6-pro": "fal-ai/kling-video/v1.6/pro/image-to-video",
    "kling-v2.1-standard": "fal-ai/kling-video/v2.1/standard/image-to-video",
})

# What the registry falls back to for an endpoint it does not know: the legacy Kling v2 body and
# the legacy Kling standard rate, i.e. exactly what the pipeline sent before this module existed.
_UNREGISTERED_RATE = 0.056
WAN_22_FPS = 16


def resolve(model: str) -> str:
    """Accept a short label or a full endpoint id; return the endpoint id."""
    model = (model or "").strip()
    return ALIASES.get(model, model)


def is_registered(model: str) -> bool:
    return resolve(model) in MODELS


def spec(model: str) -> dict | None:
    return MODELS.get(resolve(model))


def label(model: str) -> str:
    m = spec(model)
    if m:
        return m["label"]
    parts = [p for p in resolve(model).split("/") if p]
    return "-".join(parts[-3:-1]) if len(parts) >= 3 else (resolve(model) or "unregistered")


def supports_end_frame(model: str) -> bool:
    m = spec(model)
    return bool(m and m["end_frame"])


def default_resolution(model: str) -> str | None:
    m = spec(model)
    return m["default_resolution"] if m else None


def rate_usd_per_sec(model: str, resolution: str | None = None) -> float:
    """Estimated USD per generated second, for the pre-spend cap and the displayed cost only."""
    m = spec(model)
    if not m:
        return _UNREGISTERED_RATE
    rates = m["usd_per_sec"]
    if None in rates:
        return rates[None]
    res = resolution or m["default_resolution"]
    if res in rates:
        return rates[res]
    return max(rates.values())          # unknown resolution: never under-reserve


def snap_duration(model: str, seconds: float) -> int:
    """The duration the endpoint will actually be asked for, in seconds, never shorter than
    requested where the schema allows it."""
    m = spec(model)
    fam = m["family"] if m else KLING_V2
    d = m["durations"] if m else (5, 10)
    if fam in (KLING_V3, KLING_V2, WAN_26):        # discrete choices: smallest that covers
        return next((v for v in d if v >= seconds), d[-1])
    lo, hi = d[0], d[-1]                           # continuous range (Seedance, Wan 2.2)
    return int(min(hi, max(lo, math.ceil(seconds))))


def build_i2v_body(model: str, *, prompt: str, image_url: str, seconds: float,
                   end_image_url: str | None = None, negative_prompt: str | None = None,
                   resolution: str | None = None, aspect_ratio: str | None = None,
                   audio: bool = False) -> dict:
    """The request body for one fal image-to-video call, in the model's own field names.

    ``image_url`` / ``end_image_url`` are whatever the caller already uses for fal: a data-URI or
    an https URL. An end frame is silently omitted for models that cannot take one; callers that
    need it must check ``supports_end_frame`` first. A negative prompt is folded into the prompt
    as an explicit "Avoid:" clause for families whose schema has no field for it.
    """
    endpoint = resolve(model)
    m = MODELS.get(endpoint)
    fam = m["family"] if m else KLING_V2
    dur = snap_duration(endpoint, seconds)
    prompt = (prompt or "").strip()
    if negative_prompt and m is not None and not m["negative_prompt"]:
        prompt = f"{prompt} Avoid: {negative_prompt.strip()}."
    body: dict = {"prompt": prompt}

    if fam == KLING_V3:
        body["start_image_url"] = image_url
        body["duration"] = str(dur)
        body["generate_audio"] = bool(audio)              # schema default True: force explicit
        if end_image_url:
            body["end_image_url"] = end_image_url
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        return body

    if fam == KLING_V2:
        body["image_url"] = image_url
        body["duration"] = str(dur)
        if end_image_url and (m is None or m["end_frame"]):
            body["tail_image_url"] = end_image_url
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        return body

    if fam == SEEDANCE:
        body["image_url"] = image_url
        body["duration"] = str(dur)
        body["resolution"] = resolution or m["default_resolution"]
        allowed = m.get("aspect_ratios", ("auto",))
        if aspect_ratio and aspect_ratio in allowed:
            body["aspect_ratio"] = aspect_ratio
        if m["audio_flag"]:
            body["generate_audio"] = bool(audio)          # schema default True: force explicit
        if end_image_url:
            body["end_image_url"] = end_image_url
        if m.get("camera_fixed"):
            body["camera_fixed"] = False
        return body

    if fam == WAN_26:
        body["image_url"] = image_url
        body["duration"] = str(dur)
        body["resolution"] = resolution or m["default_resolution"]
        body["enable_prompt_expansion"] = False           # the prompt is authored; keep it literal
        body["multi_shots"] = False                       # one continuous shot per clip
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        return body

    if fam == WAN_22:
        body["image_url"] = image_url
        body["num_frames"] = int(min(161, max(17, round(seconds * WAN_22_FPS) + 1)))
        body["frames_per_second"] = WAN_22_FPS
        body["resolution"] = resolution or m["default_resolution"]
        body["enable_prompt_expansion"] = False
        if aspect_ratio and aspect_ratio in m.get("aspect_ratios", ()):
            body["aspect_ratio"] = aspect_ratio
        if end_image_url:
            body["end_image_url"] = end_image_url
        if negative_prompt:
            body["negative_prompt"] = negative_prompt
        return body

    raise ValueError(f"unknown fal request family {fam!r} for {endpoint!r}")


def estimate_clip_usd(model: str, seconds: float, resolution: str | None = None) -> float:
    """What one clip is expected to bill: the snapped duration times the resolution's rate."""
    return round(snap_duration(model, seconds) * rate_usd_per_sec(model, resolution), 4)

