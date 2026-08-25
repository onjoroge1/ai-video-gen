"""
Explainer video pipeline (hosted by the channel mascot, Bolt).
Claude → structured script → parallel (gpt-image-1 images + OpenAI TTS) → ffmpeg assembly.

Steps:
  1. generate_script()   — Claude writes N scenes as JSON; flags which feature the host
  2. generate_image()    — gpt-image-1 per scene (1536×1024); host scenes use the
                           mascot reference image (image-edit) for a consistent character
  3. generate_tts()      — OpenAI TTS-HD narration per scene
  4. _make_scene_segment() — ffmpeg: eased Ken Burns/pan + text overlays → per-scene MP4
  5. _assemble()         — ffmpeg: xfade transitions + audio concat + optional BG music
"""

import collections
import tempfile
import os
import re
import time
import json
import hashlib
import base64
import subprocess
import concurrent.futures
import contextvars
import urllib.request
from datetime import datetime, timezone

import openai
from media_binaries import ffmpeg as _ffmpeg_bin, ffprobe as _ffprobe_bin
import anthropic
from openai import OpenAI

from longform_retention import (
    StoryFormatAcknowledgementRequired,
    build_story_contract,
    create_story_format_review,
    story_format_fallback_payload,
    validate_story_format_review,
    validate_longform_story,
    validation_rank,
    write_retention_report,
)
from longform_shots import (
    compile_scene_shots,
    semantic_broll_beat,
    select_alternate_image_indices,
    shot_plan_metrics,
)
from longform_research import (
    _canonical_url,
    claim_context_for_prompt,
    validate_claim_joins,
    validate_research_dossier,
)
from longform_evidence import (
    compile_evidence_plan,
    evidence_asset_counts,
    record_asset_verification,
    reuse_exact_asset,
    validate_evidence_plan,
    validate_evidence_timing,
)
from longform_motion import (
    compile_motion_plan,
    freeze_opening_manifest,
    motion_prompt,
    normalize_motion_mode,
    sha256_file,
    validate_frozen_opening,
    validate_motion_plan,
)
from longform_rendered_gate import (
    HumanReviewRequired,
    blind_story_prompt,
    build_animatic_gate,
    build_contact_sheet,
    create_human_review_record,
    cross_check_blind_observations,
    diagnostic_disposition,
    diagnostic_mode_allowed,
    inspect_rendered_opening,
    load_threshold_profile,
    render_low_cost_animatic,
    score_rendered_contract,
    watermark_rejected_preview,
)
from longform_pilots import (
    ControlledPilotError,
    artifact_completeness,
    pilot_policy as frozen_pilot_policy,
    validate_effective_story_format,
    validate_pilot_request,
)
from audio_timing import build_audio_timing_report
from runtime_planner import plan_runtime, runtime_word_bounds
from retention_readiness import (
    build_audio_cues,
    score_retention_readiness,
    write_readiness_report,
)


def _context_map(executor, fn, items):
    """Map work while preserving the durable runtime ContextVar in worker threads."""
    parent = contextvars.copy_context()
    return executor.map(lambda item: parent.copy().run(fn, item), items)


# Transient errors worth retrying. NOT retried: BadRequestError (400 — includes content
# moderation), AuthenticationError (401), PermissionDeniedError (403), NotFoundError —
# those are deterministic, so retrying just wastes time and money.
_RETRYABLE = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class ContentBlocked(Exception):
    """Raised when the image model refuses a prompt on content-policy grounds."""


def _is_moderation_error(exc: Exception) -> bool:
    if isinstance(exc, openai.BadRequestError):
        blob = str(getattr(exc, "message", "") or exc).lower()
        code = str(getattr(exc, "code", "") or "").lower()
        return ("moderation" in blob or "safety" in blob or "content policy" in blob
                or "content_policy" in blob or "moderation_blocked" in code)
    return False


def _retry(fn, *, tries: int = 4, base_delay: float = 2.0, label: str = "API call"):
    """Run fn() with exponential backoff on TRANSIENT errors only.

    Non-transient errors (bad request / moderation / auth) are raised immediately —
    retrying them is pointless and costs latency.
    """
    import sys
    last = None
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except _RETRYABLE as exc:
            last = exc
            if attempt == tries:
                break
            delay = base_delay * (2 ** (attempt - 1))
            print(f"[retry] {label} failed (attempt {attempt}/{tries}): "
                  f"{type(exc).__name__}: {str(exc)[:120]} — retrying in {delay:.0f}s",
                  file=sys.stderr, flush=True)
            time.sleep(delay)
        except Exception as exc:  # non-retryable — surface immediately
            if _is_moderation_error(exc):
                raise ContentBlocked(str(getattr(exc, "message", "") or exc)) from exc
            raise
    raise last


def _claude():
    # 180s per-request timeout (+ SDK retries) so a hung connection can't stall script-gen forever
    # (a no-timeout call once appeared to "write a script for an hour").
    # max_retries=6 (was 2): a render makes ~16 Claude calls and ANY one failing aborts the whole job
    # (wasting prior spend). 529 "overloaded" spikes are transient — the SDK retries >=500/529 with
    # exponential backoff + honours retry-after, so more retries ride out a spike instead of dying on
    # attempt 3. Overridable via CLAUDE_MAX_RETRIES.
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=180.0,
                                 max_retries=int(os.environ.get("CLAUDE_MAX_RETRIES", "6")))
    try:
        from durable_execution import current as _durable_current
        runtime = _durable_current()
        return runtime.wrap_anthropic(client) if runtime else client
    except Exception:
        return client

def _openai():
    # 90s per-call timeout so a hung connection fails fast (default is 600s, which
    # makes the whole pipeline appear stuck). We do our own retries, so disable the
    # SDK's internal ones to avoid compounding long waits.
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=90.0, max_retries=0)

def _openai_video():
    # Sora i2v jobs take minutes and we poll them — generous per-request timeout + a couple
    # retries (the fast 90s _openai() client times out mid-poll).
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=600.0, max_retries=2)

def _gemini():
    from google import genai   # optional dep — only imported when the Veo provider is used
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _run_ffmpeg(cmd: list, timeout: float = 180.0):
    """Run an ffmpeg command safely.

    - injects `-nostdin` so ffmpeg never blocks waiting on inherited stdin
    - detaches stdin (DEVNULL) for the same reason
    - bounds runtime with a timeout so a hung encode raises (and the caller's
      per-scene fail-safe skips it) instead of stalling the whole job forever
    """
    # cmd[0] is a resolved path (system or bundled static build), so match on the
    # basename rather than a bare name, or -nostdin silently stops being injected.
    if cmd and os.path.basename(str(cmd[0])).startswith("ffmpeg") \
            and "-nostdin" not in cmd:
        cmd = [cmd[0], "-nostdin", *cmd[1:]]
    return subprocess.run(cmd, check=True, capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=timeout)


# ── Recurring cast ─────────────────────────────────────────────────────────────
# Long-form is human-led. Bolt remains the branded co-investigator and appears
# only when he performs story work. Both identities are locked by references.
_HERE = os.path.dirname(os.path.abspath(__file__))

# Image model: gpt-image-2 is SOTA at instruction-following (so cinematic composition
# prompts land) and ~25% cheaper output than gpt-image-1. Supports reference-image edits.
ANTHROPIC_MODEL = "claude-opus-4-8"
IMAGE_MODEL = "gpt-image-2"
TTS_MODEL = "tts-1-hd"
TRANSCRIPTION_MODEL = "whisper-1"

# Output-format presets. One toggle drives image aspect, canvas, and caption mode.
FORMATS = {
    "landscape": {"w": 1920, "h": 1080, "img_size": "1536x1024", "captions": "headline_karaoke"},
    "social":    {"w": 1080, "h": 1920, "img_size": "1024x1536", "captions": "karaoke"},
}


def transcribe_words(audio_path: str) -> list:
    """Word-level timestamps for our own TTS, for karaoke captions.
    Returns [(word, start, end), ...]; [] on failure (caller falls back)."""
    try:
        def _call():
            # Reopen on every retry. Reusing a consumed file handle submits an empty body after
            # a transient failure and turns a recoverable timing call into a false gate failure.
            with open(audio_path, "rb") as handle:
                return _openai().audio.transcriptions.create(
                    model=TRANSCRIPTION_MODEL, file=handle, response_format="verbose_json",
                    timestamp_granularities=["word"])

        r = _retry(_call, label="whisper transcription")
        words = getattr(r, "words", None) or []
        out = []
        for w in words:
            txt = (getattr(w, "word", "") or "").strip()
            if txt:
                out.append((txt, float(getattr(w, "start", 0.0)), float(getattr(w, "end", 0.0))))
        return out
    except Exception:
        return []

# ── Cost model (USD) — all rates verified from official pricing ────────────────
# gpt-image-2: text-in $5/1M, image-in $8/1M, image-out $30/1M tokens
# tts-1-hd:    $30 / 1M characters
# Opus 4.8 (script): in $5/1M, out $25/1M tokens
_RATE_IMG_TEXT_IN = 5.0  / 1_000_000
_RATE_IMG_IMG_IN  = 8.0  / 1_000_000
_RATE_IMG_OUT     = 30.0 / 1_000_000
_RATE_TTS_CHAR    = 30.0 / 1_000_000
_RATE_SCRIPT_IN   = 5.0  / 1_000_000
_RATE_SCRIPT_OUT  = 25.0 / 1_000_000
# Spend reservation, not a provider pricing assertion. Server-side search pricing can change;
# reserve a configurable conservative ceiling for every observed request.
_WEB_SEARCH_COST_CEILING = float(os.environ.get("WEB_SEARCH_COST_CEILING_USD", "0.10"))

# Pre-spend ESTIMATE only (actual spend is read from real usage tokens per call).
# MEASURED 2026-06-24 from real gpt-image-2 usage: text-only 1536×1024 ≈ $0.041,
# host (w/ bolt.png reference) ≈ $0.054. Small safety margin added.
_COST_IMG_BASE   = 0.045    # one gpt-image-2 medium 1536×1024 (measured ~$0.041)
_COST_IMG_HOST   = 0.055    # + bolt.png reference as image input (measured ~$0.054)
_COST_SCRIPT     = 0.25     # one Opus 4.8 script call (estimate)
MAX_COST_USD     = 25.00    # hard ceiling — refuse before spending (long-form 20min ≈ $23)

# ── Image-to-video (i2v) variability ────────────────────────────────────────────
# Animate a deterministic ~35% of scenes (incl. the first) with a real i2v model instead of
# ffmpeg Ken-Burns, for variety. Provider-agnostic; OFF unless I2V_PROVIDER + the matching key
# is set. Long-form is hard-capped (cost). Any i2v failure falls back to ffmpeg motion.
I2V_PROVIDER  = os.environ.get("I2V_PROVIDER", "").strip().lower()   # "sora" | "veo" | "" (off)
I2V_FRACTION  = 0.35        # long-form target share of scenes animated (30-40% band)
# Social shorts lean HARD on motion (autoplay feed + first-second retention) and are cheap to
# animate (few scenes), so they get a higher share. Tunable; verify real Veo $/s before pushing up.
I2V_FRACTION_SOCIAL = float(os.environ.get("I2V_FRACTION_SOCIAL", "0.6"))
# Shorts FRONT-LOAD their motion: ~this share of the clip budget goes to the OPENING scenes (retention
# is won/lost in the first seconds of an autoplay feed), one clip is reserved for the finale/payoff,
# and the rest are spaced across the back half. Cost-neutral vs. even/random placement.
I2V_FRONTLOAD_SOCIAL = float(os.environ.get("I2V_FRONTLOAD_SOCIAL", "0.65"))
MAX_I2V_CLIPS = 12          # hard per-video cap (cost backstop, esp. long-form)
I2V_SECONDS   = 4           # social clip length; long-form uses the dedicated 5-second contract below
I2V_SECONDS_LONGFORM = 5    # preserve a full generated shot while ordinary stills cut faster
MAX_LONGFORM_ALT_IMAGES = int(os.environ.get("MAX_LONGFORM_ALT_IMAGES", "18"))
# LITERAL/GROUNDED imagery direction (packaging research + this channel's data: real-life Water short
# hit 73% viewed, symbolic Light stalled at 2.4% CTR). When on, scene + thumbnail prompts steer to the
# LITERAL real-world subject (documentary/lab look) and away from symbolic-metaphor/glowy imagery.
# Toggle OFF (LITERAL_IMAGERY=0) to A/B the grounded direction against the old look on real data.
_LITERAL_IMAGERY = os.environ.get("LITERAL_IMAGERY", "1") == "1"
_LITERAL_SCENE_DIRECTION = (
    " GROUNDED REALISM (priority): depict the LITERAL real-world subject of this beat in a real place"
    " — a home, lab, classroom, street, or the actual object — with real materials and cinematic"
    " lighting, like a documentary/film still. Do NOT invent SYMBOLIC or METAPHOR imagery (no glowing"
    " abstract orbs, energy vortices, giant symbolic gauges/needles, hourglasses-for-time, or a"
    " 'machine that represents the concept'); if the idea is abstract, ground it in a real setting (a"
    " scientist at an instrument, a real object visibly reacting). Symbolic/abstract shots break"
    " immersion — keep them rare.")
# est USD/sec for the pre-spend cap guard + the displayed cost — affects budgeting only,
# NOT actual billing. Sora-2 720p = $0.10/s. Veo 3.1 Fast = $0.15/s WITH audio — verified
# 2026-06 against Google/3rd-party pricing pages (was wrongly $0.10 → ~50% undercount). Still
# confirm against a real Google Cloud invoice line if billing matters; override via I2V_RATE_SEC.
def _resolve_i2v_rate() -> float:
    """USD/sec for the cost guard + display. I2V_RATE_SEC overrides, but is GUARDED: an empty,
    non-numeric, or <=0 value (e.g. a bare `I2V_RATE_SEC=` left in .env) falls through to the
    provider default instead of crashing at import. Keyed off the FIRST provider in a possible
    'veo,sora' fallback chain so a chain doesn't silently mis-rate."""
    _ov = (os.environ.get("I2V_RATE_SEC") or "").strip()
    if _ov:
        try:
            v = float(_ov)
            if v > 0:
                return v
        except ValueError:
            pass
    primary = I2V_PROVIDER.split(",")[0].strip()
    # fal=0.056/s = Kling v2.1 standard ($0.28/5s, verified on fal.ai 2026-07). Was 0.05 (~11% low).
    return {"sora": 0.10, "veo": 0.15, "fal": 0.056}.get(primary, 0.15)


_RATE_I2V_SEC = _resolve_i2v_rate()
# Hero-beat i2v rate (the hybrid uses a pricier model on hook/climax). Kling v3 pro audio-off = $0.112/s
# (2× standard, verified on fal.ai 2026-07). Only applied to the ~2 hero beats; see the animation loop.
_RATE_I2V_HERO_SEC = float(os.environ.get("I2V_HERO_RATE_SEC", "0.112"))
_SORA_MODEL   = os.environ.get("SORA_MODEL", "sora-2")
# veo-3.0-fast shuts down 2026-06-30 → default to the 3.1 fast tier (verified drop-in).
_VEO_MODEL    = os.environ.get("VEO_MODEL", "veo-3.1-fast-generate-preview")
# fal.ai i2v (Kling by default) — cheaper than Veo AND a SEPARATE quota, so it's the useful fallback
# when the shared Gemini/Veo project caps out. Model + key configurable; verified working 2026-07-07.
_FAL_MODEL    = os.environ.get("FAL_MODEL", "fal-ai/kling-video/v2.1/standard/image-to-video")
# HYBRID: a pricier, more natural model on the HERO beats (hook + climax) where motion earns the
# swipe/stay decision; the cheaper _FAL_MODEL on the rest. Social only. v3 pro ≈ 2× standard.
_FAL_MODEL_HERO = os.environ.get("FAL_MODEL_HERO", "fal-ai/kling-video/v3/pro/image-to-video")
_FAL_HYBRID   = os.environ.get("FAL_HYBRID", "1") == "1"


def _fal_key() -> str:
    return os.environ.get("FAL_KEY", "").strip()


def estimate_cost(n_scenes: int, host_count: int = 0, narration_chars: int = 0,
                  extra_images: int = 0) -> float:
    """Pre-spend USD estimate for one video. Refined once host split + narration known."""
    imgs = (host_count * _COST_IMG_HOST + (n_scenes - host_count) * _COST_IMG_BASE
            + extra_images * _COST_IMG_HOST)
    tts  = narration_chars * _RATE_TTS_CHAR if narration_chars else n_scenes * 0.006
    return round(_COST_SCRIPT + imgs + tts, 2)


def _msg_cost(usage) -> float:
    """USD for one Claude (Opus 4.8) message from its usage tokens."""
    return (getattr(usage, "input_tokens", 0) or 0) * _RATE_SCRIPT_IN + \
           (getattr(usage, "output_tokens", 0) or 0) * _RATE_SCRIPT_OUT


def _image_cost_from_usage(resp) -> float:
    """Actual USD for one gpt-image-2 call, read from the response's usage tokens."""
    u = getattr(resp, "usage", None)
    if not u:
        return 0.0
    out = getattr(u, "output_tokens", 0) or 0
    det = getattr(u, "input_tokens_details", None)
    if det is not None:
        text_in = getattr(det, "text_tokens", 0) or 0
        img_in  = getattr(det, "image_tokens", 0) or 0
    else:
        text_in = getattr(u, "input_tokens", 0) or 0
        img_in  = 0
    return out * _RATE_IMG_OUT + text_in * _RATE_IMG_TEXT_IN + img_in * _RATE_IMG_IMG_IN

MASCOT_NAME = "Bolt"
MASCOT_DESC = (
    "Bolt, a small friendly robot the size of a child, with a smooth rounded "
    "matte-white body and soft mint-green panel accents, a large dark glossy "
    "screen-face displaying two simple glowing cyan dot eyes, a single slender "
    "antenna topped with a small glowing cyan sphere, short stubby arms, and a "
    "smooth hovering rounded base instead of legs"
)
MASCOT_REF = os.path.join(_HERE, "assets", "mascot", "bolt.png")
HUMAN_NAME = "Alex"
HUMAN_DESC = (
    "Alex, the recurring human lead shown in the attached reference: an adult man with short "
    "brown hair, light stubble, navy overshirt, light gray T-shirt, dark jeans, and dark sneakers"
)
HUMAN_REF = os.path.join(_HERE, "assets", "mascot", "human-model.png")
HUMAN_REF_LINE = (
    "Use the attached human reference image to keep Alex exactly consistent: same face, hair, "
    "navy overshirt, gray T-shirt, dark jeans, build, and apparent age."
)


def _scene_reference_paths(scene: dict, *, human_ok: bool, mascot_ok: bool) -> list[str] | None:
    """Return identity references in stable lead-then-support order."""
    refs: list[str] = []
    if scene.get("human_present") and human_ok:
        refs.append(HUMAN_REF)
    if scene.get("mascot_present") and mascot_ok:
        refs.append(MASCOT_REF)
    return refs or None

# Short line used in host-scene prompts — the reference image carries the identity,
# so we no longer repeat the full description (frees prompt room for cinematography).
MASCOT_REF_LINE = (
    f"Use the attached reference image: keep {MASCOT_NAME} exactly consistent — same "
    "rounded matte-white body with mint-green accents, glossy dark screen-face with "
    "glowing cyan eyes, antenna, and hovering base."
)

# Locked channel RENDER STYLE only — the cohesive cartoon look applied to every image
# across all videos. NOTE: deliberately contains NO environment/subject words (no
# "cosmic", "galaxy", "plasma") — the per-scene environment_type supplies the world, so
# non-space topics don't get wrongly forced into galaxies.
CHANNEL_STYLE = (
    "premium stylized animated educational world, polished 3D cartoon look, expressive "
    "toy-like character design, rich depth and clean silhouettes, strong readability, "
    "appealing color, high production value"
)

# ── Durable channel design SYSTEM (lives in code, NOT re-rolled by the LLM per video) ──────
# A FIXED role→colour grammar applied to EVERY video, so the same KIND of thing is always the
# same colour across the whole channel. Roles are universal explanatory functions, so they map
# onto any topic. THIS is what compounds into a recognizable identity (vs the model inventing a
# fresh palette each video). To re-skin the whole channel, edit this one dict.
SEMANTIC_PALETTE = {
    "trigger / alert / the thing being detected":   "yellow",
    "agent / chemical / substance / messenger":     "orange",
    "danger / pain / damage / cost / threat":       "red",
    "system / brain / control center / network":    "electric blue",
    "relief / solution / safe / success / calm":    "green",
    "normal body / baseline / neutral object":      "warm coral",
}
_COLOR_CODE_TEXT = (
    "\nCHANNEL COLOR CODE — FIXED across ALL videos; never reassign these meanings. Map each "
    "scene's key element to the ROLE it plays, then use that role's colour (by name) in the "
    "image_prompt:\n"
    + "".join(f"  • {role} → {col}\n" for role, col in SEMANTIC_PALETTE.items())
    + "A concept keeps its colour in every scene it appears (e.g. 'a cloud of ORANGE histamine'). "
    "Cyan is reserved for Bolt himself — do not use it as a concept colour. This consistency IS "
    "the channel's visual language.\n"
)

# Canonical Bolt poses — pick the fitting one each scene so his acting reads from a consistent
# vocabulary (the reference image + this keep him recognizable across every video).
BOLT_POSES = ("neutral-presenter", "pointing-guide", "shocked", "nervous", "curious",
              "relieved", "acting-out-the-beat", "warning/alarm")
_BOLT_POSE_TEXT = (
    "BOLT POSE VOCABULARY — each scene, give Bolt ONE pose from this fixed set: "
    + ", ".join(BOLT_POSES) + ". Keep his design identical to the reference every time.\n"
)
_DESIGN_SYSTEM_TEXT = _COLOR_CODE_TEXT + _BOLT_POSE_TEXT

# Filler/stopwords skipped when choosing the ONE caption word to accent — keeps the highlight on
# the content word, not an adverb/connective ("SIGNAL straight up" → SIGNAL, not STRAIGHT).
_CAPTION_FILLER = frozenset((
    "THE A AN OF TO IN ON AND OR BUT THAT SO IT AS AT BY UP IS ARE WAS WERE BE WITH FOR FROM "
    "INTO THEN NOW JUST EVEN MORE VERY ALSO ITS YOUR YOU WE THEY THIS THESE THOSE WHEN WHILE "
    "STRAIGHT REALLY ONLY EACH EVERY OVER OUT OFF NOT NO YES CAN WILL HERE THERE WHAT WHY HOW"
).split())


# ── Script generation ──────────────────────────────────────────────────────────

_SCRIPT_SYSTEM = "You are a YouTube explainer video writer. Return ONLY valid JSON with no markdown, no code fences."

_SCRIPT_PROMPT = """\
You are the writer + storyboard artist for a YouTube explainer channel hosted by a
recurring mascot. Write the script answering: "{question}"

Target length: ~{duration}s total. Tone / style: {style}. Number of scenes: {n_scenes}.

THE HOST (appears in most scenes as the on-screen guide):
{mascot_name} — {mascot_desc}

You are directing a SHORT FILM that tells ONE cohesive story, with {mascot_name}
guiding the viewer through it.
{theme_block}
Return this exact JSON structure with NO extra keys:
{{
  "title": "Short catchy video title (under 60 chars)",
  "hook": "One-sentence YouTube description hook",
  "style_mode": "ONE for the whole video — pick the best fit: educational | scientific | cinematic | fun",
  "scenes": [
    {{
      "id": 1,
      "narration": "What the narrator says, in ~{wpm} words TOTAL — that budget is a hard runtime constraint, not a target to exceed. Within it, vary sentence length deliberately: where the budget allows, pair a longer sentence that builds with a short one that lands (<=5 words). One even mid-length sentence per scene is this channel's most common cadence defect — every thought the same size, so no reveal has anywhere to land — but a scene that overruns its word budget breaks the runtime contract before any spend, so never buy variation with extra words.",
      "_role": "this beat's story role, from the list supplied in the STORY FORMAT section below (use the exact role name; omit only if no role fits)",
      "scene_type": "real_world_example | metaphor_scene | educational_diagram | cinematic_intro | experiment_lab | everyday_life | abstract_visualization | recap_scene",
      "environment_type": "best fit for THIS scene (VARY it): classroom | science_lab | home | city | data_center | space | microscopic_world | digital_world | nature | sports_field | simple_whiteboard | abstract_space",
      "image_prompt": "A visually engaging frame in one rich paragraph, set in THIS scene's environment_type and matching its scene_type. REQUIRED: a concrete real-world or metaphor scene (NOT 'Bolt beside a glowing concept'); an intentional ASYMMETRICAL composition with clear FOREGROUND / MIDGROUND / BACKGROUND depth; a specific CAMERA angle; mode-appropriate LIGHTING; an EMOTIONAL beat; an implied MOTION cue. For any complex idea, show a SIMPLE VISUAL METAPHOR (e.g. WiFi = invisible messages router→device; electricity = energy through a circuit). Make the focal subject instantly readable. INFORMATION-DESIGN DISCIPLINE: ONE HERO per frame (the thing the scene teaches) + at most one supporting element — Bolt is the GUIDE, smaller and pointing when the science is the hero, not always the centerpiece. SEMANTIC COLOR CODE: use the CHANNEL COLOR CODE provided below (a fixed role→colour map); map each element to its role and name that colour in every image_prompt showing it. For body/mechanism beats use a CLEAN CUTAWAY (simplified, legible like a diagram) rather than busy realistic texture; readable muted in half a second. The cutaway is UNLABELED — NO text/letters/numbers/callout labels baked into the image (convey meaning via shape + the semantic colour, not written labels).",
      "mascot_present": true,
      "shot_type": "one of: wide | medium | close | aerial | detail (drives pacing; put the real camera direction in image_prompt)",
      "text_overlay": "2-4 ALL-CAPS words — the punchy on-screen headline",
      "text_sub": "Optional supporting line (sentence case) or empty string",
      "text": {{
        "placement": "where the caption sits — pick to AVOID {mascot_name} and the main subject: top_left | top_right | top_center | lower_left | lower_right | lower_center | center",
        "alignment": "left | center | right",
        "emphasis_words": ["the ONE or two words from text_overlay that should pop in the accent color"],
        "title_color": "white | cream | cyan",
        "accent_color": "cyan | mint | violet | purple | gold | orange",
        "subtitle_color": "warm_yellow | warm_gold | mint | pale_blue",
        "card": "none | sticker | panel  (use sticker/panel for fun, punchy beats; none for clean cinematic ones)"
      }}
    }}
  ]
}}

STYLE MODE (pick ONE for the whole video and keep it consistent):
- educational = clarity-first, clean, intuitive, visually readable
- scientific = precise, structured, experiment-oriented, credible
- cinematic = dramatic, awe-filled, rich depth, strong scale and lighting
- fun = playful, charming, warm, approachable
Let that mode guide every scene's lighting and tone.

SCENE TYPE + CREATIVE MIX (this is what stops it feeling like an AI slideshow):
- Give each scene a scene_type and deliberately MIX them. Target roughly:
  ~40% real_world_example / everyday_life, ~40% educational_diagram / experiment_lab /
  metaphor_scene, ~20% cinematic_intro / abstract_visualization. Open with a
  cinematic_intro VISUAL HOOK; end on the PAYOFF/reveal scene (NOT a flat recap_scene).
- NO two adjacent scenes share the same scene_type, and use at least 4 distinct types
  across the video.

ENVIRONMENT (choose per scene to fit the IDEA — and VARY it):
- Pick from: classroom, science_lab, home, city, data_center, space, microscopic_world,
  digital_world, nature, sports_field, simple_whiteboard, abstract_space.
- DO NOT default to space / galaxy / neon / abstract digital backgrounds. Use space ONLY
  if the topic is literally about space. Prefer grounded, REAL settings (a kitchen, a
  classroom, a city street, a sports field) — they feel less "AI". Use no single
  environment for more than ~40% of scenes.

BOLT'S BEHAVIOUR (he hosts EVERY scene — he ACTS, he doesn't just point):
- {mascot_name} appears in EVERY scene as the on-screen host: always set
  "mascot_present": true. He is present even in real-world examples and diagrams —
  observing, demonstrating, or reacting within them, never just floating beside a glow.
- Give him a concrete, VARIED ACTION each scene: sorting examples, reacting to a mistake,
  pushing a button, holding a prop, comparing two things, looking surprised, testing
  something, guiding the viewer, leaning in, bracing. His reactions carry the scene.

IMAGE_PROMPT rules (direct it like an animation art director):
- GROUNDED REALISM (most important for not looking "AI"): model the scene on the TOPIC
  and set it in a BELIEVABLE REAL place with real, recognizable, topic-relevant objects
  and props (an actual kitchen, classroom, street, lab bench, server room). MINIMIZE
  abstract glows, neon, holograms, floating particles, light tunnels and sci-fi sheen —
  {mascot_name} is the ONLY cartoon-stylized element inside an otherwise grounded,
  relatable world. Real settings read as intentional; generic glow reads as AI slop.
- ASYMMETRY BY DEFAULT. Never center the subject. Place the main subject off-center with
  diagonal visual flow, and build real FOREGROUND / MIDGROUND / BACKGROUND depth that
  fits the environment_type. It must NOT feel empty, flat, or diagram-like — but it must
  stay instantly readable.
- INTEGRATE {mascot_name} when present so he is NEVER "pasted on": lighting from the
  scene on his body, cyan reflections in his face, environment elements passing in front
  of and behind him, and STRONG body language (awe, curiosity, surprise, bracing,
  pointing, shielding his eyes). Refer to him only as "{mascot_name} the robot"; do NOT
  describe his appearance (a reference handles it) and do NOT state the render style.
- VARY shot size, camera angle, environment, Bolt prominence, visual density, and
  emotional intensity across scenes so none feel alike.
- Keep the focal subject out of the very TOP strip so a caption can overlay; do NOT
  render any text, labels, arrows, numbers, UI, or diagrams (titles are added later).
- SAFE FOR THE IMAGE MODEL (avoids content blocks): NEVER name or depict a real,
  identifiable person, living artist, celebrity, politician, or branded/trademarked
  character or logo. Portray historical figures (Newton, Einstein, etc.) ONLY as
  generic, anonymous stylized characters (e.g. "a curious scientist in period clothing")
  — never as a recognizable likeness or by name. Avoid gore, graphic injury, weapons,
  and anything disturbing; keep every scene kid-friendly and tasteful.

TEXT DIRECTOR rules (the caption is part of the storytelling, not a label):
- PLACEMENT must dodge the focal point: if {mascot_name}/the subject sits on the LEFT,
  put text on the right (and vice-versa); never cover his face or the main object.
- DON'T default to top_center — vary placement across scenes (left, right, lower).
- emphasis_words: pick the single most emotionally charged word to pop in the accent.
- Match colors to the video's style_mode mood (e.g. scientific → cyan/pale_blue;
  cinematic → gold/cream; fun → violet/gold; educational → mint/warm_yellow), but keep
  them consistent across the video so it feels branded.
- Use a "sticker"/"panel" card for playful or punchy beats; "none" for clean cinematic shots.
- text_overlay is 2-4 ALL-CAPS words; text_sub is a short sentence-case line or "".

STORY + HOST rules:
- The scenes form a VISUAL NARRATIVE ARC — a journey that builds, not a list.
- Use MATCH-CUTS: end one shot so it visually leads into the next.
- {mascot_name} hosts EVERY scene ("mascot_present": true) — present and reacting in all
  of them, including real-world examples and diagrams (he observes/demonstrates within).

PACING (this is a STORY that BUILDS to a PAYOFF, not a lecture that recaps):
- Scene 1 (first ~2s) — CONSEQUENCE-FIRST: pose the ONE central QUESTION (the title's promise) in the
  FIRST line, and in the SAME breath show the first CONCRETE, VISIBLE consequence — the question and
  something clearly AT STAKE land together (e.g. "What if X? — [the thing already going wrong]"). Do
  NOT spend the opening on abstract setup; the viewer must SEE a stake within the first few words.
  Lead with STAKES in plain language; let any metaphor ride in the VISUALS. Never a stock opening.
  The image_prompt for Scene 1 is the VISUAL HOOK — the single most arresting frame, with that stake
  visibly in-frame.
- ONE QUESTION ONLY: never restate the question and never open a SECOND competing question. Do NOT
  give the ANSWER/payoff away early — that stays for the climax; keep the question open by RAISING the
  stakes, not by withholding the opening consequence. Every middle scene BUILDS toward the answer — a
  new step/complication, each caused by the last (a JOURNEY, not a list). One idea per scene.
- STATE-ONCE (repetition is the #1 score-killer): say each idea, fact, term, and the central ANSWER
  EXACTLY ONCE. Do NOT restate the hook's premise or the answer in any scene except the climax. BAN
  back-references — no "as we saw", "as mentioned", "remember", "recall", "earlier", "this is why",
  "in other words". A scene's opening words must NOT echo the previous scene's closing words; name
  each term once, then refer to it briefly — never re-define it.
- Every ~3-4 scenes: a PATTERN INTERRUPT — switch scene_type/environment/energy to re-grab attention.
- CLIMAX (~75-85% through): the single REVEAL / answer / PAYOFF — state it ONCE as the EARNED answer
  to the Scene-1 question. Earlier scenes must NOT pre-empt it.
- Final scene(s): a SHORT, EARNED closing that delivers a NEW resonant "so what" tied to THIS story —
  it must NOT re-summarize or restate any earlier fact or the answer. NEVER a boilerplate sign-off
  ("smash that like button"). End on a specific, memorable button.

LENGTH (the narration drives the video's length — hit this closely):
- Each scene's narration should be about {wpm} words ({wpm_lo}-{wpm_max}).
- The combined narration across all {n_scenes} scenes must total CLOSE TO {total_words}
  words — aim for that number and DO NOT exceed {total_words_max} words total.
- Use concise, punchy sentences. Do not pad or ramble.
{social_block}"""


def scene_count_for(duration_sec: int, video_format: str = "landscape") -> int:
    """Scenes per video → drives image cadence. SOCIAL shorts cut faster (~3s/image) for Shorts
    retention; long-form stays ~5s/scene. Default (no format passed) keeps the long-form /5 behaviour
    UNCHANGED. Supports long-form up to 20 min (240 scenes)."""
    secs_per_scene = 3 if video_format == "social" else 5
    return max(8, min(240, round(duration_sec / secs_per_scene)))


def _parse_script_json(raw: str):
    """Strip fences and parse; return (obj, repair_cost). One repair retry on failure."""
    raw = raw.strip()
    if "```" in raw:
        raw = raw[raw.find("{"): raw.rfind("}") + 1] if "{" in raw else raw
    try:
        return json.loads(raw), 0.0
    except json.JSONDecodeError:
        fix = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=16000,
            system="Return ONLY the corrected, strictly-valid JSON. No prose, no code fences.",
            messages=[{"role": "user", "content": f"Fix this into valid JSON:\n\n{raw}"}],
        )
        ft = fix.content[0].text.strip()
        if "```" in ft:
            ft = ft[ft.find("{"): ft.rfind("}") + 1]
        cost = fix.usage.input_tokens * _RATE_SCRIPT_IN + fix.usage.output_tokens * _RATE_SCRIPT_OUT
        return json.loads(ft), cost


# Above this many scenes, generate the script in chapters (one Claude call can't emit
# 100+ scenes of JSON without truncating).
CHUNK_THRESHOLD = 24


def _series_block(series: str) -> str:
    """Format-series framing: makes every episode feel like one recurring show."""
    series = (series or "").strip()
    if not series:
        return ""
    return (f"\nSERIES — this video is EPISODE in the recurring series \"{series}\". Make the title "
            "and the opening/closing fit the series' repeatable pattern so episodes feel like one "
            "show (a returning hook shape, a consistent promise), while THIS episode's specific "
            "topic stays the star. Do not restate the series name robotically every line.\n")


def _is_simulation_short(title: str) -> bool:
    """Detect the 'you change every second' Shorts lane (BoneLab-style viewer-as-character sims).
    These need a DIFFERENT structure than the standard curiosity-gap beat map (a timed-checkpoint
    ladder that never withholds), so generate_script swaps in _SIM_SOCIAL_BLOCK for them."""
    t = (title or "").lower()
    return any(p in t for p in ("every second", "every minute", "every hour", "every day"))


# Simulation lane (social only) — the viral "What If You + number + every second?" format. Replaces
# the anchor/corruption/withheld-reveal beat map with a deterministic checkpoint ladder: the changing
# total state is the engine, one persistent POV, light mechanism, punchy button. Numbers live in the
# NARRATION (they become karaoke captions) — never baked into the image (the model garbles them).
_SIM_SOCIAL_BLOCK = (
    "\nSOCIAL SHORT — SIMULATION LANE (\"you change every second\"). This title simulates a change "
    "happening to YOU on a clock. OVERRIDE the standard beat map with THIS structure (it is what makes "
    "this exact title type go viral) — do NOT use the anchor/corruption/withheld-reveal ladder:\n"
    "\n*** THE ENGINE: A CHANGING TOTAL STATE ***\n"
    "The whole video rides ONE total-state number. It rises for growth/gain and falls for shrink/loss/"
    "cooling. Say the new TOTAL out loud every beat (it becomes the on-screen caption). Never present "
    "the per-period delta as though it were the total.\n"
    "\n*** STRUCTURE ***\n"
    "- SCENE 1 = HOOK (<8 words): speak the TITLE almost verbatim as a question addressed to YOU "
    "(\"What if you gained one kilogram every second?\"). Show YOU at the ordinary starting state.\n"
    "- BODY = a LADDER OF TIME CHECKPOINTS on an accelerating clock, one per scene: e.g. \"One "
    "minute in — 130 kilos total.\" -> \"One hour — 3,670 total.\" -> \"One day — over 86,000.\" -> \"One "
    "week...\" -> \"One month...\". EACH scene: (a) state the CHECKPOINT (time) + the NEW NUMBER out "
    "loud, short and punchy; then (b) ONE concrete, visceral CONSEQUENCE at that magnitude. The number "
    "MUST progress in the title's direction. Escalate consequences only as far as the compiled magnitude "
    "supports; never force a city, planetary, or cosmic outcome.\n"
    "- GROUNDED: use only the code-compiled linear figures supplied below. Do not recalculate them or "
    "invent consequences for drama. Absurd premise, conservative real physics.\n"
    "- LIGHT ON MECHANISM: at MOST one short \"why\" line in the ENTIRE video; spend everything else on "
    "the changing total + escalating consequence. This is a thrill ride, not a lecture.\n"
    "- THE CLOCK ONLY MOVES FORWARD: the time checkpoints must appear in strictly INCREASING order and "
    "never rewind. Do NOT drop a mechanism/aside line BETWEEN two checkpoints out of sequence — fold any "
    "\"why\" into the checkpoint line at the moment that threshold is first crossed, so the timeline never "
    "jumps backward.\n"
    "- FAST CADENCE (Shorts live or die on this): keep EVERY narration line to ~6 WORDS OR FEWER — "
    "terse, staccato, punchy telegraphese (e.g. \"One hour. 3,600 kilos. Floors crack.\" / \"One week. "
    "A skyscraper of you.\"). Prefer fragments over full sentences; cut every filler word. This "
    "OVERRIDES any words-per-scene target above. ~2.5-3s of speech per scene keeps the Short snappy and "
    "on-length; long explanatory lines are the #1 thing that makes a sim Short drag.\n"
    "- SECOND-TO-LAST = the single most extreme supported checkpoint (largest or smallest total, the "
    "consequence) — the peak of the ride.\n"
    "- LAST scene = THE LESSON (answer the what-if): land the ONE real takeaway in a single punchy, "
    "memorable line with a slightly dark or witty edge. It must TEACH (this is \"Bolt EXPLAINS\") and "
    "answer the title's question — not just a joke. CRITICAL: the lesson is the REAL limiting science "
    "for THIS scenario — the actual physical wall that ends it — NOT an invented cosmic fate. Examples: "
    "GROWTH → the SQUARE-CUBE LAW (mass grows as the CUBE of height, so you collapse under your own "
    "weight and your heart can't pump blood upward LONG before you get huge); weight-GAIN → mobility and "
    "structural limits; SHRINK → stop when the human-body model ceases to apply; COOLING → ABSOLUTE ZERO "
    "(-273.15 degrees C; quantum zero-point motion remains). Do NOT end on 'black hole', 'a star', "
    "'bending spacetime' or 'bigger than the Sun' unless the authoritative numbers actually reach that "
    "scale. Then loop by echoing the Scene-1 question.\n"
    "- ONE OPEN QUESTION only (the title). Never open a second question.\n"
    "\n*** POV + VISUALS ***\n"
    "- ONE persistent POV: keep the SAME character in EVERY scene — {mascot_name} is the on-screen "
    "stand-in for YOU, visibly UNDERGOING the change (getting heavier/bigger/etc.) and physically "
    "REACTING each scene (straining, buckling, bracing, overwhelmed). Give him an ACTION per scene; "
    "never a passive bystander.\n"
    "- Escalate the CONTEXT only when the compiled scale supports it. Keep a room, body, or lab setting "
    "when the totals never justify a building, city, or orbital view.\n"
    "- SHOW THE MAGNITUDE — CALIBRATE THE PICTURE TO THE NUMBER (the #1 rule for this format; today's "
    "test failed here): EVERY image_prompt MUST draw {mascot_name} visibly AT this scene's current "
    "magnitude — transformed in the correct direction from the previous scene — AND include a "
    "CONSTANT real-world SCALE REFERENCE in frame (a human, a car, a house, then the city skyline) so "
    "the change READS in half a second. The picture MUST agree with the spoken number: audio says "
    "house-sized -> draw him dwarfing a tiny car; audio says crushing the floor -> show him sunk into a "
    "cratered, splintering floor; audio says his own gravity pulls things in -> objects visibly bending "
    "toward him. NEVER draw a normal-sized, unaffected {mascot_name} while the narration says he is "
    "enormous/immense/collapsing — that word-picture MISMATCH is exactly what makes this format fall "
    "flat. Write the magnitude + the scale-reference object explicitly INTO every image_prompt; the "
    "transformation is the HERO of the frame.\n"
    "- ONE HERO PER FRAME; big simple shapes; a muted viewer must read it in ~0.5s.\n"
    "- CRITICAL: NO text, letters, or NUMBERS baked into any image_prompt (the model garbles them and "
    "it looks cheap). The spoken number rides in the karaoke captions; convey magnitude in the image "
    "through SCALE and consequence, never written figures.\n"
    "- Shift the LOOK across adjacent scenes (camera angle / environment / scale / lighting) so it "
    "never feels like a slideshow; design connected transitions where the escalating subject carries "
    "from one scene into the next. Use the CHANNEL COLOR CODE provided below.\n"
).format(mascot_name=MASCOT_NAME)


# ── Legacy display helpers (the active math compiler is bolt_video.simulation) ─────
# LLMs are unreliable at "1cm/s x 86,400s" (a real render said 1 day = 1,800 m; it is 864 m). So we
# COMPUTE the checkpoint values in code (linear: rate x elapsed) and hand the model authoritative
# numbers + a fixed size-comparison ladder, so BOTH the narration and each image_prompt stay accurate
# AND the on-screen scale progresses consistently instead of wobbling. Compounding ("1% every second")
# explodes absurdly and is skipped (the prompt handles it).
_SIM_CHECKPOINTS = [("1 minute", 60), ("10 minutes", 600), ("1 hour", 3600), ("6 hours", 21600),
                    ("1 day", 86400), ("1 week", 604800), ("1 month", 2_592_000),
                    ("1 year", 31_536_000)]
_SIM_LEN_M = {"cm": 0.01, "centimeter": 0.01, "centimeters": 0.01, "centimetre": 0.01,
              "centimetres": 0.01, "mm": 0.001, "m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0,
              "metres": 1.0, "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0}
_SIM_MASS_KG = {"kg": 1.0, "kilogram": 1.0, "kilograms": 1.0, "g": 0.001, "gram": 0.001,
                "grams": 0.001, "tonne": 1000.0, "tonnes": 1000.0, "ton": 1000.0, "tons": 1000.0,
                "lb": 0.4536, "lbs": 0.4536, "pound": 0.4536, "pounds": 0.4536}
_SIM_PERIOD_S = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def _fmt_len(m: float) -> str:
    if m < 1:    return f"{m*100:.0f} cm"
    if m < 1000: return f"{m:.0f} m"
    return f"{m/1000:,.0f} km"


def _cmp_len(m: float) -> str:
    if m < 2:       return "only a little taller than a person"
    if m < 10:      return "taller than a two-storey house"
    if m < 50:      return "as tall as the tallest trees"
    if m < 250:     return "as tall as a skyscraper"
    if m < 2000:    return "dwarfing the whole city skyline"
    if m < 10000:   return "reaching up into the clouds"
    if m < 50000:   return "towering into the stratosphere"
    if m < 120000:  return "at the very edge of space"
    return "rising from the ground up into orbit"


def _fmt_mass(kg: float) -> str:
    if kg < 1000:    return f"{kg:.0f} kg"
    if kg < 1e6:     return f"{kg/1000:,.0f} tonnes"
    if kg < 1e9:     return f"{kg/1e6:,.1f} million kg"
    return f"{kg/1e9:,.1f} billion kg"


def _cmp_mass(kg: float) -> str:
    if kg < 300:   return "like a couple of extra adults on you"
    if kg < 3000:  return "about the weight of a car"
    if kg < 40000: return "as heavy as a loaded truck"
    if kg < 2e5:   return "the weight of a house"
    if kg < 1e8:   return "the weight of a large ship or building"
    if kg < 1e12:  return "the weight of a large hill"     # 1e8-1e12 kg: hill / small landform
    if kg < 1e18:  return "a mountain-scale mass"          # Everest ~1e15 kg
    if kg < 1e23:  return "an asteroid-to-moon-scale mass" # Moon ~7e22 kg
    return "a planet-scale mass"                           # Earth ~6e24 kg — only HERE is it a planet


def _plur(n: int, word: str) -> str:
    """'1 second' / '2 seconds' — correct singular/plural so ladders never read '1 seconds'."""
    return f"{n} {word}" + ("" if n == 1 else "s")


def _fmt_dur(sec: float) -> str:
    # Spell time out ("70 seconds" / "5 minutes") — the compact "1m 10s" form collided with sizes like
    # "1 m tall" (m = minute vs metre), so the model conflated time and size and smoothed the numbers.
    sec = max(0, int(round(sec)))
    if sec < 120:  return _plur(sec, "second")
    m, s = divmod(sec, 60)
    if m < 60:     return _plur(m, "minute") + (f" {_plur(s, 'second')}" if s else "")
    h, m = divmod(m, 60)
    return _plur(h, "hour") + (f" {_plur(m, 'minute')}" if m else "")


_SIM_DECREASE_WORDS = ("shrank", "shrink", "shrinking", "shrunk", "shrunken", "lost", "lose", "losing",
                       "slower", "colder", "cooler", "dimmer", "darker", "quieter", "weaker", "younger",
                       "lighter", "smaller", "fewer", "dropped", "decrease", "decreased", "cooled")


def _sim_decreasing(title: str) -> bool:
    """True when the sim quantity DEcreases (shrink/lose/colder/...). Its ladder must count DOWN
    toward a real floor (vanishing / absolute zero), not up — the increasing ladder is wrong for it."""
    import re
    t = (title or "").lower()
    return any(re.search(r'\b' + w + r'\b', t) for w in _SIM_DECREASE_WORDS)


def _sim_decreasing_rows(rate_per_s: float, kind: str, unit_raw: str, title: str):
    """Build a DECREASING checkpoint ladder from a real human baseline down to a real physical floor.
    Decreasing quantities hit their floor fast, so checkpoints are in ELAPSED TIME to meaningful
    thresholds (not fixed 1min..1yr). Returns (rows, climax_note)."""
    t = title.lower()
    if kind == "len":                       # SHRINK — from ~1.7 m human height down through scale
        start = 1.7
        rows = []
        for size, desc in [(1.0, "the size of a small child"),
                           (0.3, "the size of a house cat"),
                           (0.1, "mouse-sized — you shed body heat dangerously fast"),
                           (0.01, "insect-sized — surface tension turns a water drop into a deadly trap")]:
            tt = (start - size) / rate_per_s
            if tt > 0:
                rows.append(f"- {_fmt_dur(tt)}: {_fmt_len(size)} tall — {desc}")
        rows.append(f"- ~{_fmt_dur(start / rate_per_s)} (a sudden final second): you plunge through every "
                    "remaining scale — a dust speck, then a single CELL (Brownian motion hurls you "
                    "around), a virus (van der Waals forces glue you to surfaces), a molecule, then one ATOM")
        rows.append("- MODEL LIMIT: stop before microscopic scales; a scaled human-body model no longer "
                    "describes matter or biology reliably")
        note = ("DECREASING (shrink) sim: you stay roughly visible for MOST of the runtime, then cross all "
                "the microscopic scales in a sudden final-second plunge — lean into that slow-then-gone "
                "reveal. Stop when the human-body model fails; do not invent a quantum floor for a person.")
        return rows, note
    if kind == "mass":                      # LOSE WEIGHT — from ~70 kg down to nothing
        start = 70.0
        rows = []
        for kg, desc in [(50, "fat reserves gone; your body starts burning muscle"),
                         (35, "severe wasting — organs strain to keep you alive"),
                         (20, "skin and bone, the heart weakening"),
                         (5, "organ failure sets in")]:
            tt = (start - kg) / rate_per_s
            if tt > 0:
                rows.append(f"- {_fmt_dur(tt)}: {kg:.0f} kg — {desc}")
        rows.append(f"- ~{_fmt_dur(start / rate_per_s)}: nothing left — you're gone")
        note = ("DECREASING (weight-loss) sim: mass falls to zero fast; the climax is total bodily "
                "failure, NOT a cosmic event.")
        return rows, note
    if ("degree" in t or "temperature" in t) and any(w in t for w in ("cold", "colder", "cool", "cooler", "cooled")):
        start, floor = 37.0, -273.15        # COOLING — body temp down to absolute zero
        rows = []
        for c, desc in [(35, "shivering starts — hypothermia sets in"),
                        (28, "confusion, your heartbeat turns erratic"),
                        (0, "your body water freezes; ice crystals rupture every cell"),
                        (-196, "colder than liquid nitrogen — flesh is brittle as glass")]:
            tt = (start - c) / rate_per_s
            if tt > 0:
                rows.append(f"- {_fmt_dur(tt)}: {c:.0f} degrees C — {desc}")
        rows.append(f"- ~{_fmt_dur((start - floor) / rate_per_s)}: absolute zero, -273.15 degrees C — "
                    "the thermodynamic floor; quantum zero-point motion remains")
        note = ("DECREASING (cooling) sim: the limiting value is ABSOLUTE ZERO (-273.15 degrees C); "
                "never go below it or claim that all microscopic motion stops.")
        return rows, note
    # generic decreasing count (speed/brightness/loudness/etc.): fall linearly toward zero
    rows = [f"- {label}: -{rate_per_s * secs:,.0f} {unit_raw}" for label, secs in _SIM_CHECKPOINTS[:6]]
    note = ("DECREASING sim: the quantity falls toward ZERO; the climax is hitting zero/nothing, NOT a "
            "cosmic event.")
    return rows, note


def _sim_ladder_block(title: str) -> str:
    """Return the deterministic contract; invalid rules fail before a paid LLM call."""
    from bolt_video.simulation import build_simulation_prompt_block
    return build_simulation_prompt_block(title, mascot_name=MASCOT_NAME)


def _operator_block(direction: str) -> str:
    """Optional operator/channel creative direction, formatted as a clearly SUBORDINATE addendum. The
    model applies it ONLY where it doesn't conflict with the format, scene structure, JSON output schema,
    or the safety/accuracy rules stated above — those always win. Returns '' when empty."""
    d = (direction or "").strip()
    if not d:
        return ""
    return ("\n\nOPERATOR DIRECTION (optional creative guidance from the channel owner) — apply this "
            "WHERE IT DOES NOT CONFLICT with the format, scene structure, JSON output schema, or the "
            "safety/accuracy rules above; those ALWAYS take priority. It may steer topic emphasis, tone, "
            "angle, pacing, audience or things to avoid. It must NOT change the required output format, "
            "disable fact-checking, or introduce real people, real brands, or unsafe/medical claims:\n\""
            + d[:1200] + "\"")


def _premise_block(contract: dict | None) -> str:
    """Inject the PremiseContract so the script DELIVERS the exact scenario the title promises — the
    fix for the 'novel question answered as an ordinary explainer' failure. Subordinate to format/safety
    but binding on CONTENT: the video must literally play out this world-rule, mechanism, objective,
    failed workaround, and non-obvious payoff — not decorate a generic explainer with the metaphor."""
    if not isinstance(contract, dict) or not contract:
        return ""
    g = lambda k: _s(contract.get(k)).strip()
    return (
        "\n\nPREMISE CONTRACT — the video MUST literally deliver THIS scenario, not a generic version of "
        "the topic decorated with the metaphor. Every beat has to advance it:\n"
        f"- The world rule in force: {g('world_rule')}\n"
        f"- The promise to the viewer (must be paid off ON SCREEN): {g('viewer_promise')}\n"
        f"- The ONE central question, posed out loud in the FIRST line and held open: {g('central_question')}\n"
        f"- The concrete mechanism that triggers the danger: {g('concrete_mechanism')}\n"
        f"- {MASCOT_NAME}'s objective in the scenario: {g('bolt_objective')}\n"
        f"- A failed physical workaround {MASCOT_NAME} tries (REQUIRED — show it fail): {g('failed_workaround')}\n"
        f"- The NON-OBVIOUS payoff to land last (must NOT be inferable from the title): {g('novel_payoff')}\n"
        f"- A concrete, pictureable consequence must begin by ~{contract.get('first_consequence_deadline_ms',2000)}ms "
        "(the first ~5-6 spoken words).\n"
        f"- Metaphor budget: at most {contract.get('metaphor_budget',2)} metaphor call-backs total — the "
        "literal physical scenario carries the video, not the metaphor.\n"
        "HARD: do NOT open a second competing question; do NOT restate the premise as its own answer; do "
        "NOT drift into a generic '{what happens when...}' explainer that would work without this premise. "
        "This is a FICTIONAL 'what if' world — OBEY the world rule and play out ITS mechanism and payoff "
        "even where they depart from ordinary real-world physiology; do NOT retreat into explaining the "
        "everyday real biology as the answer (that is the generic failure). Any REAL science you still "
        "mention must remain accurate, but the SCENARIO's own rule wins when they conflict.")


def generate_script(question: str, duration_sec: int = 90, style: str = "engaging and scientific",
                    image_guidance: str = "", video_format: str = "landscape",
                    series: str = "", improve_note: str = "", short_template: str = "auto",
                    operator_direction: str = "", premise_contract: dict | None = None,
                    story_format: str = "standard_explainer",
                    research_dossier: dict | None = None) -> dict:
    n_scenes = scene_count_for(duration_sec, video_format)
    # ROUTING (2026-07-07): ALL long-form (landscape) goes through the BEAT-SHEET (plan→expand→dedup),
    # regardless of scene count — verified materially higher quality than the single-call path even at
    # small counts (78 vs 59: the single-call path lacks the beat-sheet's hook/throughline/climax
    # structure). This retires the deficient non-chunked landscape path (recap ending, weak hook, no
    # dedup). SOCIAL keeps the single-call social beat-map path (loop, <8-word hook, central conceit),
    # capped at CHUNK_THRESHOLD scenes so a "short" past ~72s isn't built as a mini-lecture.
    if video_format == "social":
        if n_scenes > CHUNK_THRESHOLD:
            n_scenes = CHUNK_THRESHOLD
        # Simulation lines carry a checkpoint number + real science, so they run ~11 words (~4s) even
        # with the cadence rule — too many scenes then overshoot the target length. Cap the sim lane to
        # ~11 scenes (hook + the 8 authoritative checkpoints + lesson) so it lands snappy (~45-52s).
        _sim = (short_template == "simulation"
                or (short_template not in ("explainer", "simulation") and _is_simulation_short(question)))
        if _sim:
            n_scenes = min(n_scenes, 11)
    else:
        sc = _generate_script_chunked(question, duration_sec, style, image_guidance, n_scenes,
                                      series, improve_note, operator_direction, story_format,
                                      research_dossier)
        # A sourced long-form draft must not be rewritten by a claim-unaware hook patch. The
        # fail-closed story validator rejects a missing subject and the replan keeps bindings intact.
        if not research_dossier:
            sc, _hc = _ensure_hook_names_subject(sc, question)
            if _hc:
                sc["_script_cost_usd"] = round(float(sc.get("_script_cost_usd") or 0.0) + _hc, 4)
        return sc

    # MEASURED TTS-1-HD speaking rate = ~2.64 w/s across 45 rendered videos (the old "3.5 w/s" comment
    # was wrong); budget at 2.7 (a hair conservative) so the model's word count lands the target
    # duration. This SINGLE-CALL path (social + non-chunked landscape <=24 scenes / <=120s) HITS its
    # word budget, so 3.2 here overran audio ~21% past the image cadence. ("Verified good on the 5-min
    # renders" applied only to the CHUNKED beat-sheet path (~line 826), which UNDER-writes its budget;
    # that path now uses 2.8 for a tighter ~690-word script (retention rework).) For a CAPPED social
    # base the budget on the capped scene count, not raw duration, so it stays a ~3s-cadence short.
    if video_format == "social":
        budget_dur = min(duration_sec, n_scenes * 3)   # n_scenes already capped at 24 (≈72s)
        total_words = int(budget_dur * 2.7)
    else:
        # Budget at the rate the RUNTIME PLANNER actually measures, not an optimistic one. 2.7
        # words/sec here against runtime_planner's 1.95 (minus punctuation and inter-scene pauses,
        # ~1.83 effective) meant the script was written ~45% over its own contract: a 90s request
        # produced 279 words and a 152.8s estimate against a 161-171 word allowance, and the refit
        # returned the same number twice because no rewrite can absorb a gap that large.
        total_words = int(_planned_words_for(duration_sec, n_scenes))
    # The wpm FLOOR is also part of the cadence bug: max(12,…) forced >=12 words/scene (~4.5s) even
    # after recalibration. Social uses a 6-word floor so per-scene audio can reach ~3s.
    word_floor = 6 if video_format == "social" else 12
    # Scene count and word floor have to agree with the runtime, and for short long-form they did
    # not: a 90s request yields 18 scenes, and 18 x the 12-word floor is 216 words against a ~165
    # word budget — over the runtime contract before a single line is written, which is why the
    # refit could not rescue it (it ran twice and returned the same 152.8s both times). Drop scenes
    # until the floor fits rather than asking for narration that cannot be short enough.
    if video_format != "social" and n_scenes * word_floor > total_words:
        n_scenes = max(4, total_words // word_floor)
    # Round rather than floor: truncating the per-scene budget loses up to one word per scene, which
    # on an 18-scene script is a whole scene's worth of runtime and pushed the estimate under the
    # window from the other side.
    wpm = max(word_floor, round(total_words / max(1, n_scenes)))

    # Optional user setting/theme steer — SMART LEAN: use it as the preferred world and
    # metaphor source where it strengthens the explanation; drop it where it'd be forced.
    # It steers settings/analogies ONLY — never the render style or the host's design.
    guidance = (image_guidance or "").strip()
    if guidance:
        theme_block = (
            f"\nTHEME / SETTING (user guidance): \"{guidance}\"\n"
            "- Use this as the PREFERRED real-world setting and source of visual metaphors:"
            " choose environments, props, and analogies drawn from it wherever they make the"
            " science clearer or more relatable (e.g. set scenes there, explain ideas through"
            " its objects and actions).\n"
            "- LEAN INTO IT, but do not force it: for any scene where this theme would be"
            " confusing or absurd, quietly use the clearest environment instead.\n"
            "- It steers SETTINGS and METAPHORS ONLY. Never let it change the render style, and"
            f" keep {MASCOT_NAME} exactly as described (he can appear within the theme's world).\n"
        )
    else:
        theme_block = ""

    # Social (vertical short): a sharp, fast, looping structure — overrides the calm
    # explainer pacing above. This is what separates a viral Short from a mini-explainer.
    # Template routing (social only): explicit override wins; "auto" uses the title heuristic.
    _use_sim = (short_template == "simulation"
                or (short_template not in ("explainer", "simulation") and _is_simulation_short(question)))
    if video_format == "social" and _use_sim:
        social_block = _SIM_SOCIAL_BLOCK + _sim_ladder_block(question)
    elif video_format == "social":
        social_block = (
            "\nSOCIAL SHORT — OVERRIDE the pacing/ending rules above with THIS exact beat map "
            "(it's a scroll-stopping, looping vertical short, not a calm explainer):\n"
            "\n*** THE #1 RULE — CENTRAL CONCEIT (a short LIVES OR DIES on this) ***\n"
            "The hook in Scene 1 sets up a single FRAMING DEVICE — a metaphor or lens "
            "(e.g. \"sleep is something you PAY FOR\"). That conceit is the SPINE of the whole "
            "video, not just the opener. EVERY body scene must ADVANCE the SAME conceit with a "
            "new, escalating beat — never drift into a generic fact-list. If the hook is "
            "\"what if you paid for sleep\", the body is: the nightly price tag → what a cheap vs "
            "premium night buys → a missed payment → sleep DEBT compounding → the collector comes "
            "due. Same frame, rising stakes. A viewer must feel the hook's promise being PAID OFF "
            "scene by scene. State this conceit to yourself, then check that 80%+ of scenes "
            "explicitly live inside it.\n"
            "\n*** THE #2 RULE — A COMPLETE STORY, NOT A FACT-LIST ***\n"
            "Tell ONE causal story on a 5-rung ladder, each rung CAUSED BY the one before:\n"
            "  (1) ANCHOR — open on the ORDINARY, FAMILIAR thing the viewer already knows and trusts "
            "(a match, a candle, a glass of water, an everyday job). Wonder/horror comes from "
            "CORRUPTING the familiar: a viewer cannot care about people/places they cannot picture, "
            "but they CAN care about the everyday object in their own hand. Name what this is about "
            "in plain words by Scene 2 — never leave the viewer unsure of the subject.\n"
            "  (2) CORRUPTION — reveal the hidden cause inside that familiar thing.\n"
            "  (3) ESCALATION — 2-3 consequences, each WORSE than the last.\n"
            "  (4) SIGNATURE REVEAL — the SINGLE most surprising/weird image in the whole story. Name "
            "it to yourself, then WITHHOLD it until ~70% (around the second-to-last beat). Do NOT "
            "spend it in Scene 1 — once the weirdest card is played, every later scene is downhill.\n"
            "  (5) TWIST/MORAL — reframe the anchor so it now MEANS something, then loop.\n"
            "CAUSAL-SPINE TEST: between every two beats you must be able to say '...AND SO...' or "
            "'...BUT THEN...'. If a beat only joins with '...also...' it is a LIST ITEM — cut it or "
            "re-link it. Every beat must ADVANCE THE ONE central question (below) — a beat that doesn't "
            "move that question forward is a tangent; cut it. NEVER restate an image or fact an earlier "
            "beat already showed (repeating the same reveal 3-5 times is the #1 thing that makes a short "
            "feel like a list, not a story).\n"
            "\n*** THE #3 RULE — POSE ONE CLEAR CENTRAL QUESTION (this is what CONFUSES viewers) ***\n"
            "By Scene 2 the viewer must know EXACTLY what question this video answers. State ONE clear, "
            "specific question out loud — the video's PROMISE — and WITHHOLD its answer until the reveal. "
            "e.g. 'Why do planes fly at EXACTLY 35,000 feet — never higher, never lower?' / 'Whose teeth "
            "were really in the president's mouth?'. RULES: (a) exactly ONE OPEN QUESTION may be live at "
            "a time — NEVER open a second competing question the viewer must also track (this is the #1 "
            "source of confusion); (b) do NOT answer it early — every middle beat builds toward it; "
            "(c) any background the viewer needs FIRST must be a DECLARATIVE causal beat ('First, see how "
            "he lost them —' as a STATEMENT), NEVER phrased as its own question ('why did they fall "
            "out?') — a second '?' opens a parallel loop and breaks the one-question rule; (d) the "
            "cold-open must NOT state the ANSWER/conclusion/mechanism (no 'it's about money', no 'blood "
            "pools upward' payoff) — withhold the ANSWER; but the QUESTION/premise is NOT the answer, it "
            "is the CONTEXT, so state it up front (see e); (e) the central QUESTION/premise must land IN "
            "THE HOOK so a cold viewer INSTANTLY grasps WHAT the video is about — put it in Scene 1 "
            "(ideally the very FIRST line, kept short: for a 'what if X?' topic OPEN with the what-if "
            "itself — 'What if gravity dropped just 0.5%?'), or fuse it with the relatable anchor "
            "('What if gravity weakened 0.5%? Your coffee would suddenly feel lighter…'); NEVER later "
            "than Scene 2, and NEVER open on a CRYPTIC consequence ('your coffee weighed less') that only "
            "makes sense AFTER the question is revealed later — that is exactly what drops the viewer "
            "into the middle of an explanation. Do NOT leave the question only in the title; (f) if the "
            "topic has TWO natural prongs (e.g. 'why he lost them' + 'whose replaced them'), PICK THE "
            "SINGLE most gripping one as the whole short and make the other a ONE-LINE declarative setup "
            "— a 15-scene short has NO room to pose AND answer a second question; never split it into "
            "two halves. SELF-CHECK before you finish: the CONTEXT is clear from line 1 (a cold viewer "
            "knows what the video is about), exactly ONE '?' promise is open, and it is answered LAST.\n"
            "\nBEAT MAP:\n"
            "- SCENE 1 = PLAIN SPOKEN HOOK + VISUAL CONCEIT: the first narration line is UNDER 8 WORDS "
            "and INSTANTLY understandable by anyone in half a second — a concrete, human, LITERAL "
            "stake or scenario in plain language. The STRONGEST hooks TRIGGER A BODY REACTION or "
            "directly address the viewer (\"Don't scratch — too late.\" / \"You're about to feel "
            "itchy.\" / \"What if you had to pay for sleep?\") — make the viewer FEEL or DO something "
            "in the first second, not just understand a concept. Do NOT open with the metaphor, a "
            "poetic image, or wordplay — a viewer must feel the STAKES before they decode any frame. "
            "OPEN ON A CURIOSITY GAP — a counterintuitive contrast (\"It wasn't X — it was Y\") OR a "
            "visceral present-moment stake (\"Feel that?\"); WITHHOLD the payoff. NEVER give away the "
            "conclusion in line 1, and never open with a flat past-tense history fact (\"X once "
            "happened\") — both kill the curiosity. "
            "Scene 1 IS the ANCHOR (ladder rung 1): the ordinary, familiar object/action, with a "
            "stake — and it must NOT contain the SIGNATURE REVEAL (rung 4, the weirdest image), which "
            "is withheld to ~70%. (e.g. for glowing match-factory jaws, open on the everyday match/"
            "candle and the stake, NOT on \"their jaws glowed\".) "
            "The "
            "conceit is planted VISUALLY here: the first IMAGE literalizes the framing device. NO slow "
            "setup, NO 'have you ever wondered', NO 'imagine that...'.\n"
            "- SCENE 2 = SHOW THE DANGER BEGIN (scene, not definition): if Scene 1 already stated the "
            "central question, do NOT restate it; if Scene 1 was a pure body-reaction/anchor hook, Scene 2 "
            "MAY state the ONE central question plainly here (once). Either way NEVER open a SECOND, "
            "competing question. Dramatize the event starting "
            "to go wrong — the first warning sign, the bridge beginning to tremble — so the viewer FEELS "
            "the disaster unfold in real time and NEEDS the answer, WITHOUT asking anything "
            "(\"...and at first, nothing looked wrong. Then it started to shake.\"). Hold the science "
            "for the next beats.\n"
            "- MIDDLE scenes = INFORMATION JOURNEY (the #1 thing separating memorable from "
            "forgettable): each scene ADVANCES THE REAL MECHANISM one concrete step — a NEW part of "
            "the actual process, NEVER the same idea restated louder. Each body scene must be CAUSED "
            "BY the previous one (the AND-SO / BUT-THEN chain), not a parallel fact dropped beside it. "
            "Walk the viewer THROUGH the real "
            "thing (e.g. itch: irritant on skin → cells release HISTAMINE → an itch NERVE fires → the "
            "BRAIN demands a scratch → scratching masks it with mild PAIN → skin damage makes it "
            "worse). NAME the real parts/terms (the actual chemicals, nerves, forces) — the conceit is "
            "the through-line, NOT a substitute for the science. COMPRESS the mechanism to AT MOST "
            "2-3 beats, ONE idea per beat — give the gist and the gut-punch, NOT every step. FEEL "
            "BEFORE JARGON: hit a relatable analogy FIRST (\"pushed like a kid on a swing\"), THEN name "
            "the term. The danger must visibly ESCALATE (small → bigger → break), never sit flat. Use "
            "ONE frame only (never stack "
            "bell+wire+siren+flood); do NOT just make the metaphor louder each scene. Short punchy "
            "sentences; vary sentence length (some scenes are a 3-word punch). The CONCEIT stays "
            "constant but the LOOK must not: across adjacent scenes shift at least 2 of these 4 — "
            "(a) camera (wide establishing / medium / extreme close-up / overhead / ground-level), "
            "(b) environment (indoor↔outdoor, or realistic↔abstract), (c) Bolt's scale (central & "
            "large ↔ small & distant), (d) lighting/energy (bright day ↔ dim night, calm ↔ frantic). "
            "Never let two consecutive scenes share the same framing feel (that 'slideshow' sameness "
            "kills pacing and rewatch).\n"
            "- SECOND-TO-LAST = TWIST / ONE UNCOMFORTABLE TRUTH: the most memorable line in the video "
            "— a COUNTERINTUITIVE truth or an uneasy real consequence the viewer will repeat (e.g. "
            "\"scratching feels good because it slightly HURTS\" / \"for some people the alarm never "
            "shuts off\"). It must reframe everything (\"wait, that changes it\"), NOT a neutral "
            "add-on fact. Pair it with a fresh visual surprise. This is the final acceleration before "
            "the loop.\n"
            "- LAST scene = LOOP: final narration line ECHOES the opening line almost verbatim so the "
            "video restarts seamlessly. Curiosity stays OPEN; NO recap, NO call-to-action, NO sign-off.\n"
            "\n*** {mascot_name} ACTS OUT THE CONCEIT (not a bystander) ***\n"
            "In EVERY scene {mascot_name} physically DOES something inside the frame — handing over "
            "coins for a night's sleep, getting an overdraft alert, dodging a debt collector, "
            "weighing options. Give him an ACTION VERB per scene. Passive 'Bolt stands beside a "
            "glowing concept' is BANNED.\n"
            "\n*** ONE VISUAL SURPRISE PER SCENE (NO TEXT IN THE IMAGE) ***\n"
            "Each image_prompt must literalize the conceit with one unexpected, concrete OBJECT or "
            "ACTION (a coin slot in the headboard, a piggy bank cracking, a sand-timer draining onto "
            "the pillow, a vault door on the closet, a meter needle redlining) — never a generic "
            "illustration, and NEVER convey it through a sign, label, receipt, price tag, barcode, "
            "screen text, or number, which render as garbled AI text and look cheap.\n"
            "\n*** ONE REWATCH CALLBACK ***\n"
            "Plant ONE concrete conceit object in Scene 1's image_prompt (e.g. a coin, a ticking "
            "clock, a piggy bank) and name that SAME object in at least 3 scenes' image_prompts. Have "
            "it visibly TRANSFORM or pay off in the final two scenes (the piggy bank now smashed; the "
            "clock now empty) so a looping viewer catches the arc on the second pass. ONE callback "
            "object only — don't bloat it with multiple Easter eggs.\n"
            "\n*** INFORMATION-DESIGN DISCIPLINE (keep the grounded look, but it must READ like a "
            "moving diagram, not just a pretty scene) ***\n"
            "- ONE HERO PER FRAME: each image_prompt has exactly ONE hero (usually the thing the "
            "scene teaches) + at most ONE supporting element. {mascot_name} is the GUIDE, not always "
            "the star — when the science is the point, make the science the hero and {mascot_name} "
            "smaller, pointing/reacting at the edge. Uncluttered: no competing extra objects.\n"
            "- SEMANTIC COLOR CODE: use the CHANNEL COLOR CODE provided below — map each scene's key "
            "element to the ROLE it plays and use that role's FIXED colour, named in the image_prompt. "
            "Do NOT invent per-video colour meanings; the channel code is the same in every video.\n"
            "- LEGIBLE IN HALF A SECOND: a muted viewer must grasp the frame in ~0.5s — big simple "
            "shapes, one clear focal point. For body/mechanism beats use a CLEAN CUTAWAY (simplified "
            "skin layers / a single nerve line / the brain) — grounded and lit, but legible like a "
            "diagram, never a busy realistic texture. CRITICAL: the cutaway is UNLABELED — NO text, "
            "letters, numbers, or callout labels baked into the image (the model garbles them and the "
            "renderer's captions already supply the words). Convey meaning with shape and the semantic "
            "colour, NOT with written labels.\n"
            "- CONNECTED TRANSITIONS: design adjacent scenes so one object carries into the next "
            "(the alarm light becomes the orange chemical; the chemical travels the blue nerve to "
            "the brain) — a planned chain, not unrelated cuts.\n"
        ).format(mascot_name=MASCOT_NAME)
        # A Short is the same story discipline compressed, not a different doctrine. Appended after
        # the beat map so it constrains how that map is filled rather than competing with it.
        social_block += _STORY_LED_DNA_SHORT + _story_role_block("evidence_led_short")
    else:
        social_block = ""

    prompt = _SCRIPT_PROMPT.format(
        question=question,
        duration=duration_sec,
        style=style,
        n_scenes=n_scenes,
        last_minus_1=n_scenes - 1,
        total_words=total_words,
        total_words_max=int(total_words * 1.1),
        wpm=wpm,
        # Social floors lower (4) so the per-scene range stays coherent at the 6-word social floor;
        # long-form keeps the 8-word minimum. Always <= wpm so the range can't invert.
        wpm_lo=min(wpm, max(4 if video_format == "social" else 8, wpm - 3)),
        wpm_max=wpm + 3,
        mascot_name=MASCOT_NAME,
        mascot_desc=MASCOT_DESC,
        theme_block=theme_block,
        social_block=social_block,
    )
    prompt += _DESIGN_SYSTEM_TEXT + _series_block(series)   # design grammar + format-series framing
    if improve_note:
        prompt += ("\n\nPRIORITY FIX — the previous draft scored weak here; fix this FIRST while "
                   "keeping everything else: " + improve_note)
    prompt += _premise_block(premise_contract)   # bind the short to its own promise (Gate -1)
    prompt += _operator_block(operator_direction)

    resp = _claude().messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=16000,  # rich cinematic key-art prompts × up to ~24 scenes
        system=_SCRIPT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    script, repair_cost = _parse_script_json(resp.content[0].text)
    u = resp.usage
    _cost = u.input_tokens * _RATE_SCRIPT_IN + u.output_tokens * _RATE_SCRIPT_OUT + repair_cost
    # STATE-ONCE dedup on the non-chunked long-form too — the chunked path already runs it and social
    # runs it in generate_graded_short, but the short (<=2 min) long-form path was missing this layer
    # entirely, which is why its initial repetition score sat low.
    if video_format != "social":
        _scn, _dc = _dedupe_narration(script.get("scenes", []), [], _s(script.get("throughline", "")))
        script["scenes"] = _scn
        _cost += _dc
    script, _hc = _ensure_hook_names_subject(script, question)   # zero-friction: subject named by line 2
    script["_script_cost_usd"] = round(_cost + _hc, 4)
    return script


# Per-scene JSON schema + visual rules, shared by every long-form expansion batch so a scene
# renders identically no matter which batch wrote it.
_SCENE_FIELDS_RULES = (
    'Each scene has: narration, scene_type (real_world_example|metaphor_scene|educational_diagram|'
    'cinematic_intro|experiment_lab|everyday_life|abstract_visualization|recap_scene), '
    'environment_type (classroom|science_lab|home|city|data_center|space|microscopic_world|'
    'digital_world|nature|sports_field|simple_whiteboard|abstract_space), image_prompt (a rich '
    'GROUNDED, real-world scene modeled on the topic — NOT "Bolt beside a glowing concept" and '
    'NOT "Bolt gesturing at a floating diagram"; asymmetric FG/MG/BG; minimize neon/abstract '
    'glow; include EXACTLY ONE unexpected concrete element (not a pile of three) tied to what '
    'THIS scene teaches — a visual metaphor or literal surprise that makes the idea memorable '
    '(e.g. objects frozen mid-fall for gravity), never generic glow or floating particles, and '
    'NEVER convey it through a sign, label, receipt, price tag, barcode, screen text, or number '
    '(those render as garbled AI text and look cheap) — use an OBJECT or ACTION instead; vary '
    'the surprise type across scenes), human_present (true when Alex acts, decides, predicts, reacts, '
    'or carries the personal stake), human_action (specific action toward Alex\'s current objective; '
    'empty only for a pure evidence view), mascot_present (true ONLY when Bolt performs useful story '
    'work), bolt_mode (absent|measurement|demonstration|warning|reaction|assistance). Pure evidence, '
    'location, scale, record, map, and mechanism views normally set mascot_present=false and '
    'bolt_mode="absent". If Bolt appears, the image_prompt must describe the concrete measurement, '
    'test, warning, reaction, or assistance he performs — NEVER standing or pointing beside the topic. '
    'claim_refs (copy the assigned claim_id values; for each, set narration_phrase to an EXACT '
    'consecutive substring of this scene\'s FINAL narration and evidence_id to the assigned evidence_id; '
    'use [] only when the assigned beat has no claims). WHEN YOUR BEAT HAS NO CLAIMS, the narration '
    'must not assert one: no figures, dates or percentages, and no "because", "causes", "therefore", '
    '"leads to" or "results in". Write what is seen and what someone does instead — an unbacked '
    'factual or causal line fails the run before any spend. evidence_id (copy the assigned stable id), '
    'shot_type '
    '(wide|medium|close|aerial|detail), text_overlay (USUALLY EMPTY "" — the subtitles carry the '
    'words; set it ONLY on a genuine reveal/transition/branch scene, and ONLY as a stage label or a '
    'single critical number/symbol, ≤3 words, e.g. "SIGNALS", "+5 SECONDS", "STAGE 2: MATTER" — NEVER '
    'a dramatic headline that merely repeats the narration like "THE FAMOUS NUMBER" or "STITCHED IN '
    'DEEP"), text_sub, and '
    '"text" as a JSON OBJECT with keys placement, alignment, emphasis_words (array), '
    'title_color, accent_color, subtitle_color, card. '
    'EVIDENCE STATE MAP — include "visual_beats" in narration order: 2-4 states for EVERY scene '
    'within the first 30% of runtime, then 1-3 states later. A state is a visible world change, not '
    'a camera angle. '
    'Each object has: "anchor_phrase" (an EXACT consecutive 2-8 word phrase copied from narration '
    'where this visual should begin), "purpose" (setup|action|evidence|consequence), "visual" '
    '(the specific object/action this clause needs), "state_before" and "state_after" (concrete, '
    'visibly distinguishable object conditions), "required_objects" (array of exact objects/states '
    'that must be visible), "forbidden_objects" (array of objects/states that must be absent), '
    '"source" (master|distinct|detail_reframe), "asset_strategy" '
    '(master|distinct|detail_reframe), "detail_target" (required only for detail_reframe), '
    '"pure_evidence" (true for evidence/mechanism/scale/location/record views), "human_visible" '
    '(true only when Alex is visually needed), "bolt_visible" (true only when this exact state '
    'shows Bolt performing the scene\'s permitted useful story work), "bolt_action" (the concrete '
    'measurement, test, warning, reaction, or assistance Bolt performs; empty when bolt_visible is '
    'false), "new_information" (PROVISIONAL only; true only for a '
    'declared state change and ALWAYS false for detail_reframe until pixel verification), "shot_size" '
    '(wide|medium|close|aerial|detail), and "camera_direction" (left_to_right|right_to_left|'
    'push_in|pull_out|locked). Use master for the first connected setup/action. Use distinct when the '
    'world or causal state changes. Use detail_reframe only when the required evidence already exists '
    'inside the master and name the exact detail_target; a crop never earns information automatically. '
    'Pure evidence states MUST omit Bolt even if he appears elsewhere in the scene. '
    'Also include "motion_anchor_phrase": the EXACT 2-8 narration words where physical action begins '
    '(empty only when the beat has no motion). These anchors are edit decisions, not spoken text. '
    'CONTINUITY OVER NOVELTY — this is ONE continuous experiment, not a deck of poster cards: keep a '
    f'single evolving setting/apparatus ({MASCOT_NAME}\'s lab and the instruments he checks in '
    'sequence) and let the SAME object visibly TRANSFORM across neighbouring scenes (a normal atom -> '
    'it contracts -> its colour shifts -> the molecule built from it distorts) rather than cutting to '
    'an unrelated new backdrop every scene. Causality beats frequency: connected shots that advance '
    'ONE idea beat three unrelated images of it. Still vary shot_type and lighting so it never looks '
    'static, and do not reuse the identical framing twice in a row. Do NOT depict real/identifiable '
    'people or brands.'
)


# Spoken-track rhythm. Without this the narration becomes a metronome of same-length declaratives
# (the #1 TTS-monotony retention leak) — force length variance, punch beats, and varied openers.
_NARRATION_CADENCE = (
    ' NARRATION CADENCE (this is the SPOKEN track — sameness is a retention killer): vary sentence '
    'length HARD — mix SHORT punch lines (≤5 words, e.g. "It was gone." "Nobody noticed.") with '
    'longer ones; NEVER write every line at the same ~15-word length. Land a short punch beat at '
    'each tension peak, and ask a genuine direct question at a natural turn in this batch. Vary how '
    'lines open — do NOT start most sentences with "The" or "They". VARY INTENSITY, not only length: '
    'do NOT write every line as a dramatic climax — when every line shouts, none of them lands. Use '
    'CALM, quieter setup lines and NEUTRAL mechanism lines so the genuine payoffs hit with contrast, '
    'and drop a short beat (a 3-4 word line) right AFTER a big reveal to let it breathe.'
)


def _dedupe_narration(scenes: list, beats: list, throughline: str) -> tuple[list, float]:
    """Final 'state once' pass: rewrite ONLY narration lines that re-explain a concept already
    stated in an earlier line (or drift off their assigned beat) so each scene adds something new.
    Count-preserving (keeps the 1:1 scene↔image mapping). Best-effort — any mismatch returns the
    scenes unchanged so this can never break a render."""
    lines = [s.get("narration", "") for s in scenes]
    if len(lines) < 4:
        return scenes, 0.0
    paired = "\n".join(f'{i+1}. [beat: {_s(beats[i].get("beat")) if i < len(beats) else "—"}] {lines[i]}'
                       for i in range(len(lines)))
    sys = ("You are a ruthless script editor enforcing STATE-ONCE on an explainer narration. You get "
           "an ordered list of lines, each tagged with the single BEAT it should cover. Rewrite ONLY "
           "lines that (a) re-explain a concept already stated in an EARLIER line, (b) drift off their "
           "beat, or (c) re-illustrate with YET ANOTHER metaphor a mechanic an EARLIER line already "
           "gave a metaphor (keep ONE metaphor per mechanic — rewrite the redundant ones into their "
           "literal consequence or a new point) — making each rewritten line cover its OWN beat and ADD "
           "something new. Lines "
           "that are already unique and on-beat: return them UNCHANGED. PAY SPECIAL ATTENTION TO THE "
           "FINAL QUARTER (the ending after the climax): laments like 'it is gone', 'lost forever', or "
           "'the restoration is not the original' tend to repeat there — keep ONE of each and rewrite "
           "the rest into DISTINCT closing reflections (or a forward-looking beat). Preserve order, "
           "EXACT count, tone, and approximate length. Never merge, drop, or add lines. Each entry is "
           "the rewritten SPOKEN line ONLY — do NOT include the leading number or the '[beat: …]' tag. "
           'Return ONLY JSON: {"narration":[<exactly one line per input line, same order>]}.')
    try:
        r = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=8000, system=sys,
            messages=[{"role": "user", "content":
                       (f'Throughline: "{throughline}".\n' if throughline else "")
                       + f"Rewrite repeats/drift only, keep all {len(lines)} lines:\n{paired}"}])
        cost = r.usage.input_tokens * _RATE_SCRIPT_IN + r.usage.output_tokens * _RATE_SCRIPT_OUT
        out, rc = _parse_script_json(r.content[0].text); cost += rc
        new = out.get("narration") if isinstance(out, dict) else None
        if isinstance(new, list) and len(new) == len(lines):
            import re as _re
            # The model sometimes echoes the input's "N. [beat: …]" tag into the returned line;
            # strip any leaked leading number and/or [beat:…] tag so TTS never speaks "one, beat dash".
            _pfx = _re.compile(r'^\s*(\d+[.\)]\s*)?(\[beat:[^\]]*\]\s*)?', _re.I)
            for s, nl in zip(scenes, new):
                clean = _pfx.sub("", _s(nl)).strip()
                if clean:
                    s["narration"] = clean
        return scenes, cost
    except Exception:
        return scenes, 0.0


# ── ZERO-FRICTION HOOK GUARD ────────────────────────────────────────────────────────────────────
# The video's SUBJECT must be spoken, BY NAME, in the first ~2 lines. A prompt rule alone kept
# failing: to preserve intrigue the model euphemizes the subject (an Electoral-College hook that
# says "a middleman" / "this system" but never the words "Electoral College"), so a cold viewer
# still has to INFER the topic — exactly the friction we're killing. This is the safety net: pull
# the literal subject terms out of the title, check they appear in the opening lines, and ONLY if
# they don't (fast path = zero LLM cost when the subject is already named) run a surgical LLM rewrite
# of lines 1-3 that NAMES the subject while keeping the PRIME -> QUESTION -> INTRIGUE shape.
_HOOK_STOP = {
    "why", "how", "what", "whats", "when", "where", "who", "whom", "whose", "which", "does", "do",
    "did", "is", "are", "was", "were", "be", "been", "being", "the", "a", "an", "of", "to", "in",
    "on", "at", "for", "and", "or", "if", "it", "its", "so", "we", "you", "your", "really",
    "actually", "just", "ever", "not", "no", "that", "this", "these", "those", "there", "here",
    "about", "into", "from", "with", "without", "than", "then", "but", "can", "could", "would",
    "should", "will", "may", "might", "exist", "exists", "happen", "happens", "happened", "work",
    "works", "mean", "means", "make", "makes", "get", "gets", "have", "has", "had", "our", "us",
    "my", "vs", "versus",
}


def _subject_terms(title: str) -> list:
    """Significant content words from the title — the literal subject a hook must name out loud.
    Uses a Unicode-letter class so accented subjects stay whole ("Niño" is one token, not "Ni"+"o")."""
    import re
    words = re.findall(r"[^\W\d_]+(?:['\-][^\W\d_]+)*", _s(title), re.UNICODE)
    return [w for w in words if w.lower() not in _HOOK_STOP and len(w) > 2]


def _ensure_hook_names_subject(script: dict, title: str, cost_sink=None) -> tuple[dict, float]:
    """Guarantee the opening NAMES the subject (zero-friction). Deterministic pre-filter first (no
    cost when the literal subject terms already appear in lines 1-3); otherwise an LLM judge either
    confirms a synonym names it ('planes' for 'airplanes') or surgically rewrites ONLY lines 1-3 to
    name the subject in a plain PRIME -> QUESTION -> INTRIGUE opener. Count-preserving, best-effort:
    any failure returns the script unchanged, so it can only help."""
    scenes = script.get("scenes", [])
    if len(scenes) < 3:
        return script, 0.0
    terms = _subject_terms(title)
    if not terms:
        return script, 0.0
    opening = " ".join(_s(s.get("narration", "")) for s in scenes[:4]).lower()
    hits = sum(1 for t in terms if t.lower() in opening)
    if hits >= max(1, round(len(terms) * 0.6)):
        return script, 0.0     # subject already named literally in the opening → no cost, no change
    n = min(5, len(scenes))
    numbered = "\n".join(f"{i + 1}. {_s(scenes[i].get('narration'))}" for i in range(n))
    sys = ("You enforce ZERO-FRICTION openings for YouTube explainers. A cold viewer must know the "
           "EXACT subject within the first TWO spoken lines, with the subject NAMED in plain words — "
           "the real noun from the title (e.g. 'the Electoral College', 'jet fuel', 'El Nino') — "
           "NEVER a euphemism or pronoun standing in for it on first mention ('a middleman', 'this "
           "system', 'this thing', 'it').")
    usr = (f'VIDEO SUBJECT (must be named out loud): "{_s(title)}".\n'
           f'Current opening lines:\n{numbered}\n\n'
           'Judge: do lines 1-2 NAME that subject in plain words, so a cold viewer instantly knows '
           'the topic? A close synonym that unambiguously names it counts ("planes" for "airplanes"); '
           'an implied or euphemistic reference does NOT. If YES, return {"ok":true}. If NO, REWRITE '
           'lines 1-3 ONLY so: line 1 = a COLD CONSEQUENCE — the strangest VISIBLE RESULT of the '
           'scenario, stated so the subject is NAMED in plain words (the real noun from the title), with '
           'NO definition and NO exact number; line 2 = the central QUESTION stated plainly WITH THE '
           'SUBJECT NAMED (basically the title spoken as a question); line 3 = reject the obvious answer '
           'and pose a quick prediction or preview of what is coming. Keep them short spoken lines, do '
           'NOT answer the question, do NOT open a second question, keep lines 4+ untouched, and match '
           'the existing voice. Return ONLY JSON {"ok":false,"lines":[l1,l2,l3]}.')
    try:
        r = _claude().messages.create(model=ANTHROPIC_MODEL, max_tokens=700, system=sys,
                                      messages=[{"role": "user", "content": usr}])
        cost = _msg_cost(r.usage)
        out, rc = _parse_script_json(r.content[0].text); cost += rc
        if cost_sink is not None:
            cost_sink.append(cost)
        if isinstance(out, dict) and out.get("ok") is not True:
            new = out.get("lines")
            if isinstance(new, list) and 1 <= len(new) <= 3:
                import re as _re
                _pfx = _re.compile(r'^\s*(\d+[.\)]\s*)?', _re.I)
                for i, nl in enumerate(new):
                    clean = _pfx.sub("", _s(nl)).strip()
                    if clean and i < len(scenes):
                        scenes[i]["narration"] = clean
        return script, cost
    except Exception:
        return script, 0.0


_BOLT_STORY_MODES = frozenset({"measurement", "demonstration", "warning", "reaction", "assistance"})
_BOLT_FORBIDDEN_ROLES = frozenset({"rules", "mechanism"})
_BOLT_ROLE_PRIORITY = {
    "prediction_gate": 0, "reversal": 1, "payoff": 2, "final_payoff": 3,
    "cold_consequence": 4, "rehook": 5,
}


def _plan_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = _s(value).strip().lower()
    if normalized in {"false", "0", "no", "off", "absent"}:
        return False
    if normalized in {"true", "1", "yes", "on", "present"}:
        return True
    return default


def _apply_character_budget(beats: list[dict]) -> dict:
    """Make Bolt selective and report every deterministic override.

    The planner proposes useful roles; this function enforces the release defaults so a
    prompt regression cannot quietly put Bolt back into every scene.
    """
    import math
    n = len(beats)
    first_n = max(1, math.ceil(n * 0.30))
    first_cap = max(1, math.floor(first_n * 0.35))
    total_cap = max(1, math.floor(n * 0.30))
    proposed: list[int] = []
    overrides: list[dict] = []
    for i, beat in enumerate(beats):
        mode = _s(beat.get("bolt_mode")).strip().lower()
        if mode not in _BOLT_STORY_MODES or _s(beat.get("role")) in _BOLT_FORBIDDEN_ROLES:
            beat["bolt_mode"] = "absent"
        else:
            beat["bolt_mode"] = mode
            proposed.append(i)
        if "human_present" not in beat:
            beat["human_present"] = True

    ranked = sorted(proposed, key=lambda i: (
        _BOLT_ROLE_PRIORITY.get(_s(beats[i].get("role")), 20), i))
    keep: set[int] = set()
    first_used = 0
    for i in ranked:
        if len(keep) >= total_cap:
            break
        if i < first_n:
            if first_used >= first_cap:
                continue
            first_used += 1
        keep.add(i)
    for i in proposed:
        if i not in keep:
            overrides.append({"scene": i + 1, "from": beats[i]["bolt_mode"], "to": "absent",
                              "reason": "character_presence_budget"})
            beats[i]["bolt_mode"] = "absent"
    return {
        "first_act_scene_count": first_n,
        "first_act_cap": first_cap,
        "overall_cap": total_cap,
        "bolt_scenes": [i + 1 for i in sorted(keep)],
        "overrides": overrides,
    }


def _evaluate_mystery_suitability(plan: dict, beats: list[dict]) -> tuple[bool, list[str]]:
    """Deterministically verify that a proposed mystery has something to investigate."""
    reasons: list[str] = []
    for key in ("anomaly", "accepted_belief", "contradictory_evidence",
                "recurring_location", "subject_goal"):
        if not _s(plan.get(key)):
            reasons.append(f"missing {key}")
    evidence_beats = [b for b in beats if _s(b.get("actual_outcome"))
                      or _s(b.get("visible_consequence"))]
    if len(evidence_beats) < 3:
        reasons.append("fewer than three visible evidence states")
    if not any(_s(b.get("expected_outcome")) and _s(b.get("actual_outcome"))
               and _s(b.get("expected_outcome")).casefold()
               != _s(b.get("actual_outcome")).casefold() for b in beats):
        reasons.append("no failed prediction or test")
    if not any(_s(b.get("belief_changed")) for b in beats):
        reasons.append("no evidence-led belief change")
    if not _plan_bool(plan.get("mystery_suitable")):
        reasons.append(_s(plan.get("mystery_unsuitable_reason")) or "planner marked topic unsuitable")
    return not reasons, reasons


def _opening_expansion_direction(story_format: str, is_first: bool) -> str:
    """Keep scene expansion faithful to the structure selected during planning."""
    if not is_first:
        return ""
    if story_format == "evidence_led_mystery":
        return (
            ' This batch contains the MYSTERY OPENING. Scene 1 shows the concrete anomaly acting '
            'on Alex or the exact opening object and names the title subject. Make Alex\'s objective '
            'legible by eight seconds. The next scenes follow the assigned prediction and evidence '
            'states: deliver a satisfying local clue or failed test by 10-20 seconds, but do not '
            'announce stages, recite a roadmap, or explain the deepest cause before the evidence '
            'earns it. Establish the assigned viewer/Alex knowledge gap through visible proof.'
        )
    return (
        ' This batch contains the OPENING — get to a real ANSWER FAST; do NOT stack hooks. Scene '
        '1 = COLD CONSEQUENCE: open on the single most VISCERAL, high-stakes result the viewer '
        'clicked to see (the DRAMATIC thing, NOT an atmospheric/poetic detail like a subtly '
        'changing shadow) and NAME THE SUBJECT with the actual topic noun (say the real thing, '
        'e.g. "the Electoral College" / "jet fuel" / "the Sun") — NOT a definition, NOT an '
        'exact-number dump, NEVER a euphemism/pronoun ("a middleman", "this system", "it"). Scene '
        '2 = resolve its FIRST mechanism so the viewer already holds a concrete ANSWER (~10s in). '
        'Scenes 3-4 = fast PROMISE: state the central question, NAME THE STAGES, tease the '
        'biggest twist to come, and pose ONE prediction about the DEEPER danger ("which does the '
        'real damage — X, Y, or Z?"), then a second payoff + brief false-relief. Do NOT put more '
        'than two setup/prediction beats before that first resolved answer. Keep the central '
        'question OPEN.'
    )


def _generate_script_chunked(question, duration_sec, style, image_guidance, n_scenes, series="",
                             improve_note="", operator_direction="",
                             story_format="standard_explainer",
                             research_dossier: dict | None = None) -> dict:
    """Long-form: BEAT SHEET → batched expansion → state-once dedup.

    The old approach generated independent chapters that each saw only the previous chapter's last
    two sentences, so each one re-derived the premise — which TRIPLICATED facts (the Moon-tapes
    video taught the same mechanic 4x). Now we: (1) plan ONE scene-by-scene beat sheet where each
    scene owns exactly one idea, every mechanic is introduced once, the opening leads with a cold
    consequence, and payoffs are DISTRIBUTED with the strongest reveal at a designated peak; (2)
    expand in batches that each SEE
    THE WHOLE beat sheet, so no batch can re-teach another's beat; (3) run a final 'state once'
    pass that rewrites any line that still repeats. Each Claude call stays small enough that the
    JSON never truncates."""
    # Plan to the calibrated spoken-runtime window from the first generation call. The hard runtime
    # contract later verifies the landed draft and only invokes a compression pass when the model
    # actually misses, instead of intentionally generating an overlong script and always rewriting it.
    # Scene count and the 12-word floor have to fit inside the runtime window, and for short
    # long-form they did not: 90s yields 18 scenes, whose floor demands 216 words against a 161-171
    # allowance — over the contract before a line is written, which is why the refit returned the
    # same 152.8s twice. Shed scenes until the floor fits; the bounds move with n_scenes (fewer
    # inter-scene pauses buys a few words back), so recompute rather than solving once.
    # 18, not 12. A 12-word floor let a 90s request keep 14 scenes — 6.4 seconds of speech each,
    # which is Shorts pacing on a long-form video, and the model would not write to it: asked for
    # 12 words per scene it produced 18, landing 251 words against a 163-173 allowance, and the
    # compression pass returned the same 137.1s twice because it was being asked to make every
    # scene shorter than a scene can usefully be. Budgeting 18 gives 9 scenes at ~10 seconds each,
    # which is both a natural long-form beat and what the model already writes unprompted. It also
    # buys back cadence room: a long sentence and a short one do not fit inside twelve words.
    _WORD_FLOOR = 18
    while n_scenes > 4 and n_scenes * _WORD_FLOOR > runtime_word_bounds(duration_sec, n_scenes)[2]:
        n_scenes -= 1
    total_words = runtime_word_bounds(duration_sec, n_scenes)[0]
    # Round, not floor: truncating loses up to a word per scene, and across a long sheet that is a
    # whole scene's worth of runtime lost from the other side.
    # Ask for ~18% under budget, because the planner reliably overshoots what it is asked for.
    # Measured across runs: asked for 19 words per scene it wrote 23, landing 209-220 words against
    # a 166-176 allowance. Compression then has to close ~20%, and it only removes 3-6% per pass —
    # so whether a run passed came down to how close its first draft happened to land (run 11
    # converged at 91.8s from 99.7s; run 12 ran out of passes at 106.1s from 113.2s). Correcting the
    # request is deterministic and free; asking compression to absorb a predictable bias is neither.
    # The true budget still governs validation — only the ask is adjusted.
    # The floor governs how many scenes fit the runtime; it must not also clamp the ask, or the
    # correction is a no-op — max(18, 17.8) is 18, which is what the planner was already
    # overshooting from.
    _OVERSHOOT = 0.82
    wpm = max(12, round(total_words * _OVERSHOOT / max(1, n_scenes)))
    cost = 0.0

    # 1) BEAT SHEET — spine in one call: cold-open, throughline, distributed payoffs, one beat/scene.
    beat_prompt = (
        f'Plan a {max(1, duration_sec // 60)}-minute YouTube explainer answering: "{question}".\n'
        f'Tone: {style}.'
        + (f' Theme/setting steer: "{image_guidance}".' if image_guidance else "") + "\n"
        + f'Design a SCENE-BY-SCENE BEAT SHEET of about {n_scenes} beats — one beat per scene, in order. '
        'Make beats GRANULAR: ONE micro-move each (a single consequence, number, or image), NOT a '
        f'summary of several — that is how you reach ~{n_scenes} beats WITHOUT padding. Aim NEAR '
        f'{n_scenes}; returning somewhat fewer is fine ONLY if the topic truly lacks that many DISTINCT '
        'beats — never pad with filler or repetition.\n'
        'Return ONLY JSON: {"title","hook","thumbnail_promise","throughline","false_model",'
        '"replacement_model","personal_stake","anomaly","human_subject":"Alex",'
        '"human_role","recurring_location","subject_goal","antagonistic_force","accepted_belief",'
        '"contradictory_evidence","viewer_initial_belief","viewer_belief_after_reveal",'
        '"opening_object","final_callback_object" (MUST exactly equal opening_object),'
        '"mystery_suitable":true|false,"mystery_unsuitable_reason":"",'
        '"style_mode"(educational|scientific|cinematic'
        '|fun),"stages":[2-4 SHORT ALL-CAPS act labels naming the escalating journey, e.g. '
        '["SIGNALS","MATTER","LIFE"] or ["YOUR BODY","THE PLANET","REALITY"]; for a topic with distinct '
        'TIMESCALES prefer a TEMPORAL ladder like ["INSTANT","MILLIONS OF YEARS","BILLIONS OF YEARS"] so '
        'the timeline itself is the escalation — the visible roadmap the viewer can track],'
        '"peak_scene":<int — the ONE scene with the STRONGEST, most counter-intuitive '
        'reveal, placed ~65-75% through, NOT at the very end>,"payoffs":[the scene numbers that each '
        'deliver a concrete satisfying answer; there must be one roughly every 6-10 scenes and the '
        'FIRST within the opening ~15-20%],"beats":[{"n":<int>,"pct":<int 0-100, this beat\'s position '
        'in the runtime>,"beat":"the SINGLE new idea/fact/story-move for this scene, concrete, one '
        'sentence","role":"cold_consequence|promise|prediction_gate|rules|payoff|escalation|rehook|'
        'mechanism|reversal|branch|false_relief|final_escalation|final_payoff|resonant_end",'
        '"human_present":true|false,"human_intention":"what Alex is trying to accomplish now",'
        '"human_belief":"what Alex believes",'
        '"viewer_knows":"specific evidence visible to the viewer","human_knows":"specific evidence Alex has",'
        '"expected_outcome":"what Alex predicts","actual_outcome":"what visibly occurs",'
        '"belief_changed":"old belief -> new belief or empty","decision_caused":"action forced by evidence",'
        '"continuity_anchor":"recurring subject/location/object visible in this beat",'
        '"causal_link":"because|but|therefore|so plus the preceding-beat connection",'
        '"bolt_mode":"absent|measurement|demonstration|warning|reaction|assistance",'
        '"claim_refs":[{"claim_id":"c01","narration_phrase":"planned exact factual phrase",'
        '"evidence_id":"e01"}] — REQUIRED on every beat whose narration will state a fact, a number, '
        'a date, a named finding, or a causal link ("because", "so", "which caused"). This is checked '
        'before any spend and an unbound factual beat fails the run. There are normally fewer claims '
        'than beats, so REUSE a claim across every beat that leans on it rather than leaving beats '
        'unbound, and if a beat has no ledger claim to stand on, write it as narrative or visual '
        'description instead of asserting a fact. Leave [] only for a genuinely non-factual beat,'
        '"evidence_id":"stable evidence id, required whenever claim_refs is non-empty",'
        '"question_opened":"question created by this beat or '
        'empty","question_answered":"earlier question resolved by this beat or empty",'
        '"new_complication":"larger problem created by the answer or empty","visible_consequence":'
        '"the concrete change visible on screen","opens_loop":"short stable loop id or empty",'
        '"closes_loop":"short stable loop id or empty"}]}.\n'
        'IRON RULES — viewers clicked to find out WHAT HAPPENS, not to be taught what a thing IS. Build '
        'an ESCALATING STORY WITH DISTRIBUTED REWARDS, not an expanding explanation:\n'
        '1. Each fact/mechanic/idea appears in EXACTLY ONE beat. NEVER plan to re-explain something an '
        'earlier beat already covered — a later beat may BUILD ON it, never re-teach it.\n'
        '2. COLD CONSEQUENCE FIRST + FAST ANSWER (beats 1-2, 0-8%): open on the single most VISCERAL, '
        'high-stakes result the viewer actually clicked to see — the DRAMATIC thing, NOT a poetic or '
        'atmospheric detail (a lamppost shadow subtly changing is a FAIL; "Earth is wrenched into a new '
        'orbit and the year snaps a week shorter" is right). NAME THE SUBJECT with the actual noun from '
        'the title. Then IMMEDIATELY resolve its first mechanism so the viewer gets a real ANSWER (not '
        'just another promise) within the first ~2 beats / ~10 seconds. Never a definition, exact-number '
        'dump, or "let us investigate" intro. HARD RULE: do NOT stack more than TWO setup/promise/'
        'prediction beats before the first RESOLVED payoff — a pile of hooks with no answer is the #1 '
        'opening-drop cause.\n'
        '3. PROMISE + ROADMAP (3-8%): state the ONE central question plainly (the title spoken aloud), '
        'reject the obvious answer, and NAME THE STAGES so the viewer knows this is a FINITE journey '
        'with a destination ("this breaks three things, in this order: signals, then matter, then life '
        'itself"). Keep the question OPEN; do NOT answer it yet and do NOT open a second competing '
        'question.\n'
        '4. DISTRIBUTED REWARDS (this REPLACES withholding): NEVER hoard the answer to the end. Deliver '
        'a concrete, pictureable PAYOFF roughly every 6-10 beats — the FIRST within the opening ~2-3 '
        'beats (~10% in), NOT after a stack of setup — and each payoff ANSWERS one question while '
        'OPENING a bigger one. The strongest, most counter-intuitive '
        'reveal lands at "peak_scene" (~65-75%), NOT at the very end; after it comes a brief '
        'false-relief, then a final escalation, then the final payoff. NEVER dump everything into one '
        'climax.\n'
        '5. "throughline" is the ONE central question running through every beat; every beat visibly '
        'advances THAT question. NEVER introduce a SECOND competing question the viewer must also track '
        '— any background needed first is framed as SETUP for the one question ("to answer that, you '
        'first have to know…"), never as a rival question.\n'
        '6. INFORMATION IS NOT REWARD: a reward is a consequence the viewer can PICTURE ("GPS could '
        'place you hundreds of kilometres from where you really are"), not a definition or a precise '
        'constant ("light travels at 299,792 km/s"). Ban beats whose only content is a number or a '
        'definition that does not change what the viewer imagines. If a number does not earn a mental '
        'image, cut it.\n'
        '7. PREDICTION GATES: include at least TWO beats that put a guess to the viewer BEFORE the '
        'answer ("Which breaks first — sunlight, GPS, or the atoms in your body?"), then overturn the '
        'obvious choice. This turns a passive viewer into a participant ("that can\'t be right — show '
        'me").\n'
        '7b. NARRATIVE DEBT LEDGER: use opens_loop/closes_loop to track every promised question. Open '
        'the central loop in the opening and close it at final_payoff. Each prediction_gate opens a '
        'short sub-loop; a later payoff closes it while opening the next complication. Every opened '
        'loop MUST close, and never close an id that was not opened earlier. Use short ids such as '
        '"central", "first_failure", and "hidden_cost".\n'
        '8. ESCALATION LADDER, FAMILIAR -> DEEP: climb ME -> MY TOOLS -> MY ENVIRONMENT -> CIVILISATION '
        '-> REALITY. Lead with everyday visible effects; the deep physics/mechanism is the ESCALATION '
        'and the reward, NEVER the setup. Every beat must ESCALATE (raise stakes, deepen the mystery, or '
        'open a new complication); never plateau into a flat fact-list.\n'
        '9. ONE EXPERIMENT, NO SCENARIO DRIFT: keep a single consistent framing end to end (if it is '
        '"X happens NOW", it stays "NOW" — do not silently switch to "a universe that always had X"). '
        'If the premise is genuinely ambiguous, make THAT the twist: present the variants as explicit '
        '"branch" beats near the peak, never as a mid-video drift.\n'
        '10. HUMAN-LED CAUSAL SPINE: Alex owns one objective and one developing belief. Every beat after '
        'the anomaly must be caused by the previous discovery and must change a belief, force a decision, '
        'answer a question, or create a sharper complication. Connect beats with BUT / THEREFORE / SO — '
        'never "and then". At least one beat must give the viewer evidence Alex does not yet know. Three '
        'adjacent consequence-only beats are a hard failure. Bolt is absent from pure evidence/mechanism '
        'beats and appears only when his action materially helps Alex investigate.\n'
        '11. HOOK: within the first five seconds name the title subject and show a concrete anomaly acting '
        'on Alex or his opening object. By eight seconds Alex\'s objective must be legible. Open a causal '
        'question; never open with a definition, generic beauty shot, roadmap, or Bolt pointing.\n'
        '12. ENDING (last ~6-10 beats): after the peak, ONE false-relief beat, then the final '
        'escalation, then a FINAL PAYOFF that answers the TITLE and resolves the EXACT experiment posed '
        'at the start (not a drifted one), then ONE resonant new line tied to THIS story — never a '
        'recap, never a generic PSA. Return to final_callback_object, which must be the exact opening_object, '
        'and change its meaning through the answer. Any CTA comes AFTER the payoff.\n'
        '13. NO PADDING: never invent filler or near-duplicate beats to hit the count. A tight journey '
        'of fewer rich beats beats a padded long one. Read top to bottom: every beat must ADD something '
        'the previous beats did not.\n'
        '14. TIMESCALE HONESTY (TWO CLOCKS): never present a slow effect as instant. Separate what '
        'happens IMMEDIATELY (e.g. gravity, an orbit) from what takes MILLIONS or BILLIONS of years '
        '(e.g. a star re-reaching equilibrium, evolution) — a beat calling an effect instant must NOT be '
        'contradicted by a later beat calling that same effect gradual. Use the two clocks as tension: '
        'tease the biggest long-clock stake early as a promise, pay it off late.\n'
        '15. ONE METAPHOR PER MECHANIC: each mechanic gets AT MOST ONE metaphor. NEVER schedule 2-3 '
        'consecutive beats that re-illustrate the SAME idea with different images (pressure cooker, then '
        'furnace, then candle = pick ONE). After the metaphor lands, the next beat delivers the '
        'CONSEQUENCE, not another metaphor for the same thing.\n'
        'FIXED ARCHITECTURE (by PERCENT of runtime, not scene number): 0-8% COLD CONSEQUENCE that '
        'ALREADY DELIVERS THE FIRST ANSWER (most visceral result + its immediate mechanism resolved) · '
        '8-14% fast PROMISE + name the stages + tease the biggest twist/fork to come, folded with ONE '
        'quick prediction_gate about the DEEPER danger (not the opener) · 14-28% rules + second payoff + '
        'a brief false_relief · 28-40% first escalation + a rehook ("but that assumes it is the only '
        'thing that changed") · 40-55% mechanism (ONE relationship, shown not defined, ONE metaphor max) '
        '+ third payoff + a reversal · 55-65% escalate toward the deepest stake · ~65-75% PEAK (the '
        'branch reveal / most counter-intuitive answer) · 76-82% false_relief · 83-92% final_escalation '
        '· 92-97% final_payoff (answers the title, resolves the exact experiment) · 97-100% resonant_end.'
    )
    claim_context = claim_context_for_prompt(research_dossier or {})
    if claim_context:
        beat_prompt += (
            "\nBINDING RESEARCH CLAIM LEDGER — use only these sourced claims for factual, numeric, "
            "or causal narration. Every such beat must reference one or more claim_id values and a "
            "stable evidence_id. Preserve geographic_scope, timescale, and confidence; speculative "
            "claims must be explicitly hedged. Do not invent a claim or URL:\n"
            + json.dumps(claim_context, ensure_ascii=False)
        )
    requested_story_format = (story_format if story_format in
                              {"standard_explainer", "evidence_led_mystery"}
                              else "standard_explainer")
    if requested_story_format == "evidence_led_mystery":
        beat_prompt += (
            "\nSELECTED STRUCTURE — EVIDENCE-LED MYSTERY. First decide whether this topic genuinely "
            "supports a concrete anomaly, reasonable false belief, at least three distinguishable "
            "evidence states, an investigation/test, a reveal that changes interpretation, and a "
            "recurring subject/object/location. Set mystery_suitable accordingly. If suitable, this "
            "instruction overrides the FAST ANSWER, PROMISE + ROADMAP, DISTRIBUTED REWARDS, and FIXED "
            "ARCHITECTURE timing above wherever they conflict: do not announce a roadmap; give local "
            "evidence payoffs but withhold only the deepest causal explanation until 45-70%; each clue "
            "weakens Alex's false belief and forces his next action. If unsuitable, write a STANDARD "
            "EXPLAINER plan instead and explain why in mystery_unsuitable_reason."
            + _story_role_block("evidence_led_mystery") + _STORY_LED_DNA
        )
    else:
        beat_prompt += (
            "\nSELECTED STRUCTURE — STANDARD EXPLAINER. Deliver the first useful mechanism by 10-20 "
            "seconds, then distribute connected payoffs. Preserve the human-led evidence chain, but "
            "do not artificially withhold an answer already earned. Set mystery_suitable based on the "
            "topic for reporting only; do not change the selected Standard structure."
        )
    if improve_note:
        beat_prompt += ("\nPRIORITY FIX — the previous draft scored weak here; fix this FIRST in the "
                        "beat sheet while keeping everything else: " + improve_note)
    o = _claude().messages.create(model=ANTHROPIC_MODEL, max_tokens=12000, system=_SCRIPT_SYSTEM,
                                  messages=[{"role": "user", "content": beat_prompt + _series_block(series)
                                             + _operator_block(operator_direction)}])
    plan, rc = _parse_script_json(o.content[0].text); cost += rc
    cost += o.usage.input_tokens * _RATE_SCRIPT_IN + o.usage.output_tokens * _RATE_SCRIPT_OUT
    style_mode = (_s(plan.get("style_mode")) or "educational").strip().lower()
    throughline = _s(plan.get("throughline")).strip()
    beats = [b for b in (plan.get("beats") or []) if isinstance(b, dict) and _s(b.get("beat")).strip()]
    if not beats:
        beats = [{"n": i + 1, "beat": question, "role": "setup"} for i in range(n_scenes)]
    for i, b in enumerate(beats):
        b["n"] = i + 1                                  # canonical renumber
    mystery_suitable, mystery_reasons = _evaluate_mystery_suitability(plan, beats)
    plan["mystery_suitable"] = mystery_suitable
    effective_story_format = requested_story_format
    fallback_reason = ""
    if requested_story_format == "evidence_led_mystery" and not mystery_suitable:
        effective_story_format = "standard_explainer"
        fallback_reason = "; ".join(dict.fromkeys(mystery_reasons))
    character_budget = _apply_character_budget(beats)
    n_scenes = len(beats)
    # Re-derive the per-scene word budget from the ACTUAL beat count. The model may return materially
    # fewer beats than requested (the tightness rules push it to prune), and wpm was sized for the
    # REQUESTED count — without this recompute the total narration collapses to a 2-3 min video. The
    # clamp keeps each scene ~5-8s so cadence stays healthy even when the beat count runs low.
    wpm = max(14, min(20, total_words // max(1, n_scenes)))
    peak = int(plan.get("peak_scene") or plan.get("climax_scene") or 0) or round(n_scenes * 0.7)
    peak = min(max(1, peak), n_scenes)
    # Guard the "peak ~65-75%, NOT at the end" rule: the model sometimes labels the FINAL gut-punch as
    # the peak (peak_scene≈n), which collapses the peak -> false-relief -> final-escalation shape. If it
    # lands outside a sane 55-82% band, snap it back to ~70% (the branch-reveal region).
    if not (0.55 * n_scenes <= peak <= 0.82 * n_scenes):
        peak = max(1, round(n_scenes * 0.7))
    payoffs = sorted({int(p) for p in (plan.get("payoffs") or [])
                      if isinstance(p, (int, float)) and 1 <= int(p) <= n_scenes})
    stages = [_s(x).strip() for x in (plan.get("stages") or []) if _s(x).strip()]

    # The whole causal sheet is visible to EVERY expansion batch. Passing only the topic sentence
    # here let expansion silently discard Alex's intention, the evidence state, and the continuity
    # anchor even though the planner had supplied them.
    def _expansion_beat(beat: dict) -> dict:
        return {
            "n": beat.get("n"), "role": _s(beat.get("role")) or "beat",
            "beat": _s(beat.get("beat")),
            "human_present": _plan_bool(beat.get("human_present"), True),
            "human_intention": _s(beat.get("human_intention")),
            "human_belief": _s(beat.get("human_belief")),
            "expected_outcome": _s(beat.get("expected_outcome")),
            "actual_outcome": _s(beat.get("actual_outcome")),
            "continuity_anchor": _s(beat.get("continuity_anchor")),
            "causal_link": _s(beat.get("causal_link")),
            "bolt_mode": _s(beat.get("bolt_mode")) or "absent",
            "claim_refs": beat.get("claim_refs") or [],
            "evidence_id": _s(beat.get("evidence_id")),
        }

    sheet = "\n".join(json.dumps(_expansion_beat(b), ensure_ascii=False) for b in beats)
    if stages and effective_story_format == "standard_explainer":
        roadmap = (' The escalating STAGES (name them for the viewer and signal progress through them): '
                   + " -> ".join(stages) + ".")
    elif stages:
        roadmap = (' The internal story acts are ' + " -> ".join(stages)
                   + '; do not announce this roadmap to the viewer.')
    else:
        roadmap = ""
    payoff_line = (' Payoff scenes (each must land a concrete, pictureable answer): '
                   + ", ".join(map(str, payoffs)) + "." if payoffs else "")
    answer_policy = (
        'The PEAK is the strongest evidence-led reinterpretation. Distribute concrete clue payoffs, '
        'but do not reveal the deepest causal answer before the planned reversal.'
        if effective_story_format == "evidence_led_mystery" else
        'The PEAK is the strongest reveal; do NOT hoard the answer to the end because payoffs are distributed.'
    )
    sheet_block = ('\n\nFULL BEAT SHEET for the whole video (every scene is already assigned ONE beat; '
                   'expand ONLY your assigned scenes, and NEVER explain an idea that belongs to a '
                   'different beat — it is covered there, not here). The PEAK (strongest reveal) is '
                   f'scene {peak}. {answer_policy}'
                   + roadmap + payoff_line + "\n"
                   + sheet + "\n")
    theme_line = (f' Theme/setting steer (lean in where it fits, never force): "{image_guidance}".'
                  if image_guidance else "")

    # 2) EXPANSION — batched, each batch sees the full sheet, dramatizing ONLY its assigned beats.
    # Ten rather than sixteen: every scene carries a paragraph-length image_prompt plus ~16 story
    # fields, claim_refs and now a role, and sixteen of those overran the response budget — a run
    # died on "Unterminated string" at char 41222, which is almost exactly 16 scenes of this shape.
    # Smaller batches cost more calls but cannot silently truncate a script mid-object.
    per_batch = 10
    all_scenes = []
    bi = 0
    while bi < n_scenes:
        batch = beats[bi:bi + per_batch]
        lo, hi = batch[0]["n"], batch[-1]["n"]
        is_first, is_last = (bi == 0), (bi + per_batch >= n_scenes)
        prev_tail = " ".join(s.get("narration", "") for s in all_scenes[-2:]).strip()
        seam = ("" if is_first else
                f'\nThe previous scene ended: "{prev_tail}". Continue DIRECTLY as one video — no recap, '
                'no "welcome back"/"in this chapter", do not re-introduce the topic.\n')
        assigned = "\n".join(json.dumps(_expansion_beat(b), ensure_ascii=False) for b in batch)
        opening_direction = _opening_expansion_direction(effective_story_format, is_first)
        ch_prompt = (
            f'Video: "{_s(plan.get("title")) or question}" (style_mode: {style_mode}). '
            f'Human lead: {HUMAN_NAME} — {HUMAN_DESC}. Supporting co-investigator: '
            f'{MASCOT_NAME} — {MASCOT_DESC}.'
            + (f'\nCENTRAL THROUGHLINE (every scene serves it): "{throughline}".' if throughline else "")
            + sheet_block
            + f'\nNOW WRITE scenes {lo}-{hi} ONLY. Expand EACH assigned beat below into exactly ONE scene, '
            'in order, dramatizing JUST that beat (one idea per scene; never restate a concept that '
            'belongs to another beat). STATE-ONCE — repetition is the #1 score-killer: NO back-references '
            '("as we saw", "as mentioned", "remember", "recall", "earlier", "this is why", "in other '
            'words"); do NOT restate the central answer or the hook premise in these scenes; a scene\'s '
            'opening words must NOT echo the previous scene\'s ending.'
            ' REWARD OVER INFORMATION: land a concrete, PICTUREABLE consequence (something the viewer '
            'can see happening) — not a bare number or definition; if a number does not earn a mental '
            'image, cut it. Connect lines with BUT/THEREFORE/SO, never "and then". Show the CONSEQUENCE '
            'before any diagram, and when a beat is a [prediction_gate], pose the guess to the viewer '
            'BEFORE revealing the answer. NEVER narrate the video\'s own structure: the role label in '
            'brackets is INTERNAL — do not speak it or any scaffolding word aloud ("first payoff", '
            '"here\'s the peak", "the reveal", "the hook", "prediction gate", "stage two"); the viewer '
            f'must FEEL the beat through its content, not hear it announced:\n{assigned}\n{seam}'
            f'Each narration ≈ {wpm} words.{theme_line}\n'
            'Return ONLY JSON: {"scenes":[ ... ]} — exactly one scene per assigned beat, same order. '
            + _SCENE_FIELDS_RULES
            + _NARRATION_CADENCE
            + opening_direction
            + (' This batch contains the ENDING: after the peak, write ONE brief false-relief beat, then '
               'the FINAL ESCALATION, then a FINAL PAYOFF that answers the TITLE and resolves the EXACT '
               'experiment posed at the start (do NOT drift to a different scenario), then close on ONE '
               f'specific resonant NEW thought tied to this story. Return visibly to the exact opening '
               f'object "{_s(plan.get("opening_object"))}" and change its meaning through the answer. '
               'Do NOT re-summarize or restate any '
               'earlier fact. Any call to action comes AFTER the payoff, never interrupting it.'
               if is_last else "")
        )
        c = _claude().messages.create(model=ANTHROPIC_MODEL, max_tokens=20000, system=_SCRIPT_SYSTEM,
                                      messages=[{"role": "user", "content": ch_prompt + _DESIGN_SYSTEM_TEXT}])
        if getattr(c, "stop_reason", "") == "max_tokens":
            # Truncated JSON surfaces as an opaque "Unterminated string at char N" from the parser,
            # which says nothing about the cause. Name it where it happens.
            raise ValueError(
                f"Scene expansion hit the token ceiling on beats {lo}-{hi}; the script JSON was cut "
                "off mid-object. Lower per_batch or raise max_tokens for this call.")
        part, rc = _parse_script_json(c.content[0].text); cost += rc
        cost += c.usage.input_tokens * _RATE_SCRIPT_IN + c.usage.output_tokens * _RATE_SCRIPT_OUT
        for batch_index, s in enumerate(part.get("scenes") or []):
            beat = batch[batch_index] if batch_index < len(batch) else {}
            s["human_present"] = _plan_bool(beat.get("human_present"), True)
            s["human_action"] = _s(beat.get("human_intention"))
            s["bolt_mode"] = _s(beat.get("bolt_mode")) or "absent"
            s["mascot_present"] = s["bolt_mode"] != "absent"
            # Persist the planner's story semantics. The deterministic retention gate consumes
            # these fields without asking the model to grade its own compliance.
            s["story_beat_n"] = int(beat.get("n") or (len(all_scenes) + 1))
            s["story_pct"] = int(beat.get("pct") or 0)
            s["story_role"] = _s(beat.get("role")) or "beat"
            # story_engine reads `_role`; this path only ever wrote `story_role`, so every
            # structural gate reported "beat roles absent" and none of the eleven timing bands
            # could run. Same value, both names — the planner already knows the role.
            s["_role"] = s["story_role"]
            for key in ("question_opened", "question_answered", "new_complication",
                        "visible_consequence", "opens_loop", "closes_loop", "human_intention",
                        "human_belief", "viewer_knows", "human_knows", "expected_outcome",
                        "actual_outcome", "belief_changed", "decision_caused",
                        "continuity_anchor", "causal_link"):
                s[key] = _s(beat.get(key))
            allowed_refs = beat.get("claim_refs") if isinstance(beat.get("claim_refs"), list) else []
            allowed_ids = {_s(ref.get("claim_id")) for ref in allowed_refs if isinstance(ref, dict)}
            expanded_refs = s.get("claim_refs") if isinstance(s.get("claim_refs"), list) else []
            kept_refs = [ref for ref in expanded_refs
                         if isinstance(ref, dict) and _s(ref.get("claim_id")) in allowed_ids]
            # A claimed scene must carry an evidence_id, and every reference in it must carry the
            # SAME one. Both come from the beat, so they already agree — but the planner routinely
            # omits the id entirely, and an empty string fails the join just as hard as a mismatched
            # one. The value only has to be stable and shared within the scene, which the beat
            # number already is: derive it rather than asking the model again.
            beat_evidence = _s(beat.get("evidence_id"))
            if kept_refs and not beat_evidence:
                beat_evidence = f"e{int(s['story_beat_n']):02d}"
            s["claim_refs"] = [
                {
                    "claim_id": _s(ref.get("claim_id")),
                    "narration_phrase": _s(ref.get("narration_phrase")),
                    "evidence_id": beat_evidence,
                }
                for ref in kept_refs
            ]
            s["evidence_id"] = beat_evidence
            all_scenes.append(s)
        bi += per_batch

    # 3) STATE-ONCE dedup — count-preserving rewrite of any line that still repeats.
    if research_dossier:
        dc = 0.0  # claim-unaware rewrites would invalidate exact narration/source joins
    else:
        all_scenes, dc = _dedupe_narration(all_scenes, beats, throughline)
        cost += dc

    for i, s in enumerate(all_scenes):
        s["id"] = i + 1
    plan["story_format_requested"] = requested_story_format
    plan["story_format_effective"] = effective_story_format
    plan["story_format_fallback_reason"] = fallback_reason
    plan["character_budget"] = character_budget
    story_contract = build_story_contract(question, plan, beats, all_scenes, duration_sec)
    return {
        "title": _s(plan.get("title")) or question,
        "hook": _s(plan.get("hook")),
        "style_mode": style_mode,
        "scenes": all_scenes,
        "_script_cost_usd": round(cost, 4),
        "_beats": len(beats),
        "_peak_scene": peak,
        "_payoffs": payoffs,
        "_stages": stages,
        "_story_contract": story_contract,
        "_story_format": effective_story_format,
        "_story_format_requested": requested_story_format,
        "_story_format_fallback_reason": fallback_reason,
        "_character_plan": character_budget,
        "_research_dossier": research_dossier or {},
    }


_RESEARCH_SYSTEM = (
    "You are the research editor for an evidence-led science documentary. Search the web before "
    "answering. Prefer primary sources (government science agencies, university research groups, "
    "standards bodies, peer-reviewed papers) and authoritative secondary sources only when a primary "
    "source is unavailable. Separate observed facts from calculations and speculative scenario claims. "
    "Never invent a source URL, numeric value, geographic scope, or timescale."
)


def _provider_citation_records(response) -> list[dict]:
    """Extract provider-observed URLs and quoted evidence from citation/tool blocks."""
    records: dict[tuple[str, str], dict] = {}

    def walk(value, *, provider_block: bool = False):
        if isinstance(value, dict):
            block_type = _s(value.get("type")).lower()
            is_provider = provider_block or block_type in {
                "web_search_tool_result", "web_search_result", "web_fetch_tool_result",
                "web_fetch_result", "citation_web_search_result_location",
            }
            url = _s(value.get("url") or value.get("source_url")) if is_provider else ""
            excerpt = _s(value.get("cited_text") or value.get("snippet") or value.get("content"))
            if url.startswith("https://"):
                # Some tool results expose content as nested blocks; retain the URL even when no
                # provider excerpt is available so validation can report the precise missing join.
                if isinstance(value.get("content"), (dict, list)):
                    excerpt = _s(value.get("cited_text") or value.get("snippet"))
                key = (url, excerpt)
                records[key] = {"url": url, "cited_text": excerpt}
            for key, item in value.items():
                if key != "text":
                    walk(item, provider_block=is_provider or key == "citations")
        elif isinstance(value, list):
            for item in value:
                walk(item, provider_block=provider_block)

    for block in getattr(response, "content", None) or []:
        dumped = block.model_dump() if hasattr(block, "model_dump") else getattr(block, "__dict__", {})
        if _s(dumped.get("type")) != "text":
            walk(dumped, provider_block=True)
        else:
            walk(dumped.get("citations") or [], provider_block=True)
    return sorted(records.values(), key=lambda item: (item["url"], item["cited_text"]))


def _provider_citation_urls(response) -> list[str]:
    """Extract URLs only from provider citation/tool blocks, never from model-authored JSON text."""
    urls: set[str] = set()

    def walk(value, *, provider_block: bool = False):
        if isinstance(value, dict):
            block_type = _s(value.get("type")).lower()
            is_provider = provider_block or block_type in {
                "web_search_tool_result", "web_search_result", "web_fetch_tool_result",
                "web_fetch_result", "citation_web_search_result_location",
            }
            for key, item in value.items():
                if is_provider and key in {"url", "source_url"} and isinstance(item, str) \
                        and item.startswith("https://"):
                    urls.add(item)
                elif key != "text":
                    walk(item, provider_block=is_provider or key == "citations")
        elif isinstance(value, list):
            for item in value:
                walk(item, provider_block=provider_block)

    for block in getattr(response, "content", None) or []:
        dumped = block.model_dump() if hasattr(block, "model_dump") else getattr(block, "__dict__", {})
        if _s(dumped.get("type")) != "text":
            walk(dumped, provider_block=True)
        else:
            walk(dumped.get("citations") or [], provider_block=True)
    urls.update(item["url"] for item in _provider_citation_records(response))
    return sorted(urls)


_SUPPORT_BIND_MIN_OVERLAP = 0.6


def _content_tokens(text: str) -> set:
    return {tok for tok in re.findall(r"[a-z0-9]+", _s(text).casefold()) if len(tok) > 2}


def _bind_support_quotes(dossier: dict) -> dict:
    """Replace each claim's *retyped* support quote with the provider excerpt it paraphrases.

    The dossier prompt asks the model for a "short exact excerpt", then validation checks that text
    verbatim against what the search provider returned. Models normalise whitespace, repair
    punctuation and trim clauses, so a claim that is true, correctly attributed and drawn from the
    right page still failed — six of fourteen on the run that prompted this. That is verifying what
    was generated, when the invariant should hold by construction.

    So the model's quote is demoted to a *selector*: it chooses which provider excerpt for that URL
    supports the claim, and the excerpt's own bytes become support_quote.

    This is deliberately NOT a rubber stamp. Substitution requires the model's wording to genuinely
    overlap the excerpt it is being bound to; below that threshold the original is left alone and
    validation fails exactly as before. A claim whose support resembles nothing the provider
    returned must still fail, or the check would stop protecting against a fabricated citation —
    which is the entire reason it exists.
    """
    records: dict[str, list[str]] = {}
    for record in dossier.get("citation_records") or []:
        if not isinstance(record, dict):
            continue
        url = _canonical_url(_s(record.get("url")))
        # Must be the same field the validator reads (`cited_text`), or binding would repair a
        # quote against text validation never sees and the claim would still fail.
        excerpt = _s(record.get("cited_text") or record.get("excerpt"))
        if url and excerpt:
            records.setdefault(url, []).append(excerpt)

    bound = unbindable = 0
    for claim in dossier.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        quoted = _s(claim.get("support_quote"))
        excerpts = records.get(_canonical_url(_s(claim.get("source_url")))) or []
        if not quoted or not excerpts:
            continue
        if any(quoted.casefold() in excerpt.casefold() for excerpt in excerpts):
            continue                                    # already verbatim; nothing to repair
        wanted = _content_tokens(quoted)
        if not wanted:
            continue
        best, best_overlap = "", 0.0
        for excerpt in excerpts:
            overlap = len(wanted & _content_tokens(excerpt)) / len(wanted)
            if overlap > best_overlap:
                best, best_overlap = excerpt, overlap
        if best and best_overlap >= _SUPPORT_BIND_MIN_OVERLAP:
            claim["support_quote_model"] = quoted       # keep what the model wrote, for audit
            claim["support_quote"] = best
            claim["support_quote_binding"] = round(best_overlap, 3)
            bound += 1
        else:
            unbindable += 1
    dossier["support_quote_binding"] = {"bound": bound, "unbindable": unbindable,
                                        "min_overlap": _SUPPORT_BIND_MIN_OVERLAP}
    return dossier


def _verify_claims_against_sources(dossier: dict, *, log=lambda message: None) -> dict:
    """Establish the provider-observed-evidence invariant by reading the cited pages ourselves.

    `validate_research_dossier` requires each support quote to appear in a citation record for its
    URL. The provider does not expose that text to the client — measured repeatedly: zero readable
    excerpts across search and fetch — so the records are built here instead, from pages we
    actually retrieved. The stored quote is text read from the cited URL, which is what the check
    was always asking for and is strictly stronger than a provider snippet.

    A claim whose quote cannot be found on its own page is dropped rather than carried, because a
    claim that survives here goes on to license narration.
    """
    claims = [claim for claim in (dossier.get("claims") or []) if isinstance(claim, dict)]
    if not claims:
        return dossier
    try:
        import claim_verify
    except Exception as exc:                                  # never turn a missing dep into a crash
        log(f"Claim verification unavailable ({exc}); leaving provider records in place")
        return dossier

    summary = claim_verify.verify_claims(claims, log=log)
    if not summary.get("fetched"):
        # Not one page could be retrieved. That is an outage or a sandbox, not evidence that every
        # claim is unsupported — dropping them all would blame the ledger for the network. Leave
        # the dossier untouched so the existing check reports the real problem.
        log("Claim verification: no cited page could be retrieved; leaving the ledger unchanged")
        dossier["claim_verification"] = {k: v for k, v in summary.items() if k != "pages"}
        return dossier
    verified = [claim for claim in claims if claim.get("quote_verified")]
    dropped = [claim for claim in claims if not claim.get("quote_verified")]
    for claim in dropped[:4]:
        reason = "source unreachable" if not claim.get("source_reachable") else "quote not on page"
        log(f"  ✗ dropped {claim.get('claim_id') or '?'}: {reason} — "
            f"{_s(claim.get('source_url'))[:70]}")
    dossier["claims"] = verified
    # These now describe what WE read, so the ledger and its evidence cannot disagree.
    dossier["citation_records"] = [{"url": _s(claim.get("source_url")),
                                    "cited_text": _s(claim.get("support_quote"))}
                                   for claim in verified]
    dossier["citation_urls"] = sorted({_s(claim.get("source_url")) for claim in verified})
    dossier["claim_verification"] = {k: v for k, v in summary.items() if k != "pages"}
    log(f"Claim verification: {len(verified)}/{len(claims)} claims verified against source pages"
        + (f", {summary.get('repaired', 0)} quote(s) recovered" if summary.get("repaired") else ""))
    return dossier


def _research_cache_enabled() -> bool:
    """Cache is a development convenience, and must never change behaviour under test.

    A stubbed research call writes a perfectly valid dossier, which the cache would then serve to
    the next run — so the test that asserts an API call was made saw no call at all. A cache that
    silently substitutes itself for the thing under test is worse than no cache.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("RESEARCH_CACHE", "1") == "1"


def _research_cache_path(question: str) -> str:
    root = os.environ.get("RESEARCH_CACHE_DIR", "").strip() or os.path.join(
        tempfile.gettempdir(), "reelforge", "research")
    key = hashlib.sha256(f"{ANTHROPIC_MODEL}|{_s(question).strip().casefold()}".encode()).hexdigest()
    return os.path.join(root, f"{key[:32]}.json")


def _cached_research_dossier(question: str, log) -> dict | None:
    """Reuse a previously VALIDATED dossier for the same question.

    Web search is a metered server tool, and a research call spends several of those uses. Anything
    that re-runs a render on the same question — a retry after a downstream gate, iterating on the
    script or the renderer — burned the quota again for evidence that had not changed, and
    exhausting it produces a run that fails for a reason unrelated to the code under test.

    Only validated dossiers are stored, so a cache hit can never resurrect a failure.
    """
    if not _research_cache_enabled():
        return None
    path = _research_cache_path(question)
    try:
        with open(path, encoding="utf-8") as handle:
            dossier = json.load(handle)
    except Exception:
        return None
    claims = len(dossier.get("claims") or [])
    if not claims:
        return None
    log(f"Research dossier: reusing {claims} verified claims cached for this question "
        f"(RESEARCH_CACHE=0 to force a fresh search)")
    return dossier


def _store_research_dossier(question: str, dossier: dict) -> None:
    if not _research_cache_enabled():
        return
    path = _research_cache_path(question)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(dossier, handle)
    except Exception as exc:
        print(f"[research] cache write skipped: {exc}")


def generate_research_dossier(question: str, *, cost_sink: list | None = None,
                              log=lambda message: None) -> dict:
    """Build a cited, pre-script claim ledger with server-side web search."""
    cached = _cached_research_dossier(question, log)
    if cached:
        return cached
    prompt = (
        f'Research the long-form explainer question: "{question}". Build the smallest sufficient '
        "ledger of 12-18 material claims needed to answer it accurately. Every claim must use a URL "
        "that appears in your web-search results. Cite peer-reviewed papers, government and "
        "public-health bodies, universities, museums or named institutional publications — not "
        "encyclopedias, forums or blogs, which are rejected however accurate. Each cited page is "
        "retrieved and its text checked against your support_quote, so quote a short distinctive "
        "sentence you are confident appears on that page, and prefer publicly readable sources. "
        "For a hypothetical, separate the changed premise, "
        "direct calculations, established baseline facts, modeled consequences, and speculation. "
        "Return ONLY JSON with this schema: "
        '{"topic":"","research_summary":"","claims":[{"claim_id":"c01","claim":"",'
        '"source_url":"https://...","support_quote":"short exact excerpt from the cited search evidence",'
        '"source_type":"primary|authoritative_secondary",'
        '"calculation":"formula or empty","assumptions":[],"geographic_scope":"global|regional|local|site-specific",'
        '"timescale":"immediate|hours|years|millions of years|other explicit value",'
        '"confidence":"high|medium|speculative","allowed_exaggeration":false,"material":true}]}. '
        "Do not include narration_phrase or evidence_id yet; the story compiler binds those later."
    )
    response = _claude().messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=10000,
        system=_RESEARCH_SYSTEM,
        # Search only. web_fetch was tried here to obtain quotable evidence — a web_search_result
        # block carries just url, title, page_age and an opaque encrypted_content, and `citations`
        # comes back None, so the provider never hands the client text to verify against. Fetching
        # server-side did produce that text, but eight page fetches against a 10k token budget left
        # nothing to write the ledger with: claims went 14 -> 0, truncated before the JSON. Since
        # claim_verify now retrieves each cited page itself, the model does not need the page
        # contents in context at all — it needs to find good sources and say what it expects to
        # find on them. Verification is what decides whether it was right.
        tools=[{"type": "web_search_20260318", "name": "web_search", "max_uses": 5,
                "response_inclusion": "full"}],
        messages=[{"role": "user", "content": prompt}],
        # The client default is 180s, chosen so a hung script-gen call cannot stall a render. This
        # one call is structurally longer than that budget: it runs up to five server-side web
        # searches, reads their results, then writes a ~10k-token ledger — and it timed out at 180s
        # in practice. Raised only here, so a genuinely hung call elsewhere still fails fast.
        timeout=float(os.environ.get("RESEARCH_TIMEOUT_SEC", "600")),
    )
    text_blocks = [_s(getattr(block, "text", "")) for block in response.content
                   if _s(getattr(block, "text", ""))]
    dossier, repair_cost = _parse_script_json("\n".join(text_blocks))
    if not isinstance(dossier, dict):
        raise ValueError("Research provider returned no structured dossier.")
    dossier["version"] = 1
    dossier["citation_records"] = _provider_citation_records(response)
    dossier["citation_urls"] = _provider_citation_urls(response)
    dossier["web_search_max_uses"] = 5
    dossier["provider"] = "anthropic_server_web_search"
    server_usage = getattr(response.usage, "server_tool_use", None)
    search_requests = int(getattr(server_usage, "web_search_requests", 0) or 0)
    dossier["web_search_requests"] = search_requests
    dossier["search_cost_reservation_usd"] = round(
        search_requests * _WEB_SEARCH_COST_CEILING, 4)
    _bind_support_quotes(dossier)
    _verify_claims_against_sources(dossier, log=log)
    validation = validate_research_dossier(dossier)
    dossier["validation"] = validation
    # An unverified-quote failure has two very different causes and the message could not tell them
    # apart, which cost several rounds of guessing: either the provider returned no readable
    # evidence at all (nothing CAN verify, a tool/config problem) or it returned evidence the
    # quotes do not match (a matching problem). Report the evidence actually available.
    quotable = [record for record in dossier["citation_records"]
                if isinstance(record, dict) and _s(record.get("cited_text")).strip()]
    dossier["quotable_excerpt_count"] = len(quotable)
    log(f"Provider evidence: {len(quotable)} quotable excerpts across "
        f"{len({_s(r.get('url')) for r in quotable})} sources"
        + (" — nothing to verify against" if not quotable else ""))
    if cost_sink is not None:
        cost_sink.append(_msg_cost(response.usage) + repair_cost)
        cost_sink.append(dossier["search_cost_reservation_usd"])
    log(f"Research dossier: {validation['claim_count']} claims, "
        f"{validation['citation_count']} cited URLs")
    if not validation["passed"]:
        codes = collections.Counter(_s(item.get("code")) for item in validation["errors"])
        raise ValueError(
            "Research dossier failed before scripting "
            f"[{dossier['quotable_excerpt_count']} quotable excerpts available; "
            + ", ".join(f"{code}x{count}" for code, count in codes.most_common(4)) + "]: "
            + "; ".join(item["message"] for item in validation["errors"][:3])
        )
    _store_research_dossier(question, dossier)
    return dossier


_FACTCHECK_SYSTEM = (
    "You are a meticulous science fact-checker. You get a video TITLE and the narration lines of an "
    "explainer video. (1) Correct any factual errors, misleading claims, or oversimplifications in the "
    "narration. PRIORITIZE NUMERIC CLAIMS: extract EVERY number, measurement, record, date and "
    "quantitative comparison and verify each against well-established fact; fix any that are wrong or "
    "misleading (e.g. do NOT state humans can only reach 200 m when the scuba record is ~332 m), and "
    "recompute any multiplier or ratio from the corrected baseline so narrated and on-screen numbers stay "
    "self-consistent. (2) The TITLE and the narration MUST name the SAME subject. If the narration "
    "consistently says one thing (e.g. 'soldiers') but the title says another (e.g. 'a marching band'), "
    "you MUST rewrite the title to use the narration's subject — they cannot disagree. Also fix a title "
    "that is historically inaccurate (the bridge-resonance cases were SOLDIERS in step, not bands). Keep "
    "the new title punchy. Preserve tone, length, and order. Return "
    'ONLY valid JSON: {"title": "corrected or unchanged title", "narration": ["corrected line per scene, '
    'same count and order"], "notes": ["short note per correction"]}. If a line or the title is already '
    "accurate, return it unchanged."
)


def factcheck_script(script: dict, question: str, research_dossier: dict | None = None) -> tuple[dict, list, float]:
    """Verify narration factual accuracy via a second model pass. Returns (script, notes, cost).

    Adds genuine human-grade value + accuracy; failures degrade gracefully to the original.
    """
    scenes = script.get("scenes", [])
    lines = [s.get("narration", "") for s in scenes]
    if not lines:
        return script, [], 0.0
    payload = {
        "title": _s(script.get("title")) or question,
        "question": question,
        "narration": lines,
        "binding_claim_ledger": claim_context_for_prompt(research_dossier or {}),
        "constraint": (
            "Use the binding ledger. Do not introduce a factual claim absent from it. If a correction "
            "would require a new source, identify it in notes but do not silently rewrite the narration."
        ),
    }
    try:
        resp = _claude().messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=8000,
            system=_FACTCHECK_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw[raw.find("{"): raw.rfind("}") + 1]
        data = json.loads(raw)
        fixed = data.get("narration", [])
        notes = [n for n in (data.get("notes") or []) if n and n.strip()]
        if isinstance(fixed, list) and len(fixed) == len(scenes):
            for sc, new in zip(scenes, fixed):
                if isinstance(new, str) and new.strip():
                    sc["narration"] = new.strip()
        new_title = data.get("title")
        if isinstance(new_title, str) and new_title.strip() and new_title.strip() != _s(script.get("title")):
            notes.append(f'title → "{new_title.strip()}" (subject/accuracy)')
            script["title"] = new_title.strip()
        u = resp.usage
        cost = u.input_tokens * _RATE_SCRIPT_IN + u.output_tokens * _RATE_SCRIPT_OUT
        return script, notes, round(cost, 4)
    except Exception:
        return script, [], 0.0   # never let fact-check kill the job


def _enforce_requested_runtime(
    script: dict,
    duration_sec: int,
    *,
    cost_sink: list | None = None,
    log=lambda message: None,
) -> dict:
    """Fit narration to the requested runtime before TTS or image generation.

    The fit pass preserves scene count, facts, story roles and visual semantics.
    A draft that still misses the calibrated word/timing window is rejected
    before asset spend rather than silently becoming a longer video.
    """
    scenes = script.get("scenes") or []
    if not scenes or duration_sec <= 0:
        return script
    report = plan_runtime(scenes, duration_sec)
    # Three passes, not two. The gap is routinely ~20%, and a single compression pass reliably
    # under-delivers; a run that stops one pass short of the window has paid for the model calls
    # and thrown the result away.
    for attempt in range(3):
        if report["passed"]:
            break
        target_words, min_words, max_words = runtime_word_bounds(
            duration_sec, len(scenes))
        payload = [{
            "narration": _s(scene.get("narration")),
            "visual_beats": scene.get("visual_beats") or [],
            "motion_anchor_phrase": _s(scene.get("motion_anchor_phrase")),
            "claim_refs": scene.get("claim_refs") or [],
            "evidence_id": _s(scene.get("evidence_id")),
        } for scene in scenes]
        # Concrete arithmetic, not an abstract target. Told only "must be 166-176 words", the model
        # returned 212 and then 210 — it was not measuring. Naming the current count and the exact
        # number of words to remove turns this into a countable edit.
        current_words = int(report.get("word_count") or 0)
        surplus = max(0, current_words - max_words)
        prompt = (
            f"Fit this explainer narration to {duration_sec} seconds BEFORE voice or image generation. "
            f"It is currently {current_words} words, which runs "
            f"{report.get('estimated_seconds', 0):.0f}s — you must REMOVE AT LEAST {surplus} words. "
            f"Keep exactly {len(scenes)} scenes in the same order. The COMPLETE narration must be "
            f"{min_words}-{max_words} words, ideally {target_words} — count them before answering, and "
            f"aim for about {max(1, target_words // max(1, len(scenes)))} words per scene. "
            "Cut whole clauses and redundant restatement rather than trimming a word here and there; "
            "a 20% reduction is a rewrite, not an edit.\n"
            "THESE SURVIVE THE CUT — they are checked immediately afterwards and losing one fails "
            "the run:\n"
            "  * Scene 1 opens on a COLD VISIBLE CONSEQUENCE — something already happening or "
            "already wrong — not on setup or context.\n"
            "  * The exact subject is named in the FIRST FIVE SECONDS, so within roughly the first "
            "ten words of scene 1.\n"
            "  * At least one scene poses a question the viewer can predict the answer to, before "
            "that answer arrives.\n"
            "  * The final scene pays off the title explicitly.\n"
            "  * At least one scene has Bolt doing concrete work — measuring, demonstrating, "
            "warning, reacting or assisting — not merely present.\n"
            "Compress exposition and description to protect those five. Preserve every factual claim, "
            "story role, open-loop payoff and the final answer; remove padding and compress wording. "
            "Vary sentence length and keep natural speech. For every scene, return a visual_beats array "
            "whose anchor_phrase values are exact consecutive 2-8 word phrases copied from that scene's "
            "FINAL narration. Preserve each beat's purpose/visual/source/new_information/shot_size/"
            "camera_direction/bolt_visible/bolt_action when still relevant. Keep every claim_id and "
            "evidence_id unchanged. For "
            "each claim reference, update narration_phrase to an exact consecutive substring of the "
            "FINAL narration that states the same sourced claim; never drop, merge, or invent a claim. "
            "Return motion_anchor_phrase as exact words from the FINAL narration where physical action "
            "begins, or empty if none. Return ONLY JSON: "
            '{"scenes":[{"narration":"...","visual_beats":[...],'
            '"motion_anchor_phrase":"...","claim_refs":[...],"evidence_id":"..."}]}.\nINPUT:\n'
            + json.dumps(payload, ensure_ascii=False)
        )
        try:
            response = _claude().messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=10000,
                system=_SCRIPT_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            fitted, repair_cost = _parse_script_json(response.content[0].text)
            if cost_sink is not None:
                cost_sink.append(_msg_cost(response.usage) + repair_cost)
            new_scenes = fitted.get("scenes") if isinstance(fitted, dict) else None
            if not isinstance(new_scenes, list) or len(new_scenes) != len(scenes):
                break
            for scene, fitted_scene in zip(scenes, new_scenes):
                narration = _s(fitted_scene.get("narration")).strip()
                if narration:
                    scene["narration"] = narration
                visual_beats = fitted_scene.get("visual_beats")
                if isinstance(visual_beats, list):
                    scene["visual_beats"] = visual_beats
                scene["motion_anchor_phrase"] = _s(
                    fitted_scene.get("motion_anchor_phrase")).strip()
                if isinstance(fitted_scene.get("claim_refs"), list):
                    scene["claim_refs"] = fitted_scene["claim_refs"]
                if _s(fitted_scene.get("evidence_id")):
                    scene["evidence_id"] = _s(fitted_scene.get("evidence_id"))
            report = plan_runtime(scenes, duration_sec)
            log(
                f"Runtime fit {attempt + 1}: {report['estimated_seconds']:.1f}s estimated, "
                f"{report['word_count']} words (target {duration_sec}s)"
            )
        except Exception as exc:
            log(f"⚠ Runtime fit unavailable ({type(exc).__name__})")
            break
    script["_runtime_plan"] = report
    contract = script.get("_story_contract")
    if isinstance(contract, dict):
        contract["requested_runtime_sec"] = duration_sec
        contract["natural_runtime_sec"] = report["estimated_seconds"]
    if not report["passed"]:
        raise ValueError(
            "Runtime contract failed before image/TTS spend: "
            f"{report['estimated_seconds']:.1f}s estimated for a {duration_sec}s request "
            f"({report['word_count']} words; allowed {report['min_words']}-{report['max_words']})."
        )
    return script


_CONCEIT_SYSTEM = (
    "You are a ruthless short-form (TikTok/Shorts/Reels) story editor. A short LIVES OR DIES on "
    "whether the framing device (the metaphor/lens) set up in SCENE 1 runs through and ESCALATES "
    "across the WHOLE video. The #1 failure mode is: scene 1 plants a great frame (e.g. 'sleep is "
    "something you PAY FOR'), then the body drifts into a generic fact-list that never pays off the "
    "hook. Your job: (1) name the scene-1 conceit in a few words; (2) rewrite EVERY scene that "
    "drifts so it ADVANCES THE REAL EXPLANATION one concrete step (a NEW part of the actual "
    "mechanism, NOT the same idea restated louder), kept inside the conceit and NAMING the real "
    "terms/parts — the conceit connects the steps, it does NOT replace the science; "
    "(3) rewrite EVERY image_prompt so it LEADS with what {mascot} is DOING, "
    "in this exact shape: '{mascot} <strong action verb> <physically performing THIS scene's conceit "
    "beat>, in <a grounded, real-world setting>, with ONE surprising concrete element that inverts "
    "expectation, conveyed through an OBJECT or ACTION — never a sign, label, receipt, price tag, "
    "barcode, screen text, or number (those render as garbled AI text and look cheap)'. Good text-free "
    "surprises: a coin slot built into the headboard, a piggy bank cracking apart, a sand-timer "
    "draining onto the bed, a vault door on the closet, a meter needle redlining. {mascot} must be "
    "MID-ACTION; the phrases 'stands beside', 'observes', 'watches', and 'next to' are BANNED. Name "
    "the one surprising object explicitly so the image can't render as a generic illustration; "
    "(4) make the SECOND-TO-LAST scene a COUNTERINTUITIVE or uncomfortable TRUTH that reframes "
    "everything (the single most memorable, repeatable line), with its own fresh visual surprise. "
    "Keep each narration's "
    "word count about the same, keep the scene COUNT and ORDER identical, keep scene 1's hook PLAIN "
    "and LITERAL (its conceit lives in the IMAGE, not the words — never make scene 1's spoken line "
    "metaphorical or poetic) and keep the LAST line's loop-echo intact. "
    "Return ONLY JSON: {\"conceit\":\"...\",\"narration\":[one line per scene, same count/order],"
    "\"image_prompt\":[each begins with \"{mascot} <verb>...\" and names one surprising concrete "
    "element; same count/order]}."
)


def enforce_conceit(script: dict, question: str, cost_sink: list | None = None) -> tuple[dict, str, float]:
    """Social shorts: rewrite scenes that drift off the scene-1 framing device so the body pays
    off the hook. Returns (script, conceit, cost). Degrades gracefully to the original."""
    scenes = script.get("scenes", [])
    if len(scenes) < 3:
        return script, "", 0.0
    payload = {"question": question,
               "narration": [s.get("narration", "") for s in scenes],
               "image_prompt": [s.get("image_prompt", "") for s in scenes]}
    try:
        resp = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=8000,
            system=_CONCEIT_SYSTEM.replace("{mascot}", MASCOT_NAME) + _COLOR_CODE_TEXT,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw[raw.find("{"): raw.rfind("}") + 1]
        data = json.loads(raw)
        nar, imgs = data.get("narration", []), data.get("image_prompt", [])
        if isinstance(nar, list) and len(nar) == len(scenes):
            for sc, new in zip(scenes, nar):
                if isinstance(new, str) and new.strip():
                    sc["narration"] = new.strip()
        if isinstance(imgs, list) and len(imgs) == len(scenes):
            for sc, new in zip(scenes, imgs):
                if isinstance(new, str) and new.strip():
                    sc["image_prompt"] = new.strip()
        u = resp.usage
        cost = round(u.input_tokens * _RATE_SCRIPT_IN + u.output_tokens * _RATE_SCRIPT_OUT, 4)
        if cost_sink is not None:
            cost_sink.append(cost)
        return script, (data.get("conceit") or "").strip(), cost
    except Exception:
        return script, "", 0.0   # never let the revision pass kill the job


# ── Image generation ───────────────────────────────────────────────────────────

def _write_image_result(datum, output_path: str) -> None:
    # gpt-image-1 returns base64; dall-e style returns a url. Handle both.
    if getattr(datum, "b64_json", None):
        with open(output_path, "wb") as f:
            f.write(base64.b64decode(datum.b64_json))
    else:
        urllib.request.urlretrieve(datum.url, output_path)


def generate_image(prompt: str, output_path: str, reference_paths: list[str] | None = None,
                   cost_sink: list | None = None, size: str = "1536x1024") -> str:
    """Generate a scene image with gpt-image-2.

    If reference_paths is given, use image-edit mode so referenced cast members
    remain consistent; otherwise use text-to-image.
    `size` is the gpt-image-2 size string (landscape 1536x1024 or portrait 1024x1536).
    If cost_sink is given, the call's ACTUAL USD cost (from usage tokens) is appended.
    """
    client = _openai()
    valid_refs = [p for p in (reference_paths or []) if os.path.exists(p)]

    def _call(idempotency_key: str | None = None):
        extra_headers = ({"Idempotency-Key": idempotency_key} if idempotency_key else None)
        if valid_refs:
            files = [open(p, "rb") for p in valid_refs]
            try:
                return client.images.edit(
                    model=IMAGE_MODEL,
                    image=files if len(files) > 1 else files[0],
                    prompt=prompt,
                    size=size,
                    quality="medium",
                    extra_headers=extra_headers,
                )
            finally:
                for f in files:
                    f.close()
        return client.images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size=size,          # 1536x1024 (landscape) or 1024x1536 (portrait)
            quality="medium",
            n=1,
            extra_headers=extra_headers,
        )

    try:
        from durable_execution import canonical_hash, current as _durable_current
        runtime = _durable_current()
    except Exception:
        runtime = None
    if runtime:
        rel = os.path.relpath(os.path.abspath(output_path), runtime.output_dir)
        refs = [{"path": os.path.basename(path), "sha256": sha256_file(path)} for path in valid_refs]
        request = {"model": IMAGE_MODEL, "prompt": prompt, "size": size,
                   "quality": "medium", "references": refs}
        stage_key = "image:" + canonical_hash({"output": rel, "request": request})[:32]

        def _durable_call(idempotency_key: str):
            # tries=6 rides out transient endpoint blips; every retry carries the same stable key.
            resp = _retry(lambda: _call(idempotency_key), tries=6, label="image generation")
            actual = _image_cost_from_usage(resp)
            _write_image_result(resp.data[0], output_path)
            return {"model": IMAGE_MODEL, "output": rel}, actual

        _, actual, _ = runtime.paid_file(
            stage_key=stage_key, provider="openai-images", request=request,
            estimated_cost=_COST_IMG_HOST if valid_refs else _COST_IMG_BASE,
            output_path=output_path, operation=_durable_call)
        if cost_sink is not None:
            cost_sink.append(actual)
    else:
        resp = _retry(_call, tries=6, label="image generation")
        if cost_sink is not None:
            cost_sink.append(_image_cost_from_usage(resp))
        _write_image_result(resp.data[0], output_path)
    return output_path


def _evidence_reference_paths(state: dict, *, human_ok: bool, mascot_ok: bool,
                              continuity_source: str | None = None) -> list[str] | None:
    """Deterministic identity-first reference order; pure evidence can never receive Bolt."""
    refs: list[str] = []
    if state.get("include_human") and human_ok:
        refs.append(HUMAN_REF)
    if state.get("include_bolt") and not state.get("pure_evidence") and mascot_ok:
        refs.append(MASCOT_REF)
    # Pure evidence may explicitly forbid an object present in the master. Passing that master
    # back as a reference makes the generator copy the forbidden state.
    if (continuity_source and not state.get("pure_evidence")
            and os.path.exists(continuity_source) and continuity_source not in refs):
        refs.append(continuity_source)
    return refs or None


def _evidence_state_prompt(scene: dict, state: dict, continuity_pack: dict,
                           style_suffix: str) -> str:
    required = "; ".join(_s(item) for item in state.get("required_objects") or [])
    forbidden = "; ".join(_s(item) for item in state.get("forbidden_objects") or []) or "none"
    cast = "No characters. Show only physical evidence."
    if state.get("include_human") and state.get("include_bolt"):
        cast = "Alex performs the declared investigation action while Bolt materially assists."
    elif state.get("include_human"):
        cast = "Alex performs the declared investigation action; Bolt is absent."
    elif state.get("include_bolt"):
        cast = "Bolt performs the declared useful action; Alex is outside the frame."
    location = _s((continuity_pack.get("first_act_location") or {}).get("label"))
    absence = ""
    if state.get("forbidden_objects"):
        absence = (
            "ABSENCE IS A HARD COMPOSITION RULE: do not depict, imply, silhouette, reflect, "
            "or place any forbidden object anywhere in frame. "
        )
    return (
        f"Create one evidence-state frame for this narration phrase: "
        f"{_s(state.get('anchor_phrase'))}. PURPOSE: {_s(state.get('purpose'))}. "
        f"STATE BEFORE: {_s(state.get('state_before'))}. STATE NOW/AFTER: "
        f"{_s(state.get('state_after'))}. REQUIRED AND CLEARLY VISIBLE: {required}. "
        f"FORBIDDEN: {forbidden}. {absence}{cast} "
        + (f"CONTINUITY LOCATION: preserve {location}. " if state.get("opening") and location else "")
        + (f"COMPOSITION: {_s(state.get('visual'))}. " if _s(state.get("visual")) else "")
        + "The image must prove the state change without labels, arrows, text, or narration cards. "
        + style_suffix
    )


def _make_detail_reframe(source_path: str, output_path: str) -> str:
    """Create a deterministic center detail; it earns information only after vision verification."""
    from PIL import ImageOps
    image = Image.open(source_path).convert("RGB")
    width, height = image.size
    crop_width, crop_height = max(1, int(width * 0.68)), max(1, int(height * 0.68))
    left, top = (width - crop_width) // 2, (height - crop_height) // 2
    detail = image.crop((left, top, left + crop_width, top + crop_height))
    ImageOps.fit(detail, (width, height)).save(output_path, "JPEG", quality=92)
    return output_path


_EVIDENCE_VERIFY_SYSTEM = (
    "You are a fail-closed visual evidence inspector. Judge only visible pixels, never the prompt's "
    "intent. The first image is the target; any later images are identity/location/object continuity "
    "references and must be compared directly. Return ONLY JSON: "
    "{\"required_objects\":{\"exact requirement\":true|false},"
    "\"forbidden_objects_absent\":{\"exact forbidden item\":true|false},"
    "\"visible_information\":true|false,\"human_identity_matches\":true|false|null,"
    "\"clothing_matches\":true|false|null,\"location_matches\":true|false|null,"
    "\"opening_object_matches\":true|false|null,\"bolt_present\":true|false,"
    "\"reasons\":[\"specific visible failure\"]}. visible_information is true only when the "
    "requested state/evidence is actually readable, not merely because the image differs."
)


def verify_evidence_asset(image_path: str, state: dict, continuity_pack: dict,
                          cost_sink: list | None = None,
                          reference_paths: list[str] | None = None) -> dict:
    """Vision-verify object state and continuity. Invalid/unavailable judgment fails closed."""
    try:
        def image_block(path: str) -> dict:
            with open(path, "rb") as handle:
                payload = handle.read()
                encoded = base64.b64encode(payload).decode()
            # Image APIs may return PNG bytes into a .jpg path. Detect the encoded bytes instead
            # of trusting the extension; Anthropic rejects mismatched media types.
            media_type = "image/png" if payload.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
            return {"type": "image", "source": {
                "type": "base64", "media_type": media_type, "data": encoded}}
        expected = {
            "required_objects": state.get("required_objects") or [],
            "forbidden_objects": state.get("forbidden_objects") or [],
            "state_before": state.get("state_before"),
            "state_after": state.get("state_after"),
            "expect_human_identity": bool(state.get("include_human")),
            "expect_clothing": bool(state.get("include_human")),
            "expect_location": bool(state.get("location_id")),
            "expect_opening_object": bool(state.get("opening_object_id")),
            "pure_evidence": bool(state.get("pure_evidence")),
            "continuity": continuity_pack,
        }
        content = [image_block(image_path), {
            "type": "text", "text": "TARGET EVIDENCE IMAGE ABOVE. Verify it against:\n"
            + json.dumps(expected, ensure_ascii=False)}]
        for index, reference in enumerate(reference_paths or []):
            if os.path.isfile(reference):
                content.extend([
                    {"type": "text", "text": f"CONTINUITY REFERENCE {index + 1} BELOW:"},
                    image_block(reference),
                ])
        response = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=900, system=_EVIDENCE_VERIFY_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        if cost_sink is not None:
            cost_sink.append(_msg_cost(response.usage))
        result, repair_cost = _parse_script_json(response.content[0].text)
        if cost_sink is not None and repair_cost:
            cost_sink.append(repair_cost)
        if not isinstance(result, dict):
            raise ValueError("invalid evidence verification response")
        required = result.get("required_objects") if isinstance(result.get("required_objects"), dict) else {}
        forbidden = (result.get("forbidden_objects_absent")
                     if isinstance(result.get("forbidden_objects_absent"), dict) else {})
        required_pass = all(required.get(item) is True for item in expected["required_objects"])
        forbidden_pass = all(forbidden.get(item) is True for item in expected["forbidden_objects"])
        continuity_pass = all(
            result.get(field) is True
            for expected_key, field in (
                ("expect_human_identity", "human_identity_matches"),
                ("expect_clothing", "clothing_matches"),
                ("expect_location", "location_matches"),
                ("expect_opening_object", "opening_object_matches"),
            )
            if expected[expected_key]
        )
        bolt_pass = not (expected["pure_evidence"] and result.get("bolt_present") is True)
        visible = result.get("visible_information") is True
        passed = required_pass and forbidden_pass and continuity_pass and bolt_pass and visible
        reasons = [_s(item) for item in result.get("reasons") or [] if _s(item)]
        if not passed and not reasons:
            reasons = ["pixel verification did not satisfy every object-state and continuity check"]
        return {**result, "passed": passed, "visible_information": visible, "reasons": reasons}
    except Exception as exc:
        return {"passed": False, "visible_information": False,
                "reasons": [f"evidence verifier unavailable: {type(exc).__name__}: {str(exc)[:160]}"]}


def safe_image_prompt(scene: dict) -> str:
    """A moderation-safe retry that KEEPS the scene's surprise intent — a calm cosmic abstraction
    would tank visual_surprise on any blocked scene, so stay peculiar, just safe."""
    topic = (_s(scene.get("text_overlay")) or _s(scene.get("image_prompt"))[:60]).strip()
    if scene.get("human_present") and scene.get("mascot_present"):
        cast = "Alex actively investigating, with Bolt performing the declared supporting action"
    elif scene.get("human_present"):
        cast = "Alex actively investigating"
    elif scene.get("mascot_present"):
        cast = "Bolt performing the declared supporting action"
    else:
        cast = "no characters; show only the physical evidence"
    return (
        f"A simple, moderation-safe but VISUALLY ODD representation of '{topic}' — an object used "
        f"the wrong way, a wrong-scale prop, or a surprising juxtaposition; {cast}. Preserve the "
        "story action and make the evidence readable in half a second. Keep it peculiar and "
        "eye-catching, not calm, glowy, generic, violent, disturbing, or branded. Premium clean "
        "3D animated style. No text, letters, numbers, labels, UI, or watermark."
    )


def opening_evidence_gate_message(validation: dict) -> str:
    """Format the verified-information result without legacy percent-format crashes."""
    ratio = float(validation.get("verified_information_ratio") or 0.0)
    return f"Opening evidence gate: PASS — {ratio:.0%} verified-information cuts"


def make_fallback_frame(output_path: str, headline: str = "", w: int = 1920, h: int = 1080) -> str:
    """A local (no-API) branded filler frame, used when image generation can't recover.

    Guarantees every scene has a usable visual so one image failure never kills the job.
    """
    # Deep-navy → near-black vertical gradient (1px column, then stretched — fast).
    col = Image.new("RGB", (1, h))
    cpx = col.load()
    for y in range(h):
        t = y / h
        cpx[0, y] = (int(24 - 16 * t), int(34 - 22 * t), int(74 - 48 * t))
    col.resize((w, h)).save(output_path, "JPEG", quality=90)
    return output_path


# ── TTS generation ─────────────────────────────────────────────────────────────

def generate_tts(text: str, output_path: str, voice: str = "echo") -> str:
    def _call(idempotency_key: str | None = None):
        resp = _openai().audio.speech.create(
            model=TTS_MODEL,
            voice=voice,
            input=text,
            response_format="mp3",
            extra_headers=({"Idempotency-Key": idempotency_key} if idempotency_key else None),
        )
        with open(output_path, "wb") as f:
            for chunk in resp.iter_bytes():
                f.write(chunk)
        return output_path

    try:
        from durable_execution import canonical_hash, current as _durable_current
        runtime = _durable_current()
    except Exception:
        runtime = None
    if not runtime:
        return _retry(_call, label="TTS")
    rel = os.path.relpath(os.path.abspath(output_path), runtime.output_dir)
    request = {"model": TTS_MODEL, "voice": voice, "text_sha256":
               hashlib.sha256(text.encode("utf-8")).hexdigest(), "characters": len(text)}
    stage_key = "tts:" + canonical_hash({"output": rel, "request": request})[:32]

    def _durable_call(idempotency_key: str):
        _retry(lambda: _call(idempotency_key), label="TTS")
        return {"model": TTS_MODEL, "voice": voice, "output": rel}, len(text) * _RATE_TTS_CHAR

    runtime.paid_file(
        stage_key=stage_key, provider="openai-tts", request=request,
        estimated_cost=len(text) * _RATE_TTS_CHAR, output_path=output_path,
        operation=_durable_call)
    return output_path


# ── Helpers ────────────────────────────────────────────────────────────────────

def _audio_dur(path: str) -> float:
    r = subprocess.run(
        [_ffprobe_bin(), "-v", "quiet", "-print_format", "json", "-show_format", path],
        capture_output=True, text=True, check=True,
        stdin=subprocess.DEVNULL, timeout=30.0,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def _fit_script_to_measured_audio(script: dict, timing_report: dict, target_seconds: float,
                                  *, cost_sink: list | None = None) -> None:
    """Rewrite only narration-bound fields using observed natural-speed scene durations."""
    scenes = script.get("scenes") or []
    measured = timing_report.get("scenes") or []
    if len(scenes) != len(measured):
        raise ValueError("Measured audio fit cannot map every scene.")
    scale = float(target_seconds) / max(0.1, float(timing_report.get("measured_seconds") or 0.0))
    payload = []
    for scene, timing in zip(scenes, measured):
        payload.append({
            "narration": _s(scene.get("narration")),
            "measured_seconds": timing.get("duration_sec"),
            "target_seconds": round(float(timing.get("duration_sec") or 0.0) * scale, 3),
            "visual_beats": scene.get("visual_beats") or [],
            "motion_anchor_phrase": _s(scene.get("motion_anchor_phrase")),
            "claim_refs": scene.get("claim_refs") or [],
            "evidence_id": _s(scene.get("evidence_id")),
        })
    prompt = (
        f"The complete narration was rendered at natural 1.0x TTS speed and measured "
        f"{timing_report.get('measured_seconds')} seconds. Rewrite it to measure {target_seconds} "
        f"seconds (allowed ±3%) with the SAME voice and exactly {len(scenes)} scenes. Use each scene's "
        "measured_seconds and target_seconds as observed calibration, not a generic words-per-minute "
        "guess. Preserve story role, human intention, belief/decision, question payoff, all facts, every "
        "claim_id, and every evidence_id. Update claim narration_phrase, visual beat anchor_phrase, and "
        "motion_anchor_phrase so each is an exact consecutive substring of the FINAL narration. Never "
        "add an unsupported claim or post-stretch instruction. Return ONLY JSON: "
        '{"scenes":[{"narration":"","visual_beats":[],"motion_anchor_phrase":"",'
        '"claim_refs":[],"evidence_id":""}]}.\nINPUT:\n' + json.dumps(payload, ensure_ascii=False)
    )
    response = _claude().messages.create(
        model=ANTHROPIC_MODEL, max_tokens=12000, system=_SCRIPT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    fitted, repair_cost = _parse_script_json(response.content[0].text)
    if cost_sink is not None:
        cost_sink.append(_msg_cost(response.usage) + repair_cost)
    new_scenes = fitted.get("scenes") if isinstance(fitted, dict) else None
    if not isinstance(new_scenes, list) or len(new_scenes) != len(scenes):
        raise ValueError("Measured audio fitter changed the scene count.")
    for scene, new in zip(scenes, new_scenes):
        narration = _s(new.get("narration"))
        if not narration:
            raise ValueError("Measured audio fitter returned empty narration.")
        scene["narration"] = narration
        if isinstance(new.get("visual_beats"), list):
            scene["visual_beats"] = new["visual_beats"]
        scene["motion_anchor_phrase"] = _s(new.get("motion_anchor_phrase"))
        if isinstance(new.get("claim_refs"), list):
            scene["claim_refs"] = new["claim_refs"]
        if _s(new.get("evidence_id")):
            scene["evidence_id"] = _s(new.get("evidence_id"))


def _prepare_longform_audio(script: dict, dossier: dict, aud_dir: str, voice: str,
                            target_seconds: float, *, tts_costs: list[float],
                            aux_costs: list[float], question: str = "",
                            log=lambda message: None) -> tuple[list[dict], dict]:
    """Generate, measure, and if necessary refit all TTS before buying visual assets."""
    scenes = script.get("scenes") or []
    os.makedirs(aud_dir, exist_ok=True)

    def render_audio(force: bool) -> list[dict]:
        def one(item):
            i, scene = item
            path = os.path.join(aud_dir, f"scene_{i:02d}.mp3")
            digest_path = path + ".narration.sha256"
            digest_payload = f"{TTS_MODEL}\0{voice}\0{_s(scene.get('narration'))}"
            digest = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()
            generated = False
            cached_digest = ""
            try:
                with open(digest_path) as handle:
                    cached_digest = handle.read().strip()
            except OSError:
                pass
            if force or cached_digest != digest:
                if os.path.exists(path):
                    os.remove(path)
            if force and os.path.exists(digest_path):
                os.remove(digest_path)
            if not os.path.exists(path) or os.path.getsize(path) <= 0:
                generate_tts(_s(scene.get("narration")), path, voice=voice)
                with open(digest_path, "w") as handle:
                    handle.write(digest)
                tts_costs.append(len(_s(scene.get("narration"))) * _RATE_TTS_CHAR)
                generated = True
            timings = transcribe_words(path)
            with open(path, "rb") as audio_handle:
                audio_sha256 = hashlib.sha256(audio_handle.read()).hexdigest()
            return {
                "i": i, "aud": path, "word_times": timings, "generated": generated,
                "audio_transformation": {
                    "provider": "openai", "model": TTS_MODEL, "voice": voice,
                    "speed_multiplier": 1.0, "operations": [],
                    "audio_sha256": audio_sha256,
                    "cache_status": "generated" if generated else "digest_verified_cache",
                },
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            return sorted(_context_map(executor, one, enumerate(scenes)),
                          key=lambda item: item["i"])

    results: list[dict] = []
    report: dict = {}
    for attempt in range(3):
        results = render_audio(force=attempt > 0)
        report = build_audio_timing_report(
            scenes,
            [item["aud"] for item in results],
            [item["word_times"] for item in results],
            target_seconds,
            duration_probe=_audio_dur,
            audio_transformations=[item["audio_transformation"] for item in results],
        )
        log(f"Measured natural-speed TTS: {report.get('measured_seconds', 0):.2f}s "
            f"for {target_seconds:.2f}s target (pass {attempt + 1}/3)")
        if report.get("passed"):
            break
        non_runtime = [error for error in report.get("errors", [])
                       if error.get("code") != "measured_runtime_outside_tolerance"]
        if non_runtime:
            raise ValueError(
                "Measured audio timing failed: "
                + "; ".join(error["message"] for error in non_runtime[:6])
            )
        if attempt >= 2:
            break
        _fit_script_to_measured_audio(
            script, report, target_seconds, cost_sink=aux_costs)
        story_validation = validate_longform_story(script, question or _s(script.get("title")))
        claim_validation = validate_claim_joins(script, dossier)
        if not story_validation.get("passed") or not claim_validation.get("passed"):
            raise ValueError(
                "Measured runtime rewrite broke the story or claim contract before visual spend."
            )

    if not report.get("passed"):
        raise ValueError(
            "Measured natural-speed runtime failed before visual spend: "
            f"{report.get('measured_seconds', 0):.2f}s for {target_seconds:.2f}s target "
            f"(allowed {report.get('minimum_seconds', 0):.2f}–{report.get('maximum_seconds', 0):.2f}s)."
        )
    script["_audio_timing"] = report
    return results, report


# Fun ROUNDED bold first (the branded headline look), with plain-bold fallbacks.
_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
    "/System/Library/Fonts/SFNSRounded.ttf",
    "/System/Library/Fonts/SFCompactRounded.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

def _find_font() -> str | None:
    for p in _FONT_PATHS:
        if os.path.exists(p):
            return p
    return None


# ── Text overlay (Pillow → transparent PNG) ────────────────────────────────────
# This ffmpeg build has no drawtext filter, so we render text with Pillow and
# composite it via the overlay filter.

from PIL import Image, ImageDraw, ImageFont, ImageFilter   # noqa: E402

W, H = 1920, 1080
FADE_DUR = 0.5   # crossfade length between scenes (seconds)


def _pil_font(size: int):
    p = _find_font()
    if p:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


# ── Text director — branded, scene-aware typography (rendered in Pillow) ───────

# Named palette → RGB. Claude picks from these names; code guarantees they render.
_NAMED_COLORS = {
    "white": (255, 255, 255), "cream": (255, 248, 230), "cyan": (90, 230, 255),
    "mint": (150, 255, 210), "violet": (180, 150, 255), "purple": (190, 130, 255),
    "gold": (255, 205, 70), "orange": (255, 150, 60), "warm_yellow": (255, 225, 120),
    "warm_gold": (255, 210, 110), "pale_blue": (180, 215, 255), "navy": (12, 18, 40),
}

# Per style-mode defaults used when Claude omits a color.
_MODE_PALETTE = {
    "educational": {"title": "white", "accent": "mint",   "subtitle": "warm_yellow"},
    "scientific":  {"title": "white", "accent": "cyan",   "subtitle": "pale_blue"},
    "cinematic":   {"title": "cream", "accent": "gold",   "subtitle": "warm_gold"},
    "fun":         {"title": "white", "accent": "violet", "subtitle": "warm_yellow"},
}


def _s(v, default: str = "") -> str:
    """Coerce a model-supplied field to a safe string. The script LLM occasionally emits a
    bool/int/list where a string is expected (e.g. "card": true), and a bare .strip()/.lower()
    on that value crashes the whole render (caught by the scene-1 smoke-test)."""
    return v if isinstance(v, str) else default


def _rgb(name, fallback=(255, 255, 255)):
    return _NAMED_COLORS.get(_s(name).strip().lower(), fallback)


def _anchor_xy(placement: str, block_w: int, block_h: int) -> tuple[int, int]:
    """Top-left origin for a text block given a placement keyword."""
    mx, top, bottom = int(W * 0.055), int(H * 0.07), int(H * 0.70)
    p = (_s(placement) or "top_center").lower()
    if "lower" in p or "bottom" in p:
        y = bottom
    elif "center" in p and "top" not in p:
        y = (H - block_h) // 2
    else:
        y = top
    if "left" in p:
        x = mx
    elif "right" in p:
        x = W - mx - block_w
    else:
        x = (W - block_w) // 2
    return x, y


def _tint(rgb, f):
    """Lighten an RGB toward white by fraction f (0..1)."""
    return tuple(int(c + (255 - c) * f) for c in rgb)


def _vgrad(size, top_rgb, bot_rgb, y0, y1):
    """Vertical 2-stop gradient RGBA spanning rows y0..y1 (clamped outside)."""
    w, h = size
    col = Image.new("RGB", (1, h))
    px = col.load()
    span = max(1, y1 - y0)
    for y in range(h):
        t = min(1.0, max(0.0, (y - y0) / span))
        px[0, y] = tuple(int(top_rgb[i] + (bot_rgb[i] - top_rgb[i]) * t) for i in range(3))
    return col.resize((w, h)).convert("RGBA")


def _draw_word(base, xy, word, font, color_rgb, stroke_rgb, stroke_w, glow_rgb):
    """Sticker word: drop-shadow + neon glow + chunky dark outline + glossy gradient fill.
    Returns the pen-advance width."""
    d0 = ImageDraw.Draw(base)
    bb = d0.textbbox((0, 0), word, font=font, stroke_width=stroke_w)
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    pad = stroke_w + 30
    tile = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    ox, oy = pad - bb[0], pad - bb[1]

    # 1) drop shadow (sticker lift)
    sh = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((ox + 6, oy + 9), word, font=font, fill=(0, 0, 0, 150),
                            stroke_width=stroke_w, stroke_fill=(0, 0, 0, 150))
    tile.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4)))

    # 2) neon outer glow in the word's colour
    if glow_rgb:
        gl = Image.new("RGBA", tile.size, (0, 0, 0, 0))
        ImageDraw.Draw(gl).text((ox, oy), word, font=font, fill=(*glow_rgb, 255),
                                stroke_width=stroke_w + 6, stroke_fill=(*glow_rgb, 255))
        tile.alpha_composite(gl.filter(ImageFilter.GaussianBlur(11)))

    # 3) chunky dark outline (drawn as stroked dark glyph)
    ImageDraw.Draw(tile).text((ox, oy), word, font=font, fill=stroke_rgb,
                              stroke_width=stroke_w, stroke_fill=stroke_rgb)

    # 4) glossy gradient fill inside the glyph (light top → colour bottom)
    glyph_mask = Image.new("L", tile.size, 0)
    ImageDraw.Draw(glyph_mask).text((ox, oy), word, font=font, fill=255)
    grad = _vgrad(tile.size, _tint(color_rgb, 0.65), color_rgb, oy, oy + h)
    tile = Image.composite(grad, tile, glyph_mask)

    base.alpha_composite(tile, (xy[0] - pad, xy[1] - pad))
    return int(d0.textlength(word, font=font))


def _sparkles(base, cx, cy, color, n=3, scale=1.0):
    """Comic-style accent ticks + a sparkle near (cx,cy)."""
    d = ImageDraw.Draw(base)
    import math
    for k in range(n):
        ang = math.radians(-90 + (k - (n - 1) / 2) * 34)
        r0, r1 = int(14 * scale), int(34 * scale)
        x0, y0 = cx + r0 * math.cos(ang), cy + r0 * math.sin(ang)
        x1, y1 = cx + r1 * math.cos(ang), cy + r1 * math.sin(ang)
        d.line([(x0, y0), (x1, y1)], fill=(*color, 235), width=max(3, int(5 * scale)))
    # 4-point sparkle
    sx, sy, s = cx + int(20 * scale), cy - int(26 * scale), int(11 * scale)
    d.polygon([(sx, sy - s), (sx + s // 3, sy - s // 3), (sx + s, sy),
               (sx + s // 3, sy + s // 3), (sx, sy + s), (sx - s // 3, sy + s // 3),
               (sx - s, sy), (sx - s // 3, sy - s // 3)], fill=(*color, 240))


def _make_text_png(text_overlay: str, text_sub: str, output_path: str,
                   text_meta: dict | None = None, style_mode: str = "educational") -> bool:
    """Render branded, scene-aware title + subtitle to a 1920×1080 PNG. False if empty."""
    title = _s(text_overlay).strip().upper()
    sub   = _s(text_sub).strip()
    if not (title or sub):
        return False

    meta = text_meta if isinstance(text_meta, dict) else {}   # tolerate non-dict 'text' from the model
    pal  = _MODE_PALETTE.get(style_mode, _MODE_PALETTE["educational"])
    title_rgb  = _rgb(meta.get("title_color"), _rgb(pal["title"]))
    accent_rgb = _rgb(meta.get("accent_color"), _rgb(pal["accent"]))
    sub_rgb    = _rgb(meta.get("subtitle_color"), _rgb(pal["subtitle"]))
    _ew        = meta.get("emphasis_words")
    emphasis   = {_s(w).strip().upper() for w in _ew if _s(w).strip()} if isinstance(_ew, list) else set()
    placement  = _s(meta.get("placement"), "top_center")
    card       = (_s(meta.get("card")) or "none").lower()
    stroke     = (*_rgb("navy"), 235)

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    title_f, sub_f = _pil_font(96), _pil_font(40)
    sw_t, sw_s = 8, 3            # chunky title outline, slim subtitle outline
    words = title.split()

    # Two-tone like the reference: emphasis words (or the last word, if none flagged)
    # take the accent colour; the rest take the title colour.
    if not emphasis and len(words) >= 2:
        emphasis = {words[-1]}

    sp = int(draw.textlength(" ", font=title_f))
    word_ws = [int(draw.textlength(w, font=title_f)) for w in words]
    title_w = sum(word_ws) + sp * max(0, len(words) - 1) if words else 0
    tb = draw.textbbox((0, 0), title or "X", font=title_f, stroke_width=sw_t)
    title_h = tb[3] - tb[1]
    sub_w = int(draw.textlength(sub, font=sub_f)) if sub else 0
    pill_pad_x, pill_pad_y = 26, 14
    sub_block_h = (draw.textbbox((0, 0), sub, font=sub_f)[3] + 2 * pill_pad_y) if sub else 0
    gap = int(title_h * 0.20) if (title and sub) else 0
    block_w = max(title_w, sub_w + 2 * pill_pad_x)
    block_h = title_h + gap + sub_block_h

    x0, y0 = _anchor_xy(placement, block_w, block_h)
    left_align = "left" in placement.lower() or (meta.get("alignment") == "left")
    right_align = "right" in placement.lower() or (meta.get("alignment") == "right")

    def line_x(line_w):
        if left_align:  return x0
        if right_align: return x0 + block_w - line_w
        return x0 + (block_w - line_w) // 2

    # Optional full backing card (only when Claude asks for "panel").
    if card == "panel":
        pad = 30
        cl = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(cl).rounded_rectangle(
            [x0 - pad, y0 - pad, x0 + block_w + pad, y0 + block_h + pad],
            radius=36, fill=(*_rgb("navy"), 170), outline=(*accent_rgb, 230), width=5)
        img.alpha_composite(cl)

    # Title — sticker words, each with neon glow + glossy gradient.
    cx = line_x(title_w)
    for w, ww in zip(words, word_ws):
        col = accent_rgb if w in emphasis else title_rgb
        _draw_word(img, (cx, y0), w, title_f, color_rgb=col,
                   stroke_rgb=(*_rgb("navy"), 255), stroke_w=sw_t, glow_rgb=col)
        cx += ww + sp

    # Comic accent bursts at the title's upper corners.
    _sparkles(img, line_x(title_w) - 6, y0 + int(title_h * 0.18), accent_rgb, n=3, scale=1.1)
    _sparkles(img, line_x(title_w) + title_w + 6, y0 + int(title_h * 0.10),
              _rgb(pal["accent"]) if not emphasis else title_rgb, n=3, scale=0.9)

    # Subtitle as a sticker pill.
    if sub:
        sy = y0 + title_h + gap
        sx = line_x(sub_w + 2 * pill_pad_x)
        pill = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(pill).rounded_rectangle(
            [sx, sy, sx + sub_w + 2 * pill_pad_x, sy + draw.textbbox((0, 0), sub, font=sub_f)[3] + 2 * pill_pad_y],
            radius=22, fill=(*_rgb("navy"), 215), outline=(*sub_rgb, 235), width=3)
        img.alpha_composite(pill)
        ImageDraw.Draw(img).text((sx + pill_pad_x, sy + pill_pad_y), sub, font=sub_f,
                                 fill=(*sub_rgb, 255), stroke_width=2, stroke_fill=(*_rgb("navy"), 230))

    img.save(output_path, "PNG")
    return True


def _make_caption_png(phrase: str, vw: int, vh: int, output_path: str,
                      style_mode: str = "educational") -> None:
    """Clean 'premium science' caption: a short phrase in white on a dark translucent pill, with
    the single most important word in the accent colour. Lower-MIDDLE safe zone (clear of the
    Shorts bottom UI). 9:16 social format."""
    pal = _MODE_PALETTE.get(style_mode, _MODE_PALETTE["educational"])
    accent = _rgb(pal["accent"])
    white = (244, 246, 250)
    words = [w for w in _s(phrase).strip().upper().split() if w]
    if not words:
        Image.new("RGBA", (vw, vh), (0, 0, 0, 0)).save(output_path, "PNG")
        return
    img = Image.new("RGBA", (vw, vh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    size = int(vh * 0.052)
    f = _pil_font(size)
    sp = int(d.textlength(" ", font=f))
    while size > 32 and d.textlength(" ".join(words), font=f) > vw * 0.84:
        size -= 5
        f = _pil_font(size)
        sp = int(d.textlength(" ", font=f))

    # Greedy wrap to ≤2 lines.
    lines, cur = [], []
    for w in words:
        if cur and d.textlength(" ".join(cur + [w]), font=f) > vw * 0.84:
            lines.append(cur); cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)

    # Highlight ONE word (the key term): longest CONTENT word ≥4 chars, skipping filler/adverbs
    # (so "SIGNAL straight up" highlights SIGNAL, not "STRAIGHT"). No highlight if none qualifies.
    cand = [w for w in words if w not in _CAPTION_FILLER and len(w) >= 4]
    hi = max(cand, key=lambda w: (len(w), -words.index(w))) if cand else ""

    ab = d.textbbox((0, 0), "Xg", font=f)
    line_h = (ab[3] - ab[1]) + int(size * 0.34)
    total_h = line_h * len(lines)
    line_ws = [sum(int(d.textlength(w, font=f)) for w in ln) + sp * (len(ln) - 1) for ln in lines]
    block_w = max(line_ws) if line_ws else 0

    y0 = int(vh * 0.68) - total_h // 2          # lower-middle, above the bottom UI
    # Dark translucent rounded pill behind the whole block.
    pad_x, pad_y = int(size * 0.6), int(size * 0.42)
    pill = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle(
        [(vw - block_w) // 2 - pad_x, y0 - pad_y,
         (vw + block_w) // 2 + pad_x, y0 + total_h + pad_y],
        radius=int(size * 0.5), fill=(12, 15, 24, 188))
    img.alpha_composite(pill)

    y = y0
    for ln, lw in zip(lines, line_ws):
        x = (vw - lw) // 2
        for w in ln:
            d.text((x, y), w, font=f, fill=(*(accent if w == hi else white), 255),
                   stroke_width=max(2, size // 18), stroke_fill=(8, 10, 16, 235))
            x += int(d.textlength(w, font=f)) + sp
        y += line_h
    img.save(output_path, "PNG")


def _make_bubble_png(phrase: str, vw: int, vh: int, side: str, output_path: str,
                     style_mode: str = "educational") -> None:
    """A comic speech bubble (rounded panel + tail toward Bolt) holding a short phrase,
    placed in an upper corner — for the landscape 'Bolt is talking' treatment.
    `side` is where the BUBBLE sits (the clear zone); the tail points to the opposite side."""
    pal = _MODE_PALETTE.get(style_mode, _MODE_PALETTE["educational"])
    accent = _rgb(pal["accent"])
    words = [w for w in _s(phrase).strip().upper().split() if w]
    img = Image.new("RGBA", (vw, vh), (0, 0, 0, 0))
    if not words:
        img.save(output_path, "PNG"); return
    d = ImageDraw.Draw(img)

    bw, bh = int(vw * 0.42), int(vh * 0.24)
    my = int(vh * 0.07)
    if "left" in side:    bx = int(vw * 0.04)
    elif "right" in side: bx = vw - bw - int(vw * 0.04)
    else:                 bx = (vw - bw) // 2

    # Bubble panel.
    bubble = Image.new("RGBA", img.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(bubble)
    bd.rounded_rectangle([bx, my, bx + bw, my + bh], radius=40,
                         fill=(*_rgb("navy"), 224), outline=(*accent, 240), width=6)
    # Tail toward Bolt (opposite the bubble side): a slim pointer with accent edges to
    # match the bubble outline.
    ty = my + bh
    if "left" in side:       tx = bx + int(bw * 0.72)   # bubble left → Bolt right
    elif "right" in side:    tx = bx + int(bw * 0.28)   # bubble right → Bolt left
    else:                    tx = bx + bw // 2
    tdir = 1 if "left" in side else (-1 if "right" in side else 0)
    TW, TH = 64, 66
    if tdir < 0:                       # point down-left
        pts = [(tx, ty - 2), (tx + TW, ty - 2), (tx - 8, ty + TH)]
    elif tdir > 0:                     # point down-right
        pts = [(tx - TW, ty - 2), (tx, ty - 2), (tx + 8, ty + TH)]
    else:                              # straight down
        pts = [(tx - TW // 2, ty - 2), (tx + TW // 2, ty - 2), (tx, ty + TH)]
    bd.polygon(pts, fill=(*_rgb("navy"), 224))
    bd.line([pts[0], pts[2]], fill=(*accent, 240), width=5)   # accent the slanted edges
    bd.line([pts[1], pts[2]], fill=(*accent, 240), width=5)
    img.alpha_composite(bubble)

    # Sticker text inside the bubble (wrap ≤2 lines, fit width).
    size = int(bh * 0.42)
    f = _pil_font(size)
    while size > 28 and d.textlength(" ".join(words), font=f) > bw * 0.84:
        size -= 4; f = _pil_font(size)
    sp = int(d.textlength(" ", font=f))
    lines, cur = [], []
    for w in words:
        if cur and d.textlength(" ".join(cur + [w]), font=f) > bw * 0.84:
            lines.append(cur); cur = [w]
        else:
            cur.append(w)
    if cur: lines.append(cur)
    line_h = d.textbbox((0, 0), "X", font=f, stroke_width=6)[3] + int(size * 0.10)
    # Center the text block vertically in the panel, with a small downward nudge (caps
    # sit visually high because the bbox reserves descent space they don't use).
    y = my + (bh - line_h * len(lines)) // 2 + int(size * 0.12)
    for ln in lines:
        lw = sum(int(d.textlength(w, font=f)) for w in ln) + sp * (len(ln) - 1)
        x = bx + (bw - lw) // 2
        for w in ln:
            _draw_word(img, (x, y), w, f, color_rgb=accent,
                       stroke_rgb=(*_rgb("navy"), 255), stroke_w=6, glow_rgb=accent)
            x += int(d.textlength(w, font=f)) + sp
        y += line_h
    img.save(output_path, "PNG")


def _even_split(words: list, t0: float, t1: float) -> list:
    """Distribute words evenly across [t0, t1] — timing fallback when Whisper is unusable."""
    n = len(words)
    span = max(0.1, t1 - t0)
    step = span / max(1, n)
    return [(w, t0 + i * step, t0 + (i + 1) * step) for i, w in enumerate(words)]


def align_caption_phrases(narration: str, whisper_words: list, audio_dur: float,
                          max_words: int = 3) -> list:
    """FORCED ALIGNMENT: captions always show the SCRIPT's words (correct spelling);
    Whisper supplies only timing. Falls back to an even split when Whisper is unusable.
    Returns phrase tokens [(text, start, end)], grouped ≤max_words, with no gaps."""
    script_words = [w for w in (narration or "").split() if w]
    if not script_words:
        return []
    if whisper_words and len(whisper_words) == len(script_words):
        timed = [(script_words[i], float(whisper_words[i][1]), float(whisper_words[i][2]))
                 for i in range(len(script_words))]
    elif whisper_words:
        timed = _even_split(script_words, float(whisper_words[0][1]), float(whisper_words[-1][2]))
    else:
        timed = _even_split(script_words, 0.0, audio_dur)

    phrases = []
    for i in range(0, len(timed), max_words):
        chunk = timed[i:i + max_words]
        phrases.append([" ".join(w for w, _, _ in chunk), chunk[0][1], chunk[-1][2]])
    for j in range(len(phrases)):
        nxt = phrases[j + 1][1] if j + 1 < len(phrases) else min(audio_dur, phrases[j][2] + 0.4)
        phrases[j][2] = max(phrases[j][1] + 0.2, nxt)
    return [(t, s, e) for t, s, e in phrases]


# ── Camera motion presets ──────────────────────────────────────────────────────
# Eased Ken Burns / pan presets. Commas inside min()/max() are escaped with "\,"
# because an unescaped comma is read as a filter separator inside filter_complex.

_CENTER_X = "iw/2-(iw/zoom/2)"
_CENTER_Y = "ih/2-(ih/zoom/2)"


def _motion(preset: str, n: int) -> tuple[str, str, str]:
    """Return (z_expr, x_expr, y_expr) for a zoompan preset over n frames."""
    r = f"on/{n}"                       # 0 → 1 linear ramp
    ease = f"(1-(1-{r})*(1-{r}))"       # ease-out (decelerate)
    ZMAX = "1.14"

    presets = {
        "locked":        ("1.0", _CENTER_X, _CENTER_Y),
        "kenburns_in":  (f"min(1.0+0.14*{ease}\\,{ZMAX})", _CENTER_X, _CENTER_Y),
        "kenburns_out": (f"max({ZMAX}-0.14*{ease}\\,1.0)", _CENTER_X, _CENTER_Y),
        "pan_right":    ("1.14", f"(iw-iw/zoom)*{ease}",            _CENTER_Y),
        "pan_left":     ("1.14", f"(iw-iw/zoom)*(1-{ease})",        _CENTER_Y),
        "pan_up":       ("1.14", _CENTER_X, f"(ih-ih/zoom)*(1-{ease})"),
        "pan_down":     ("1.14", _CENTER_X, f"(ih-ih/zoom)*{ease}"),
        "zoom_tl":      (f"min(1.0+0.16*{ease}\\,1.16)", "0", "0"),
        "zoom_br":      (f"min(1.0+0.16*{ease}\\,1.16)", "iw-iw/zoom", "ih-ih/zoom"),
    }
    return presets.get(preset, presets["kenburns_in"])


# Map shot_type → two motion variants; index parity picks one so adjacent
# scenes of the same type still move differently.
_SHOT_MOTION = {
    "wide":   ["pan_right", "pan_left"],
    "aerial": ["pan_down", "kenburns_out"],
    "close":  ["kenburns_in", "zoom_tl"],
    "detail": ["zoom_br", "zoom_tl"],
    "medium": ["kenburns_in", "kenburns_out"],
}


def _pick_motion(shot_type: str, index: int) -> str:
    variants = _SHOT_MOTION.get((_s(shot_type) or "medium").lower(), _SHOT_MOTION["medium"])
    return variants[index % 2]


# ── Per-scene segment ──────────────────────────────────────────────────────────

def _i2v_size(vw: int, vh: int) -> str:
    """Map our canvas to the nearest 720p i2v size the providers accept."""
    return "720x1280" if vh > vw else "1280x720"


def _select_i2v_indices(scenes: list, question: str, video_format: str,
                        budget_clips: int) -> frozenset:
    """Deterministic, seeded pick of ~I2V_FRACTION of scenes to animate. ALWAYS includes scene 0
    (the opener), favours the hook/twist/loop/metaphor beats, then fills evenly. Capped at
    min(MAX_I2V_CLIPS, budget_clips). Same (question, format, n) → same picks (resume-stable)."""
    import random
    n = len(scenes)
    if n == 0 or budget_clips <= 0:
        return frozenset()
    frac = I2V_FRACTION_SOCIAL if video_format == "social" else I2V_FRACTION
    target = min(budget_clips, MAX_I2V_CLIPS, max(1, round(n * frac)))

    # FRONT-LOAD motion into the OPENING (viewers — feed OR long-form — decide in the first seconds),
    # keep one clip for the FINALE (payoff/loop — for sims that's the climax), and space the rest across
    # the back half so it isn't all stills. Applies to BOTH formats now (long-form i2v is off by default,
    # but WHEN it's on, front-loading beats the old even spread). Cost-neutral — just better placement.
    if n >= 4 and target >= 2:
        mid = max(2, (n + 1) // 2)                    # scenes [0, mid) = the "first half"
        picks = {0}                                   # opener, always
        first_target = max(1, round(target * I2V_FRONTLOAD_SOCIAL))
        i = 1
        while sum(1 for p in picks if p < mid) < first_target and i < mid:
            picks.add(i); i += 1                      # densely animate the earliest scenes
        if target - len(picks) >= 1 and n >= 3:
            picks.add(n - 1)                          # reserve the finale/payoff
        remaining = target - len(picks)
        back = [j for j in range(mid, n - 1) if j not in picks]
        if back and remaining > 0:
            step = len(back) / remaining              # spread the leftover evenly across the back half
            for k in range(remaining):
                picks.add(back[min(len(back) - 1, int(k * step))])
        return frozenset(sorted(picks)[:target])

    # LONG-FORM (and tiny shorts): original seeded pick — opener + twist/loop/metaphor + even fill.
    import hashlib
    # STABLE seed: Python's built-in hash() of a string is salted per-process (PYTHONHASHSEED), so it
    # would pick DIFFERENT scenes after a restart — breaking the docstring's resume-stability promise and
    # wasting spend on a resumed long-form render. md5 of the key is deterministic across processes.
    seed = int(hashlib.md5(f"{question}|{video_format}|{n}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    picks = {0}                                       # the first image, unconditionally
    for i in [n - 1, n - 2] + [j for j, s in enumerate(scenes)
                               if s.get("scene_type") == "metaphor_scene"]:
        if len(picks) >= target:
            break
        if 0 <= i < n:
            picks.add(i)
    rest = [i for i in range(n) if i not in picks]
    rng.shuffle(rest)
    for i in rest:
        if len(picks) >= target:
            break
        picks.add(i)
    return frozenset(sorted(picks)[:target])


# Provider fallback chain parsed from I2V_PROVIDER (e.g. "veo,sora"): try each in order, drop
# to the next on quota/failure, then ffmpeg Ken-Burns if all fail. Veo 3.x share ONE project
# quota (probed), so the useful fallback is a DIFFERENT provider (Sora = separate OpenAI quota).
_I2V_CHAIN = [p.strip() for p in I2V_PROVIDER.split(",") if p.strip()]


def _motion_model_id(provider: str, *, fal_model: str | None = None) -> str:
    models = {
        "sora": _SORA_MODEL,
        "veo": _VEO_MODEL,
        "fal": fal_model or _FAL_MODEL,
    }
    model_id = models.get(provider)
    if not model_id:
        raise ValueError(f"Unsupported I2V provider in generation manifest: {provider!r}")
    return model_id


def _generation_manifest_payload(*, video_format: str, motion_mode: str,
                                 threshold_profile: dict) -> dict:
    """Describe the exact provider request identifiers used by this pipeline build.

    This is an execution manifest, not a claim that provider aliases are immutable.
    """
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "video_format": video_format,
        "motion_mode": motion_mode,
        "models": [
            # Not a pinned snapshot: current-generation Anthropic IDs carry no date suffix and
            # no dated snapshot of this model exists to pin to, so this is a request identifier
            # like every other entry. Labelling it otherwise recorded false provenance for the
            # model behind the evidence verifier and the blind story judge.
            {"purpose": "research_script_factcheck_and_visual_judges", "provider": "anthropic",
             "model_id": ANTHROPIC_MODEL, "identifier_stability": "request_identifier"},
            {"purpose": "evidence_and_scene_images", "provider": "openai",
             "model_id": IMAGE_MODEL, "identifier_stability": "request_identifier"},
            {"purpose": "narration", "provider": "openai", "model_id": TTS_MODEL,
             "identifier_stability": "request_identifier"},
            {"purpose": "word_timestamps", "provider": "openai",
             "model_id": TRANSCRIPTION_MODEL, "identifier_stability": "request_identifier"},
        ] + [
            {"purpose": "image_to_video", "provider": provider,
             "model_id": _motion_model_id(provider),
             "identifier_stability": "configured_request_identifier"}
            for provider in _I2V_CHAIN
        ] + ([
            {"purpose": "image_to_video_hero", "provider": "fal",
             "model_id": _FAL_MODEL_HERO,
             "identifier_stability": "configured_request_identifier"},
        ] if "fal" in _I2V_CHAIN and _FAL_HYBRID else []),
        "threshold_profile": threshold_profile,
        "actual_motion": [],
        "status": "started",
    }


def _write_generation_manifest(path: str, manifest: dict) -> str:
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
    os.replace(temp, path)
    return path


def _clip_is_real(path, min_dur=0.8):
    """True only if `path` is a real decodable video clip (has a video stream with width>0 and
    a plausible duration). Guards the i2v success gate so a corrupt/truncated/empty file — or an
    audio-only artifact — can never be reported as a successful animation (the silent-slop bug)."""
    try:
        import subprocess as _sp
        w = _sp.run([_ffprobe_bin(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                     "stream=width", "-of", "csv=p=0", path], capture_output=True, text=True, timeout=20).stdout.strip()
        d = _sp.run([_ffprobe_bin(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                    capture_output=True, text=True, timeout=20).stdout.strip()
        return bool(w) and int(w) > 0 and float(d or 0) >= min_dur
    except Exception:
        return False


def _hero_i2v_indices(usable, sel) -> set:
    """The ~2 beats that earn the pricier hybrid model: the HOOK (first animated beat) + the CLIMAX
    (a payoff/reveal-typed animated scene, else the last animated beat)."""
    order = sorted(sel)
    if not order:
        return set()
    hero = {order[0]}                                   # hook / opener
    climax = None
    for k in order:
        if _s(usable[k]["scene"].get("scene_type")).lower() in (
                "climax", "payoff", "reveal", "twist", "final_payoff"):
            climax = k
    hero.add(climax if climax is not None else order[-1])
    return hero


def _animate_one(provider: str, image_path: str, prompt: str, out_mp4: str,
                 vw: int, vh: int, seconds: int, fal_model: str | None = None,
                 idempotency_key: str | None = None, stage_note=None):
    """Generate ONE i2v clip with a SPECIFIC provider. Returns (ok, quota_hit, err_str).
    fal_model overrides _FAL_MODEL for THIS clip (used by the hero-beat hybrid); fal branch only."""
    size = _i2v_size(vw, vh)
    sw, sh = (int(x) for x in size.split("x"))
    if "narration-aligned evidence change" in (prompt or ""):
        motion = (prompt or "").strip()[:900]
    else:
        motion = ("Subtle, restrained motion: locked-off camera, very slow gentle drift and slight "
                  "parallax, soft ambient life, the character blinks and shifts slightly. No cuts, no "
                  "camera shake; keep the composition stable and photoreal. " + (prompt or "")).strip()[:900]
    ref = out_mp4 + ".ref.jpg"
    try:
        from PIL import Image, ImageOps
        ImageOps.fit(Image.open(image_path).convert("RGB"), (sw, sh), Image.LANCZOS).save(ref, quality=92)
        if provider == "sora":
            c = _openai_video()
            vid = c.videos.create_and_poll(model=_SORA_MODEL, prompt=motion,
                                           input_reference=open(ref, "rb"),
                                           seconds=str(seconds), size=size,
                                           extra_headers=({"Idempotency-Key": idempotency_key}
                                                          if idempotency_key else None))
            if getattr(vid, "status", "") != "completed":
                return (False, False, f"sora status={getattr(vid, 'status', '?')}")
            c.videos.download_content(vid.id, variant="video").write_to_file(out_mp4)
        elif provider == "veo":
            import time as _t
            from google.genai import types
            g = _gemini()
            op = g.models.generate_videos(
                model=_VEO_MODEL, prompt=motion,
                image=types.Image(image_bytes=open(ref, "rb").read(), mime_type="image/jpeg"),
                config=types.GenerateVideosConfig(
                    aspect_ratio=("9:16" if sh > sw else "16:9"),
                    resolution="720p", duration_seconds=seconds, number_of_videos=1))
            waited = 0
            while not op.done and waited < 360:
                _t.sleep(8); waited += 8; op = g.operations.get(op)
            if not op.done or getattr(op, "error", None):
                err = str(getattr(op, "error", "timeout"))
                return (False, ("RESOURCE_EXHAUSTED" in err or "429" in err), err[:140])
            v = op.response.generated_videos[0]
            g.files.download(file=v.video); v.video.save(out_mp4)
        elif provider == "fal":
            import time as _t, requests as _rq
            key = _fal_key()
            if not key:
                return (False, False, "no FAL_KEY")
            hdr = {"Authorization": f"Key {key}"}
            if idempotency_key:
                hdr["Idempotency-Key"] = idempotency_key
            uri = "data:image/jpeg;base64," + base64.b64encode(open(ref, "rb").read()).decode()
            dur = "10" if seconds > 5 else "5"            # Kling supports only 5 or 10s
            _model = fal_model or _FAL_MODEL              # hero beats pass a pricier model
            sub = _rq.post(f"https://queue.fal.run/{_model}", headers=hdr, timeout=60,
                           json={"prompt": motion, "image_url": uri, "duration": dur})
            low = sub.text.lower()
            if sub.status_code == 429 or "exhaust" in low or "balance" in low or "quota" in low:
                return (False, True, f"fal quota/balance: {sub.text[:120]}")
            if sub.status_code not in (200, 201):
                return (False, False, f"fal submit {sub.status_code}: {sub.text[:120]}")
            j = sub.json(); su, ru = j.get("status_url"), j.get("response_url")
            if stage_note:
                stage_note({"provider_request_id": j.get("request_id"),
                            "status_url": su, "response_url": ru})
            waited = 0
            while waited < 360:
                _t.sleep(6); waited += 6
                st = _rq.get(su, headers=hdr, timeout=30).json().get("status")
                if st == "COMPLETED":
                    break
                if st in ("FAILED", "ERROR"):
                    return (False, False, f"fal job {st}")
            else:
                return (False, False, "fal timeout")
            res = _rq.get(ru, headers=hdr, timeout=30).json()
            vurl = (res.get("video") or {}).get("url")
            if not vurl:
                return (False, False, f"fal no video: {str(res)[:120]}")
            open(out_mp4, "wb").write(_rq.get(vurl, timeout=120).content)
        else:
            return (False, False, f"unknown provider '{provider}'")
        ok = os.path.exists(out_mp4) and _clip_is_real(out_mp4)
        return (ok, False, "" if ok else "no valid video (empty/corrupt/too short)")
    except Exception as e:
        s = f"{type(e).__name__}: {str(e)[:140]}"
        return (False, ("RESOURCE_EXHAUSTED" in s or "429" in s or "quota" in s.lower()), s)
    finally:
        try:
            os.remove(ref)
        except OSError:
            pass


def animate_scene(image_path: str, prompt: str, out_mp4: str, vw: int, vh: int,
                  cost_sink: list | None = None, seconds: int = I2V_SECONDS,
                  err_sink: list | None = None, exhausted: set | None = None,
                  fal_model: str | None = None, rate: float | None = None) -> str | None:
    """Generate a subtle image-to-video clip, trying the provider chain (_I2V_CHAIN, e.g.
    veo→sora) in order. When a provider hits quota it's added to `exhausted` so the rest of the
    run skips straight to the next provider. Returns the clip path, or None if EVERY provider
    fails (caller falls back to ffmpeg Ken-Burns). NEVER raises."""
    try:
        from durable_execution import canonical_hash, current as _durable_current
        runtime = _durable_current()
    except Exception:
        runtime = None
    for provider in _I2V_CHAIN:
        if exhausted is not None and provider in exhausted:
            continue
        if runtime:
            rel = os.path.relpath(os.path.abspath(out_mp4), runtime.output_dir)
            request = {
                "provider": provider, "model": fal_model if provider == "fal" else None,
                "prompt": prompt, "seconds": seconds, "size": [vw, vh],
                "source_sha256": sha256_file(image_path),
            }
            stage_key = "motion:" + canonical_hash({"output": rel, "request": request})[:32]

            def _motion_call(idempotency_key: str):
                ok, quota, err = _animate_one(
                    provider, image_path, prompt, out_mp4, vw, vh, seconds,
                    fal_model=fal_model, idempotency_key=idempotency_key,
                    stage_note=lambda patch: runtime.store.note_stage(
                        runtime.job_id, stage_key, patch))
                if not ok:
                    raise RuntimeError(("quota:" if quota else "provider:") + (err or "failed"))
                actual = round(seconds * (rate if rate is not None else _RATE_I2V_SEC), 4)
                return {"provider": provider, "output": rel}, actual

            try:
                _, actual, reused = runtime.paid_file(
                    stage_key=stage_key, provider=provider, request=request,
                    estimated_cost=seconds * (rate if rate is not None else _RATE_I2V_SEC),
                    output_path=out_mp4, operation=_motion_call)
                ok, quota, err = True, False, ""
                if cost_sink is not None:
                    cost_sink.append(actual)
                if err_sink is not None:
                    err_sink.append(f"ok:{provider}")
                return out_mp4
            except Exception as exc:
                message = str(exc)
                ok, quota, err = False, message.startswith("quota:"), message
        else:
            ok, quota, err = _animate_one(provider, image_path, prompt, out_mp4, vw, vh, seconds,
                                          fal_model=fal_model)
        if ok:
            if cost_sink is not None:
                cost_sink.append(round(seconds * (rate if rate is not None else _RATE_I2V_SEC), 4))
            if err_sink is not None:
                err_sink.append(f"ok:{provider}")   # caller can see which provider rendered it
            return out_mp4
        if quota and exhausted is not None:
            exhausted.add(provider)                 # skip this provider for the rest of the run
        if err_sink is not None and err:
            err_sink.append(f"[{provider}] {err}")
    return None


def _make_scene_segment(
    image_path: str,
    audio_path: str,
    output_path: str,
    text_overlay: str,
    text_sub: str,
    motion: str = "kenburns_in",
    tail: float = 0.0,
    text_meta: dict | None = None,
    style_mode: str = "educational",
    vw: int = 1920,
    vh: int = 1080,
    captions: str = "headline",
    word_times: list | None = None,
    bubble_side: str = "right",
    motion_video: str | None = None,
    duration_override: float | None = None,
) -> None:
    """Varied eased Ken Burns / pan + text → scene video (no audio), at vw×vh.

    captions="headline": one branded title card (top).
    captions="karaoke": per-phrase sticker captions timed to word_times (bottom).
    captions="headline_karaoke": BOTH — headline card (top) + karaoke captions (bottom).
    captions="bubble": per-phrase Bolt speech bubble timed to word_times.
    `tail` extends the clip past the narration so a crossfade overlaps the hold.
    """
    dur = (float(duration_override) if duration_override is not None else _audio_dur(audio_path)) + tail
    fps = 30

    # Motion source → resolves to [v0] at vw×vh either way; the overlay graph below is
    # identical. If a real image-to-video clip (Veo) is supplied use it as the moving
    # background; otherwise ffmpeg Ken-Burns on the still.
    if motion_video and os.path.exists(motion_video):
        # Retime one continuous generated clip to the semantic shot window. A small narration
        # remainder is absorbed by gently slowing the clip instead of looping it and creating
        # a visible reset or appending a 0.3-second still flash.
        source_dur = max(0.05, _audio_dur(motion_video))
        # Never accelerate generated motion to fake pace. Short evidence windows trim the real clip;
        # longer windows may slow it, but that camera timing never earns an evidence event.
        retime = max(1.0, dur / source_dur)
        inputs = ["-i", motion_video]
        bg_chain = (
            f"setpts={retime:.6f}*PTS,"
            f"scale={vw}:{vh}:force_original_aspect_ratio=increase,"
            f"crop={vw}:{vh},fps={fps},setsar=1"
        )
    else:
        n_frames = max(1, int(dur * fps))
        z_expr, x_expr, y_expr = _motion(motion, n_frames)
        # Cover the canvas, then Ken-Burns within it. SUPERSAMPLE the frame ~2× before
        # zoompan: zoompan rounds its crop origin (x/y) to whole INPUT pixels every frame, so
        # running it at output size makes pans/zooms jump ±1px = visible shake. Feeding it a
        # 2× frame makes that rounding sub-pixel in the 1× output → smooth. x/y use iw/ih so
        # they scale automatically; zoompan downscales to the target via s=.
        SS = 2
        cw, ch = vw * SS, vh * SS
        inputs = ["-loop", "1", "-i", image_path]
        bg_chain = (
            f"scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},"
            f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={n_frames}:s={vw}x{vh}:fps={fps},"
            "setsar=1"
        )

    # ── Unified overlay builder ──────────────────────────────────────────────
    # Optional headline card (top, fade+slide) and/or timed phrase overlays
    # (karaoke captions or Bolt bubble, bottom). "headline_karaoke" stacks both.
    want_headline = captions in ("headline", "headline_karaoke")
    want_phrases  = bool(captions in ("karaoke", "bubble", "headline_karaoke") and word_times)

    parts = [f"[0:v]{bg_chain}[v0]"]
    prev, nidx = "v0", 1

    if want_headline:
        # In combined mode pin the headline to the TOP so it can't collide with the
        # bottom captions.
        hmeta = dict(text_meta) if isinstance(text_meta, dict) else {}
        if captions == "headline_karaoke":
            hmeta["placement"], hmeta["alignment"] = "top_center", "center"
        hp = output_path + ".text.png"
        if _make_text_png(text_overlay, text_sub, hp, text_meta=hmeta, style_mode=style_mode):
            inputs += ["-loop", "1", "-i", hp]
            y_slide = "26-26*min(t/0.5\\,1)"   # slide up while fading in
            parts.append(f"[{nidx}:v]format=rgba,fade=in:st=0:d=0.5:alpha=1[hl]")
            parts.append(f"[{prev}][hl]overlay=x=0:y='{y_slide}':format=auto[h{nidx}]")
            prev = f"h{nidx}"; nidx += 1

    if want_phrases:
        for word, start, end in word_times:
            cap_png = f"{output_path}.cap{nidx:03d}.png"
            if captions == "bubble":
                _make_bubble_png(word, vw, vh, bubble_side, cap_png, style_mode=style_mode)
            else:
                _make_caption_png(word, vw, vh, cap_png, style_mode=style_mode)
            inputs += ["-loop", "1", "-i", cap_png]
            # commas inside between() must be escaped in filter_complex
            parts.append(f"[{prev}][{nidx}:v]overlay=0:0:enable='between(t\\,{start:.2f}\\,{end:.2f})'[p{nidx}]")
            prev = f"p{nidx}"; nidx += 1

    cmd = [_ffmpeg_bin(), "-y", *inputs, "-filter_complex", ";".join(parts),
           "-map", f"[{prev}]", "-t", f"{dur:.3f}",
           "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-an",
           output_path]
    _run_ffmpeg(cmd, timeout=180.0)   # raises if it hangs


def _make_multishot_background(
    result: dict,
    shots: list[dict],
    output_path: str,
    vw: int,
    vh: int,
    motion_video: str | None = None,
    motion_videos: dict[str, str] | None = None,
    tail: float = 0.0,
) -> None:
    """Render an exact-duration, hard-cut visual bed for one narrative scene."""
    work = [dict(s) for s in shots]
    if work:
        work[-1]["duration"] = float(work[-1]["duration"]) + tail
    clips, list_path = [], output_path + ".shots.txt"
    for j, shot in enumerate(work):
        clip = f"{output_path}.shot{j:02d}.mp4"
        evidence_assets = result.get("evidence_assets") or {}
        image = evidence_assets.get(shot.get("source"))
        if not image:
            image = result.get("alt_img") if shot.get("source") == "alternate" else result["img"]
        if not image or not os.path.exists(image):
            image = result["img"]
        _make_scene_segment(
            image, result["aud"], clip, "", "",
            motion=shot.get("motion") or "kenburns_in", captions="none",
            vw=vw, vh=vh, duration_override=float(shot["duration"]),
            motion_video=((motion_videos or {}).get(_s(shot.get("state_id"))) or motion_video)
            if shot.get("kind") == "i2v" else None,
        )
        clips.append(clip)
    with open(list_path, "w") as f:
        for clip in clips:
            f.write(f"file '{clip}'\n")
    _run_ffmpeg([
        _ffmpeg_bin(), "-y", "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", output_path,
    ], timeout=240.0)
    for path in clips + [list_path]:
        try:
            os.remove(path)
        except OSError:
            pass


# ── Assembly ───────────────────────────────────────────────────────────────────

def _xfade_concat(videos: list[str], durations: list[float], out: str, tmp_dir: str) -> None:
    """xfade a (small) list of clips into `out`. durations = narration length per clip;
    each clip holds a FADE_DUR tail so the crossfade overlaps the hold, not the words."""
    if len(videos) == 1:
        import shutil as _sh
        _sh.copy(videos[0], out)
        return
    inputs = []
    for v in videos:
        inputs += ["-i", v]
    fc, cur, offset = [], "0:v", durations[0]
    for i in range(1, len(videos)):
        fc.append(f"[{cur}][{i}:v]xfade=transition=fade:duration={FADE_DUR}:offset={offset:.3f}[v{i}]")
        cur = f"v{i}"
        if i < len(videos) - 1:
            offset += durations[i]
    _run_ffmpeg([
        _ffmpeg_bin(), "-y", *inputs,
        "-filter_complex", ";".join(fc),
        "-map", f"[{cur}]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        out,
    ], timeout=600.0)


def _make_audio_cue_track(cues: list[dict], total_duration: float, out: str) -> str | None:
    """Synthesize a restrained, licence-free cue bed for predictions and payoffs."""
    sounded = [c for c in cues if c.get("type") in {"prediction_tick", "impact"}][:20]
    if not sounded:
        return None
    inputs, filters, labels = [], [], []
    for i, cue in enumerate(sounded):
        impact = cue.get("type") == "impact"
        freq, dur, volume = (88, 0.42, 0.10) if impact else (1040, 0.12, 0.055)
        inputs += ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={dur}:sample_rate=44100"]
        delay = max(0, round(float(cue.get("time_sec") or 0) * 1000))
        filters.append(
            f"[{i}:a]volume={volume},afade=t=out:st={max(0, dur - 0.08):.2f}:d=0.08,"
            f"adelay={delay}|{delay}[c{i}]"
        )
        labels.append(f"[c{i}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest,"
                   f"atrim=0:{total_duration:.3f}[cues]")
    _run_ffmpeg([
        _ffmpeg_bin(), "-y", *inputs, "-filter_complex", ";".join(filters),
        "-map", "[cues]", "-c:a", "pcm_s16le", out,
    ], timeout=120.0)
    return out


def _assemble(
    scene_videos: list[str],
    scene_audios: list[str],
    output_path: str,
    tmp_dir: str,
    bg_music_path: str | None = None,
    audio_cues: list[dict] | None = None,
) -> None:
    n = len(scene_videos)
    durations = [_audio_dur(a) for a in scene_audios]   # narration-only durations

    # 1. Concat video with xfade transitions. Each segment is (narration + fade_dur) long,
    # so the crossfade overlaps the held tail (no narration covered); the result is
    # sum(narration)+fade_dur long. For long-form we batch the xfade (a 240-input
    # filtergraph would choke ffmpeg) — each batch is xfaded, then the batch outputs are
    # xfaded together. A batch behaves like one super-segment of length sum(its narration),
    # so the offset math is identical at both levels.
    if n == 1:
        concat_video = scene_videos[0]
    else:
        BATCH = 20
        if n <= BATCH:
            concat_video = os.path.join(tmp_dir, "_concat_video.mp4")
            _xfade_concat(scene_videos, durations, concat_video, tmp_dir)
        else:
            batch_videos, batch_durs = [], []
            for b, i in enumerate(range(0, n, BATCH)):
                vids = scene_videos[i:i + BATCH]
                durs = durations[i:i + BATCH]
                bv = os.path.join(tmp_dir, f"_batch_{b:03d}.mp4")
                _xfade_concat(vids, durs, bv, tmp_dir)
                batch_videos.append(bv)
                batch_durs.append(sum(durs))   # batch's narration length (super-segment)
            concat_video = os.path.join(tmp_dir, "_concat_video.mp4")
            _xfade_concat(batch_videos, batch_durs, concat_video, tmp_dir)

    # 2. Concat narration audio
    audio_list = os.path.join(tmp_dir, "_audio_list.txt")
    with open(audio_list, "w") as f:
        for a in scene_audios:
            f.write(f"file '{a}'\n")

    concat_audio = os.path.join(tmp_dir, "_concat_audio.mp3")
    _run_ffmpeg([
        _ffmpeg_bin(), "-y",
        "-f", "concat", "-safe", "0", "-i", audio_list,
        "-c:a", "libmp3lame",
        concat_audio,
    ], timeout=180.0)

    # 3. Optional BG music mix
    if bg_music_path and os.path.exists(bg_music_path):
        mixed = os.path.join(tmp_dir, "_mixed.mp3")
        drops = [float(c.get("time_sec") or 0) for c in (audio_cues or [])
                 if c.get("type") == "music_drop"]
        music_volume = "0.10"
        for t in reversed(drops):
            music_volume = f"if(between(t\\,{max(0, t - 0.2):.2f}\\,{t + 0.8:.2f})\\,0.018\\,{music_volume})"
        _run_ffmpeg([
            _ffmpeg_bin(), "-y",
            "-i", concat_audio,
            "-stream_loop", "-1", "-i", bg_music_path,
            "-filter_complex",
            f"[0:a]volume=1.0[vo];[1:a]volume='{music_volume}':eval=frame[bg];"
            "[vo][bg]amix=inputs=2:duration=first[mix]",
            "-map", "[mix]", "-c:a", "libmp3lame",
            mixed,
        ], timeout=180.0)
        final_audio = mixed
    else:
        final_audio = concat_audio

    # 3b. Story-turn cues are generated locally; no bundled/licensed SFX are required.
    try:
        cue_track = _make_audio_cue_track(
            audio_cues or [], sum(durations), os.path.join(tmp_dir, "_retention_cues.wav"))
    except Exception:
        cue_track = None  # audio punctuation is an enhancement; never sacrifice the complete video
    if cue_track:
        cued = os.path.join(tmp_dir, "_cued.mp3")
        _run_ffmpeg([
            _ffmpeg_bin(), "-y", "-i", final_audio, "-i", cue_track,
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first[mix]",
            "-map", "[mix]", "-c:a", "libmp3lame", cued,
        ], timeout=180.0)
        final_audio = cued

    # 4. Mux video + audio — NORMALIZE loudness to the streaming/Shorts standard (-14 LUFS,
    #    true-peak -1 dB). OpenAI TTS comes out ~-23 LUFS (≈9 dB too quiet), which reads as
    #    low-confidence vs native Shorts; loudnorm brings it up to platform level.
    _run_ffmpeg([
        _ffmpeg_bin(), "-y",
        "-i", concat_video,
        "-i", final_audio,
        "-map", "0:v", "-map", "1:a",
        "-af", "loudnorm=I=-12:TP=-1:LRA=11",   # target -12: single-pass undershoots ~2 LU -> lands ~-14
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path,
    ], timeout=300.0)


def _render_first_minute_preview(
    results: list[dict],
    output_dir: str,
    *,
    cap_mode: str,
    style_mode: str,
    vw: int,
    vh: int,
    bg_music_path: str | None,
    motion_clips: dict[str, str] | None = None,
) -> tuple[str, dict, list[dict], dict[int, str], list[list[dict]]]:
    """Render the paid opening assets into a real preview before later image spend."""
    import shutil
    gate_dir = os.path.join(output_dir, "approved_opening")
    os.makedirs(gate_dir, exist_ok=True)
    videos, audios, plan, gate_scenes, frozen_segments = [], [], [], [], {}
    for k, result in enumerate(r for r in results if r.get("aud_ok")):
        scene = result["scene"]
        duration = _audio_dur(result["aud"])
        shots = compile_scene_shots(
            scene, duration, k, has_alternate=bool(result.get("alt_img")),
            i2v_seconds=I2V_SECONDS_LONGFORM,
            word_times=result.get("word_times"),
            evidence_states=result.get("evidence_states"),
            motion_state_ids=frozenset((motion_clips or {}).keys()),
        )
        visual = None
        if len(shots) > 1:
            visual = os.path.join(gate_dir, f"opening_{k:02d}_shots.mp4")
            _make_multishot_background(
                result, shots, visual, vw, vh, tail=FADE_DUR,
                motion_videos=motion_clips)
        word_times = None
        if cap_mode in ("karaoke", "bubble", "headline_karaoke"):
            word_times = align_caption_phrases(
                scene.get("narration", ""), result.get("word_times"), duration)
        text = scene.get("text")
        placement = ((_s(text.get("placement")) if isinstance(text, dict) else "") or "top_right").lower()
        bubble_side = "left" if "left" in placement else ("right" if "right" in placement else "center")
        segment = os.path.join(gate_dir, f"opening_{k:02d}.mp4")
        _make_scene_segment(
            result["img"], result["aud"], segment,
            scene.get("text_overlay", ""), scene.get("text_sub", ""),
            motion=_pick_motion(scene.get("shot_type", "medium"), k), tail=FADE_DUR,
            text_meta=scene.get("text"), style_mode=style_mode, vw=vw, vh=vh,
            captions=cap_mode, word_times=word_times, bubble_side=bubble_side,
            motion_video=visual,
        )
        videos.append(segment); audios.append(result["aud"])
        frozen_segments[int(result["i"])] = segment
        plan.append(shots); gate_scenes.append(scene)
    if not videos:
        raise RuntimeError("First-minute gate has no renderable scenes")
    durations = [_audio_dur(a) for a in audios]
    cues = build_audio_cues(gate_scenes, durations)
    raw = os.path.join(gate_dir, "opening_raw.mp4")
    _assemble(videos, audios, raw, gate_dir, bg_music_path, audio_cues=cues)
    preview_path = os.path.join(output_dir, "first_minute_preview.mp4")
    # The first tranche crosses 45 seconds at a narration boundary. Preserve that complete final
    # beat instead of cutting its sentence and leaving the inspection plan pointing past the MP4.
    # This normally yields 45–55 seconds while purchasing no scene beyond the 45-second boundary.
    shutil.copy(raw, preview_path)
    return preview_path, shot_plan_metrics(plan), cues, frozen_segments, plan


def _blind_rendered_story_judge(contact_sheet_path: str, transcript_cues: list[dict],
                                cost_sink: list | None = None) -> dict:
    """Judge the chronological rendered opening without planner metadata or expected answers."""
    try:
        with open(contact_sheet_path, "rb") as handle:
            encoded = base64.b64encode(handle.read()).decode()
        response = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=1400,
            system=("You are a blind sequential story editor. Judge only the supplied encoded "
                    "frames and spoken narration. Never infer an intended story or reward production "
                    "metadata. If a fact is not recoverable, mark it false."),
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                               "data": encoded}},
                {"type": "text", "text": blind_story_prompt(transcript_cues)},
            ]}],
        )
        if cost_sink is not None:
            cost_sink.append(_msg_cost(response.usage))
        result, repair_cost = _parse_script_json(response.content[0].text)
        if cost_sink is not None and repair_cost:
            cost_sink.append(repair_cost)
        if not isinstance(result, dict):
            raise ValueError("blind rendered-story judge returned invalid JSON")
        return result
    except Exception as exc:
        return {"valid": False, "judge_error": f"{type(exc).__name__}: {str(exc)[:180]}"}


# ── Main runner ────────────────────────────────────────────────────────────────

_SLOP_ENVS = ("space", "galaxy", "neon", "abstract", "digital", "cosmic", "nebula", "starfield")


def _slop_warnings(scenes: list) -> list:
    """Metadata 'AI-slideshow' detector — flags low-variety videos (logged, non-fatal)."""
    from collections import Counter
    n = len(scenes)
    out = []
    if n < 4:
        return out
    # Character-presence budgets are enforced by the long-form story contract; this
    # detector stays focused on visual variety for both long-form and social output.
    envs = Counter((_s(s.get("environment_type"), "?").strip().lower() or "?") for s in scenes)
    slop = sum(c for e, c in envs.items() if any(k in e for k in _SLOP_ENVS))
    if slop / n > 0.40:
        out.append(f"{slop}/{n} scenes use space/neon/abstract/digital backdrops (>40%)")
    top_env, top_c = envs.most_common(1)[0]
    if top_c / n > 0.40:
        out.append(f"environment '{top_env}' repeats in {top_c}/{n} scenes (>40%)")
    types = Counter((_s(s.get("scene_type"), "?").strip().lower() or "?") for s in scenes)
    if len(types) < 4:
        out.append(f"only {len(types)} distinct scene_types (want ≥4 for variety)")
    tt, tc = types.most_common(1)[0]
    if tc / n > 0.50:
        out.append(f"scene_type '{tt}' dominates ({tc}/{n}, >50%)")
    # adjacent scene_type repetition (same composition feel)
    adj = sum(1 for i in range(1, n)
              if (scenes[i].get("scene_type") or "") == (scenes[i-1].get("scene_type") or "")
              and scenes[i].get("scene_type"))
    if adj >= 3:
        out.append(f"{adj} adjacent scene-pairs share a scene_type (repetitive rhythm)")
    # image_prompt quality (free, non-LLM backstop to the prompt rules, BOTH formats):
    # text-objects gpt-image-2 will garble, and a passive (non-acting) Bolt.
    _txt_obj = ("price tag", "sign read", "sign saying", "label read", "receipt", "barcode",
                "billboard", "newspaper", "headline", "license plate", "neon sign")
    _passive = ("stands beside", "standing beside", "stand beside", "observing", "watches ",
                "next to a", "looks on", "gazes at")
    txt_hits = sum(1 for s in scenes
                   if any(k in _s(s.get("image_prompt")).lower() for k in _txt_obj))
    pas_hits = sum(1 for s in scenes
                   if any(k in _s(s.get("image_prompt")).lower() for k in _passive))
    if txt_hits:
        out.append(f"{txt_hits} image_prompt(s) name a text object (sign/label/price tag) — "
                   "gpt-image-2 will garble the text")
    if pas_hits:
        out.append(f"{pas_hits} image_prompt(s) describe a PASSIVE Bolt (beside/observing) — "
                   "should be mid-action")
    return out


def _srt_ts(t: float) -> str:
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60); ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        s += 1; ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_transcript(narrations: list, durations: list, out_dir: str):
    """Write transcript.txt (full narration) + captions.srt (timed, one cue per scene).
    Cue timing tracks the concatenated narration audio = the muxed video audio."""
    txt_path = os.path.join(out_dir, "transcript.txt")
    srt_path = os.path.join(out_dir, "captions.srt")
    full = " ".join(n.strip() for n in narrations if n and n.strip())
    with open(txt_path, "w") as f:
        f.write(full + "\n")
    cues, t, idx = [], 0.0, 1
    for n, d in zip(narrations, durations):
        start, end = t, t + d
        t = end
        if n and n.strip():
            cues.append(f"{idx}\n{_srt_ts(start)} --> {_srt_ts(end)}\n{n.strip()}\n")
            idx += 1
    with open(srt_path, "w") as f:
        f.write("\n".join(cues))
    return txt_path, srt_path


_SHORT_GRADE_KEYS = ["first_second_hook", "story_coherence", "conceit_consistency", "escalation",
                     "visual_surprise", "explanation_clarity", "pacing", "loop_ending",
                     "bolt_activity", "rewatch_potential"]
# Retention-weighted overall: hook / story / conceit / escalation / pacing / loop decide whether a
# viewer STAYS; the visual dims barely move the outcome. Aligns the gate with the punchy-shorts
# standard (an old-style lecture with great visuals should NOT outscore a punchy one). story_coherence
# is weighted 2 — a viewer dropped into an unclear subject or a fact-list swipes away fast.
_SHORT_GRADE_WEIGHTS = {"first_second_hook": 3, "story_coherence": 2, "conceit_consistency": 2,
                        "escalation": 2, "pacing": 2, "loop_ending": 2, "explanation_clarity": 1,
                        "rewatch_potential": 1, "visual_surprise": 1, "bolt_activity": 1}


def grade_short(script: dict, cost_sink: list | None = None):
    """Ruthless self-grade of a social-short SCRIPT against the short-form checklist.
    Returns {'scores':{...}, 'overall':int, 'notes':str} or None (best-effort)."""
    scenes = script.get("scenes", [])
    if len(scenes) < 2:
        return None
    first = _s(scenes[0].get("narration")).strip()
    last = _s(scenes[-1].get("narration")).strip()
    # Show narration + spoken length + the IMAGE plan, so the visual dimensions
    # (visual_surprise, bolt_activity) are judged from the actual visuals — not guessed
    # from narration, which is what bottomed those two scores out historically.
    lines = "\n".join(
        f'{i+1}. [{s.get("scene_type","?")}] (~{round(len(_s(s.get("narration")).split())/3.0,1)}s) '
        f'{_s(s.get("narration"))}\n   IMAGE: {_s(s.get("image_prompt"))[:200]}'
        for i, s in enumerate(scenes))
    try:
        r = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=600,
            system=("You are a ruthless short-form (TikTok/Shorts/Reels) editor. Grade this ~45s "
                    "vertical short. For each scene you see the narration, its spoken length in "
                    "seconds, and its IMAGE plan — judge the visual dimensions from the IMAGE lines.\n"
                    "Score each 0-10:\n"
                    "- first_second_hook (THE #1 score): reward a CURIOSITY GAP — a counterintuitive "
                    "contrast (\"It wasn't X, it was Y\") OR a visceral present-moment stake "
                    "(\"Feel that?\") that makes the swipe impossible. PENALIZE a hook that gives away "
                    "the payoff/conclusion in line 1, or a flat past-tense history fact "
                    "(\"X once happened\").\n"
                    "- story_coherence (does it tell a COMPLETE story, not a fact-list): can a "
                    "first-time viewer say WHAT this is about by scene 2 — opening on an ORDINARY, "
                    "FAMILIAR anchor (a match, a candle, an everyday job), NOT dropped cold into the "
                    "weirdest detail? Is every beat CAUSED BY the previous (AND-SO / BUT-THEN), with "
                    "the single most surprising image WITHHELD to ~70% rather than spent in line 1? "
                    "Is exactly ONE clear question posed OUT LOUD by scene 2 and held open until the "
                    "reveal? PENALIZE HARD: an unclear/ungrounded subject; beats that only join with "
                    "'...also...'; the same reveal restated 3+ times; a SECOND competing question opened "
                    "while the first is unanswered (two '?' promises — including a setup phrased as its "
                    "own question like 'why did they fall out?'); and an ANSWER-FIRST cold open where "
                    "line 1 states or paraphrases the video's conclusion. Any of these = score <=4.\n"
                    "- conceit_consistency: does scene 1's framing device run through the WHOLE video, "
                    "or does the body drift into a generic fact-list?\n"
                    "- escalation: does the danger/stakes visibly BUILD across the body (small → bigger "
                    "→ break), or sit flat as an explanation?\n"
                    "- visual_surprise (0-2 every IMAGE generic; 9-10 every scene a distinct visual "
                    "contradiction that makes you pause).\n"
                    "- explanation_clarity.\n"
                    "- pacing: every beat ~3-6s AND ONE idea per beat. PENALIZE scenes >8s, beats that "
                    "pile 2+ ideas, leading with jargon before the viewer FEELS it (analogy first, term "
                    "after), and any mechanism 'lecture' longer than ~3 explanation beats.\n"
                    "- loop_ending: last line echoes the first (or lands a forward open-loop).\n"
                    "- bolt_activity (0-2 static bystander; 9-10 a clear action verb in EVERY IMAGE).\n"
                    "- rewatch_potential.\n"
                    "Be harsh and honest. Return ONLY JSON: {\"scores\":{\"first_second_hook\":int,"
                    "\"story_coherence\":int,"
                    "\"conceit_consistency\":int,\"escalation\":int,\"visual_surprise\":int,"
                    "\"explanation_clarity\":int,\"pacing\":int,\"loop_ending\":int,"
                    "\"bolt_activity\":int,\"rewatch_potential\":int},"
                    "\"notes\":\"one sentence — the single biggest fix\"}."),
            messages=[{"role": "user", "content": f'FIRST line: "{first}"\nLAST line: "{last}"\n\nScenes:\n{lines}'}],
        )
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        o, _ = _parse_script_json(r.content[0].text)
        if not (isinstance(o, dict) and isinstance(o.get("scores"), dict)):
            return None
        sc = o["scores"]
        wsum = sum(_SHORT_GRADE_WEIGHTS.values())
        tot = sum(_SHORT_GRADE_WEIGHTS.get(k, 1) * int(sc.get(k, 0) or 0) for k in _SHORT_GRADE_KEYS)
        o["overall"] = round(100 * tot / (10 * wsum))   # retention-weighted; overrides model's number
        # HARD veto: a short that poses two competing questions / opens answer-first / is incoherent
        # (story_coherence<=4) CANNOT pass the gate, no matter how strong its hook/visuals — cap it
        # below _SHORT_GATE_PASS so generate_graded_short regenerates it (and flags below-floor if
        # every retry stays incoherent, e.g. an inherently two-pronged topic that needs reframing).
        if int(sc.get("story_coherence", 10) or 10) <= 4:
            o["overall"] = min(o["overall"], 60)
        return o
    except Exception:
        return None


def _write_grade(grade: dict, out_dir: str) -> str:
    """Write the short self-grade breakdown to grade.txt; return the path."""
    sc = grade.get("scores", {})
    lines = [f"SHORT SELF-GRADE — overall {grade.get('overall','?')}/100", ""]
    lines += [f"  {k.replace('_',' '):22s} {sc.get(k,'?')}/10" for k in _SHORT_GRADE_KEYS]
    if grade.get("notes"):
        lines += ["", f"Biggest fix: {grade['notes']}"]
    path = os.path.join(out_dir, "grade.txt")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


_DESC_DISCLOSURE = ("🤖 Created with AI assistance (synthetic narration and AI-generated "
                    "visuals); disclosed as altered/synthetic content.")


def _fmt_ts(sec: float) -> str:
    """Seconds → YouTube timestamp (m:ss, or h:mm:ss past an hour)."""
    sec = max(0, int(round(sec)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _build_chapters(scene_starts: list, picks: list) -> list:
    """Turn LLM chapter picks into VALID YouTube chapters, snapped to real scene-start times.

    YouTube only renders chapters if: the first timestamp is 0:00, there are >=3 of them, they are
    in ascending order, and each is >=10s after the previous. `picks` = [{"scene":<1-based int>,
    "title":str}]; `scene_starts` = cumulative start seconds per scene. Returns [(ts_str, title)] or
    [] (caller then omits the CHAPTERS block entirely rather than ship broken half-chapters)."""
    n = len(scene_starts)
    if n < 3:
        return []
    cleaned = []
    for p in picks or []:
        if not isinstance(p, dict):
            continue
        try:
            idx = int(p.get("scene", 0)) - 1                 # to 0-based
        except (TypeError, ValueError):
            continue
        title = _s(p.get("title")).strip().lstrip("-•").strip()
        if 0 <= idx < n and title:
            cleaned.append((idx, title[:70]))
    cleaned.sort(key=lambda t: t[0])
    # Force a 0:00 opener: if the first pick isn't scene 1, retitle-prepend scene 1.
    if not cleaned:
        return []
    if cleaned[0][0] != 0:
        cleaned.insert(0, (0, "Introduction"))   # first chapter MUST be 0:00; don't dupe the next title
    out, last = [], -10.0
    seen_idx = set()
    for idx, title in cleaned:
        if idx in seen_idx:
            continue
        start = scene_starts[idx]
        if start < last + 10:                                # enforce the >=10s spacing rule
            continue
        out.append((_fmt_ts(start), title))
        last = start
        seen_idx.add(idx)
    out[0] = ("0:00", out[0][1])                             # first MUST be exactly 0:00
    return out if len(out) >= 3 else []


def generate_description(title: str, hook: str, transcript: str, out_dir: str,
                         cost_sink: list | None = None, question: str = "",
                         video_format: str = "landscape", scene_narr: list | None = None,
                         scene_durs: list | None = None) -> str:
    """Write a ready-to-paste, SEO-rich YouTube description (best-effort Claude; template fallback).

    Long-form gets the full package: keyword-front-loaded hook + summary, EXACT auto-chapters
    (timestamps snapped to real per-scene audio durations, not estimated), an 'In this video'
    keyword list, a 'Questions answered' block (search/voice bait), a soft CTA, hashtags, and a
    plain-text tags line. Social shorts get a compact variant (summary + hashtags + tags — no
    chapters/bullets). The LLM writes only the LANGUAGE; code owns the timestamps, YouTube chapter
    rules, layout, and the mandatory AI-disclosure line. Any failure → the old simple template."""
    social = video_format == "social"
    # Exact scene-start times from real narration durations → frame-accurate chapters.
    scene_starts = []
    total = 0.0
    if scene_durs:
        acc = 0.0
        for d in scene_durs:
            scene_starts.append(acc)
            acc += max(0.0, float(d or 0.0))   # clamp: a bad (neg) dur must not make starts descend
        total = acc
    want_chapters = (not social) and len(scene_starts) >= 6 and total >= 120

    scene_lines = ""
    if want_chapters and scene_narr:
        rows = []
        for i, nar in enumerate(scene_narr):
            if i < len(scene_starts):
                rows.append(f'{i+1} [{_fmt_ts(scene_starts[i])}] {_s(nar).strip()[:140]}')
        scene_lines = "\n".join(rows)

    # Format-appropriate FORMAT tags — long-form must NOT get "shorts" tags and vice-versa.
    fmt_tag_examples = ("'science shorts','educational shorts','what if scenario','animated explainer'"
                        if social else
                        "'documentary','explainer video','educational video','[subject] explained'")
    fmt_word = "a vertical Short" if social else "a long-form video"
    sys = (
        "You are a YouTube SEO strategist. Write description COPY for an explainer video and return "
        "ONLY JSON. Front-load the primary keyword/topic in the first sentence (it shows in search "
        "and above the fold). Be accurate to the transcript; for political/historical topics stay "
        "NEUTRAL and factual — do NOT name real living politicians, take sides, or imply false "
        "consequences. No clickbait that the video doesn't deliver.\n"
        "TAG ARCHITECTURE (critical for a new channel — specific tags are the MATCHMAKER that picks the "
        "video's initial test audience; generic tags kill reach). Build ~15-18 TOPIC-SPECIFIC tags in "
        "THIS ORDER: (1) 5 EXACT-PREMISE tags that mirror the title + natural search queries for THIS "
        "exact topic; (2) 5 CONSEQUENCE tags for what the video actually shows/explains; (3) 3 "
        "SUBJECT-CATEGORY tags (the real discipline, e.g. earth science, anthropology); "
        f"(4) 2-4 FORMAT tags appropriate to THIS format ({fmt_word}): e.g. {fmt_tag_examples}. "
        "NEVER include generic front-loaders like 'shorts','viral','trending','fyp','facts','animation' "
        "(and never use 'shorts'-style tags on a long-form video, or vice-versa) — they identify "
        "nothing and waste the metadata.\n"
        + ('Return JSON: {"summary": "2-3 SHORT paragraphs (plain text, \\n\\n between them); the '
           'FIRST sentence names the topic + the core question", "chapters": [{"scene": <int scene '
           'number from the list>, "title": "3-6 word chapter label"}] (6-9 chapters that mark where '
           'the video SHIFTS topic — pick the scene number where each new section BEGINS; the first '
           'should be scene 1), "in_this_video": ["5-7 keyword-rich bullets of what the viewer '
           'learns"], "questions_answered": ["4-6 real search-style questions the video answers"], '
           '"hashtags": ["4-6 relevant hashtags WITHOUT the # sign"], "tags": ["~15-18 topic-specific '
           'tags following the TAG ARCHITECTURE, in order (5 exact-premise, 5 consequence, 3 '
           'subject-category, 2-4 format)"]}'
           if want_chapters else
           'Return JSON: {"summary": "1-2 SHORT punchy paragraphs; first sentence names the topic", '
           '"hashtags": ["4-6 hashtags WITHOUT the # sign"], "tags": ["~15-18 topic-specific tags '
           'following the TAG ARCHITECTURE, in order (5 exact-premise, 5 consequence, 3 subject-category, '
           '2-4 format)"]}')
    )
    user = f"Title: {title}\nTopic: {question or title}\nHook: {hook}\n\n"
    user += (f"SCENES (number [start] narration) — choose chapter breaks by SCENE NUMBER:\n{scene_lines}"
             if scene_lines else f"Transcript:\n{transcript[:6000]}")

    try:
        r = _claude().messages.create(model=ANTHROPIC_MODEL, max_tokens=2400, system=sys,
                                      messages=[{"role": "user", "content": user}])
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        o, _ = _parse_script_json(r.content[0].text)
        if not isinstance(o, dict) or not _s(o.get("summary")).strip():
            raise ValueError("bad description JSON")
        parts = [_s(o.get("summary")).strip()]
        if want_chapters:
            chapters = _build_chapters(scene_starts, o.get("chapters") or [])
            if chapters:
                parts.append("⏱️ CHAPTERS\n" + "\n".join(f"{ts} {ti}" for ts, ti in chapters))
            itv = [_s(b).strip().lstrip("-•").strip() for b in (o.get("in_this_video") or []) if _s(b).strip()]
            if itv:
                parts.append("🔎 IN THIS VIDEO\n" + "\n".join(f"• {b}" for b in itv[:7]))
            qa = [_s(q).strip() for q in (o.get("questions_answered") or []) if _s(q).strip()]
            if qa:
                parts.append("❓ QUESTIONS ANSWERED\n" + " ".join(qa[:6]))
            parts.append("Subscribe for clear, no-spin explainers on how the world really works — "
                         "new videos regularly.")
        tags = [_s(t).strip().lstrip("#").strip() for t in (o.get("hashtags") or []) if _s(t).strip()]
        if tags:
            parts.append(" ".join("#" + t.replace(" ", "") for t in tags[:6]))
        kw = [_s(t).strip() for t in (o.get("tags") or []) if _s(t).strip()]
        if kw:
            parts.append("Tags: " + ", ".join(kw[:18]))   # full 5/5/3/2-4 architecture
        parts.append(_DESC_DISCLOSURE)
        desc = "\n\n".join(parts)
    except Exception:
        desc = (f"{hook}\n\n{title}\n\n#explainer #education #learning #science #howitworks\n\n"
                + _DESC_DISCLOSURE)
    path = os.path.join(out_dir, "description.txt")
    try:                                        # best-effort: a write failure must not kill a rendered video
        with open(path, "w") as f:
            f.write(desc + "\n")
    except Exception:
        return ""
    return path


# ── Curiosity-gap topic engine ───────────────────────────────────────────────────
# Generates SPECIFIC, provocative, curiosity-gap video questions and GRADES each on the packaging
# rubric that actually drives click-through. Generic/saturated topics ("How does WiFi work?") are
# the #1 reason a small explainer channel dies — only high-scorers pass to the UI's trending list.
_CURIOSITY_SYSTEM = (
    "You are a YouTube packaging strategist for explainer channels. You generate VIDEO QUESTIONS "
    "(titles) and grade each on CURIOSITY GAP — the single thing that makes a viewer click. A "
    "strong question is SPECIFIC, provocative, and opens a loop the viewer NEEDS closed; it implies "
    "stakes (survival, the body, money, danger, a hidden truth, a 'wait, WHAT?'). WEAK questions are "
    "generic/saturated ('How does WiFi work?', 'What is a data center?') — they die because giant "
    "channels own them and they spark zero curiosity.\n"
    "Score each 0-10 on curiosity_gap using: SPECIFICITY (not generic), an OPEN LOOP it forces, "
    "STAKES or relatability, and FRESHNESS (not worn out). 9-10 = irresistible (e.g. 'Humans Barely "
    "Menstruated Until This Happened'); 4-6 = mild; 0-3 = generic/saturated. Be a harsh grader.\n"
    "Also score 0-10 on visual_promise (an instantly legible visual transformation), production_fit "
    "(can this channel illustrate it without licensed footage), fact_confidence (a defensible answer "
    "from reliable sources), and novelty (meaningfully different from common framings).\n"
    "Return ONLY JSON: {\"questions\":[{\"question\":\"...\",\"curiosity_gap\":int,\"visual_promise\":"
    "int,\"production_fit\":int,\"fact_confidence\":int,\"novelty\":int,\"why\":\"one short phrase on "
    "the hook\"}]}. Every question must be one a SMALL channel could realistically win — concrete, "
    "single-topic, answerable in one video."
)


def generate_curiosity_topics(niche: str = "science, technology & history explainers",
                              n: int = 14, min_score: int = 8,
                              cost_sink: list | None = None,
                              exclude: list | None = None,
                              content_format: str = "long") -> list[dict]:
    """Generate + grade curiosity-gap video questions for `niche`; return only those scoring
    >= min_score, best first. Each item: {question, curiosity_gap, why}. Best-effort ([] on fail).

    `exclude` = questions already used/published (from the DB) — the model is told to avoid these
    AND any close paraphrase, and we hard-filter the output against them, so the 12h refresh stops
    resurfacing topics that already became videos."""
    excl = [(_s(e)).strip() for e in (exclude or []) if _s(e).strip()]
    excl_block = ""
    if excl:
        excl_block = ("\n\nDO NOT propose any of these already-covered questions or a close "
                      "paraphrase / same-subject angle of them:\n- " + "\n- ".join(excl[:60]))
    content_format = "short" if str(content_format).lower() in ("short", "shorts", "social") else "long"
    format_brief = (
        "SHORTS: each idea must pay off in 25-45 seconds, make sense with sound off, and promise a "
        "dramatic first-frame visual plus a consequence ladder. Avoid topics that require long setup."
        if content_format == "short" else
        "LONG-FORM: each idea must sustain 5-12 minutes with a reveal chain, evidence, and at least "
        "three distinct visual chapters. Avoid one-fact ideas that would need padding."
    )
    prompt = (f"Niche: {niche}.\nTarget format: {content_format.upper()}. {format_brief}\n"
              f"Generate {max(n * 2, 16)} candidate video questions, then grade "
              "each. Strongly favour SPECIFIC, weird, high-stakes, curiosity-gap angles; AVOID "
              "generic 'how does X work' / 'what is X'. Vary subjects widely. Return the JSON."
              + excl_block)
    try:
        r = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=3500,
            system=_CURIOSITY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        data, _ = _parse_script_json(r.content[0].text)
        qs = data.get("questions", []) if isinstance(data, dict) else []
        out = [{"question": _s(q.get("question")).strip(),
                "curiosity_gap": int(q.get("curiosity_gap", 0) or 0),
                "visual_promise": int(q.get("visual_promise", 5) or 5),
                "production_fit": int(q.get("production_fit", 5) or 5),
                "fact_confidence": int(q.get("fact_confidence", 5) or 5),
                "novelty": int(q.get("novelty", 5) or 5),
                "content_format": content_format,
                "why": _s(q.get("why")).strip()}
               for q in qs if isinstance(q, dict) and _s(q.get("question")).strip()]
        out = [q for q in out if q["curiosity_gap"] >= min_score]
        if excl:
            import topic_roi
            out = [q for q in out if not any(
                q["question"].lower() == used.lower()
                or topic_roi.topic_similarity(q["question"], used) >= 0.56 for used in excl)]
        out.sort(key=lambda q: -q["curiosity_gap"])
        return out[:n]
    except Exception:
        return []


_SIM_TOPIC_SYSTEM = (
    "You are a YouTube SHORTS packaging strategist for the viral 'simulation' format (BoneLab-style): "
    "the viewer IS the subject, ONE measurable quantity changes to THEM on a clock, and it escalates "
    "to an absurd-but-REAL climax with a hard science lesson. You generate TITLES and grade each on "
    "curiosity_gap.\n"
    "TITLE FORMAT (strict): 'What If You [changed] [ONE number][unit] Every Second?' — always "
    "second-person ('you'), always a MEASURABLE rate, always containing the exact words 'every "
    "second' (occasionally 'every minute'). Examples that WORK: 'What If You Grew 1cm Every Second?', "
    "'What If You Gained 1kg Every Second?', 'What If You Got 1 IQ Every Second?', 'What If You Aged 1 "
    "Year Every Second?', 'What If You Got 1 Degree Hotter Every Second?'. DECREASING sims are great too "
    "(they count DOWN to a real floor): 'What If You Shrank 1cm Every Second?' (a proven winner), 'What "
    "If You Got 1 Degree Colder Every Second?', 'What If You Lost 1kg Every Second?'.\n"
    "HARD RULES:\n"
    "- LINEAR, ABSOLUTE units ONLY (cm, m, kg, IQ, degrees, decibels, dollars, years, mph). NEVER a "
    "PERCENTAGE ('1% stronger') and never a compounding/multiplying rate — those explode into nonsense "
    "and are BANNED.\n"
    "- The rate must be a DIGIT + a plain-word unit right after it (e.g. '1cm', '1 kg', '1 IQ', '5 "
    "degrees') — spell units as words/letters, never symbols like the degree sign or a slash.\n"
    "- Pick a rate that reaches a DRAMATIC scale within a day-to-a-year (not so tiny it never matters, "
    "not so fast it is instantly over).\n"
    "- Each MUST have (a) an escalating VISUAL consequence ladder and (b) a REAL limiting-science "
    "payoff (square-cube law, pressure, heat, biology, orbital mechanics) — grounded, NEVER fantasy or "
    "a false 'black hole' climax the numbers don't support.\n"
    "- Personal, visceral, everyday relatable quantity. Vary the dimension widely across the batch "
    "(height, weight, speed, size, IQ, temperature, age, money, loudness, strength-as-force).\n"
    "Score 0-10 on curiosity_gap (SPECIFIC + irresistible open loop + STAKES + FRESH). Be a harsh "
    "grader. Return ONLY JSON: {\"questions\":[{\"question\":\"...\",\"curiosity_gap\":int,\"why\":"
    "\"the escalation + the real science lesson in one short phrase\"}]}."
)


def generate_simulation_topics(n: int = 10, min_score: int = 8, cost_sink: list | None = None,
                               exclude: list | None = None) -> list[dict]:
    """Generate + grade 'you [change] N<unit> every second?' SIMULATION-lane titles. Same output
    shape as generate_curiosity_topics ({question, curiosity_gap, why}), so it flows through the
    validation/dashboard/db pipeline unchanged. Best-effort ([] on fail).

    CRITICAL: hard-filters to titles the sim MATH ENGINE can actually parse and render correctly —
    every surfaced title must trigger `_is_simulation_short` AND yield a non-empty `_sim_ladder_block`
    (a parseable linear rate). This guarantees the dashboard never suggests a title that would render
    with wrong/uncomputable numbers (the whole point of the math engine)."""
    excl = [(_s(e)).strip() for e in (exclude or []) if _s(e).strip()]
    excl_block = ("\n\nDO NOT propose any of these already-covered titles or a close paraphrase:\n- "
                  + "\n- ".join(excl[:60])) if excl else ""
    prompt = (f"Generate {max(n * 2, 20)} candidate simulation-short titles, then grade each. Vary the "
              "measured dimension widely (height, weight, speed, size, IQ, temperature, age, money, "
              "loudness). Return the JSON." + excl_block)
    try:
        r = _claude().messages.create(model=ANTHROPIC_MODEL, max_tokens=3500,
                                      system=_SIM_TOPIC_SYSTEM,
                                      messages=[{"role": "user", "content": prompt}])
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        data, _ = _parse_script_json(r.content[0].text)
        qs = data.get("questions", []) if isinstance(data, dict) else []
        out = [{"question": _s(q.get("question")).strip(),
                "curiosity_gap": int(q.get("curiosity_gap", 0) or 0),
                "why": _s(q.get("why")).strip()}
               for q in qs if isinstance(q, dict) and _s(q.get("question")).strip()]
        out = [q for q in out if q["curiosity_gap"] >= min_score]
        # HARD-FILTER: only titles the sim lane detects AND the math engine can parse (linear rate).
        out = [q for q in out if _is_simulation_short(q["question"]) and _sim_ladder_block(q["question"])]
        if excl:
            _seen = {e.lower() for e in excl}
            out = [q for q in out if q["question"].lower() not in _seen]
        out.sort(key=lambda q: -q["curiosity_gap"])
        return out[:n]
    except Exception:
        return []


# ── YouTube demand & outlier validation ──────────────────────────────────────────
# Validates Claude-generated topic candidates against REAL YouTube market data so the
# trending list reflects PROVEN demand, not just LLM opinion. Per candidate it runs ONE
# search.list (top results) then videos.list (viewCount/publishedAt) + channels.list
# (subscriberCount) and derives:
#   - competition   : how many strong results already exist (saturation proxy)
#   - median_views  : demand of the top results (median resists one-viral skew)
#   - outlier       : best views÷subscribers found — THE signal a topic carries a SMALL
#                     channel (replicable demand independent of an existing audience)
#   - recency_days  : age of the strongest result (rising vs stale-evergreen)
#   - winning_titles: the framings the winners use (numbers, specificity) — feeds title gen
# These roll into an `opportunity` score (0-100). Gated on YOUTUBE_API_KEY; if it is unset
# or the API fails/quota-exhausts, candidates pass through unchanged (validated=False) so
# the pipeline never breaks. Quota: search.list=100 units, videos/channels.list=1 each →
# ~102 units/candidate, ~100 candidates/day on the default 10k/day quota.

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
_YT_BASE        = "https://www.googleapis.com/youtube/v3"
_YT_MAX_RESULTS = 12      # top results pulled per candidate (search.list)
_YT_TIMEOUT     = 20


class YouTubeQuotaError(Exception):
    """Raised when the YouTube Data API returns a quota/rate 403, so callers can stop early
    (every subsequent call this day will also 403 — no point burning the loop)."""


def _yt_get(path: str, params: dict) -> dict:
    """One YouTube Data API v3 GET. Raises YouTubeQuotaError on a quota 403, else raises on
    HTTP error (both caught by callers)."""
    import requests
    p = dict(params)
    p["key"] = YOUTUBE_API_KEY
    r = requests.get(f"{_YT_BASE}/{path}", params=p, timeout=_YT_TIMEOUT)
    if r.status_code == 403 and ("quota" in r.text.lower() or "ratelimit" in r.text.lower()):
        raise YouTubeQuotaError("YouTube API quota exceeded / rate-limited")
    r.raise_for_status()
    return r.json()


def _median(xs: list) -> float:
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    m = n // 2
    return float(s[m]) if n % 2 else (s[m - 1] + s[m]) / 2.0


# Relevance gate — YouTube search matches on keywords, so a broad query ("...knock out their
# teeth") drags in tangential hits ("These Dentists DESTROYED His Teeth!") whose huge views÷subs
# would FAKE an outlier. We only count a result toward demand/outlier if its TITLE actually shares
# enough significant terms with the topic. Cheap, deterministic, no extra API cost.
_YT_STOP = frozenset((
    "a an the of to in on for and or but with without is are was were be been being this that these "
    "those it its do did does done how why what when where who whom which whose will would can could "
    "your you their his her our my we they he she as at by from into out up down over under than then "
    "so if not no yes about more most less least very just only also even still vs versus per get got "
    "make made use used one two new old way back well much many such each any all some other"
).split())


def _stem(w: str) -> str:
    """Tiny order-insensitive stemmer so singular/plural/verb forms collapse to ONE token,
    applied identically to query and title. Key property: cave==caves, hole==holes,
    class==classes, knock==knocked==knocking (the naive 'strip s/es' version left cave/caves
    on different stems and silently dropped on-topic videos)."""
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"                                # stories → story
    if len(w) > 5 and w.endswith("sses"):
        w = w[:-2]                                      # classes → class
    for suf in ("ing", "ed"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            w = w[:-len(suf)]                           # knocking/knocked → knock
            break
    if len(w) > 4 and w.endswith("es"):
        w = w[:-2]                                      # boxes → box, caves → cav, tapes → tap
    elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        w = w[:-1]                                      # sharks → shark
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]                                      # cave → cav  (so cave == caves), game → gam
    return w


def _topic_terms(text: str) -> set:
    """Significant, stemmed content words of a title/question (stopwords + short words out)."""
    import re
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) >= 3 and w not in _YT_STOP}


def _is_relevant(qterms: set, title: str) -> bool:
    """True if `title` is plausibly ABOUT the topic (shares enough significant terms with qterms)."""
    if not qterms:
        return True                                     # can't judge → don't filter
    ov = len(qterms & _topic_terms(title))
    if len(qterms) <= 2:
        return ov >= 1
    return ov >= 2 or (ov / len(qterms)) >= 0.4


def _yt_search_metrics(query: str, content_format: str = "long") -> dict | None:
    """One topic → real YouTube demand/competition/outlier metrics. None on hard failure
    (network/quota), so the caller can mark the topic unvalidated and move on."""
    import datetime
    try:
        sr = _yt_get("search", {
            "part": "snippet", "q": query, "type": "video",
            "maxResults": _YT_MAX_RESULTS, "order": "relevance",
            "relevanceLanguage": "en", "safeSearch": "none",
            # YouTube's short bucket is <4 min; medium (4-20 min) is the closest like-for-like
            # market for ReelForge explainers. This prevents a viral 30s Short from proving a 10m idea.
            "videoDuration": "short" if content_format == "short" else "medium",
        })
    except YouTubeQuotaError:
        raise                                   # let the caller stop the whole batch
    except Exception as e:
        print(f"[youtube] search failed for {query!r}: {e}")
        return None
    items = sr.get("items", [])
    vids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
    if not vids:
        return {"competition": 0, "median_views": 0, "demand": 0, "outlier": 0.0,
                "outlier_title": "", "recency_days": None, "top_titles": []}
    try:
        vr = _yt_get("videos", {"part": "statistics,snippet,contentDetails", "id": ",".join(vids)})
    except YouTubeQuotaError:
        raise
    except Exception as e:
        print(f"[youtube] videos.list failed: {e}")
        return None
    vstats, chan_ids = {}, set()
    for it in vr.get("items", []):
        sn = it.get("snippet", {})
        ch = sn.get("channelId", "")
        vstats[it["id"]] = {
            "views": int(it.get("statistics", {}).get("viewCount", 0) or 0),
            "channel": ch, "title": sn.get("title", ""), "published": sn.get("publishedAt", ""),
        }
        if ch:
            chan_ids.add(ch)
    subs = {}
    if chan_ids:
        try:
            cr = _yt_get("channels", {"part": "statistics", "id": ",".join(sorted(chan_ids))})
            for it in cr.get("items", []):
                subs[it["id"]] = int(it.get("statistics", {}).get("subscriberCount", 0) or 0)
        except YouTubeQuotaError:
            raise
        except Exception as e:
            print(f"[youtube] channels.list failed (outlier ratio degraded): {e}")
    # Keep only results whose TITLE is actually on-topic — demand/outlier are computed over these,
    # so a tangential viral video can no longer fake an outlier.
    qterms = _topic_terms(query)
    relevant = [v for v in vstats.values() if _is_relevant(qterms, v["title"])]
    now = datetime.datetime.now(datetime.timezone.utc)
    best_outlier, best_title, best_age = 0.0, "", None
    velocities = []
    for v in relevant:
        # views÷subs, subs floored at 100 so 0-sub noise can't explode the ratio; require a
        # real audience (≥1k views) so a 5-view video on a 1-sub channel isn't a fake outlier.
        ratio = v["views"] / max(subs.get(v["channel"], 0), 100)
        try:
            pub = datetime.datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
            age_days = max(1, (now - pub).days)
        except Exception:
            age_days = None
        velocity = v["views"] / age_days if age_days else 0.0
        velocities.append((velocity, v["title"], age_days))
        if ratio > best_outlier and v["views"] >= 1000:
            best_outlier, best_title = ratio, v["title"]
    if velocities:
        _, _, best_age = max(velocities, key=lambda item: item[0])
    views_list = [v["views"] for v in relevant]
    top_titles = [v["title"] for v in sorted(relevant, key=lambda x: -x["views"])[:5]]
    return {
        "competition": len(relevant),          # ON-TOPIC competition (not raw keyword hits)
        "relevant_count": len(relevant),       # evidence depth → dampens thin-sample scores
        "total_results": len(vids),            # raw keyword hits, for reference
        "median_views": int(_median(views_list)),
        "median_views_per_day": round(_median([v[0] for v in velocities]), 1),
        "top_views_per_day": round(max((v[0] for v in velocities), default=0.0), 1),
        "demand": max(views_list) if views_list else 0,
        "outlier": round(best_outlier, 1),
        "outlier_title": best_title,
        "recency_days": best_age,
        "top_titles": top_titles,
    }


def youtube_validation_active() -> bool:
    return bool(YOUTUBE_API_KEY)


def validate_topics_youtube(questions: list[dict], content_format: str | None = None,
                            metrics: list[dict] | None = None) -> list[dict]:
    """Enrich each candidate with real YouTube demand/outlier metrics + an `opportunity`
    score (0-100), then RE-RANK by opportunity (validated first, then by score, curiosity as
    tiebreak). When YOUTUBE_API_KEY is unavailable, channel analytics still produce a baseline
    score while validated remains false, so topic refresh never breaks. Mutates + returns the list."""
    import topic_roi
    metrics = metrics or []
    # Channel evidence is useful even when the YouTube API is disabled, unreachable, or out of
    # quota. Seed every candidate with a deterministic baseline, then replace only the market
    # portion when a validated search result is available.
    for q in questions:
        fmt = content_format or q.get("content_format") or "long"
        q["content_format"] = fmt
        q["own_fit"], q["own_evidence"] = topic_roi.own_channel_fit(
            q.get("question", ""), fmt, metrics)
        q["opportunity"], q["score_breakdown"] = topic_roi.opportunity_score(
            q, {}, q["own_fit"])
        q["pattern"] = "promising" if q["opportunity"] >= 55 else "weak"
        q["roi_version"] = 2
    if not YOUTUBE_API_KEY:
        for q in questions:
            q.setdefault("validated", False)
        questions.sort(key=lambda q: (q.get("opportunity", -1), q.get("curiosity_gap", 0)),
                       reverse=True)
        return questions
    n_ok = 0
    quota_hit = False
    for q in questions:
        if quota_hit:
            q["validated"] = False
            continue
        try:
            m = _yt_search_metrics(q.get("question", ""), q["content_format"])
        except YouTubeQuotaError:
            # Quota gone — every remaining call today will 403 too. Stop, mark the rest
            # unvalidated, and let the caller keep the prior validated cache (no clobber).
            print("[youtube] quota exhausted — stopping validation; remaining topics unvalidated")
            quota_hit = True
            q["validated"] = False
            continue
        if not m:
            q["validated"] = False
            continue
        n_ok += 1
        rc = m.get("relevant_count", 0)
        own_fit, own_evidence = q["own_fit"], q["own_evidence"]
        opp, score_breakdown = topic_roi.opportunity_score(q, m, own_fit)
        pattern = ("proven" if opp >= 72 and rc >= 3 else
                   "untapped" if opp >= 60 and rc < 3 else
                   "saturated" if m.get("competition", 0) >= 9 and opp < 70 else
                   "promising" if opp >= 55 else "weak")
        q.update({
            "validated": True, "opportunity": opp, "pattern": pattern,
            "median_views": m["median_views"], "demand": m["demand"],
            "median_views_per_day": m.get("median_views_per_day", 0),
            "top_views_per_day": m.get("top_views_per_day", 0),
            "outlier": m["outlier"], "outlier_title": m.get("outlier_title", ""),
            "competition": m["competition"], "relevant_count": rc,
            "total_results": m.get("total_results", 0), "recency_days": m.get("recency_days"),
            "winning_titles": m.get("top_titles", []),
            "own_fit": own_fit, "own_evidence": own_evidence,
            "score_breakdown": score_breakdown, "roi_version": 2,
        })
    questions.sort(key=lambda q: (q.get("validated", False), q.get("opportunity", -1),
                                  q.get("curiosity_gap", 0)), reverse=True)
    print(f"[youtube] validated {n_ok}/{len(questions)} topics against market data")
    return questions


_REFRAME_SYSTEM = (
    "You are a YouTube packaging strategist. For each video TOPIC, write ONE scroll-stopping TITLE — a "
    "click hook, NOT a reworded topic. Use the RELATABLE-MYSTERY framing that wins for this channel: the "
    "hidden, surprising, slightly-unsettling truth about everyday life, the body, or the mind. Front-load "
    "the curiosity, be specific and ACCURATE, ~40-60 characters. AVOID 'how does X work' / 'what is X' "
    "framing — that pattern flops here. If 'winning' titles are given, echo what's working without copying. "
    'Return ONLY JSON: {"titles":[{"suggested_title":"<the hook>"}]} in the SAME order as the topics given.'
)


def suggest_titles(topics: list, cost_sink: list | None = None) -> list:
    """Add a click-optimized `suggested_title` to each topic (ONE batched Claude call for the whole
    list). Separate from `question` (which stays the content brief); this is the title hook. Best-effort
    — on failure topics are returned unchanged. Mutates + returns the list."""
    items = [t for t in topics if _s(t.get("question")).strip()]
    if not items:
        return topics
    lines = []
    for i, t in enumerate(items):
        wt = (t.get("winning_titles") or [])[:2]
        lines.append(f'{i+1}. TOPIC: {_s(t.get("question"))}'
                     + (f' | winning: {" / ".join(wt)}' if wt else ""))
    try:
        r = _claude().messages.create(model=ANTHROPIC_MODEL, max_tokens=1500, system=_REFRAME_SYSTEM,
                                      messages=[{"role": "user", "content": "\n".join(lines)}])
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        data, _ = _parse_script_json(r.content[0].text)
        out = data.get("titles", []) if isinstance(data, dict) else []
        for i, t in enumerate(items):
            if i < len(out) and isinstance(out[i], dict):
                st = _s(out[i].get("suggested_title")).strip()
                if st:
                    t["suggested_title"] = st
    except Exception as e:
        print(f"[reframe] suggest_titles failed: {e}")
    return topics


def _thumbnail_caption(title: str, question: str, cost_sink: list | None = None):
    """A BLUNT 2-4 word ALL-CAPS emotional 'itch' hook (+ short sub). The thumbnail text creates
    curiosity — it does NOT summarize the video and is NOT the searchable title (competitor pattern:
    '1 emotional/vivid word + 1 confusion word')."""
    try:
        r = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=150,
            system=('Return ONLY JSON: {"hook":"a BLUNT 2-4 word ALL-CAPS curiosity hook, usually one '
                    'vivid/emotional word + one confusion word, ending with ? — e.g. "NO DENTIST?", '
                    '"SAFE TO EAT?", "1% HEAVIER?", "SLEEP SAFE?", "WHY VANISH?", "NO FOOD?". Create '
                    'the ITCH; do NOT summarize or explain the video, and do NOT just repeat the '
                    'title.","sub":"1-3 word subtitle, or empty"}.'),
            messages=[{"role": "user", "content": f"Video title: {title}\nTopic: {question}"}])
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        o, _ = _parse_script_json(r.content[0].text)
        hook = _s(o.get("hook")).strip().upper()[:28]   # was 20 — chopped legit 4-word itches ("WHO PICKS THE PRESIDENT?")
        sub = _s(o.get("sub")).strip().upper()[:22]
        if hook:
            return hook, sub
    except Exception:
        pass
    w = question.strip().rstrip("?").split()
    return ((" ".join(w[:2]).upper() + "?!") if w else "WATCH?!"), "EXPLAINED"


# CONSEQUENCE-FIRST thumbnail strategy. The old caption showed the PREMISE ("1% HEAVIER?"); a heavier-Sun
# video got 1 click / 472 impressions (~0.2% CTR). The rule the packaging follows now: TITLE = the cause,
# THUMBNAIL = the single most surprising visible CONSEQUENCE (e.g. "EARTH LOSES 7 DAYS"), rendered as a
# clean flat-vector scene (subject + threat + before/after + loss cue, cool=old / warm=new), Bolt optional.
_THUMB_STRATEGY_SYSTEM = (
    "You are an elite YouTube thumbnail art director for a science / 'what if' explainer channel. The "
    "TITLE states the CAUSE/premise; the THUMBNAIL must show the single most surprising, high-stakes "
    "CONSEQUENCE — NEVER repeat the premise. From the video, pick the ONE consequence a cold mobile "
    "viewer would stop scrolling for, that reads in under a second and triggers at least THREE of: "
    "threat, loss, before/after change, numerical specificity, curiosity gap.\n"
    "Return ONLY JSON: {"
    '"consequence_text":"a 2-5 word ALL-CAPS CONSEQUENCE line, concrete and direct, with a specific '
    'NUMBER when one is the hook (e.g. \\"EARTH LOSES 7 DAYS\\", \\"YOUR BLOOD BOILS\\", \\"IMMUNE SYSTEM '
    'TURNS ON YOU\\") — NOT the premise, NEVER vague (\\"LESS TIME\\", \\"THIS CHANGES EVERYTHING\\", '
    '\\"WHAT HAPPENS NEXT\\" are BANNED)",'
    '"affected_subject":"the concrete thing under threat (Earth, a human body, a single cell, the year)",'
    '"threat_source":"the force/cause looming (a swollen heavier Sun, a stopped program) or \\"\\" if none",'
    '"old_state":"the normal/safe BEFORE state (drawn in a COOL color) or \\"\\"",'
    '"new_state":"the dangerous/changed AFTER state (drawn in a WARM color) or \\"\\"",'
    '"loss_cue":"ONE concrete symbol of the loss/change: torn calendar pages, a shrinking orbit, a '
    'cracking planet, a snapping DNA strand, a wilting body — or \\"\\"",'
    '"include_bolt":true or false — include the Bolt robot mascot ONLY if it adds emotion without '
    "competing with the consequence; OMIT it when a clean consequence reads stronger,"
    '"desired_reaction":"the one-line thought the viewer should have (\\"how can 1% do THAT?\\")"}.'
)


def _thumbnail_strategy(title: str, question: str, transcript: str = "",
                        cost_sink: list | None = None) -> dict:
    """Derive the CONSEQUENCE-driven thumbnail strategy (title=cause -> thumbnail=consequence). Mines the
    transcript for the single most surprising payoff. Best-effort: {} on failure (caller falls back)."""
    try:
        usr = (f'VIDEO TITLE (the cause/premise): "{title}"\nTOPIC: {question}\n'
               + (f'\nTRANSCRIPT — mine the single most surprising, pictureable CONSEQUENCE from here '
                  f'(prefer a concrete number):\n{_s(transcript)[:4500]}' if transcript else ""))
        r = _claude().messages.create(model=ANTHROPIC_MODEL, max_tokens=500,
                                      system=_THUMB_STRATEGY_SYSTEM,
                                      messages=[{"role": "user", "content": usr}])
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        o, _ = _parse_script_json(r.content[0].text)
        if isinstance(o, dict) and _s(o.get("consequence_text")).strip():
            return o
    except Exception:
        pass
    return {}


_THUMB_VARIANT_STEER = {
    "clarity":   "CLARITY-FIRST: the simplest possible layout, the affected subject the single largest "
                 "element, the before/after contrast unmistakable.",
    "threat":    "THREAT-FIRST: make the threat source much larger and closer, the subject in visible "
                 "peril, the loss cue violently mid-motion.",
    "curiosity": "CURIOSITY-FIRST: emphasize the surprising consequence and the before/after gap while "
                 "keeping one clean focal conflict.",
}


def _flat_thumb_prompt(strat: dict, question: str, layout: str, variant: str,
                       bolt_line: str, bolt_emotion: str) -> str:
    """Build a CLEAN FLAT-VECTOR thumbnail scene prompt from the strategy (composition formula +
    semantic cool/warm color + 3-5 elements + Bolt optional). NO baked text — the headline is
    composited separately (image models garble text)."""
    subj = _s(strat.get("affected_subject")) or question
    threat = _s(strat.get("threat_source"))
    old_s, new_s = _s(strat.get("old_state")), _s(strat.get("new_state"))
    loss = _s(strat.get("loss_cue"))
    bolt = bool(strat.get("include_bolt", True))
    p = [
        "A premium, highly clickable YouTube THUMBNAIL in a CLEAN FLAT VECTOR science-explainer "
        "illustration style — bold graphic shapes, saturated colors, strong silhouettes, minimal "
        "texture, very high contrast, designed to read on a tiny mobile screen. NOT photorealistic, "
        "NOT a cinematic poster, NOT cluttered.",
        f"It must instantly communicate this consequence (do NOT write any text): "
        f"{_s(strat.get('desired_reaction')) or question}.",
        f"MAIN SUBJECT: {subj} — a large, simplified, instantly recognizable shape near the center.",
    ]
    if threat:
        p.append(f"THREAT/FORCE: {threat} — oversized and cropped by the RIGHT edge so it looms.")
    if old_s and new_s:
        p.append(f"BEFORE vs AFTER: show the OLD/normal state ({old_s}) in a COOL color (blue / cyan / "
                 f"purple) and the NEW/dangerous state ({new_s}) in a WARM color (orange / red / yellow). "
                 "Make the change unmistakable through position, scale and color — never through labels.")
    if loss:
        p.append(f"LOSS CUE: {loss} — dynamic, mid-motion, clearly breaking away / disappearing.")
    p.append("Semantic color: COOL = normal/safe/old, WARM = danger/new. Deep navy or purple space-like "
             "background. THREE to FIVE major elements ONLY, generous negative space, one clean eye path.")
    p.append(layout)
    if bolt:
        p.append(f"{bolt_line}Include {MASCOT_NAME} the robot SMALL in a lower corner, {bolt_emotion}, "
                 "simplified to the flat style — never covering the subject or the headline zone.")
    else:
        p.append(f"Do NOT include the {MASCOT_NAME} robot or any mascot — a clean consequence reads stronger here.")
    p.append(_THUMB_VARIANT_STEER.get(variant, ""))
    p.append("Do NOT depict real, identifiable or recent real-world events, real public figures, or "
             "partisan symbols — use generic, timeless, symbolic imagery. Absolutely NO text, letters, "
             "words or numbers baked into the image.")
    return " ".join(x for x in p if x).strip()


def _compose_thumbnail(bg_path, hook, sub, out_path, tw, th, style_mode):
    """Overlay a big two-tone sticker title + subtitle pill on the title side (Bolt is in bg)."""
    from PIL import ImageOps
    pal = _MODE_PALETTE.get(style_mode, _MODE_PALETTE["educational"])
    accent = _rgb(pal["accent"]); white = _rgb("white"); navy = _rgb("navy")
    base = ImageOps.fit(Image.open(bg_path).convert("RGB"), (tw, th)).convert("RGBA")
    d = ImageDraw.Draw(base)
    words = [w for w in hook.upper().split() if w]
    x0 = int(tw * 0.05)
    # Drawable title band: full width minus the left margin and a right gutter for Bolt (baked into
    # the bg lower-right). Text must fit THIS — the old per-word `tw*0.60` check + size-40 floor let a
    # long word (e.g. "PRESIDENT?") overflow off-canvas when it couldn't shrink enough ("PRESIDEN").
    avail = int(tw * (0.90 if th > tw else 0.72)) - x0   # 9:16 social is narrow, so allow more width

    def _wrap(font):
        ln, cur = [], []
        for w in words:
            if cur and d.textlength(" ".join(cur + [w]), font=font) > avail:
                ln.append(cur); cur = [w]
            else:
                cur.append(w)
        if cur: ln.append(cur)
        return ln

    def _overflows(font):
        widest_word = max((d.textlength(w, font=font) for w in words), default=0)
        widest_line = max((d.textlength(" ".join(l), font=font) for l in _wrap(font)), default=0)
        return max(widest_word, widest_line) + 18 > avail   # +18 ≈ stroke margin so nothing clips

    size = int(th * 0.18); f = _pil_font(size)
    while size > 26 and _overflows(f):                       # lower floor: guarantee it fits, then draw
        size -= 5; f = _pil_font(size)
    sp = int(d.textlength(" ", font=f))
    lines = _wrap(f)
    line_h = d.textbbox((0, 0), "X", font=f, stroke_width=8)[3] + int(size * 0.12)
    x0, y = int(tw * 0.05), int(th * 0.10)
    # Accent the NUMBER (consequence hooks like "EARTH LOSES 7 DAYS" live or die on the number); if
    # there's no digit, fall back to accenting the final word.
    accent_word = next((w for w in words if any(c.isdigit() for c in w)), words[-1] if words else "")
    for ln in lines:
        x = x0
        for w in ln:
            col = accent if w == accent_word else white   # the NUMBER pops, else the final word
            _draw_word(base, (x, y), w, f, color_rgb=col, stroke_rgb=(*navy, 255), stroke_w=8, glow_rgb=col)
            x += int(d.textlength(w, font=f)) + sp
        y += line_h
    if sub and sub.strip():
        s = sub.strip().upper()
        ssize = int(th * 0.065)
        sf = _pil_font(ssize)
        px, py = 26, 12
        # Shrink the subtitle until its pill fits within the canvas (overflowed on 9:16 before).
        while ssize > 26 and d.textlength(s, font=sf) + 2 * px > tw - x0 - int(tw * 0.04):
            ssize -= 4
            sf = _pil_font(ssize)
        sw = int(d.textlength(s, font=sf))
        bh = d.textbbox((0, 0), s, font=sf, stroke_width=3)[3]
        pill = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(pill).rounded_rectangle(
            [x0, y + 8, x0 + sw + 2 * px, y + 8 + bh + 2 * py], radius=20,
            fill=(*navy, 224), outline=(*accent, 235), width=5)
        base.alpha_composite(pill)
        ImageDraw.Draw(base).text((x0 + px, y + 8 + py), s, font=sf, fill=(*accent, 255),
                                  stroke_width=3, stroke_fill=(*navy, 235))
    base.convert("RGB").save(out_path, "JPEG", quality=90)


# The publish-readiness checklist for thumbnails (CTR is the channel's #1 wall). Graded by vision.
_THUMB_GRADE_SYSTEM = (
    "You are a ruthless YouTube thumbnail critic for a science/'what-if' channel, judging for MOBILE "
    "click-through. A title is given alongside. The TITLE is the CAUSE; a strong thumbnail shows the "
    "CONSEQUENCE (not the premise). Grade each item strictly true/false:\n"
    "1. one_second: understandable in ONE second at tiny (~160px) mobile size?\n"
    "2. consequence_shown: does it SHOW a consequence / change / loss — NOT merely restate the premise "
    "or the title's cause?\n"
    "3. stakes: is there a clear THREAT, LOSS, or dramatic BEFORE/AFTER change visible in the frame?\n"
    "4. single_focal: one dominant focal conflict, uncluttered (passes the squint test), <=5 major "
    "elements?\n"
    "5. text_readable: is the headline text short (<=5 words) and readable at mobile size? (true if no "
    "baked text)\n"
    "6. curiosity_gap: does it open a loop the title's cause makes you NEED explained?\n"
    "7. flat_clean: clean flat / bold-graphic / vector style with high contrast — NOT photo-cluttered, "
    "muddy, or AI-generic-noisy?\n"
    "8. not_title_echo: does the image add a CONSEQUENCE the title does not already state (thumbnail != "
    "a picture of the title)?\n"
    "Return ONLY JSON: {\"items\":{\"one_second\":bool,...all 8...},\"fails\":int (count of false),"
    "\"redesign_note\":\"one sentence — the single biggest fix\"}."
)


def grade_thumbnail(image_path: str, title: str, cost_sink: list | None = None) -> dict | None:
    """Vision-grade a finished thumbnail against the 8-point checklist. Returns
    {items, fails, redesign_note} or None (best-effort). 'fails >= 3' → redesign."""
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        r = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=500, system=_THUMB_GRADE_SYSTEM,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": f'Title shown next to this thumbnail: "{title}". Grade it.'}]}],
        )
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        o, _ = _parse_script_json(r.content[0].text)
        return o if isinstance(o, dict) and "fails" in o else None
    except Exception:
        return None


# Match the thumbnail's mood to the TOPIC (playbook: "match the emotion to the science wow"). Forcing
# danger/threat on every topic produced apocalypse thumbnails for POSITIVE ones (e.g. an asteroid
# slamming Earth on "Why Earth Is Perfect For Life" — image contradicts premise → weak, low CTR).
_VALENCE_WONDER = ("perfect", "beautiful", "amazing", "incredible", "wonder", "suspiciously", "best",
                   "luckiest", "miracle", "impossibly", "stunning", "gorgeous", "elegant", "goldilocks",
                   "hospitable", "just right", "how did life", "why is", "why does")
_VALENCE_DANGER = ("die", "death", "deadly", "kill", "danger", "disaster", "survive", "survival",
                   "collapse", "explode", "explosion", "catastrophe", "apocalypse", "destroy", "toxic",
                   "extinct", "crush", "freeze", "burn", "starve", "suffocate", "fall", "crash", "worst")
_THUMB_EMOTION = {
    "danger":  ["SHOCKED, recoiling with hands up", "ALARMED, eyes huge, leaning back",
                "HORRIFIED, jaw-dropped", "PANICKED, bracing away", "STUNNED and aghast"],
    "wonder":  ["AMAZED, eyes wide with WONDER", "AWESTRUCK, gazing up in marvel",
                "DELIGHTED, mouth agape in wonder", "DAZZLED and curious", "in AWE, hands raised"],
    "neutral": ["CURIOUS, leaning in intrigued", "SURPRISED, eyebrows raised",
                "INTRIGUED, wide-eyed", "fascinated, tilting his head", "wondering, hand on chin"],
}
_THUMB_MOMENT = {
    "danger":  ("Show the SINGLE MOST DRAMATIC MOMENT of it ACTUALLY HAPPENING — the real stakes in "
                "motion (the event, the danger, the consequence; a subject caught mid-action) as the "
                "clear HERO."),
    "wonder":  ("Show the SINGLE MOST AWE-INSPIRING, beautiful moment of it — the breathtaking, "
                "'how is this even real' sight (the wonder, the beauty, the marvel) as the clear HERO. "
                "POSITIVE awe — absolutely NOT danger, destruction, or catastrophe."),
    "neutral": ("Show the SINGLE MOST STRIKING, curiosity-provoking moment of it — the surprising "
                "sight that makes you look twice — as the clear HERO."),
}


def _topic_valence(title: str, question: str, cost_sink: list | None = None) -> str:
    """'danger' | 'wonder' | 'neutral' — so the thumbnail's imagery+emotion match the topic's tone.
    LLM-first with a keyword fallback; defaults to 'danger' (the prior always-threat behaviour)."""
    try:
        r = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=8,
            system=("Classify the emotional tone a YouTube thumbnail for this topic should have. Reply "
                    "ONE word: 'danger' (threat/death/disaster/survival stakes), 'wonder' (awe, beauty, "
                    "positive marvel, 'how is this real'), or 'neutral'."),
            messages=[{"role": "user", "content": f"Topic: {title or question}"}])
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        v = _s(r.content[0].text).strip().lower()
        for cand in ("wonder", "danger", "neutral"):
            if cand in v:
                return cand
    except Exception:
        pass
    t = f"{title} {question}".lower()
    if any(w in t for w in _VALENCE_WONDER):
        return "wonder"
    if any(w in t for w in _VALENCE_DANGER):
        return "danger"
    return "danger"


def generate_thumbnail(title, question, style_mode, video_format, out_dir, cost_sink=None,
                       concept=None, thumb_style=None, report=None, transcript="") -> str:
    """CONSEQUENCE-FIRST thumbnail (title = cause -> thumbnail = the surprising consequence). Derives the
    single most clickable consequence from the transcript, renders it as a CLEAN FLAT-VECTOR scene
    (subject + threat + before/after + loss cue, cool = old / warm = new, Bolt optional), composites a
    short consequence headline (the NUMBER pops), and keeps the BEST of N variants (clarity/threat/
    curiosity) by the vision grader. Best-effort; returns the path. THUMB_VARIANTS caps the variant count."""
    import random as _r, shutil as _sh
    social = video_format == "social"
    tw, th = (720, 1280) if social else (1280, 720)
    img_size = "1024x1536" if social else "1536x1024"
    ref = [MASCOT_REF] if os.path.exists(MASCOT_REF) else None
    bolt_line = (MASCOT_REF_LINE + " ") if ref else ""
    out = os.path.join(out_dir, "thumbnail.jpg")
    bg = os.path.join(out_dir, "_thumb_bg.jpg")
    _rep = report if isinstance(report, dict) else {}

    valence = _topic_valence(title, question, cost_sink=cost_sink)
    bolt_emotion = _r.Random(hash((question, video_format)) & 0xffffffff).choice(_THUMB_EMOTION[valence])
    strat = _thumbnail_strategy(title, question, transcript, cost_sink=cost_sink)
    bolt = bool(strat.get("include_bolt", True)) if strat else True

    # Headline: caller-supplied > strategy CONSEQUENCE > premise-caption fallback.
    if concept and _s(concept.get("text")):
        hook = _s(concept["text"]).upper()[:40]
    elif strat.get("consequence_text"):
        hook = _s(strat["consequence_text"]).upper()[:40]
    else:
        hook, _sub = _thumbnail_caption(title, question, cost_sink=cost_sink)
    _rep["headline"] = hook
    if strat:
        _rep["strategy"] = {k: strat.get(k) for k in
                            ("affected_subject", "threat_source", "loss_cue", "include_bolt")}

    layout = ("Keep the TOP third of the frame clear/simple (flat background) for a large text headline; "
              "the subject fills the middle." if social else
              "Keep the UPPER-LEFT third clear/simple (flat background) for a large text headline; place "
              "the subject center to center-right.")

    def _prompt(variant: str, extra: str = "") -> str:
        base = _flat_thumb_prompt(strat, question, layout, variant, bolt_line, bolt_emotion)
        return (base + " " + extra).strip() if extra else base

    def _render(variant: str) -> tuple[str, dict | None, bool]:
        """Render ONE flat-vector variant + composite the headline; return (path, grade, fell_back)."""
        vpath = os.path.join(out_dir, f"_thumb_{variant}.jpg")
        rp = ref if bolt else None                   # only pass the Bolt reference when Bolt is wanted
        fell = False
        try:
            generate_image(_prompt(variant), bg, reference_paths=rp, cost_sink=cost_sink, size=img_size)
        except ContentBlocked:                       # moderation block → one safe, symbolic redraw
            try:
                generate_image(_prompt(variant, "SAFE REDRAW: keep it dramatic but symbolic and "
                                       "non-graphic — no gore, blood, weapons, or explicit violence."),
                               bg, reference_paths=rp, cost_sink=cost_sink, size=img_size)
            except Exception:
                make_fallback_frame(bg, "", w=tw, h=th); fell = True
        except Exception:
            make_fallback_frame(bg, "", w=tw, h=th); fell = True
        _compose_thumbnail(bg, hook, "", vpath, tw, th, style_mode)
        return vpath, grade_thumbnail(vpath, title, cost_sink=cost_sink), fell

    # Render N variants, keep the fewest-fails one. Default 3 landscape (CTR-critical) / 2 social;
    # stop early on a perfect (0-fail) variant so we don't overspend.
    n_var = max(1, min(3, int(os.environ.get("THUMB_VARIANTS", "3" if not social else "2"))))
    plan = ["clarity", "threat", "curiosity"][:n_var]
    best_path, best_grade, any_fell = None, None, False
    for v in plan:
        vpath, g, fell = _render(v)
        any_fell = any_fell or fell
        if best_grade is None or (g or {}).get("fails", 99) < best_grade.get("fails", 99):
            best_path, best_grade = vpath, g
        if g and g.get("fails", 99) == 0:
            break
    if best_path:
        _sh.copy(best_path, out)
    else:                                            # nothing rendered → dead-frame fallback
        make_fallback_frame(bg, "", w=tw, h=th)
        _compose_thumbnail(bg, hook, "", out, tw, th, style_mode); any_fell = True

    for v in plan:                                   # cleanup variant temp files + bg
        try: os.remove(os.path.join(out_dir, f"_thumb_{v}.jpg"))
        except OSError: pass
    try: os.remove(bg)
    except OSError: pass

    _rep["qa"] = "skipped" if best_grade is None else "ok"
    _rep["fails"] = (best_grade or {}).get("fails")
    _rep["weak"] = bool(best_grade and best_grade.get("fails", 0) >= 3)
    _rep["fallback"] = any_fell
    _rep["variants"] = len(plan)
    return out


# ── Script engagement gate ───────────────────────────────────────────────────────
# Auto-grades a generated long-form script on the three things that decide whether a viewer
# stays and wants more — HOOK (grabs), STORY (ramps + keeps you guessing), ENDING (pays off) —
# plus repetition + cadence as supporting checks, and regenerates a weak draft (targeting its
# weakest axis) before a single dollar is spent on images/TTS/render. Mirrors how thumbnails
# self-grade. Tunable via env; degrades gracefully (a grader failure never blocks a render).
_SCRIPT_GATE_PASS    = int(os.environ.get("SCRIPT_GATE_PASS", "78"))      # regen TARGET: regenerate below this, keep best
_SCRIPT_GATE_RETRIES = int(os.environ.get("SCRIPT_GATE_RETRIES", "1"))    # extra regen attempts
# Premise (Gate -1) gets a BIGGER regen budget than the generic gate: escaping the "explain the real
# biology" attractor to actually deliver a fictional scenario reliably takes more than one re-roll.
_PREMISE_GATE_RETRIES = int(os.environ.get("PREMISE_GATE_RETRIES", "3"))
# Quality FLOOR — distinct from the regen TARGET above. Only BELOW the floor is a script genuinely
# weak → flagged degraded (and aborted if SCRIPT_GATE_HARD). The inline 1-call grader runs ~7 pts
# harsher than the validation panel, so a 74 ≈ a solid B+ on the panel — shippable, not "degraded".
# Conflating the floor with the 78 target made decent 70-77 scripts cry "degraded"; the floor sits
# lower so only real duds (repetitive/incoherent, panel ~B- or worse) trip it.
_SCRIPT_GATE_FLOOR   = int(os.environ.get("SCRIPT_GATE_FLOOR", "70"))     # below = degraded
# Long-form ELEVATION: max targeted-revision passes to climb a sub-target draft toward PASS. Each
# pass fixes the current weakest axis, re-grades, and is KEPT only if it improved (so it can't hurt)
# and STOPS early on no improvement — so the real cost is usually 0-1 extra calls. 2 lets it fix two
# different weak axes (e.g. hook then ending). Bump for more aggressive elevation.
_SCRIPT_ELEVATE_PASSES = int(os.environ.get("SCRIPT_ELEVATE_PASSES", "2"))
# Structural retries happen before the subjective engagement grader. One re-plan is usually enough
# to repair a missing prediction/payoff/loop while keeping provider cost bounded.
_LONGFORM_CONTRACT_RETRIES = int(os.environ.get("LONGFORM_CONTRACT_RETRIES", "1"))


def _script_gate_hard() -> bool:
    """True when the operator wants a below-floor draft to ABORT before any image/TTS/Veo spend.
    Accepts 1/true/yes/on (a bare `SCRIPT_GATE_HARD=1` that does nothing is a costly footgun)."""
    return (os.environ.get("SCRIPT_GATE_HARD") or "").strip().lower() in ("1", "true", "yes", "on")


def _longform_retention_hard() -> bool:
    """Fail before image/TTS spend when objective story-contract checks still fail.

    Enabled by default: unlike the subjective LLM score, these checks cover explicit structural
    promises (prediction/payoff timing, loop closure, final payoff) and get an automatic retry first.
    """
    return (os.environ.get("LONGFORM_RETENTION_HARD", "1") or "1").strip().lower() \
        in ("1", "true", "yes", "on")
_SHORT_GATE_PASS     = int(os.environ.get("SHORT_GATE_PASS", "72"))       # social grade_short regen TARGET
                                                                          # (lowered for the harsher
                                                                          # retention-weighted rubric)
_SHORT_GATE_FLOOR    = int(os.environ.get("SHORT_GATE_FLOOR", "64"))      # below = degraded (≠ target)

_SCRIPT_GRADE_SYSTEM = (
    "You are a brutal YouTube retention editor grading an explainer's NARRATION (the spoken track) "
    "on whether a viewer will STAY and want more. Score 0-100 on five axes:\n"
    "- hook: do the first 1-2 lines hit a concrete gut-punch/stake within ~10s AND leave an OPEN "
    "LOOP (a dangling mystery), instead of a flat assertion or slow setup?\n"
    "- story: does the MIDDLE escalate (each beat adds a new stake/complication/clue) and KEEP THE "
    "VIEWER GUESSING (the answer stays genuinely uncertain), not plateau into a fact-list?\n"
    "- ending: does the climax land as ONE earned payoff and the final line resonate (specific + "
    "shareable), not a generic 'remember to...' PSA?\n"
    "- repetition: is each core idea stated ONCE (no concept re-explained, no answer re-stated)?\n"
    "- cadence: does the narration vary sentence length (short punch beats + real questions), not a "
    "monotone of same-length declaratives?\n"
    "Be harsh; most drafts land 60-78. Return ONLY JSON: {\"hook\":int,\"story\":int,\"ending\":int,"
    "\"repetition\":int,\"cadence\":int,\"weakest\":\"hook|story|ending|repetition|cadence\","
    "\"notes\":\"one concrete sentence naming the single biggest fix\"}."
)


def grade_script(script: dict, cost_sink: list | None = None) -> dict | None:
    """Engagement self-grade of the narration. Returns {scores, overall (hook/story/ending double-
    weighted), weakest, notes} or None on failure (best-effort — never raises)."""
    scenes = script.get("scenes", [])
    narr = [s.get("narration", "") for s in scenes]
    if len(narr) < 4:
        return None
    full = " ".join(narr)
    sample = full if len(full) <= 12000 else full[:6000] + " […] " + full[-6000:]
    try:
        r = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=600, system=_SCRIPT_GRADE_SYSTEM,
            messages=[{"role": "user", "content":
                       f'Title: "{_s(script.get("title"))}". Hook: "{_s(script.get("hook"))}".\n'
                       f'{len(scenes)} scenes. Full narration:\n{sample}'}])
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        o, _ = _parse_script_json(r.content[0].text)
        if not isinstance(o, dict):
            return None
        sc = {k: int(o.get(k, 0) or 0) for k in ("hook", "story", "ending", "repetition", "cadence")}
        overall = round((2 * sc["hook"] + 2 * sc["story"] + 2 * sc["ending"]
                         + sc["repetition"] + sc["cadence"]) / 8)
        weakest = _s(o.get("weakest")).strip().lower()
        if weakest not in sc:
            weakest = min(sc, key=sc.get)
        return {"scores": sc, "overall": overall, "weakest": weakest, "notes": _s(o.get("notes")).strip()}
    except Exception:
        return None


# Targeted, axis-specific repair instructions — used to REVISE the winning draft (vs re-rolling).
_AXIS_FIX = {
    "hook":   ("Rewrite ONLY the first 1-3 lines into a sharper gut-punch that ends on an OPEN LOOP "
               "(a dangling mystery the viewer needs resolved), in the first ~15s. Do NOT give away "
               "the payoff. KEEP THE SUBJECT NAMED in plain words (the actual topic noun) — never "
               "swap it for a euphemism or pronoun; a cold viewer must still know the exact topic. "
               "Leave every other line UNCHANGED."),
    "ending": ("Rewrite ONLY the final ~6 lines into an EARNED, specific payoff: state the loss/answer "
               "ONCE, no generic PSA or 'thanks for watching', end on a resonant button. Leave the "
               "rest UNCHANGED."),
    "story":  ("Tighten the MIDDLE: rewrite lines that plateau so each one ESCALATES — raises the "
               "stakes, deepens the mystery, or adds a NEW complication — and keep one open question "
               "alive throughout. Touch only the flat lines; leave strong ones UNCHANGED."),
    "repetition": ("Rewrite ONLY lines that re-state a concept an earlier line already covered, so each "
                   "line adds something NEW (state-once). Leave unique lines UNCHANGED."),
    "cadence": ("Vary sentence length HARD — mix <=5-word punch lines with longer ones, vary how lines "
                "open (not all 'The'/'They'), and land a genuine question at a turn. Keep the meaning; "
                "only change rhythm/wording."),
}


def _revise_for_axis(script: dict, weakest: str, notes: str, cost_sink: list | None = None) -> tuple[dict, float]:
    """ELEVATE the winning draft by surgically fixing ONLY its weakest grading axis, instead of
    re-rolling a fresh script (which throws away the good parts). Count-preserving + narration-only,
    so the scene↔image mapping stays intact and a long script can't truncate. Best-effort: returns
    the script unchanged on any failure, so it can only help (caller keeps-best)."""
    scenes = script.get("scenes", [])
    lines = [_s(s.get("narration", "")) for s in scenes]
    if len(lines) < 3:
        return script, 0.0
    rule = _AXIS_FIX.get(weakest, _AXIS_FIX["story"])
    numbered = "\n".join(f"{i+1}. {l}" for i, l in enumerate(lines))
    sys = ("You are a ruthless script editor improving ONE weakness of an explainer's spoken narration "
           "WITHOUT breaking the rest. Keep the EXACT line count and order. Rewrite only the lines the "
           "instruction targets; return all others UNCHANGED, verbatim. Each entry is the SPOKEN line "
           "ONLY — no leading numbers, no tags. Return ONLY JSON: "
           '{"narration":[<exactly one line per input line, same order>]}.')
    try:
        r = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=8000, system=sys,
            messages=[{"role": "user", "content":
                       f"WEAKEST AXIS: {weakest}. FIX: {rule}\n"
                       + (f"Grader's note: {notes}\n" if notes else "")
                       + f"Keep all {len(lines)} lines:\n{numbered}"}])
        cost = _msg_cost(r.usage)
        out, rc = _parse_script_json(r.content[0].text); cost += rc
        new = out.get("narration") if isinstance(out, dict) else None
        if isinstance(new, list) and len(new) == len(lines):
            import re as _re
            _pfx = _re.compile(r'^\s*(\d+[.\)]\s*)?', _re.I)
            for s, nl in zip(scenes, new):
                clean = _pfx.sub("", _s(nl)).strip()
                if clean:
                    s["narration"] = clean
        return script, cost
    except Exception:
        return script, 0.0


def generate_graded_script(question, duration_sec, style, image_guidance, video_format, series,
                           cost_sink=None, log=lambda m: None, operator_direction: str = "",
                           story_format: str = "standard_explainer",
                           research_dossier: dict | None = None) -> dict:
    """Generate a script, engagement-grade it, and ELEVATE a sub-target draft by surgically revising
    its weakest axis (up to `_SCRIPT_GATE_RETRIES` passes), keeping the best-scoring version. Returns
    that draft. Stores the winning grade on `script['_grade']`. Never blocks: a grader failure accepts
    the draft. Revising the winner (vs re-rolling a fresh script) keeps the good parts and reliably
    climbs toward the PASS target instead of gambling on a new roll."""
    import copy
    best = generate_script(question, duration_sec, style, image_guidance=image_guidance,
                           video_format=video_format, series=series, operator_direction=operator_direction,
                           story_format=story_format, research_dossier=research_dossier)
    total_generation_cost = float(best.get("_script_cost_usd") or 0.0)
    best_validation = validate_longform_story(best, question)
    for _ in range(max(0, _LONGFORM_CONTRACT_RETRIES)):
        if best_validation.get("passed"):
            break
        fixes = "; ".join(x.get("message", "") for x in best_validation.get("errors", [])[:6])
        log(f"Long-form contract {best_validation.get('score', 0)}/100 — replanning once before render: {fixes}")
        cand = generate_script(
            question, duration_sec, style, image_guidance=image_guidance,
            video_format=video_format, series=series, operator_direction=operator_direction,
            story_format=story_format,
            research_dossier=research_dossier,
            improve_note="DETERMINISTIC CONTRACT FAILURES: " + fixes,
        )
        total_generation_cost += float(cand.get("_script_cost_usd") or 0.0)
        cand_validation = validate_longform_story(cand, question)
        if validation_rank(cand_validation) < validation_rank(best_validation):
            best, best_validation = cand, cand_validation
    # Track every beat-sheet/expansion attempt, including a discarded retry.
    best["_script_cost_usd"] = round(total_generation_cost, 4)
    best["_retention_validation"] = best_validation
    best_g = grade_script(best, cost_sink=cost_sink)
    if best_g is not None and not research_dossier:
        for _ in range(max(0, _SCRIPT_ELEVATE_PASSES)):
            if best_g["overall"] >= _SCRIPT_GATE_PASS:
                break
            log(f"Script grade {best_g['overall']}/100 (weakest: {best_g['weakest']}) — "
                f"revising the {best_g['weakest']} to lift it toward {_SCRIPT_GATE_PASS}…")
            cand = copy.deepcopy(best)
            cand, _rc = _revise_for_axis(cand, best_g["weakest"], best_g.get("notes", ""),
                                         cost_sink=cost_sink)
            cg = grade_script(cand, cost_sink=cost_sink)
            if cg and cg["overall"] > best_g["overall"]:
                best, best_g = cand, cg            # keep-best: a revision can only help
            else:
                break                              # no improvement → stop spending on this axis
    # Backstop: a hook-axis revision above can strip the subject the guard named in generate_script.
    # Re-assert zero-friction naming on the FINAL chosen draft (and track its cost here, tracked path).
    if research_dossier:
        _hc = 0.0
    else:
        best, _hc = _ensure_hook_names_subject(best, question, cost_sink=cost_sink)
    best["_retention_validation"] = validate_longform_story(best, question)
    if best_g:
        best["_grade"] = best_g
        sc = best_g["scores"]
        log("Script engagement grade: %d/100 — hook %d, story %d, ending %d, repetition %d, cadence %d"
            % (best_g["overall"], sc["hook"], sc["story"], sc["ending"], sc["repetition"], sc["cadence"]))
        # Real floor: the old "gate" kept the best draft unconditionally (it never blocked), so a
        # sub-threshold script still consumed full image/TTS/Veo spend with no signal. Now we MARK
        # it (→ surfaced as degraded at the end) and, if SCRIPT_GATE_HARD=1, abort before spending.
        if best_g["overall"] < _SCRIPT_GATE_FLOOR:
            best["_grade"]["below_floor"] = True
            log(f"⚠ Best script graded {best_g['overall']}/100 — BELOW the {_SCRIPT_GATE_FLOOR} "
                f"quality floor. Rendering anyway (set SCRIPT_GATE_HARD=1 to abort instead).")
            if _script_gate_hard():
                raise ValueError(
                    f"Script graded {best_g['overall']}/100, below the {_SCRIPT_GATE_FLOOR} floor "
                    f"(SCRIPT_GATE_HARD=1) — aborted before any image/TTS/Veo spend.")
        elif best_g["overall"] < _SCRIPT_GATE_PASS:
            log(f"Script graded {best_g['overall']}/100 — under the {_SCRIPT_GATE_PASS} target but "
                f"above the {_SCRIPT_GATE_FLOOR} floor; shipping as-is.")
    return best


_PREMISE_FILLER = re.compile(
    r"here'?s the (part|crazy part|wild part|best part|thing)|stays with you|wait for it|"
    r"here'?s what (happens|nobody)|but here'?s the (twist|kicker)|the craziest part", re.I)

# Only PREMISE-DELIVERY failures veto (these ARE the 22% causes). Opening-structure/length flags are
# ADVISORY — they inform the regen note but don't hard-veto, because grade_short (hook/pacing) and the
# render-side hook dry-run already cover them, and double-vetoing perma-blocks otherwise-good drafts.
_PREMISE_VETO_FLAGS = {"answers_generic_question", "payoff_obvious_or_weak",
                       "no_failed_workaround", "metaphor_over_budget"}

def build_premise_contract(question, cost_sink=None):
    """Gate -1: turn a Short's title/topic into a binding PremiseContract the script MUST deliver —
    the fix for 'novel question, ordinary answer'. Best-effort → None on failure (never blocks)."""
    try:
        r = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=700,
            system=("You design a binding PREMISE CONTRACT for a ~40s vertical Short whose title makes a "
                    "specific, novel promise. Pin the video to DELIVER THAT EXACT promise, not a generic "
                    "explainer of the topic. central_question = the ONE question the title implicitly asks. "
                    "concrete_mechanism = the physical trigger of the danger. failed_workaround = a "
                    "specific physical thing the character tries that FAILS. novel_payoff = a TRUE insight "
                    "a viewer CANNOT already guess from the title (if the honest answer is obvious, pick "
                    "the most surprising true angle). Every field ONE short concrete sentence. Return ONLY "
                    "JSON: {\"viewer_promise\":\"\",\"world_rule\":\"\",\"central_question\":\"\","
                    "\"concrete_mechanism\":\"\",\"bolt_objective\":\"\",\"failed_workaround\":\"\","
                    "\"novel_payoff\":\"\",\"first_consequence_deadline_ms\":2000,\"metaphor_budget\":2}."),
            messages=[{"role": "user", "content": f"Short title / topic: {question}"}])
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        o, _ = _parse_script_json(r.content[0].text)
        return o if isinstance(o, dict) and o.get("central_question") else None
    except Exception:
        return None


def grade_premise(script, contract, cost_sink=None, duration_sec=45):
    """Gate -1 veto: score how well the SCRIPT delivers the PremiseContract + hard boolean gates.
    Returns {'scores','flags','flags_fired','fired','overall','notes'} or None (best-effort)."""
    scenes = script.get("scenes", [])
    if not (isinstance(contract, dict) and contract) or len(scenes) < 2:
        return None
    words = sum(len(_s(s.get("narration")).split()) for s in scenes)
    est_sec = round(words / 2.64, 1)                       # measured TTS-1-HD rate
    lines = "\n".join(f'{i+1}. {_s(s.get("narration"))}' for i, s in enumerate(scenes))
    # over_length is RELATIVE to the requested duration (a flat 115-word cap permanently vetoed every
    # ~45s short — the density-driven ~17-scene count runs ~120 words by design). Fire only when clearly
    # long: >~3.0 words/requested-sec OR >8s past target.
    _word_ceiling = round(duration_sec * 3.0)
    det = {                                                # deterministic — don't trust the LLM for these
        "over_length": words > _word_ceiling or est_sec > duration_sec + 8,
        "empty_phrases": bool(_PREMISE_FILLER.search(" ".join(_s(s.get("narration")) for s in scenes))),
    }
    try:
        r = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=600,
            system=("You are a ruthless Shorts editor enforcing a PREMISE CONTRACT. Given the contract and "
                    "the script, score 0-10: premise_fidelity (does the video literally play out THIS "
                    "scenario end to end), early_consequence (a concrete pictureable consequence in the "
                    "first ~6 spoken words), payoff_novelty (ending NON-obvious AND stronger than the "
                    "opening), escalation (stakes visibly compound, not a list), workaround (a physical "
                    "workaround is tried and fails). Then set BOOLEAN flags: answers_generic_question "
                    "(TRUE if the script could be retitled to a generic 'what happens when...' and still "
                    "work unchanged — THE #1 failure), hook_repeats_question (lines 1-2 ask the same thing "
                    "or a second competing question opens), consequence_after_2s (no concrete consequence "
                    "by ~6 words), no_failed_workaround, payoff_obvious_or_weak (guessable from title or "
                    "weaker than the open), metaphor_over_budget (more metaphor call-backs than the "
                    "contract budget). Return ONLY JSON: {\"scores\":{\"premise_fidelity\":int,"
                    "\"early_consequence\":int,\"payoff_novelty\":int,\"escalation\":int,\"workaround\":int},"
                    "\"flags\":{\"answers_generic_question\":bool,\"hook_repeats_question\":bool,"
                    "\"consequence_after_2s\":bool,\"no_failed_workaround\":bool,"
                    "\"payoff_obvious_or_weak\":bool,\"metaphor_over_budget\":bool},"
                    "\"notes\":\"one sentence — the single biggest premise fix\"}."),
            messages=[{"role": "user",
                       "content": f"CONTRACT:\n{json.dumps(contract)}\n\nSCRIPT ({words} words, ~{est_sec}s):\n{lines}"}])
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        o, _ = _parse_script_json(r.content[0].text)
        if not (isinstance(o, dict) and isinstance(o.get("scores"), dict)):
            return None
        flags = {**(o.get("flags") or {}), **det}
        sc = o["scores"]
        wts = {"premise_fidelity": 2.0, "early_consequence": 1.5, "payoff_novelty": 1.5,
               "escalation": 1.0, "workaround": 0.7}
        tot = sum(wts[k] * int(sc.get(k, 0) or 0) for k in wts)
        overall = round(100 * tot / (10 * sum(wts.values())))
        fired = [k for k, v in flags.items() if v]
        veto = [k for k in fired if k in _PREMISE_VETO_FLAGS]        # premise-delivery failures only
        advisory = [k for k in fired if k not in _PREMISE_VETO_FLAGS]
        if veto:
            overall = min(overall, 55)                    # only a premise-delivery flag vetoes
        return {"scores": sc, "flags": flags, "flags_fired": bool(veto), "fired": fired,
                "veto": veto, "advisory": advisory, "overall": overall, "notes": o.get("notes", "")}
    except Exception:
        return None


_HOOK_DRYRUN_MIN = int(os.environ.get("HOOK_DRYRUN_MIN", "6"))
def _hook_dryrun_hard() -> bool:
    return os.environ.get("HOOK_DRYRUN_HARD", "0") == "1"

def _hook_dryrun(frame_png, promise, hook_text, cost_sink=None):
    """3-second hook dry-run (render-side companion to Gate -1): a vision check on the OPENING frame —
    does it read at a phone-sized, MUTED glance? Returns {'instant_read','reads','unclear'} or None."""
    try:
        with open(frame_png, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        r = _claude().messages.create(
            model=ANTHROPIC_MODEL, max_tokens=250,
            system=("You are a Shorts viewer scrolling fast, sound OFF, on a phone — you get ONE glance at "
                    "the opening frame. Judge ONLY this frame. Score instant_read 0-10: at a muted glance, "
                    "can you tell WHAT this is about AND that something is at stake? Reward a clear subject + "
                    "a visible tension/threat/action; penalize pretty-but-ambiguous, a generic medical/diagram "
                    "look, or needing to read fine print. Return ONLY JSON: {\"instant_read\":int,"
                    "\"unclear\":\"the one thing that doesn't read\"}."),
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": f"Intended promise: {promise}\nSpoken hook: {hook_text}\n"
                                         "Does the FRAME convey it at a glance, muted?"}]}])
        if cost_sink is not None:
            cost_sink.append(_msg_cost(r.usage))
        o, _ = _parse_script_json(r.content[0].text)
        if not isinstance(o, dict):
            return None
        s = int(o.get("instant_read", 0) or 0)
        return {"instant_read": s, "reads": s >= _HOOK_DRYRUN_MIN, "unclear": _s(o.get("unclear"))}
    except Exception:
        return None


def _premise_regen_note(contract, pg):
    """Forceful regen instruction quoting the contract's mechanism/payoff and banning the biology drift —
    targets the SPECIFIC premise flags the last draft fired."""
    g = lambda k: _s(contract.get(k))
    return ("The previous draft FAILED the premise contract [" + ",".join(pg.get("fired", [])) + "]. "
            "Do NOT explain generic real-world biology/physiology as the answer — that is the failure. "
            "Play out THIS fictional scenario's OWN mechanism and land its exact payoff:\n"
            f"- World rule: {g('world_rule')}\n"
            f"- Mechanism that triggers the danger: {g('concrete_mechanism')}\n"
            f"- A physical workaround that must be TRIED and FAIL on screen: {g('failed_workaround')}\n"
            f"- The EXACT non-obvious payoff to end on (must NOT be guessable from the title): {g('novel_payoff')}\n"
            "Pose ONE question in line 1 paired IMMEDIATELY with a concrete visible consequence; never "
            "repeat the question; keep it under ~100 words. Grader's note: " + (pg.get("notes") or ""))


def generate_graded_short(question, duration_sec, style, image_guidance, series,
                          cost_sink=None, log=lambda m: None, short_template="auto",
                          operator_direction: str = ""):
    """Social gate (the shorts equivalent of generate_graded_script): generate → enforce_conceit →
    grade_short, and regenerate a weak draft (targeting the grader's 'biggest fix') up to
    _SCRIPT_GATE_RETRIES, keeping the best by grade_short overall. Returns (script, short_grade).
    Best-effort — a grader failure accepts the draft so a render never blocks."""
    best, best_g = None, None
    # Gate -1: pin the short to its own promise BEFORE any generation, so the script delivers the exact
    # scenario the title sells (not a generic explainer decorated with the metaphor).
    contract = build_premise_contract(question, cost_sink=cost_sink)
    if contract:
        log(f"Premise contract: {_s(contract.get('central_question'))} → payoff: {_s(contract.get('novel_payoff'))}")
    # Premise failures get the bigger budget — escaping the generic-biology attractor takes >1 re-roll.
    attempts = 1 + max(_SCRIPT_GATE_RETRIES, (_PREMISE_GATE_RETRIES if contract else 0))
    last_pg = None
    for i in range(attempts):
        note = ""
        if i > 0:
            if contract and last_pg and last_pg.get("flags_fired"):
                note = _premise_regen_note(contract, last_pg)   # forceful, contract-quoting
                log(f"Regenerating to fulfil the premise (attempt {i+1}/{attempts})…")
            elif best_g:
                note = "The previous short underperformed — fix this FIRST: " + (best_g.get("notes") or "")
                log(f"Short grade {best_g.get('overall')}/100 — regenerating to improve…")
        cand = generate_script(question, duration_sec, style, image_guidance=image_guidance,
                               video_format="social", series=series, improve_note=note,
                               short_template=short_template, operator_direction=operator_direction,
                               premise_contract=contract)
        try:
            cand, _conceit, _cc = enforce_conceit(cand, question, cost_sink=cost_sink)
            if _conceit and i == 0:
                log(f"Central conceit enforced: {_conceit}")
        except Exception:
            _conceit = ""
        # State-once pass on social too (long-form already runs it): kills the "same reveal
        # repeated 3-5×" that makes a short feel like a fact-list (e.g. "the bone glowed" ×5).
        try:
            _scn, _dc = _dedupe_narration(cand.get("scenes", []),
                                          [], _conceit or _s(cand.get("throughline", "")))
            cand["scenes"] = _scn
            if cost_sink is not None and _dc:
                cost_sink.append(_dc)
        except Exception:
            pass
        g = grade_short(cand, cost_sink=cost_sink)
        if g is None:
            best = best or cand
            break
        # Gate -1 veto: a premise failure caps the short's grade so the existing regen loop re-rolls it
        # targeting the promise (not just hook/pacing). Rides the same _SCRIPT_GATE_RETRIES budget.
        pg = grade_premise(cand, contract, cost_sink=cost_sink, duration_sec=duration_sec) if contract else None
        cand["_premise"] = pg
        last_pg = pg
        if pg and pg.get("flags_fired"):
            g["overall"] = min(g.get("overall", 0), 55)
            g["notes"] = ("PREMISE [" + ",".join(pg.get("fired", [])) + "]: " + (pg.get("notes") or "")
                          + " | " + (g.get("notes") or ""))
            log("  ⚠ premise gate: " + ", ".join(pg.get("fired", [])) + " — regenerating to fulfil the promise")
        if best_g is None or (g.get("overall", 0) > best_g.get("overall", 0)):
            best, best_g = cand, g
        if (best_g.get("overall", 0) if best_g else 0) >= _SHORT_GATE_PASS:
            break
    if best_g:
        sc = best_g.get("scores", {})
        log("Short self-grade: %s/100 — hook %s, pacing %s, loop %s, rewatch %s/10"
            % (best_g.get("overall", "?"), sc.get("first_second_hook", "?"), sc.get("pacing", "?"),
               sc.get("loop_ending", "?"), sc.get("rewatch_potential", "?")))
        if best_g.get("notes"):
            log(f"  fix: {best_g['notes']}")
        # Symmetric hard floor with the long-form gate: social is the cheaper-per-clip but
        # most-run format (i2v defaults ON), so SCRIPT_GATE_HARD must protect it too.
        if best_g.get("overall", 0) < _SHORT_GATE_FLOOR:
            best_g["below_floor"] = True
            log(f"⚠ Best short graded {best_g.get('overall')}/100 — BELOW the {_SHORT_GATE_FLOOR} "
                f"floor. Rendering anyway (set SCRIPT_GATE_HARD=1 to abort instead).")
            if _script_gate_hard():
                raise ValueError(
                    f"Short graded {best_g.get('overall')}/100, below the {_SHORT_GATE_FLOOR} floor "
                    f"(SCRIPT_GATE_HARD=1) — aborted before any image/TTS/Veo spend.")
    if best is not None and contract:
        best["_premise_contract"] = contract      # surfaced for the render-side hook dry-run
    return best, best_g


def _overlay_opening_thumbnail(video_path: str, thumb_path: str, hold: float = 1.0) -> bool:
    """Burn the thumbnail onto the FIRST `hold` seconds of the video (audio untouched), so a Short's
    opening frame IS the thumbnail — YouTube Shorts can't take a custom thumbnail, so the feed/grid
    sample a frame. The spoken hook plays UNDER the card (no silent dead-air), runtime is preserved.
    In-place, best-effort — returns False (and leaves the video untouched) on any failure."""
    import subprocess
    if not (thumb_path and os.path.exists(thumb_path) and os.path.exists(video_path)):
        return False
    try:
        wh = subprocess.run([_ffprobe_bin(), "-v", "quiet", "-select_streams", "v:0",
                             "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path],
                            capture_output=True, text=True).stdout.strip()
        w, h = [int(x) for x in wh.split(",")[:2]]
    except Exception:
        return False
    tmp = video_path + ".thumbfirst.mp4"
    cmd = [_ffmpeg_bin(), "-y", "-loglevel", "error", "-i", video_path, "-i", thumb_path,
           "-filter_complex",
           f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}[t];"
           f"[0:v][t]overlay=0:0:enable='lte(t,{hold})'[v]",
           "-map", "[v]", "-map", "0:a?", "-c:a", "copy", "-c:v", "libx264", "-preset", "medium",
           "-crf", "19", "-pix_fmt", "yuv420p", tmp]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and os.path.exists(tmp):
            os.replace(tmp, video_path)
            return True
    except Exception:
        pass
    try:
        os.remove(tmp)
    except OSError:
        pass
    return False


# Distilled from a hand-rewritten reference script (H. pylori / Barry Marshall) that scored far
# above anything the planner had produced. Each rule below fixes a defect that was MEASURED in
# generated output, not one that was theorised:
#   - "Cast: Alex leads 0/15 scenes; Bolt assists in 15/15" — the human-led format produced zero
#     human-led scenes and put the mascot in every frame.
#   - story_engine measured 1.0 sentences per scene, 0% short lines, 6.7% long ones.
#   - the planner opened on exposition and postponed its own title promise past the halfway mark.
_STORY_LED_DNA = (
    "\nSTORY-LED DISCIPLINE — these override any conflicting guidance above.\n"
    "1. HUMANS CARRY THE STORY. Real named people own the discovery, the rejection, the risk and "
    "the cure. Bolt appears in AT MOST a third of scenes and only to demonstrate a mechanism or "
    "react at a decision — never as the protagonist, never in place of physical evidence, and "
    "never standing in for a real person.\n"
    "2. FRAME ONE IS AN IRREVERSIBLE ACTION, NOT A SUMMARY. Open inside the strangest moment with "
    "something already happening, and deliver the title's promise within the first ~8 seconds "
    "rather than teasing it to the end. An early payoff does not end the video; it resets the "
    "question to WHY it happened and whether it proved anything.\n"
    "3. RECURRING PHYSICAL OBJECTS CARRY THE EVIDENCE. Choose 3-5 concrete objects that actually "
    "appear in the account and pass causality between them in a fixed chain, then close the loop by "
    "returning to the first object. Decorative props that carry no evidence — ticking clocks, "
    "generic glowing orbs — are forbidden; if an object does not change a character's decision, cut "
    "it.\n"
    "4. EVERY ANSWER MUST CREATE THE NEXT QUESTION. Never list consequences. Each beat resolves the "
    "previous question and opens a sharper one, and the new question must open before the old one "
    "fully closes.\n"
    "5. THE VIEWER MUST ENTER EARLY. Within the first ~20 seconds, show the ordinary experience the "
    "audience already recognises, and return to that person at the end so the payoff is theirs.\n"
    "6. END LARGER THAN THE FACT, AND STOP. The closing beat reframes what the discovery means for "
    "ordinary people; an award or a statistic is validation, not the ending. No subscribe request "
    "and no dead-air outro — finish on the callback image.\n"
    "7. NEVER OVERCLAIM TO SHARPEN A STORY. State precisely what the evidence showed and keep the "
    "caveat that complicates it. A dramatic sentence that is slightly wrong is a defect, not a "
    "trade-off.\n"
)


# The same doctrine as _STORY_LED_DNA, compressed for a Short. Not a weaker version — a Short has
# less room, so the rules that survive are the ones that decide whether a viewer stays: who carries
# the story, what is on screen at t=0, and whether each answer opens the next question.
_STORY_LED_DNA_SHORT = (
    "\nSTORY-LED DISCIPLINE (compressed long-form doctrine — overrides conflicts above).\n"
    "1. A real person carries it, not the mascot. Bolt appears in at most a third of scenes, only to "
    "demonstrate a mechanism or react at a decision, and never replaces the physical evidence.\n"
    "2. Frame one is an action already happening, not a summary of what is coming. Pay the title's "
    "promise off almost immediately, then reset the question to WHY it happened.\n"
    "3. Pick 2-3 concrete objects that actually appear in the account and pass causality between "
    "them; return to the first one at the end to close the loop. No decorative props — if an object "
    "does not change a decision, cut it.\n"
    "4. Each answer opens a sharper question, and the new one opens before the old one closes. "
    "Never a list.\n"
    "5. Show the ordinary experience the viewer recognises early, and give the payoff back to that "
    "person at the end.\n"
    "6. Never overclaim to sharpen a line: state exactly what the evidence showed and keep the "
    "caveat that complicates it.\n"
)


def _story_role_block(format_name: str) -> str:
    """Name the beat roles and their runtime bands so the planner can emit `_role` per scene.

    Without this the model has no vocabulary to label beats with, `_role` comes back empty, and
    every structural gate in story_engine reports "beat roles absent — could not run". The bands
    are stated as percentages of runtime because that is exactly how they are measured.
    """
    try:
        import story_engine
        fmt = story_engine.get(format_name)
    except Exception:
        return ""
    if not getattr(fmt, "bands", None):
        return ""
    rows = ", ".join(f"{role} ({lo:.0f}-{hi:.0f}%)" for role, (lo, hi) in fmt.bands.items())
    required = ", ".join(fmt.required)
    return (
        "\nSTORY FORMAT — BEAT ROLES. Tag every scene with \"_role\", using EXACTLY these names and "
        "placing each within its share of the runtime: " + rows + ". "
        "These are required and must all appear: " + required + ". "
        "Order them as listed; a role may span more than one scene, and roles that do not fit the "
        "topic may be omitted, but never invent a role name outside this list."
    )


def _planned_words_for(duration_sec: float, n_scenes: int) -> int:
    """Words that fit `duration_sec`, using the same model the runtime contract validates against.

    Mirrors runtime_planner: speech at PLANNED_TTS_WORDS_PER_SECOND, minus the inter-scene pauses
    and an allowance for sentence punctuation, so the script is written to the budget it will later
    be measured by rather than to a more generous one.
    """
    from runtime_planner import DEFAULT_SCENE_PAUSE_SECONDS, DEFAULT_WORDS_PER_SECOND

    pause_budget = max(0, int(n_scenes) - 1) * DEFAULT_SCENE_PAUSE_SECONDS
    punctuation_budget = max(0, int(n_scenes)) * 0.28      # ~2 sentence stops per scene
    speech_seconds = max(1.0, float(duration_sec) - pause_budget - punctuation_budget)
    return max(20, int(speech_seconds * DEFAULT_WORDS_PER_SECOND))


def _repair_claim_phrases(script: dict, log=lambda message: None) -> int:
    """Re-bind each claim reference to wording that survives in the final narration.

    validate_claim_joins requires `narration_phrase` to be an exact substring of the scene's
    narration. The planner binds those phrases, and then the FACT-CHECK PASS REWRITES THE
    NARRATION — its own log from the run that exposed this reads "removed 'completely'" and
    "'Over ninety percent' aligned to 'more than 90%'". Both are correct edits, and both silently
    invalidate a binding made against the older wording.

    So the phrase is re-derived from whatever the narration now says: the sentence carrying the
    claim is located by content overlap, and a short exact run of its words becomes the binding. A
    reference whose claim no longer appears anywhere in the scene is dropped rather than repointed
    — if the fact-check removed the assertion, the citation should go with it.
    """
    repaired = dropped = 0
    for scene in script.get("scenes") or []:
        narration = _s(scene.get("narration")).strip()
        refs = scene.get("claim_refs")
        if not isinstance(refs, list) or not refs:
            continue
        haystack = narration.casefold()
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", narration) if s.strip()]
        kept = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            phrase = _s(ref.get("narration_phrase")).strip()
            if phrase and phrase.casefold() in haystack:
                kept.append(ref)
                continue
            wanted = _content_tokens(phrase) or _content_tokens(_s(ref.get("claim_id")))
            best, best_score = "", 0.0
            for sentence in sentences:
                if not wanted:
                    break
                score = len(wanted & _content_tokens(sentence)) / len(wanted)
                if score > best_score:
                    best, best_score = sentence, score
            if best and best_score >= 0.34:
                words = best.split()
                ref["narration_phrase_model"] = phrase
                ref["narration_phrase"] = " ".join(words[:min(6, len(words))])
                kept.append(ref)
                repaired += 1
            else:
                dropped += 1
        scene["claim_refs"] = kept
        if not kept:
            scene["evidence_id"] = ""      # an unclaimed scene must not carry a dangling join
    if repaired or dropped:
        log(f"Claim phrases: re-bound {repaired} to the fact-checked narration"
            + (f", dropped {dropped} whose claim no longer appears" if dropped else ""))
    return repaired


def _repair_anchor_phrases(script: dict, log=lambda message: None) -> int:
    """Make every visual beat's anchor_phrase an exact substring of its own narration.

    Four separate gates depend on this one model-authored field being locatable verbatim: the
    evidence-state compiler, the measured-audio timing report, the motion plan's semantic-alignment
    ratio, and the final motion_sync_ratio. The model writes an approximation — it paraphrases,
    reorders, or quotes wording that survived only until the fact-check rewrote the line — and each
    of those gates then fails for what is really the same reason.

    The narration is authoritative and already on hand, so the phrase is derived from it rather than
    trusted: any anchor not found verbatim is replaced with the opening words of the clause it was
    closest to. Beat zero is pinned to the narration's own opening words, because the shot compiler
    requires the first shot's span to begin within 1.0s of the scene start and a first anchor taken
    from mid-sentence can never satisfy that.

    Returns the number of anchors rewritten.
    """
    from longform_shots import _derived_visual_beats

    repaired = 0
    for scene in script.get("scenes") or []:
        narration = _s(scene.get("narration")).strip()
        beats = scene.get("visual_beats")
        if not narration or not isinstance(beats, list) or not beats:
            continue
        haystack = narration.casefold()
        fallbacks = [_s(b.get("anchor_phrase")) for b in _derived_visual_beats(scene)]
        opening = " ".join(narration.split()[:5])
        for index, beat in enumerate(beats):
            if not isinstance(beat, dict):
                continue
            anchor = _s(beat.get("anchor_phrase")).strip()
            wanted = opening if index == 0 else anchor
            if wanted and wanted.casefold() in haystack and (index or wanted == opening):
                if beat.get("anchor_phrase") != wanted:
                    # Keep what the model wrote whenever we overwrite it, on every path — an
                    # anchor that silently changed is impossible to audit afterwards.
                    beat["anchor_phrase_model"] = anchor
                    beat["anchor_phrase"] = wanted
                    repaired += 1
                continue
            replacement = ""
            if index < len(fallbacks) and fallbacks[index].casefold() in haystack:
                replacement = fallbacks[index]
            elif fallbacks and fallbacks[0].casefold() in haystack:
                replacement = fallbacks[0]
            else:
                replacement = opening
            if replacement and replacement != anchor:
                beat["anchor_phrase_model"] = anchor
                beat["anchor_phrase"] = replacement
                repaired += 1
    if repaired:
        log(f"Anchor phrases: rewrote {repaired} to exact narration substrings")
    return repaired


def _review_story_structure(script: dict, requested_format: str, video_format: str, log) -> dict:
    """Measure narration against its story format's structure gates and REPORT ONLY.

    Returns the raw report so it lands in the persisted script, and logs a short summary. Never
    raises and never blocks: story_engine is stdlib-only and provider-free, so the cost of being
    wrong here is a misleading log line, but the cost of gating on an unproven band would be a
    dead run on a topic that is fine.

    Roles are the input the pipeline does not yet emit — without a per-beat ``_role`` the
    structural checks cannot run at all and say so, which is the honest result rather than a pass.
    """
    try:
        import story_engine
    except Exception as exc:                                  # module absent → silently skip
        return {"available": False, "reason": str(exc)}
    # This API and story_engine name the default lane differently. The lookup would land on the
    # right format anyway via its unknown-name fallback, but that path exists to survive typos —
    # leaning on it would silently change behaviour the day a "standard_explainer" format is added.
    alias = {"standard_explainer": "default_explainer"}
    requested = alias.get((requested_format or "").strip().lower(), requested_format or "")
    try:
        fmt = story_engine.resolve(requested, video_format=video_format)
        report = story_engine.check(script, fmt)
        failures = report.get("failures") or []
        reviews = report.get("requires_review") or []
        verdict = "clean" if report.get("passed") else f"{len(failures)} would-fail"
        log(f"Story structure [{fmt.name}] — review only: {verdict}"
            + (f", {len(reviews)} for judgement" if reviews else ""))
        for item in failures[:4]:
            log(f"  ⚠ {item}")
        for item in reviews[:3]:
            log(f"  ? {item}")
        return report
    except Exception as exc:
        log(f"Story structure review skipped: {type(exc).__name__}: {exc}")
        return {"available": True, "error": str(exc)}


def run_explainer_pipeline(
    question: str,
    output_dir: str,
    duration_sec: int = 90,
    voice: str = "echo",
    style: str = "engaging and scientific",
    image_guidance: str = "",
    fact_check: bool = True,
    video_format: str = "landscape",
    speech_bubble: bool = False,
    bg_music_path: str | None = None,
    max_cost_usd: float = MAX_COST_USD,
    resume: bool = False,
    i2v: bool | None = None,
    motion_mode: str | None = None,
    series: str = "",
    short_template: str = "auto",   # social only: auto | explainer | simulation
    operator_direction: str = "",   # optional per-video/channel creative direction (subordinate to rules)
    story_format: str = "standard_explainer",
    controlled_pilot: bool = False,
    pilot_batch_id: str = "",
    pilot_kind: str = "",
    pilot_policy: dict | None = None,
    progress_cb=None,
) -> dict:

    def log(msg: str):
        if progress_cb:
            progress_cb(msg)

    output_dir = os.path.abspath(output_dir)   # absolute so ffmpeg concat lists never double the path
    os.makedirs(output_dir, exist_ok=True)
    fmt = FORMATS.get(video_format, FORMATS["landscape"])
    vw, vh, img_size, cap_mode = fmt["w"], fmt["h"], fmt["img_size"], fmt["captions"]
    resolved_motion_mode = (
        "social" if video_format == "social"
        else ("stills" if motion_mode is None and i2v is None
              else normalize_motion_mode(motion_mode, legacy_i2v=i2v))
    )
    # Social retains its existing automatic motion policy. Long-form uses the explicit PR4 modes.
    i2v_on = ((i2v if i2v is not None else True) if video_format == "social"
              else resolved_motion_mode != "stills") and bool(I2V_PROVIDER)
    threshold_profile = load_threshold_profile() if video_format != "social" else {}
    pilot_request = None
    if controlled_pilot:
        pilot_request = {
            "question": question,
            "duration_sec": duration_sec,
            "voice": voice,
            "style": style,
            "image_guidance": image_guidance,
            "fact_check": fact_check,
            "video_format": video_format,
            "speech_bubble": speech_bubble,
            "i2v": i2v,
            "motion_mode": resolved_motion_mode,
            "series": series,
            "short_template": short_template,
            "operator_direction": operator_direction,
            "story_format": story_format,
            "controlled_pilot": controlled_pilot,
            "pilot_batch_id": pilot_batch_id,
            "pilot_kind": pilot_kind,
            "pilot_policy": pilot_policy or {},
        }
        validate_pilot_request(pilot_request)
        try:
            from durable_execution import current as _durable_current
            if _durable_current() is None:
                raise ControlledPilotError(
                    "Controlled pilots require durable Postgres/Blob execution.")
        except ImportError as exc:
            raise ControlledPilotError(
                "Controlled pilots require durable Postgres/Blob execution.") from exc
    generation_manifest_path = os.path.join(output_dir, "generation_manifest.json")
    generation_manifest = _generation_manifest_payload(
        video_format=video_format, motion_mode=resolved_motion_mode,
        threshold_profile=threshold_profile)
    _write_generation_manifest(generation_manifest_path, generation_manifest)
    pilot_control_path = None
    pilot_script_path = None
    pilot_cost_report_path = None
    if controlled_pilot:
        pilot_control_path = os.path.join(output_dir, "pilot_control.json")
        pilot_script_path = os.path.join(output_dir, "pilot_script.json")
        pilot_cost_report_path = os.path.join(output_dir, "pilot_cost_report.json")
        pilot_control = {
            "schema_version": 1,
            "status": "rendering",
            "pilot_batch_id": pilot_batch_id,
            "pilot_kind": pilot_kind,
            "request": pilot_request,
            "request_sha256": hashlib.sha256(json.dumps(
                pilot_request, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False).encode("utf-8")).hexdigest(),
            "threshold_profile": threshold_profile,
            "threshold_profile_sha256": hashlib.sha256(json.dumps(
                threshold_profile, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False).encode("utf-8")).hexdigest(),
            "manual_checkpoint_edits": [],
            "manual_asset_replacements": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_generation_manifest(pilot_control_path, pilot_control)
        generation_manifest["controlled_pilot"] = {
            "batch_id": pilot_batch_id,
            "pilot_kind": pilot_kind,
            "policy": frozen_pilot_policy(),
            "request_sha256": pilot_control["request_sha256"],
            "threshold_profile_sha256": pilot_control["threshold_profile_sha256"],
        }
        _write_generation_manifest(generation_manifest_path, generation_manifest)
    # Landscape + speech_bubble → Bolt "talks" via a synced phrase bubble (replaces headline).
    if video_format == "landscape" and speech_bubble:
        cap_mode = "bubble"
    log(f"Format: {video_format} ({vw}×{vh}, captions={cap_mode})")
    if video_format != "social":
        log(f"Motion treatment: {resolved_motion_mode}")
        if resolved_motion_mode != "stills" and not I2V_PROVIDER:
            raise ValueError(
                "Standard/Full Motion requires I2V_PROVIDER. Configure a motion provider or choose Stills.")
    aux_costs: list[float] = []   # Claude calls outside the script (grade, description) — were uncounted

    # ── RESUME: if a checkpoint exists, reuse the script + already-paid scene assets ──
    state_path = os.path.join(output_dir, "_state.json")
    resumed = False
    asset_resume_allowed = False
    research_dossier: dict = {}
    claim_validation: dict | None = None
    research_report_path = None
    claim_report_path = None
    audio_timing_report_path = None
    evidence_plan_path = None
    evidence_validation_path = None
    continuity_pack_path = None
    motion_report_path = None
    opening_freeze_path = None
    animatic_report_path = None
    animatic_preview_path = None
    rendered_contract_path = None
    rendered_contact_sheet_path = None
    human_review_path = None
    story_format_review_path = None
    diagnostic_preview_path = None
    evidence_plan: dict = {}
    evidence_validation: dict | None = None
    motion_plan: dict = {}
    opening_freeze: dict = {}
    animatic_report: dict = {}
    rendered_contract: dict = {}
    frozen_opening_segments: dict[int, str] = {}
    short_grade = None
    retention_report_path = None
    retention_json_path = None
    readiness_report_path = None
    readiness_json_path = None
    first_minute_preview_path = None
    retention_validation = None
    preview_state: dict = {}
    readiness = None
    if resume and os.path.exists(state_path):
        try:
            with open(state_path) as _sf:
                _st = json.load(_sf)
            script = _st["script"]
            style_mode = _st.get("style_mode", "educational")
            scenes = script.get("scenes", [])
            research_dossier = script.get("_research_dossier") or {}
            if video_format != "social" and not validate_research_dossier(research_dossier).get("passed"):
                raise ValueError("Checkpoint predates the sourced research contract")
            if video_format != "social":
                checkpoint_evidence = script.get("_evidence_plan") or {}
                checkpoint_evidence_validation = validate_evidence_plan(checkpoint_evidence)
                if (checkpoint_evidence.get("version") != 1
                        or not checkpoint_evidence_validation.get("passed")):
                    raise ValueError("Checkpoint predates the evidence-asset contract")
            short_grade = _st.get("short_grade")
            resumed = True
            asset_resume_allowed = True
            done = len([s for i, s in enumerate(scenes)
                        if os.path.exists(os.path.join(output_dir, "images", f"scene_{i:02d}.jpg"))])
            log(f"▶ RESUMING from checkpoint — {len(scenes)} scenes, {done} images already on disk (won't re-pay).")
        except Exception as exc:
            log(f"⚠ Resume checkpoint unreadable ({type(exc).__name__}) — starting fresh")
            resumed = False

    # Pre-spend cost guard: refuse absurd jobs BEFORE the (paid) script call.
    rough_scenes = scene_count_for(duration_sec, video_format)
    rough_est = estimate_cost(rough_scenes, host_count=rough_scenes)  # assume all host = upper bound
    if rough_est > max_cost_usd:
        raise ValueError(
            f"Estimated cost ~${rough_est:.2f} exceeds the ${max_cost_usd:.2f} cap before "
            f"generation started. Lower duration_sec or raise max_cost_usd."
        )

    # 1. Script (skipped entirely on resume — the checkpoint already holds it)
    if not resumed:
        log("stage:Writing script...")
        if image_guidance.strip():
            log(f"Theme/setting steer: {image_guidance.strip()}")
        if video_format == "social":
            # Social gate: generate → enforce conceit → grade_short, regenerate weak drafts, keep best.
            script, short_grade = generate_graded_short(question, duration_sec, style, image_guidance,
                                                        series, cost_sink=aux_costs, log=log,
                                                        short_template=short_template,
                                                        operator_direction=operator_direction)
        else:
            log("stage:Researching sourced claims...")
            research_dossier = generate_research_dossier(
                question, cost_sink=aux_costs, log=log)
            # Engagement gate: grade hook/story/ending + regenerate weak drafts BEFORE we spend a
            # cent on images/TTS/render. Best-effort — a grader failure accepts the draft.
            script = generate_graded_script(question, duration_sec, style, image_guidance,
                                            video_format, series, cost_sink=aux_costs, log=log,
                                            operator_direction=operator_direction,
                                            story_format=story_format,
                                            research_dossier=research_dossier)
        scenes = script.get("scenes", [])
        style_mode = (_s(script.get("style_mode")) or "educational").strip().lower()
        log(f"Script ready: {len(scenes)} scenes — \"{script.get('title', '')}\"")
        log(f"Style mode: {style_mode}")

        # 1b. Fact-check pass — verify the science, correct errors before rendering.
        if fact_check and scenes:
            log("stage:Fact-checking script...")
            script, fc_notes, fc_cost = factcheck_script(script, question, research_dossier)
            script["_script_cost_usd"] = round(script.get("_script_cost_usd", 0.0) + fc_cost, 4)
            if fc_notes:
                log(f"Fact-check: {len(fc_notes)} correction(s) applied")
                for nft in fc_notes[:6]:
                    log(f"  • {nft}")
            else:
                log("Fact-check: no corrections needed ✓")
            scenes = script.get("scenes", [])
        # Story-structure gates, REVIEW-ONLY. Measured after fact-check because that pass rewrites
        # narration, and cadence/anchor measurements are only meaningful on the final wording.
        # Deliberately gates nothing yet: the bands need to be trusted against real topics before
        # they are allowed to stop a run. Promote to blocking behind an env flag once they are.
        # Both bindings are made against pre-fact-check wording and are re-derived here, after the
        # last pass that can rewrite narration and before anything validates them against it.
        if video_format != "social":
            _repair_claim_phrases(script, log)
            _repair_anchor_phrases(script, log)
        script["_story_engine"] = _review_story_structure(script, story_format, video_format, log)
        if video_format != "social":
            claim_validation = validate_claim_joins(script, research_dossier)
            script["_claim_validation"] = claim_validation
            if not claim_validation.get("passed"):
                raise ValueError(
                    "Claim ledger failed after script/fact-check before asset spend: "
                    + "; ".join(item["message"] for item in claim_validation.get("errors", [])[:6])
                )
        n_host = sum(1 for s in scenes if s.get("mascot_present"))
        n_human = sum(1 for s in scenes if s.get("human_present"))
        log(f"Cast: {HUMAN_NAME} leads {n_human}/{len(scenes)} scenes; "
            f"{MASCOT_NAME} assists in {n_host}/{len(scenes)} scenes")
        for _w in _slop_warnings(scenes):
            log(f"⚠ slop-check: {_w}")

        # (Social conceit-enforcement + grade_short now run inside generate_graded_short above,
        #  which regenerates a weak short before any render spend. fact-check ran after, on the winner.)

        # 1d. CHECKPOINT: persist the plan so a crash/reload can resume without re-paying. Write
        # ATOMICALLY (tmp + os.replace): a SIGTERM mid-dump (RELOAD=1 kills the worker on any .py
        # save) would otherwise truncate _state.json → on resume json.load raises → resumed=False →
        # the whole paid script+gate is regenerated, defeating the checkpoint.
        try:
            _tmp = state_path + ".tmp"
            with open(_tmp, "w") as _sf:
                json.dump({"script": script, "style_mode": style_mode,
                           "short_grade": short_grade, "video_format": video_format}, _sf)
            os.replace(_tmp, state_path)
        except OSError:
            pass

    # Runtime is a pre-spend contract. Fit/reject the final fact-checked narration now, before
    # any TTS or image provider call. Re-check resumed checkpoints too so an older overlong plan
    # cannot bypass the new contract.
    if video_format != "social":
        log("stage:Enforcing requested runtime...")
        script = _enforce_requested_runtime(
            script, duration_sec, cost_sink=aux_costs, log=log)
        scenes = script.get("scenes", [])
        claim_validation = validate_claim_joins(script, research_dossier)
        script["_claim_validation"] = claim_validation
        if not claim_validation.get("passed"):
            raise ValueError(
                "Runtime fit broke the sourced claim joins before TTS/image spend: "
                + "; ".join(item["message"] for item in claim_validation.get("errors", [])[:6])
            )
        try:
            _tmp = state_path + ".tmp"
            with open(_tmp, "w") as _sf:
                json.dump({"script": script, "style_mode": style_mode,
                           "short_grade": short_grade, "video_format": video_format}, _sf)
            os.replace(_tmp, state_path)
        except OSError:
            pass
        _rp = script.get("_runtime_plan") or {}
        log(
            "Runtime contract: PASS — %(estimated_seconds).1fs estimated for "
            "%(target_seconds).0fs target (%(word_count)d words)" % _rp
        )

    # Objective long-form gate: inspect the persisted story roles and narrative-debt ledger before
    # any image/TTS spend. The planner already received one automatic retry in
    # generate_graded_script; a remaining error is therefore a genuine structural failure.
    if video_format != "social":
        retention_validation = validate_longform_story(script, question)
        script["_retention_validation"] = retention_validation
        retention_report_path = write_retention_report(
            retention_validation, script.get("_story_contract") or {}, output_dir)
        retention_json_path = os.path.join(output_dir, "retention_report.json")
        log("Long-form retention contract: %s %s/100 — %d blocking, %d warning(s)"
            % ("PASS" if retention_validation.get("passed") else "FAIL",
               retention_validation.get("score", 0),
               len(retention_validation.get("errors") or []),
               len(retention_validation.get("warnings") or [])))
        if not retention_validation.get("passed"):
            for issue in (retention_validation.get("errors") or [])[:6]:
                log(f"  ✗ [{issue.get('code')}] {issue.get('message')}")
            if _longform_retention_hard():
                raise ValueError(
                    "Long-form retention contract failed before image/TTS spend: "
                    + "; ".join(x.get("message", "") for x in retention_validation.get("errors", [])[:6])
                )

        if controlled_pilot:
            effective_story = validate_effective_story_format(script, pilot_request or {})
            if not effective_story["passed"]:
                with open(pilot_control_path, encoding="utf-8") as handle:
                    pilot_control = json.load(handle)
                pilot_control.update({
                    "status": "failed_before_visual_spend",
                    "effective_story_format": effective_story,
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                })
                _write_generation_manifest(pilot_control_path, pilot_control)
                raise ControlledPilotError("; ".join(effective_story["errors"]))

        fallback = story_format_fallback_payload(script)
        if (fallback["requested"] == "evidence_led_mystery"
                and fallback["effective"] == "standard_explainer"):
            story_format_review_path = os.path.join(output_dir, "story_format_review.json")
            review = None
            if os.path.isfile(story_format_review_path):
                try:
                    with open(story_format_review_path, encoding="utf-8") as handle:
                        review = json.load(handle)
                except (OSError, ValueError, TypeError):
                    review = None
            if review and review.get("decision") == "reject":
                raise ValueError("Operator rejected the Mystery-to-Standard fallback.")
            if not validate_story_format_review(review or {}, script):
                create_story_format_review(script, story_format_review_path)
                raise StoryFormatAcknowledgementRequired(
                    "Evidence-led Mystery cannot be honored for this plan. Proposed Standard "
                    f"fallback requires acknowledgement before visual spending: {fallback['reason']}")
            log(f"Story-format fallback acknowledged: Mystery → Standard — {fallback['reason']}")

        research_report_path = os.path.join(output_dir, "research_dossier.json")
        claim_report_path = os.path.join(output_dir, "claim_ledger_report.json")
        with open(research_report_path, "w") as handle:
            json.dump(research_dossier, handle, indent=2, ensure_ascii=False)
        with open(claim_report_path, "w") as handle:
            json.dump(claim_validation or {}, handle, indent=2, ensure_ascii=False)

        _repair_anchor_phrases(script, log)
        evidence_plan = compile_evidence_plan(script)
        evidence_validation = evidence_plan.get("validation") or {}
        script["_evidence_plan"] = evidence_plan
        if not evidence_validation.get("passed"):
            raise ValueError(
                "Evidence-state plan failed before TTS/image spend: "
                + "; ".join(item["message"] for item in evidence_validation.get("errors", [])[:8])
            )
        evidence_plan_path = os.path.join(output_dir, "evidence_asset_plan.json")
        evidence_validation_path = os.path.join(output_dir, "evidence_validation.json")
        continuity_pack_path = os.path.join(output_dir, "continuity_pack.json")
        motion_report_path = os.path.join(output_dir, "motion_report.json")
        opening_freeze_path = os.path.join(output_dir, "opening_freeze.json")
        animatic_report_path = os.path.join(output_dir, "animatic_gate.json")
        animatic_preview_path = os.path.join(output_dir, "animatic_preview.mp4")
        rendered_contract_path = os.path.join(output_dir, "rendered_contract.json")
        rendered_contact_sheet_path = os.path.join(output_dir, "rendered_contact_sheet.jpg")
        human_review_path = os.path.join(output_dir, "human_review.json")
        with open(evidence_plan_path, "w") as handle:
            json.dump(evidence_plan, handle, indent=2, ensure_ascii=False)
        with open(evidence_validation_path, "w") as handle:
            json.dump(evidence_validation, handle, indent=2, ensure_ascii=False)
        with open(continuity_pack_path, "w") as handle:
            json.dump(evidence_plan["continuity_pack"], handle, indent=2, ensure_ascii=False)
        counts = evidence_asset_counts(evidence_plan)
        log("Evidence compiler: PASS — %(planned_state_count)d states, "
            "%(distinct_source_count)d distinct, %(reframe_count)d reframes, "
            "%(exact_reuse_count)d exact callback reuse" % counts)

    mascot_ok = os.path.exists(MASCOT_REF)
    human_ok = os.path.exists(HUMAN_REF)
    if not mascot_ok:
        log(f"⚠ mascot reference missing ({MASCOT_REF}) — host scenes will use text only")
    if not human_ok:
        log(f"⚠ human reference missing ({HUMAN_REF}) — human-led long-form cannot render consistently")
    if video_format != "social":
        evidence_states = [state for scene_plan in evidence_plan.get("scenes") or []
                           for state in scene_plan.get("states") or []]
        if any(state.get("include_human") for state in evidence_states) and not human_ok:
            raise FileNotFoundError("Human continuity reference is required before evidence rendering.")
        if any(state.get("include_bolt") for state in evidence_states) and not mascot_ok:
            raise FileNotFoundError("Bolt continuity reference is required for declared support states.")

    # Locked cartoon RENDER style + constraints. The render look is constant (cohesion);
    # the per-scene environment + dominant style_mode supply variety. We rely on the
    # renderer's text scrim for caption legibility, so we only keep the focal subject out
    # of the very top strip.
    if cap_mode == "karaoke":
        framing = (
            " Vertical 9:16 composition: keep the main subject in the upper two-thirds and the"
            " lower third simpler, leaving room for captions.")
    elif cap_mode == "headline_karaoke":
        framing = (
            " Keep the main subject in the MIDDLE band: leave the top strip clear for a headline"
            " and the bottom strip clear for captions.")
    elif cap_mode == "bubble":
        framing = (
            " {mascot} is speaking to the viewer: keep ONE upper corner relatively clear for a"
            " speech bubble, and have {mascot} glance toward that corner. Keep the focal subject"
            " out of the very top strip.").format(mascot=MASCOT_NAME)
    else:
        framing = " Keep the focal subject out of the very top strip so a title caption can overlay."
    style_suffix = (
        f" Render style: {CHANNEL_STYLE}; style mode: {style_mode}."
        f"{framing}"
        " Avoid: generic centered layouts, flat empty compositions, diagram-like looks,"
        " and repetitive galaxy/nebula/starfield backdrops unless the topic is truly about"
        " space. No text, letters, numbers, labels, arrows, UI, watermark, or accidental"
        " writing — titles are added later by the renderer."
        + (_LITERAL_SCENE_DIRECTION if _LITERAL_IMAGERY else "")
    )

    def _full_prompt(scene: dict, cartoon_lean: bool = False) -> str:
        body = _s(scene.get("image_prompt")).rstrip(".")
        env = _s(scene.get("environment_type")).strip()
        if env:
            body = f"Environment: {env}. {body}"
        # Host scenes: prepend the SHORT reference line (the reference image carries the
        # identity), leaving the rest of the prompt for the scene design.
        if scene.get("mascot_present") and mascot_ok:
            body = f"{MASCOT_REF_LINE} {body}"
        if scene.get("human_present") and human_ok:
            body = f"{HUMAN_REF_LINE} {body}"
        out = body + "." + style_suffix
        # Prompt recency: re-assert action + surprise as the FINAL instruction so the
        # "clean/readable" style guardrails above don't bias gpt-image-2 toward a safe,
        # static illustration. Lifts bolt_activity + visual_surprise without weakening the
        # locked art-style language earlier in style_suffix.
        out += (" MOST IMPORTANT: the single most surprising, unexpected element of the scene must"
                " be prominent and unmissable, and if Bolt is present he must be visibly MID-ACTION"
                " (a clear action-verb pose) — never a passive bystander.")
        # Expressive-action finish on the beats that depend on it most — pose Bolt to LITERALIZE
        # the surprising idea, while the SETTING stays a believable real place (grounded realism),
        # so it doesn't drift into AI-slop look.
        if cartoon_lean:
            out += (" Make Bolt EXTRA expressive and pose him to literalize the scene's surprising"
                    " idea — a bold action gesture or exaggerated reaction that physically performs"
                    " the beat — while keeping the surrounding environment grounded, realistic, and"
                    " topic-accurate (real objects, real materials — not flat, abstract, or glowy).")
        return out

    # Cost cap — refine the estimate now that we know host split + narration length,
    # and refuse BEFORE spending on images if it exceeds the ceiling.
    narration_chars = sum(len(_s(s.get("narration"))) for s in scenes)
    if video_format != "social":
        planned_states = [state for scene_plan in evidence_plan.get("scenes") or []
                          for state in scene_plan.get("states") or []]
        generated_states = [state for state in planned_states
                            if state.get("asset_strategy") in {"master", "distinct"}]
        host_count = sum(1 for state in generated_states
                         if ((state.get("include_bolt") and mascot_ok)
                             or (state.get("include_human") and human_ok)))
        alt_selected = frozenset()
        # One verifier call per state is reserved at a conservative two cents. It is an estimate,
        # never presented as provider pricing, and prevents the multi-state compiler undercounting.
        base_est = round(estimate_cost(len(generated_states), host_count, narration_chars)
                         + len(planned_states) * 0.02, 2)
        motion_cap = (min(MAX_I2V_CLIPS, int(max(0, max_cost_usd - base_est)
                                             // (I2V_SECONDS_LONGFORM * _RATE_I2V_SEC)))
                      if i2v_on else 0)
        motion_plan = compile_motion_plan(
            script, evidence_plan, mode=resolved_motion_mode, max_requests=motion_cap)
        if not motion_plan["validation"]["passed"]:
            raise ValueError("Motion plan failed before media spend: " + "; ".join(
                error["message"] for error in motion_plan["validation"]["errors"]))
        script["_motion_plan"] = motion_plan
        with open(motion_report_path, "w") as handle:
            json.dump(motion_plan, handle, indent=2, ensure_ascii=False)
        est = round(base_est + (motion_plan["selected_count"] * I2V_SECONDS_LONGFORM
                               * _RATE_I2V_SEC if i2v_on else 0), 2)
    else:
        host_count = sum(1 for s in scenes if ((s.get("mascot_present") and mascot_ok)
                                               or (s.get("human_present") and human_ok)))
        alt_selected = frozenset()
        est = estimate_cost(len(scenes), host_count, narration_chars)
    if i2v_on and video_format == "social":   # social retains the legacy scene-based estimate
                 # estimate (and the pre-spend cap guard) reflect reality instead of undercounting.
        _frac = I2V_FRACTION_SOCIAL
        _clips = min(MAX_I2V_CLIPS, max(1, round(len(scenes) * _frac)))
        _i2v_seconds = I2V_SECONDS if video_format == "social" else I2V_SECONDS_LONGFORM
        est = round(est + _clips * _i2v_seconds * _RATE_I2V_SEC, 2)
        if video_format == "social" and _FAL_HYBRID and "fal" in _I2V_CHAIN:   # ~2 hero beats at v3 (2×)
            est = round(est + min(2, _clips) * _i2v_seconds * (_RATE_I2V_HERO_SEC - _RATE_I2V_SEC), 2)
    log(f"Estimated cost: ${est:.2f} (cap ${max_cost_usd:.2f})")
    if est > max_cost_usd:
        raise ValueError(
            f"Estimated cost ${est:.2f} exceeds the ${max_cost_usd:.2f} cap. "
            f"Lower the duration or raise the cap."
        )

    # 2. Natural-speed TTS is measured before visual purchase. Social keeps its legacy
    # interleaved path; long-form images cannot start until the audio contract passes.
    #    Image fails  → local fallback frame (job continues).
    #    Moderation   → one safe-prompt retry, else fallback frame.
    #    Audio fails  → scene is dropped (narration is the backbone).
    log("stage:Preparing narration and visual assets...")

    img_dir = os.path.join(output_dir, "images")
    aud_dir = os.path.join(output_dir, "audio")
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(aud_dir, exist_ok=True)
    n = len(scenes)
    img_costs: list[float] = []   # ACTUAL per-image USD (thread-safe list.append)
    tts_costs: list[float] = []
    prepared_audio: dict[int, dict] = {}
    if video_format != "social":
        log("stage:Generating and measuring final-speed narration...")
        prepared, audio_timing = _prepare_longform_audio(
            script, research_dossier, aud_dir, voice, duration_sec,
            tts_costs=tts_costs, aux_costs=aux_costs, question=question, log=log)
        prepared_audio = {item["i"]: item for item in prepared}
        audio_timing_report_path = os.path.join(output_dir, "audio_timing_report.json")
        with open(audio_timing_report_path, "w") as handle:
            json.dump(audio_timing, handle, indent=2, ensure_ascii=False)
        scenes = script.get("scenes", [])
        n = len(scenes)
        claim_validation = validate_claim_joins(script, research_dossier)
        retention_validation = validate_longform_story(script, question)
        script["_claim_validation"] = claim_validation
        script["_retention_validation"] = retention_validation
        if not claim_validation.get("passed") or not retention_validation.get("passed"):
            raise ValueError("Measured narration changed a story or claim contract before visual spend.")
        # A measured-runtime rewrite may change visual anchor phrases. Recompile the evidence states
        # from the final narration and fail before the first image if any opening beat lost its proof.
        _repair_anchor_phrases(script, log)
        evidence_plan = compile_evidence_plan(script)
        evidence_validation = evidence_plan.get("validation") or {}
        final_evidence_timing = validate_evidence_timing(evidence_plan, audio_timing)
        evidence_validation["timing"] = final_evidence_timing
        if not final_evidence_timing.get("passed"):
            evidence_validation["passed"] = False
            evidence_validation["errors"] = (
                evidence_validation.get("errors", []) + final_evidence_timing.get("errors", []))
        script["_evidence_plan"] = evidence_plan
        if not evidence_validation.get("passed"):
            raise ValueError(
                "Measured narration broke the evidence-state plan before visual spend: "
                + "; ".join(item["message"] for item in evidence_validation.get("errors", [])[:8])
            )
        with open(evidence_plan_path, "w") as handle:
            json.dump(evidence_plan, handle, indent=2, ensure_ascii=False)
        with open(evidence_validation_path, "w") as handle:
            json.dump(evidence_validation, handle, indent=2, ensure_ascii=False)
        with open(continuity_pack_path, "w") as handle:
            json.dump(evidence_plan["continuity_pack"], handle, indent=2, ensure_ascii=False)
        animatic_report = build_animatic_gate(script, evidence_plan, audio_timing)
        with open(animatic_report_path, "w") as handle:
            json.dump(animatic_report, handle, indent=2, ensure_ascii=False)
        if not animatic_report.get("passed"):
            raise ValueError(
                "Low-cost animatic failed before visual purchase: "
                + "; ".join(item["message"] for item in animatic_report.get("errors", [])[:8]))
        render_low_cost_animatic(
            script, evidence_plan, prepared_audio, animatic_preview_path, width=960, height=540)
        animatic_report["preview_path"] = animatic_preview_path
        animatic_report["preview_sha256"] = sha256_file(animatic_preview_path)
        with open(animatic_report_path, "w") as handle:
            json.dump(animatic_report, handle, indent=2, ensure_ascii=False)
        log("Low-cost animatic gate: PASS — subject, objective, anomaly, evidence, belief change, "
            "and forward question are recoverable from final narration/storyboards")
        final_states = [state for scene_plan in evidence_plan.get("scenes") or []
                        for state in scene_plan.get("states") or []]
        final_generated = [state for state in final_states
                           if state.get("asset_strategy") in {"master", "distinct"}]
        final_hosts = sum(1 for state in final_generated
                          if ((state.get("include_bolt") and mascot_ok)
                              or (state.get("include_human") and human_ok)))
        base_est = round(estimate_cost(len(final_generated), final_hosts, narration_chars)
                         + len(final_states) * 0.02, 2)
        motion_cap = (min(MAX_I2V_CLIPS, int(max(0, max_cost_usd - base_est)
                                             // (I2V_SECONDS_LONGFORM * _RATE_I2V_SEC)))
                      if i2v_on else 0)
        motion_plan = compile_motion_plan(
            script, evidence_plan, mode=resolved_motion_mode, max_requests=motion_cap)
        selected_motion_ids = {
            candidate["state_id"] for candidate in motion_plan.get("candidates") or []
            if candidate.get("selected")
        }
        motion_preflight_shots = []
        for scene_index, (scene, scene_plan) in enumerate(zip(
                scenes, evidence_plan.get("scenes") or [])):
            planned_states = [dict(state, asset_status="accepted")
                              for state in scene_plan.get("states") or []]
            motion_preflight_shots.append(compile_scene_shots(
                scene, _audio_dur(prepared_audio[scene_index]["aud"]), scene_index,
                word_times=prepared_audio[scene_index].get("word_times"),
                evidence_states=planned_states,
                motion_state_ids=frozenset(selected_motion_ids)))
        preflight_by_state = {
            shot.get("state_id"): shot for shots in motion_preflight_shots for shot in shots
        }
        for candidate in motion_plan.get("candidates") or []:
            if candidate.get("selected"):
                candidate["semantic_aligned"] = bool(
                    (preflight_by_state.get(candidate["state_id"]) or {}).get("semantic_aligned"))
        motion_plan["edit_preflight_metrics"] = shot_plan_metrics(motion_preflight_shots)
        motion_plan["validation"] = validate_motion_plan(motion_plan)
        if not motion_plan["validation"]["passed"]:
            raise ValueError("Measured narration broke the motion plan before visual spend: "
                             + "; ".join(error["message"]
                                          for error in motion_plan["validation"]["errors"]))
        script["_motion_plan"] = motion_plan
        with open(motion_report_path, "w") as handle:
            json.dump(motion_plan, handle, indent=2, ensure_ascii=False)
        est = round(base_est + (motion_plan["selected_count"] * I2V_SECONDS_LONGFORM
                               * _RATE_I2V_SEC if i2v_on else 0), 2)
        if est > max_cost_usd:
            raise ValueError(
                f"Final evidence plan estimate ${est:.2f} exceeds the ${max_cost_usd:.2f} cap "
                "before visual purchase."
            )
        retention_report_path = write_retention_report(
            retention_validation, script.get("_story_contract") or {}, output_dir)
        with open(claim_report_path, "w") as handle:
            json.dump(claim_validation, handle, indent=2, ensure_ascii=False)
        try:
            temporary_state = state_path + ".tmp"
            with open(temporary_state, "w") as handle:
                json.dump({"script": script, "style_mode": style_mode,
                           "short_grade": short_grade, "video_format": video_format}, handle)
            os.replace(temporary_state, state_path)
        except OSError:
            pass

    evidence_asset_paths: dict[str, str] = {}

    def _gen_evidence_assets(i: int, scene: dict, img_path: str, aud_path: str) -> dict:
        """Generate every declared state; failures stay rejected and cannot become a master crop."""
        scene_plan = (evidence_plan.get("scenes") or [])[i]
        states = scene_plan.get("states") or []
        generated_paths: dict[str, str] = {}
        attempts = []
        master_path = ""
        for state_index, state in enumerate(states):
            suffix = "master" if state_index == 0 else f"e{state_index + 1:02d}"
            state_path = img_path if state_index == 0 else os.path.join(
                img_dir, f"scene_{i:02d}_{suffix}.jpg")
            strategy = _s(state.get("asset_strategy"))
            source_path = evidence_asset_paths.get(_s(state.get("source_asset_id")), "")
            if not source_path and state_index > 0:
                source_path = master_path
            if not source_path and i > 0 and state.get("opening"):
                source_path = evidence_asset_paths.get("asset:s001:e01", "")
            generation_error = ""
            cached = False
            try:
                if strategy == "exact_reuse":
                    verification = reuse_exact_asset(source_path, state_path)
                elif strategy == "detail_reframe":
                    if not source_path or not os.path.isfile(source_path):
                        raise FileNotFoundError("detail source asset is unavailable")
                    _make_detail_reframe(source_path, state_path)
                    verification = verify_evidence_asset(
                        state_path, state, evidence_plan["continuity_pack"], cost_sink=aux_costs,
                        reference_paths=[source_path])
                else:
                    continuity_source = source_path or (master_path if state_index else "")
                    refs = _evidence_reference_paths(
                        state, human_ok=human_ok, mascot_ok=mascot_ok,
                        continuity_source=continuity_source)
                    prompt = _evidence_state_prompt(
                        scene, state, evidence_plan["continuity_pack"], style_suffix)
                    cached = (asset_resume_allowed and os.path.isfile(state_path)
                              and os.path.getsize(state_path) > 0)
                    if not cached:
                        try:
                            generate_image(prompt, state_path, reference_paths=refs,
                                           cost_sink=img_costs, size=img_size)
                        except ContentBlocked:
                            generate_image(
                                prompt + " SAFE REDRAW: symbolic, non-graphic, and moderation-safe while "
                                "preserving every required object state and forbidden-object rule.",
                                state_path, reference_paths=refs, cost_sink=img_costs, size=img_size)
                    verification = verify_evidence_asset(
                        state_path, state, evidence_plan["continuity_pack"], cost_sink=aux_costs,
                        reference_paths=refs)
            except Exception as exc:
                generation_error = f"{type(exc).__name__}: {str(exc)[:160]}"
                verification = None
            record_asset_verification(
                state, asset_path=state_path, verification=verification,
                generation_error=generation_error)
            attempts.append({
                "state_id": state.get("state_id"), "asset_id": state.get("asset_id"),
                "strategy": strategy, "status": state.get("asset_status"),
                "reused_checkpoint_asset": cached,
                "rejection_reasons": state.get("rejection_reasons") or [],
            })
            if state.get("asset_status") in {"accepted", "reused_exact"}:
                evidence_asset_paths[_s(state.get("asset_id"))] = state_path
                generated_paths[_s(state.get("asset_id"))] = state_path
                if state_index == 0:
                    master_path = state_path
                log(f"Evidence {i+1}.{state_index+1} ✓ {strategy}")
            else:
                log(f"✗ Evidence {i+1}.{state_index+1} REJECTED — "
                    + "; ".join(state.get("rejection_reasons") or ["unknown failure"]))

        prepared_item = prepared_audio.get(i)
        word_times = prepared_item.get("word_times") if prepared_item else None
        audio_path = prepared_item.get("aud") if prepared_item else aud_path
        evidence_ok = bool(states) and all(
            state.get("asset_status") in {"accepted", "reused_exact"} for state in states)
        accepted_paths = [generated_paths.get(_s(state.get("asset_id"))) for state in states]
        accepted_paths = [path for path in accepted_paths if path]
        return {
            "i": i, "scene": scene, "img": master_path or img_path,
            "alt_img": accepted_paths[1] if len(accepted_paths) > 1 else None,
            "evidence_assets": generated_paths, "evidence_states": states,
            "evidence_attempts": attempts, "evidence_ok": evidence_ok,
            "aud": audio_path, "img_ok": evidence_ok, "aud_ok": bool(prepared_item),
            "note": "evidence-accepted" if evidence_ok else "evidence-rejected",
            "word_times": word_times,
        }

    def _gen_assets(args):
        i, scene = args
        img_path = os.path.join(img_dir, f"scene_{i:02d}.jpg")
        alt_path = os.path.join(img_dir, f"scene_{i:02d}_alt.jpg")
        aud_path = os.path.join(aud_dir, f"scene_{i:02d}.mp3")
        if video_format != "social":
            return _gen_evidence_assets(i, scene, img_path, aud_path)
        # RESUME: if this scene's image + audio already exist on disk, reuse them — never
        # re-pay for a scene we already generated (the whole point of the checkpoint).
        if (asset_resume_allowed and os.path.exists(img_path) and os.path.getsize(img_path) > 0
                and os.path.exists(aud_path) and os.path.getsize(aud_path) > 0):
            wt = None
            if cap_mode in ("karaoke", "bubble", "headline_karaoke"):
                try:
                    wt = transcribe_words(aud_path)   # cheap; timing not persisted
                except Exception:
                    wt = None
            log(f"Scene {i+1}/{n} ✓ reused from checkpoint (no re-pay)")
            return {"i": i, "scene": scene, "img": img_path,
                    "alt_img": alt_path if os.path.exists(alt_path) else None, "aud": aud_path,
                    "img_ok": True, "aud_ok": True, "note": "reused", "word_times": wt}
        refs = _scene_reference_paths(scene, human_ok=human_ok, mascot_ok=mascot_ok)
        host_tag = " (host)" if refs else ""
        # Expressive-action treatment always on for the beats that depend on it most — the hook
        # (i==0), the twist + loop (last two), and metaphor scenes — else ~alternate scenes.
        _lean = (i == 0 or i >= n - 2
                 or scene.get("scene_type") == "metaphor_scene" or i % 2 == 0)
        full_prompt = _full_prompt(scene, cartoon_lean=_lean)
        log(f"Prompt {i+1}/{n}{host_tag}: {full_prompt}")

        # ---- image (with moderation recovery + local fallback) ----
        img_ok, note = True, ""
        try:
            generate_image(full_prompt, img_path, reference_paths=refs, cost_sink=img_costs,
                           size=img_size)
            log(f"Image {i+1}/{n} ✓{host_tag}")
        except ContentBlocked:
            log(f"⚠ Image {i+1}/{n} blocked by moderation — retrying with a safe prompt")
            try:
                generate_image(safe_image_prompt(scene), img_path, reference_paths=refs,
                               cost_sink=img_costs, size=img_size)
                note = "moderation→safe"
                log(f"Image {i+1}/{n} ✓ (safe fallback)")
            except Exception:
                make_fallback_frame(img_path, scene.get("text_overlay", ""), w=vw, h=vh)
                img_ok, note = False, "moderation→filler"
                log(f"⚠ Image {i+1}/{n} still blocked — using filler frame")
        except Exception as exc:
            make_fallback_frame(img_path, scene.get("text_overlay", ""), w=vw, h=vh)
            img_ok, note = False, f"img-error:{type(exc).__name__}"
            log(f"⚠ Image {i+1}/{n} failed ({type(exc).__name__}) — using filler frame")

        # A bounded number of retention turns earn a genuinely different camera view.
        # Failure is non-fatal: the shot compiler falls back to a crop/reframe of the master.
        alt_img = None
        if i in alt_selected and img_ok:
            try:
                broll = semantic_broll_beat(scene)
                anchor = _s(broll.get("anchor_phrase"))
                purpose = _s(broll.get("purpose")) or "evidence"
                visual = _s(broll.get("visual")) or _s(
                    scene.get("visible_consequence") or scene.get("narration"))
                shot_size = _s(broll.get("shot_size")) or "detail"
                camera_direction = _s(broll.get("camera_direction")) or "matched screen direction"
                alt_prompt = (
                    "Create clause-specific B-roll for this exact narration moment"
                    + (f' — "{anchor}"' if anchor else "")
                    + f". Editorial purpose: {purpose}. Show this genuinely new information: {visual}. "
                    f"Use a {shot_size} view with {camera_direction}. Preserve the same character "
                    "identity, setting, lighting, geography and factual details as the reference image; "
                    "do not merely crop or re-angle the same composition. The viewer must learn something "
                    "new from this cutaway. No text, labels, arrows, UI or watermark."
                )
                generate_image(alt_prompt, alt_path, reference_paths=[img_path],
                               cost_sink=img_costs, size=img_size)
                alt_img = alt_path
                log(f"Alternate shot {i+1}/{n} ✓")
            except Exception as exc:
                log(f"⚠ Alternate shot {i+1}/{n} failed ({type(exc).__name__}) — using reframe")

        # ---- audio (no fallback — a scene with no narration is dropped) ----
        aud_ok, word_times = True, None
        if i in prepared_audio:
            aud_path = prepared_audio[i]["aud"]
            word_times = prepared_audio[i]["word_times"]
            log(f"Audio {i+1}/{n} ✓ measured before visual purchase")
        else:
            try:
                generate_tts(_s(scene.get("narration")), aud_path, voice=voice)
                tts_costs.append(len(_s(scene.get("narration"))) * _RATE_TTS_CHAR)
                log(f"Audio {i+1}/{n} ✓")
                if cap_mode in ("karaoke", "bubble", "headline_karaoke"):
                    word_times = transcribe_words(aud_path)
            except Exception as exc:
                aud_ok = False
                log(f"⚠ Audio {i+1}/{n} failed ({type(exc).__name__}) — dropping this scene")

        return {"i": i, "scene": scene, "img": img_path, "alt_img": alt_img, "aud": aud_path,
                "img_ok": img_ok, "aud_ok": aud_ok, "note": note, "word_times": word_times}

    # PR4 long-form motion is keyed to verified evidence states, never coarse scene indices.
    state_motion_clips: dict[str, str] = {}
    i2v_costs: list[float] = []
    i2v_errs: list[str] = []
    i2v_exhausted: set[str] = set()

    def _generate_longform_motion(results_for_motion: list[dict], scene_indices: set[int]) -> None:
        if video_format == "social" or resolved_motion_mode == "stills":
            return
        by_scene = {int(result["i"]): result for result in results_for_motion}
        selected = [candidate for candidate in motion_plan.get("candidates") or []
                    if candidate.get("selected") and int(candidate["scene_index"]) in scene_indices]
        if not selected:
            return
        i2v_dir = os.path.join(output_dir, "i2v")
        os.makedirs(i2v_dir, exist_ok=True)
        log(f"stage:Animating {len(selected)} evidence state(s) before edit approval...")
        for candidate in selected:
            result = by_scene.get(int(candidate["scene_index"]))
            image_path = ((result or {}).get("evidence_assets") or {}).get(candidate["asset_id"])
            safe_state = candidate["state_id"].replace(":", "-")
            clip = os.path.join(i2v_dir, f"{safe_state}.mp4")
            identity_path = clip + ".identity.json"
            prompt_text = motion_prompt(candidate)
            cache_identity = {
                "version": 1,
                "motion_id": candidate["motion_id"],
                "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
                "source_sha256": sha256_file(image_path) if image_path and os.path.isfile(image_path) else "",
                "seconds": I2V_SECONDS_LONGFORM,
            }
            try:
                with open(identity_path) as handle:
                    cached_identity = json.load(handle)
            except (OSError, ValueError, TypeError):
                cached_identity = {}
            cached_provider = _s(cached_identity.get("provider"))
            cached_model_id = _s(cached_identity.get("model_id"))
            base_identity_matches = all(
                cached_identity.get(key) == value for key, value in cache_identity.items())
            reusable_provider = cached_provider in _I2V_CHAIN and cached_model_id == (
                _motion_model_id(cached_provider) if cached_provider in _I2V_CHAIN else "")
            reused = bool(base_identity_matches and reusable_provider and os.path.isfile(clip)
                          and _clip_is_real(clip))
            start_cost = sum(i2v_costs)
            start_errors = len(i2v_errs)
            rendered = clip if reused else None
            spent_now = (sum(img_costs) + sum(tts_costs) + sum(aux_costs) + sum(i2v_costs)
                         + float(script.get("_script_cost_usd", 0.0) or 0.0))
            has_motion_budget = (spent_now + I2V_SECONDS_LONGFORM * _RATE_I2V_SEC
                                 <= max_cost_usd + 1e-9)
            if not rendered and image_path and has_motion_budget:
                rendered = animate_scene(
                    image_path, prompt_text, clip, vw, vh,
                    cost_sink=i2v_costs, seconds=I2V_SECONDS_LONGFORM,
                    err_sink=i2v_errs, exhausted=i2v_exhausted)
            new_errors = i2v_errs[start_errors:]
            provider = (cached_provider if reused else next(
                (item.split(":", 1)[1] for item in reversed(new_errors)
                if item.startswith("ok:")), ""))
            model_id = _motion_model_id(provider) if provider else ""
            if rendered:
                if not reused:
                    with open(identity_path, "w") as handle:
                        json.dump({**cache_identity, "provider": provider, "model_id": model_id},
                                  handle, indent=2)
                candidate.update({
                    "generation_status": "animated", "provider": provider,
                    "model_id": model_id,
                    "clip_path": rendered, "cost_usd": round(sum(i2v_costs) - start_cost, 4),
                    "fallback_reason": "", "reused_checkpoint_clip": reused,
                    "cache_identity": cache_identity,
                    "provider_attempts": new_errors,
                })
                state_motion_clips[candidate["state_id"]] = rendered
                log(f"  motion {candidate['state_id']} ✓ {candidate['story_role']}"
                    + (" (reused)" if reused else ""))
            else:
                reason = "; ".join(item for item in new_errors if not item.startswith("ok:"))
                if not image_path:
                    reason = "verified evidence image is unavailable"
                elif not has_motion_budget:
                    reason = "motion cost cap reached before provider request"
                candidate.update({
                    "generation_status": "fallback", "provider": "", "clip_path": "",
                    "cost_usd": round(sum(i2v_costs) - start_cost, 4),
                    "fallback_reason": reason or "all motion providers failed",
                    "provider_attempts": new_errors,
                })
                log(f"  motion {candidate['state_id']} ✗ — locked evidence fallback")
        motion_plan["validation"] = validate_motion_plan(motion_plan, require_generation=False)
        motion_plan["generation_validation"] = validate_motion_plan(
            motion_plan, require_generation=True)
        motion_plan["provider_errors"] = [item for item in i2v_errs if not item.startswith("ok:")]
        motion_plan["exhausted_providers"] = sorted(i2v_exhausted)
        with open(motion_report_path, "w") as handle:
            json.dump(motion_plan, handle, indent=2, ensure_ascii=False)

    # ── Render smoke-test: PROVE scene 1 renders before paying for the other images. ──
    # A render bug once torched a full 120-image run; this caps that loss at ~1 image.
    log("Smoke-testing the render on scene 1 before generating the rest...")
    r0 = _gen_assets((0, scenes[0]))   # generates scene-1 image + audio (counts toward cost)
    if video_format != "social" and not r0.get("evidence_ok"):
        evidence_validation = validate_evidence_plan(
            evidence_plan, require_verified_assets=True, opening_only=True)
        with open(evidence_plan_path, "w") as handle:
            json.dump(evidence_plan, handle, indent=2, ensure_ascii=False)
        with open(evidence_validation_path, "w") as handle:
            json.dump(evidence_validation, handle, indent=2, ensure_ascii=False)
        raise RuntimeError("Opening evidence assets were rejected before the render smoke test.")
    if not r0["aud_ok"]:
        raise RuntimeError("Scene 1 audio failed — aborting before generating the other images.")
    try:
        _smoke = os.path.join(output_dir, "_smoke_scene0.mp4")
        _wt = (align_caption_phrases(scenes[0].get("narration", ""), r0.get("word_times"),
                                     _audio_dur(r0["aud"]))
               if cap_mode in ("karaoke", "bubble", "headline_karaoke") else None)
        _tm0 = scenes[0].get("text")
        _pl = ((_s(_tm0.get("placement")) if isinstance(_tm0, dict) else "") or "top_right").lower()
        _bs = "left" if "left" in _pl else ("right" if "right" in _pl else "center")
        _make_scene_segment(
            r0["img"], r0["aud"], _smoke,
            scenes[0].get("text_overlay", ""), scenes[0].get("text_sub", ""),
            motion=_pick_motion(scenes[0].get("shot_type", "medium"), 0), tail=FADE_DUR,
            text_meta=scenes[0].get("text"), style_mode=style_mode,
            vw=vw, vh=vh, captions=cap_mode, word_times=_wt, bubble_side=_bs)
        log("Render smoke-test passed ✓ — generating the remaining scenes")
    except Exception as exc:
        import traceback as _tb, sys as _sys
        print(f"[smoke-test] {_tb.format_exc()}", file=_sys.stderr, flush=True)
        raise RuntimeError(
            f"Render smoke-test FAILED on scene 1 ({type(exc).__name__}: {str(exc)[:120]}). "
            f"Aborted before generating the other {len(scenes) - 1} images — only ~$0.10 spent "
            f"instead of ~${est:.2f}. Fix the render path and retry."
        ) from exc

    # ── Hook dry-run (SOCIAL): does the OPENING read at a phone-sized, MUTED glance? Runs on the
    # smoke-rendered opening BEFORE paying for the other images. Advisory unless HOOK_DRYRUN_HARD=1. ──
    if video_format == "social" and os.path.exists(_smoke):
        _ff = _smoke + ".frame.png"
        try:
            subprocess.run([_ffmpeg_bin(), "-y", "-loglevel", "error", "-ss", "1.0", "-i", _smoke,
                            "-frames:v", "1", _ff], check=True)
            _ctr = script.get("_premise_contract") or {}
            _promise = _s(_ctr.get("viewer_promise")) or _s(script.get("hook")) or question
            _dr = _hook_dryrun(_ff, _promise, _s(scenes[0].get("narration")), cost_sink=aux_costs)
        except Exception:
            _dr = None
        if _dr and not _dr["reads"]:
            log(f"⚠ Hook dry-run: instant-read {_dr['instant_read']}/10 — opening may not read at a "
                f"glance ({_dr['unclear']})")
            if _hook_dryrun_hard():
                for _p in (_ff, _smoke):
                    if os.path.exists(_p):
                        os.remove(_p)
                raise RuntimeError(
                    f"Hook dry-run failed ({_dr['instant_read']}/10): {_dr['unclear']} — aborted before "
                    f"generating the other {len(scenes) - 1} images (HOOK_DRYRUN_HARD=1).")
        elif _dr:
            log(f"Hook dry-run ✓ instant-read {_dr['instant_read']}/10 — opening reads muted")
        if os.path.exists(_ff):
            os.remove(_ff)
    if os.path.exists(_smoke):
        os.remove(_smoke)

    # LONG-FORM 45-SECOND GATE: pay only for the opening tranche, render it, and grade the
    # actual edit before purchasing the remaining images/TTS. Social retains its one-frame hook gate.
    all_indexed = list(enumerate(scenes))
    opening_stop = len(scenes)
    if video_format != "social":
        estimate_cursor = 0.0
        opening_stop = 0
        for i, scene in all_indexed:
            prepared_item = prepared_audio.get(i)
            estimate_cursor += (_audio_dur(prepared_item["aud"]) if prepared_item else
                                max(0.8, len(_s(scene.get("narration")).split()) / 2.64))
            opening_stop = i + 1
            if estimate_cursor >= 45.0:
                break
    opening_rest = []
    if opening_stop > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            opening_rest = list(_context_map(ex, _gen_assets, all_indexed[1:opening_stop]))
    opening_results = [r0] + opening_rest

    if video_format != "social":
        if any(not result.get("evidence_ok") for result in opening_results):
            with open(evidence_plan_path, "w") as handle:
                json.dump(evidence_plan, handle, indent=2, ensure_ascii=False)
            raise RuntimeError("One or more first-tranche evidence assets were explicitly rejected.")
        evidence_validation = validate_evidence_plan(
            evidence_plan, require_verified_assets=True, opening_only=True)
        with open(evidence_plan_path, "w") as handle:
            json.dump(evidence_plan, handle, indent=2, ensure_ascii=False)
        with open(evidence_validation_path, "w") as handle:
            json.dump(evidence_validation, handle, indent=2, ensure_ascii=False)
        if not evidence_validation.get("passed"):
            raise RuntimeError(
                "Opening evidence gate failed before later visual purchase: "
                + "; ".join(item["message"] for item in evidence_validation.get("errors", [])[:8])
            )
        log(opening_evidence_gate_message(evidence_validation))
        _generate_longform_motion(opening_results, set(range(opening_stop)))
        opening_motion = [candidate for candidate in motion_plan.get("candidates") or []
                          if candidate.get("selected")
                          and int(candidate.get("scene_index") or 0) < opening_stop]
        if opening_motion and not any(candidate.get("generation_status") == "animated"
                                      for candidate in opening_motion):
            raise RuntimeError(
                "The selected motion treatment produced no real opening motion; aborted before "
                "purchasing later visual assets. Choose Stills or restore a working motion provider.")
        log(f"stage:Rendering 45-second gate ({opening_stop}/{len(scenes)} planned scenes)...")
        try:
            (first_minute_preview_path, opening_metrics, opening_cues,
             frozen_opening_segments, opening_shot_plan) = _render_first_minute_preview(
                opening_results, output_dir, cap_mode=cap_mode, style_mode=style_mode,
                vw=vw, vh=vh, bg_music_path=bg_music_path,
                motion_clips=state_motion_clips)
            opening_motion_clips = {
                state_id: path for state_id, path in state_motion_clips.items()
                if any(candidate.get("state_id") == state_id
                       and int(candidate.get("scene_index") or 0) < opening_stop
                       for candidate in motion_plan.get("candidates") or [])
            }
            opening_freeze = freeze_opening_manifest(
                frozen_opening_segments, opening_motion_clips, opening_freeze_path)
            freeze_validation = validate_frozen_opening(opening_freeze)
            if not freeze_validation["passed"]:
                raise RuntimeError("Opening freeze failed: " + "; ".join(
                    error["message"] for error in freeze_validation["errors"]))
            preview_duration = _audio_dur(first_minute_preview_path)
            preview_state = {"decodable": _clip_is_real(first_minute_preview_path, min_dur=10),
                             "duration_sec": round(preview_duration, 1), "target_sec": 45}
            opening_script = dict(script)
            opening_script["scenes"] = [r["scene"] for r in opening_results if r.get("aud_ok")]
            readiness = score_retention_readiness(
                opening_script, retention_validation or {}, opening_metrics, opening_cues,
                preview=preview_state)
            readiness_report_path, readiness_json_path = write_readiness_report(readiness, output_dir)
            log(f"45-second Retention Readiness: {readiness['score']}/100 "
                f"({readiness['grade']}) — {readiness['label']}")
            inspection = inspect_rendered_opening(
                first_minute_preview_path, opening_shot_plan, output_dir, evidence_plan,
                threshold_profile=threshold_profile)
            build_contact_sheet(inspection, rendered_contact_sheet_path)
            cue_cursor = 0.0
            transcript_cues = []
            for result in opening_results:
                if not result.get("aud_ok"):
                    continue
                duration = _audio_dur(result["aud"])
                transcript_cues.append({
                    "start_sec": round(cue_cursor, 2),
                    "end_sec": round(cue_cursor + duration, 2),
                    "narration": _s(result["scene"].get("narration")),
                })
                cue_cursor += duration
            blind = _blind_rendered_story_judge(
                rendered_contact_sheet_path, transcript_cues, cost_sink=aux_costs)
            checked_blind = cross_check_blind_observations(
                blind, inspection.get("deterministic") or {})
            callback = evidence_plan.get("continuity_pack", {}).get("callback", {})
            callback_exact = bool(
                callback.get("reuse_source_asset_id")
                and any(state.get("asset_strategy") == "exact_reuse"
                        and state.get("source_asset_id") == callback.get("reuse_source_asset_id")
                        for scene_plan in evidence_plan.get("scenes") or []
                        for state in scene_plan.get("states") or []))
            prior_review = None
            prior_review_bound = False
            if human_review_path and os.path.isfile(human_review_path):
                try:
                    with open(human_review_path) as handle:
                        prior_review = json.load(handle)
                    prior_review_bound = bool(
                        prior_review.get("decision") in {"approve", "reject"}
                        and os.path.isfile(rendered_contract_path)
                        and prior_review.get("rendered_report_sha256")
                        == sha256_file(rendered_contract_path)
                        and prior_review.get("preview_sha256")
                        == sha256_file(first_minute_preview_path))
                except (OSError, ValueError, TypeError):
                    prior_review = None
                    prior_review_bound = False
            rendered_contract = score_rendered_contract(
                deterministic=inspection.get("deterministic") or {}, blind=checked_blind,
                story_validation=retention_validation or {}, claim_validation=claim_validation or {},
                callback_exact=callback_exact,
                human_review=prior_review if prior_review_bound else None)
            rendered_contract.update({
                "inspection": inspection,
                "blind_story_judge": checked_blind,
                "contact_sheet_path": rendered_contact_sheet_path,
                "animatic_gate_passed": bool(animatic_report.get("passed")),
            })
            with open(rendered_contract_path, "w") as handle:
                json.dump(rendered_contract, handle, indent=2, ensure_ascii=False)
            log(f"Rendered opening contract: {rendered_contract['score']}/100 "
                f"({rendered_contract['status']})")
            if controlled_pilot:
                # PR7 stops here by contract.  Both automated passes and automated failures receive
                # an editorial record and a complete durable artifact snapshot; neither can buy a
                # later scene or be silently re-rendered under a different threshold.
                if not os.path.isfile(human_review_path):
                    create_human_review_record(
                        rendered_contract_path, first_minute_preview_path, human_review_path)
                with open(pilot_script_path, "w", encoding="utf-8") as handle:
                    json.dump(script, handle, indent=2, ensure_ascii=False)
                script_cost = float(script.get("_script_cost_usd", 0.0) or 0.0)
                actual_cost = round(
                    sum(img_costs) + sum(tts_costs) + sum(aux_costs)
                    + sum(i2v_costs) + script_cost, 4)
                cost_report = {
                    "schema_version": 1,
                    "pilot_batch_id": pilot_batch_id,
                    "pilot_kind": pilot_kind,
                    "currency": "USD",
                    "script_and_factcheck": round(script_cost, 4),
                    "images": round(sum(img_costs), 4),
                    "narration": round(sum(tts_costs), 4),
                    "judges_and_support": round(sum(aux_costs), 4),
                    "motion": round(sum(i2v_costs), 4),
                    "actual_total": actual_cost,
                    "estimated_cap": round(float(max_cost_usd), 4),
                    "full_video_assets_purchased": False,
                    "opening_scene_count": opening_stop,
                    "total_planned_scene_count": len(scenes),
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                }
                with open(pilot_cost_report_path, "w", encoding="utf-8") as handle:
                    json.dump(cost_report, handle, indent=2, ensure_ascii=False)
                generation_manifest["actual_audio_transformations"] = (
                    audio_timing.get("audio_transformations") or [])
                generation_manifest["actual_motion"] = [
                    {
                        "state_id": item.get("state_id"),
                        "provider": item.get("provider"),
                        "model_id": item.get("model_id"),
                        "generation_status": item.get("generation_status"),
                        "provider_attempts": item.get("provider_attempts") or [],
                    }
                    for item in (motion_plan.get("candidates") or []) if item.get("selected")
                ]
                generation_manifest["status"] = "pilot_rendered_awaiting_editorial"
                generation_manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
                generation_manifest["output_sha256"] = sha256_file(first_minute_preview_path)
                _write_generation_manifest(generation_manifest_path, generation_manifest)
                with open(pilot_control_path, encoding="utf-8") as handle:
                    pilot_control = json.load(handle)
                pilot_control.update({
                    "status": "awaiting_editorial",
                    "effective_story_format": validate_effective_story_format(
                        script, pilot_request or {}),
                    "rendered_score": rendered_contract.get("score"),
                    "automated_pass": bool(rendered_contract.get("automated_pass")),
                    "hard_failures": rendered_contract.get("hard_failures") or [],
                    "preview_sha256": sha256_file(first_minute_preview_path),
                    "rendered_contract_sha256": sha256_file(rendered_contract_path),
                    "rendered_at": datetime.now(timezone.utc).isoformat(),
                })
                _write_generation_manifest(pilot_control_path, pilot_control)
                completeness = artifact_completeness(output_dir)
                return {
                    "controlled_pilot": True,
                    "pilot_batch_id": pilot_batch_id,
                    "pilot_kind": pilot_kind,
                    "pilot_policy": frozen_pilot_policy(),
                    "pilot_artifact_completeness": completeness,
                    "output_path": first_minute_preview_path,
                    "script": script,
                    "title": script.get("title", question),
                    "hook": script.get("hook", ""),
                    "scene_count": opening_stop,
                    "video_format": video_format,
                    "motion_mode": resolved_motion_mode,
                    "duration_sec": round(preview_duration, 1),
                    "est_cost": est,
                    "actual_cost": actual_cost,
                    "status": "pilot_awaiting_editorial",
                    "degraded_reasons": list(rendered_contract.get("hard_failures") or []),
                    "rendered_contract": rendered_contract,
                    "retention_readiness": readiness,
                    "pilot_control_path": pilot_control_path,
                    "pilot_script_path": pilot_script_path,
                    "pilot_cost_report_path": pilot_cost_report_path,
                    "research_report_path": research_report_path,
                    "claim_report_path": claim_report_path,
                    "audio_timing_report_path": audio_timing_report_path,
                    "generation_manifest_path": generation_manifest_path,
                    "evidence_plan_path": evidence_plan_path,
                    "evidence_validation_path": evidence_validation_path,
                    "continuity_pack_path": continuity_pack_path,
                    "motion_report_path": motion_report_path,
                    "opening_freeze_path": opening_freeze_path,
                    # The manifest content, not just its local path: a later PR8 production run
                    # starts in a different container and needs the approved opening hashes to
                    # survive in durable storage.
                    "opening_freeze": opening_freeze,
                    "animatic_report_path": animatic_report_path,
                    "animatic_preview_path": animatic_preview_path,
                    "rendered_contract_path": rendered_contract_path,
                    "rendered_contact_sheet_path": rendered_contact_sheet_path,
                    "human_review_path": human_review_path,
                    "readiness_json_path": readiness_json_path,
                    "first_minute_preview_path": first_minute_preview_path,
                }
            if not rendered_contract.get("automated_pass"):
                diagnostic = diagnostic_mode_allowed()
                if diagnostic:
                    diagnostic_preview_path = os.path.join(
                        output_dir, "rejected_diagnostic_preview.mp4")
                    watermark_rejected_preview(first_minute_preview_path, diagnostic_preview_path)
                    rendered_contract = diagnostic_disposition(rendered_contract, allowed=True)
                    rendered_contract["diagnostic_preview_path"] = diagnostic_preview_path
                    with open(rendered_contract_path, "w") as handle:
                        json.dump(rendered_contract, handle, indent=2, ensure_ascii=False)
                raise RuntimeError(
                    f"Rendered opening scored {rendered_contract['score']}/100; "
                    f"hard failures: {', '.join(rendered_contract.get('hard_failures') or ['score floor'])}. "
                    f"Aborted before purchasing {len(scenes) - opening_stop} later scenes."
                )
            if not rendered_contract.get("passed"):
                if prior_review_bound and prior_review.get("decision") == "reject":
                    raise RuntimeError(
                        "Human editor rejected the rendered opening; later visual assets were not purchased.")
                create_human_review_record(
                    rendered_contract_path, first_minute_preview_path, human_review_path)
                raise HumanReviewRequired(
                    "Rendered opening passed automation and is awaiting human editorial approval; "
                    "later visual assets have not been purchased. Review the contact sheet/preview, "
                    "POST the completed checklist, then resume this job.")
        except Exception as exc:
            # PR5 removes the advisory escape hatch for long-form. Diagnostics may preserve a
            # watermarked rejected preview, but no exception can authorize later asset purchase.
            raise
        if (not frozen_opening_segments or not rendered_contract
                or not rendered_contract.get("passed")):
            raise RuntimeError(
                "The rendered opening was not automatically and human approved/frozen; later visual "
                "assets will not be purchased.")

    later = []
    if opening_stop < len(scenes):
        log(f"45-second gate passed ✓ — generating the remaining {len(scenes) - opening_stop} scenes")
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            later = list(_context_map(ex, _gen_assets, all_indexed[opening_stop:]))
    results = opening_results + later   # _gen_assets never raises

    if video_format != "social":
        evidence_validation = validate_evidence_plan(
            evidence_plan, require_verified_assets=True)
        with open(evidence_plan_path, "w") as handle:
            json.dump(evidence_plan, handle, indent=2, ensure_ascii=False)
        with open(evidence_validation_path, "w") as handle:
            json.dump(evidence_validation, handle, indent=2, ensure_ascii=False)
        if not evidence_validation.get("passed"):
            raise RuntimeError(
                "Final evidence asset validation failed: "
                + "; ".join(item["message"] for item in evidence_validation.get("errors", [])[:8])
            )

    # END-OF-RUN RECOVERY: a transient blip (APIConnectionError) can strand scenes on filler frames
    # even though the endpoint recovers seconds later. Retry ONLY those transient fillers once more,
    # serially (the blip has usually passed by now), BEFORE we count degradation. Moderation-blocked
    # scenes are NOT retried here — that's a content issue, not a transient one.
    _recover = [r for r in results
                if not r["img_ok"] and "moderation" not in (r.get("note") or "")]
    if _recover:
        log(f"↻ Recovering {len(_recover)} scene image(s) that hit transient errors...")
        for r in _recover:
            i, scene = r["i"], r["scene"]
            refs = _scene_reference_paths(scene, human_ok=human_ok, mascot_ok=mascot_ok)
            _lean = (i == 0 or i >= n - 2
                     or scene.get("scene_type") == "metaphor_scene" or i % 2 == 0)
            try:
                generate_image(_full_prompt(scene, cartoon_lean=_lean), r["img"],
                               reference_paths=refs, cost_sink=img_costs, size=img_size)
                r["img_ok"], r["note"] = True, "recovered"
                log(f"Image {i+1}/{n} ✓ recovered on retry")
            except Exception as exc:
                log(f"⚠ Image {i+1}/{n} still failing ({type(exc).__name__}) — keeping filler")

    # Keep only scenes that have narration; image is guaranteed (real or filler).
    usable = [r for r in results if r["aud_ok"]]
    dropped = n - len(usable)
    filler  = sum(1 for r in usable if not r["img_ok"])
    if dropped:
        log(f"⚠ Dropped {dropped} scene(s) with no audio")
    if filler:
        log(f"⚠ {filler} scene(s) using filler frames")
    if not usable:
        raise RuntimeError("All scenes failed to generate audio — cannot assemble a video.")

    # 3a. Image-to-video: animate a deterministic ~35% of scenes (incl. the opener) for variety.
    #     Budget-capped against the remaining headroom under max_cost_usd; ANY failure (refusal,
    #     timeout, no-quota) falls back to ffmpeg Ken-Burns motion so the render never breaks.
    i2v_clips: dict[int, str] = {}  # social legacy: scene index -> clip
    i2v_requested = 0
    if video_format != "social":
        _generate_longform_motion(results, set(range(opening_stop, len(scenes))))
        i2v_requested = sum(1 for candidate in motion_plan.get("candidates") or []
                            if candidate.get("selected"))
        motion_plan["generation_validation"] = validate_motion_plan(
            motion_plan, require_generation=True)
        if not motion_plan["generation_validation"]["passed"]:
            raise RuntimeError("Motion generation report is incomplete: " + "; ".join(
                error["message"] for error in motion_plan["generation_validation"]["errors"]))
        with open(motion_report_path, "w") as handle:
            json.dump(motion_plan, handle, indent=2, ensure_ascii=False)
        if opening_freeze:
            freeze_validation = validate_frozen_opening(opening_freeze)
            if not freeze_validation["passed"]:
                raise RuntimeError("Approved opening changed before final edit: " + "; ".join(
                    error["message"] for error in freeze_validation["errors"]))
    if i2v_on and video_format == "social":
        i2v_seconds = I2V_SECONDS if video_format == "social" else I2V_SECONDS_LONGFORM
        spent = (sum(img_costs) + sum(tts_costs) + sum(aux_costs)
                 + float(script.get("_script_cost_usd", 0.0) or 0.0))
        budget_clips = int(max(0, max_cost_usd - spent) // (i2v_seconds * _RATE_I2V_SEC))
        sel = _select_i2v_indices([r["scene"] for r in usable], question, video_format, budget_clips)
        i2v_requested = len(sel)
        if sel:
            log(f"stage:Animating up to {len(sel)} scenes ({'/'.join(_I2V_CHAIN)})...")
            log(f"i2v: animating {len(sel)}/{len(usable)} scenes via {'→'.join(_I2V_CHAIN)} "
                f"(~${len(sel) * i2v_seconds * _RATE_I2V_SEC:.2f})")
            i2v_dir = os.path.join(output_dir, "i2v")
            os.makedirs(i2v_dir, exist_ok=True)
            i2v_exhausted: set = set()   # providers whose quota ran out → skip for the rest of run
            # HYBRID: pricier, more-natural model on the hook + climax (social) where motion earns the
            # swipe/stay decision; the cheaper _FAL_MODEL on the rest.
            _hero = (_hero_i2v_indices(usable, sel)
                     if (video_format == "social" and _FAL_HYBRID and "fal" in _I2V_CHAIN) else set())
            if _hero:
                log(f"i2v hybrid: {_FAL_MODEL_HERO.split('/')[2]}-pro on hero beats "
                    f"{sorted(k + 1 for k in _hero)}, standard on the rest")

            def _anim(k):
                r = usable[k]
                clip = os.path.join(i2v_dir, f"scene_{k:02d}.mp4")
                if os.path.exists(clip) and os.path.getsize(clip) > 0:   # resume: never re-pay
                    return k, clip, True
                _is_hero = k in _hero
                res = animate_scene(r["img"], r["scene"].get("image_prompt", ""), clip,
                                    vw, vh, cost_sink=i2v_costs, err_sink=i2v_errs,
                                    exhausted=i2v_exhausted,
                                    seconds=i2v_seconds,
                                    fal_model=_FAL_MODEL_HERO if _is_hero else None,
                                    rate=_RATE_I2V_HERO_SEC if _is_hero else None)
                return k, res, False

            # SERIAL: video APIs cap concurrent active generations — running 2 at once made the
            # first-submitted clip (the opener) fail repeatedly. One at a time is reliable.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                for k, res, reused in _context_map(ex, _anim, sorted(sel)):
                    if res:
                        i2v_clips[k] = res
                        log(f"  i2v scene {k+1} ✓{' (reused)' if reused else ''}")
                    else:
                        log(f"  i2v scene {k+1} ✗ — ffmpeg motion fallback")

            # Summary + a LOUD, actionable warning so a motion-less video is never a silent mystery.
            n_ok = len(i2v_clips)
            ok_providers = sorted({e.split(":", 1)[1] for e in i2v_errs if e.startswith("ok:")})
            quota_hit = any(("RESOURCE_EXHAUSTED" in e or "429" in e or "quota" in e.lower())
                            for e in i2v_errs if not e.startswith("ok:"))
            prov_note = f" via {'+'.join(ok_providers)}" if ok_providers else ""
            log(f"i2v: {n_ok}/{i2v_requested} scenes animated{prov_note}, "
                f"{i2v_requested - n_ok} on Ken Burns")
            if i2v_exhausted and n_ok > 0:
                log(f"⚠ i2v: {'/'.join(sorted(i2v_exhausted))} quota hit mid-run — fell back to "
                    "the next provider automatically.")
            if n_ok == 0:
                log(f"⚠ i2v: NO scenes animated — all {i2v_requested} clips failed across "
                    f"{'→'.join(_I2V_CHAIN)}"
                    + (". Provider QUOTA EXHAUSTED (429) — raise quota or wait for the daily reset."
                       if quota_hit else " (provider errors).")
                    + " The video uses Ken Burns motion only.")
            elif n_ok < i2v_requested and quota_hit:
                log(f"⚠ i2v: only {n_ok}/{i2v_requested} animated — provider quota ran out partway; "
                    "raise quota or rely on the fallback provider.")

    # 3. Render per-scene segments
    log("stage:Rendering scenes...")
    scene_dir = os.path.join(output_dir, "scenes")
    os.makedirs(scene_dir, exist_ok=True)

    scene_videos, scene_audios, rendered_narr, rendered_shot_plan = [], [], [], []
    cap_missing = 0   # social scenes that ended up with NO captions (health floor)
    for k, r in enumerate(usable):
        scene = r["scene"]
        seg = os.path.join(scene_dir, f"scene_{k:02d}.mp4")
        motion = _pick_motion(scene.get("shot_type", "medium"), k)
        word_times = None
        bubble_side = "right"
        if cap_mode in ("karaoke", "bubble", "headline_karaoke"):
            # Forced alignment: SCRIPT words for text, Whisper for timing (even-split fallback).
            word_times = align_caption_phrases(
                scene.get("narration", ""), r.get("word_times"), _audio_dur(r["aud"]))
            if not word_times:
                cap_missing += 1
                log(f"⚠ Scene {k+1} has no {'bubble' if cap_mode=='bubble' else 'captions'} (no words/timing)")
            # The bubble sits in the caption's clear zone (away from Bolt); tail points at Bolt.
            _tm = scene.get("text")
            placement = ((_s(_tm.get("placement")) if isinstance(_tm, dict) else "") or "top_right").lower()
            bubble_side = "left" if "left" in placement else ("right" if "right" in placement else "center")
        # Label the actual motion source so the log doesn't say "kenburns" for an i2v scene.
        _mv = i2v_clips.get(k)
        try:
            # Inside the try deliberately. This sat outside it, so a shot-compilation raise aborted
            # the entire run — after every image, TTS call and motion clip had been purchased. The
            # preflight at the pre-spend gate is NOT equivalent: it forces asset_status="accepted"
            # on planned states, while here the real statuses give a smaller set with different
            # spacing, so passing there does not guarantee passing here. A scene that cannot be cut
            # should be skipped like any other scene failure, not cost the whole render.
            _shot_plan = compile_scene_shots(
                scene, _audio_dur(r["aud"]), k,
                has_i2v=bool(_mv), has_alternate=bool(r.get("alt_img")),
                i2v_seconds=(I2V_SECONDS if video_format == "social" else I2V_SECONDS_LONGFORM),
                word_times=r.get("word_times"),
                evidence_states=r.get("evidence_states"),
                motion_state_ids=frozenset(state_motion_clips),
            ) if video_format != "social" else []
            if video_format != "social" and int(r["i"]) in frozen_opening_segments:
                frozen = frozen_opening_segments[int(r["i"])]
                if not _clip_is_real(frozen):
                    raise RuntimeError("approved opening segment is missing or invalid")
                scene_videos.append(frozen)
                scene_audios.append(r["aud"])
                rendered_narr.append(scene.get("narration", ""))
                if _shot_plan:
                    rendered_shot_plan.append(_shot_plan)
                log(f"Rendering scene {k+1}/{len(usable)} (frozen approved opening reused) ✓")
                continue
            _visual_source = _mv
            if len(_shot_plan) == 1 and _shot_plan[0].get("kind") == "i2v":
                _visual_source = state_motion_clips.get(_s(_shot_plan[0].get("state_id")))
            if len(_shot_plan) > 1:
                _visual_source = os.path.join(scene_dir, f"scene_{k:02d}_shots.mp4")
                _make_multishot_background(
                    r, _shot_plan, _visual_source, vw, vh, motion_video=_mv,
                    motion_videos=state_motion_clips, tail=FADE_DUR)
            source_label = (f"{len(_shot_plan)}-shot cut" if _shot_plan
                            else ('🎬 i2v animated clip' if _mv else motion))
            log(f"Rendering scene {k+1}/{len(usable)} ({source_label})...")
            _make_scene_segment(
                r["img"], r["aud"], seg,
                scene.get("text_overlay", ""),
                scene.get("text_sub", ""),
                motion=motion,
                tail=FADE_DUR,
                text_meta=scene.get("text"),
                style_mode=style_mode,
                vw=vw, vh=vh, captions=cap_mode, word_times=word_times,
                bubble_side=bubble_side,
                motion_video=_visual_source,
            )
            scene_videos.append(seg)
            scene_audios.append(r["aud"])
            rendered_narr.append(scene.get("narration", ""))
            if _shot_plan:
                rendered_shot_plan.append(_shot_plan)
        except Exception as exc:
            import traceback as _tb, sys as _sys
            print(f"[scene {k+1} render] {_tb.format_exc()}", file=_sys.stderr, flush=True)
            log(f"⚠ Scene {k+1} render failed ({type(exc).__name__}: {str(exc)[:80]}) — skipping")

    if not scene_videos:
        raise RuntimeError("Every scene failed to render — cannot assemble a video.")

    # Capture per-scene durations BEFORE the audio dir is reclaimed (for the transcript/SRT).
    rendered_durs = [_audio_dur(a) for a in scene_audios]
    rendered_count = len(scene_videos)
    shot_metrics = shot_plan_metrics(rendered_shot_plan) if rendered_shot_plan else {
        "shot_count": rendered_count, "still_shot_count": rendered_count - (
            len(i2v_clips) if video_format == "social" else len(state_motion_clips)),
        "i2v_shot_count": (len(i2v_clips) if video_format == "social"
                           else len(state_motion_clips)), "alternate_shot_count": 0,
        "avg_still_seconds": 0.0, "max_still_seconds": 0.0,
        "i2v_seconds": ((len(i2v_clips) * I2V_SECONDS) if video_format == "social"
                        else len(state_motion_clips) * I2V_SECONDS_LONGFORM),
    }
    if rendered_shot_plan:
        log("Visual cadence: %(shot_count)d shots, %(avg_still_seconds).2fs average still, "
            "%(max_still_seconds).2fs max still" % shot_metrics)
    if video_format != "social" and shot_metrics.get("motion_sync_ratio", 1.0) < 0.90:
        raise RuntimeError(
            f"Motion semantic alignment is {shot_metrics['motion_sync_ratio']:.0%}; 90% required.")
    full_audio_cues = build_audio_cues(
        [r["scene"] for r in usable if r["aud"] in scene_audios], rendered_durs)

    # 4. Assemble
    log("stage:Assembling final video...")
    output_path = os.path.join(output_dir, "explainer.mp4")
    _assemble(scene_videos, scene_audios, output_path, output_dir, bg_music_path,
              audio_cues=full_audio_cues)

    if video_format != "social" and opening_freeze:
        opening_freeze["final_reuse_validation"] = validate_frozen_opening(opening_freeze)
        opening_freeze["reused_scene_indices"] = sorted(frozen_opening_segments)
        if not opening_freeze["final_reuse_validation"]["passed"]:
            raise RuntimeError("Final edit did not preserve the approved opening assets.")
        with open(opening_freeze_path, "w") as handle:
            json.dump(opening_freeze, handle, indent=2, ensure_ascii=False)
        motion_plan["final_edit_metrics"] = shot_metrics
        motion_plan["opening_freeze_validation"] = opening_freeze["final_reuse_validation"]
        with open(motion_report_path, "w") as handle:
            json.dump(motion_plan, handle, indent=2, ensure_ascii=False)

    if video_format != "social":
        readiness = score_retention_readiness(
            script, retention_validation or {}, shot_metrics, full_audio_cues,
            preview=preview_state)
        readiness_report_path, readiness_json_path = write_readiness_report(readiness, output_dir)
        log(f"Final Retention Readiness: {readiness['score']}/100 "
            f"({readiness['grade']}) — {readiness['label']}")

    # 4b. Transcript + timed captions (.txt for description/auto-sync, .srt for YouTube subs).
    transcript_path, srt_path = _write_transcript(rendered_narr, rendered_durs, output_dir)
    log(f"Transcript + captions written ({len(rendered_narr)} cues)")

    # 4c. Ready-to-paste YouTube description (best-effort).
    full_transcript = " ".join(n.strip() for n in rendered_narr if n and n.strip())
    description_path = generate_description(
        script.get("title", question), script.get("hook", ""), full_transcript, output_dir,
        cost_sink=aux_costs, question=question, video_format=video_format,
        scene_narr=rendered_narr, scene_durs=rendered_durs)
    log("YouTube description written")

    # 4c-ii. Persist the social self-grade (if we graded one).
    grade_path = (_write_grade(short_grade, output_dir) if short_grade
                  else (readiness_report_path or retention_report_path))

    # 4d. Branded thumbnail (best-effort — never fail the video over a thumbnail).
    thumbnail_path = None
    _thumb_report: dict = {}
    try:
        log("stage:Generating thumbnail...")
        thumbnail_path = generate_thumbnail(
            script.get("title", question), question, style_mode, video_format, output_dir,
            cost_sink=img_costs, report=_thumb_report, transcript=full_transcript)
        if _thumb_report.get("fallback"):
            log("⚠ Thumbnail: image gen failed even after the safe-retry — BLANK fallback used")
        elif _thumb_report.get("qa") == "skipped":
            log("ℹ Thumbnail QA skipped (grader unavailable)")
        elif _thumb_report.get("weak"):
            log(f"⚠ Thumbnail graded WEAK ({_thumb_report.get('fails')}/8 checks failed after redesign)")
        else:
            log("Thumbnail ✓")
    except Exception as exc:
        log(f"⚠ Thumbnail generation failed ({type(exc).__name__}) — skipping")

    # 4d-ii. SOCIAL: burn the thumbnail onto the opening second so the Short's first frame IS the
    #        thumbnail (Shorts have no custom-thumbnail upload — the feed/grid sample a video frame).
    #        The spoken hook still plays under it; runtime unchanged. Best-effort.
    if video_format == "social" and thumbnail_path:
        try:
            if _overlay_opening_thumbnail(output_path, thumbnail_path, hold=1.0):
                log("Opening frame set to the thumbnail (Shorts) ✓")
        except Exception as exc:
            log(f"⚠ Could not set opening thumbnail frame ({type(exc).__name__})")

    # Reclaim disk: drop the bulky intermediates (images/audio/scene clips), keep the MP4 + text.
    import shutil as _sh
    for d in (img_dir, aud_dir, scene_dir):
        _sh.rmtree(d, ignore_errors=True)

    # ── ACTUAL cost (from real usage tokens), not the pre-spend estimate ──
    # img_costs: scene + thumbnail images + the thumbnail caption call.
    # aux_costs: grade + description Claude calls. script_cost: script + fact-check.
    script_cost = float(script.get("_script_cost_usd", 0.0) or 0.0)
    actual_cost = round(sum(img_costs) + sum(tts_costs) + sum(aux_costs)
                        + sum(i2v_costs) + script_cost, 2)

    # ── Quality floor: tell the truth about a degraded result instead of "done" ──
    try:
        final_dur = _audio_dur(output_path)
    except Exception:
        final_dur = 0.0
    if video_format != "social":
        runtime_tolerance = float(duration_sec) * 0.03
        if not final_dur or abs(final_dur - float(duration_sec)) > runtime_tolerance:
            raise RuntimeError(
                "Final natural-speed runtime gate failed: "
                f"{final_dur:.2f}s for a {duration_sec:.2f}s target "
                f"(allowed {duration_sec - runtime_tolerance:.2f}–"
                f"{duration_sec + runtime_tolerance:.2f}s)."
            )
    rendered = len(scene_videos)
    reasons = []
    if n and dropped / n > 0.25:
        reasons.append(f"{dropped}/{n} scenes dropped (no audio)")
    if rendered and filler / rendered > 0.25:
        reasons.append(f"{filler}/{rendered} scenes are filler frames")
    # Social shorts run punchy/short BY DESIGN (~30s for a 45s "target") — that's healthy for
    # Shorts, not degraded. Only flag a genuinely truncated one. Long-form keeps the strict 70%
    # floor (a 20-min that lands at 12-min IS broken).
    # Render faithfulness ≠ hitting the requested duration. The beat sheet now RIGHT-SIZES a topic
    # (anti-pad), so a narrow topic legitimately yields a shorter video — that is NOT degraded.
    # Flag degraded only if the RENDER lost a big chunk of the script's planned scenes (real truncation).
    planned = len(script.get("scenes", [])) or rendered
    if planned and rendered < 0.70 * planned:
        reasons.append(f"only {rendered}/{planned} planned scenes rendered")
    # Duration faithfulness. Right-sizing SHORTER than target is by-design (anti-pad beat sheet),
    # so a modestly-short video is INFO. But two cases ARE defects the old code hid behind "ok":
    #  (a) a SOCIAL short that runs LONG — its ~3s cadence is broken (the "5 seconds not 3" bug), and
    #  (b) any video that lands drastically short (<50% of target) — the topic/plan collapsed.
    if duration_sec and final_dur:
        if video_format == "social" and final_dur > 1.35 * duration_sec:
            reasons.append(f"short ran {final_dur:.0f}s vs {duration_sec}s target "
                           f"(~{final_dur / max(1, rendered):.1f}s/scene — cadence too slow for a Short)")
        elif final_dur < 0.50 * duration_sec:
            reasons.append(f"video ran {final_dur:.0f}s — far under the {duration_sec}s target")
        elif video_format != "social" and final_dur < 0.70 * duration_sec:
            log(f"ℹ Topic supported {final_dur:.0f}s of non-repetitive content (you targeted {duration_sec}s) "
                f"— the beat sheet right-sized it; use a broader topic or a shorter target for full length.")
    # i2v requested but EVERY clip fell back to Ken Burns.
    #  - LONG-FORM: motion is an optional enhancement, and Veo's monthly cap makes all-fallback routine —
    #    flagging it DEGRADED would train the operator to ignore the flag. So it stays an INFO note.
    #  - SOCIAL: motion is CENTRAL to a Short (the front-loaded hook clips + the whole retention premise).
    #    A zero-motion Short is a real quality miss and, with fal as a separate working quota, is now an
    #    anomaly (dead provider / missing key), not routine — so surface it as a DEGRADED reason instead
    #    of letting a silently-motionless short ship as "ok".
    actual_motion_count = len(i2v_clips) if video_format == "social" else len(state_motion_clips)
    if i2v_requested and not actual_motion_count:
        if video_format == "social":
            reasons.append(f"NO motion — all {i2v_requested} i2v clips fell back to Ken Burns "
                           f"(provider/key issue); a Short with zero motion is a retention risk")
        else:
            log(f"ℹ Motion skipped — all {i2v_requested} i2v clip(s) fell back to Ken Burns "
                f"(provider unavailable/quota); the video is complete, just without Veo motion.")
    # Engagement floor: the script/short graded below its gate but rendered anyway → say so.
    _g = script.get("_grade") or {}
    if _g.get("below_floor"):
        reasons.append(f"script graded {_g.get('overall')}/100 — below the {_SCRIPT_GATE_FLOOR} quality floor")
    if (short_grade and isinstance(short_grade, dict)
            and short_grade.get("overall", 100) < _SHORT_GATE_FLOOR):
        reasons.append(f"short graded {short_grade.get('overall')}/100 — below the {_SHORT_GATE_FLOOR} floor")
    if cap_mode in ("karaoke", "bubble", "headline_karaoke") and rendered and cap_missing / rendered > 0.25:
        label = "speech bubbles" if cap_mode == "bubble" else "captions"
        reasons.append(f"{cap_missing}/{rendered} scenes have NO {label}")
    if readiness and not readiness.get("passed"):
        log(f"ℹ Legacy metadata readiness is {readiness.get('score')}/100; PR5 rendered-contract "
            "pixels—not planner metadata—own the opening release decision.")
    # Thumbnail is the channel's #1 CTR lever — a blank fallback (image gen failed) is near-0 CTR, and
    # a still-weak thumbnail after redesign is a real click risk. Gate on both (grade_thumbnail was
    # previously advisory-only and never reached this list).
    if _thumb_report.get("fallback"):
        reasons.append("thumbnail is a BLANK fallback (image generation failed) — near-zero CTR")
    elif _thumb_report.get("weak"):
        reasons.append(f"thumbnail graded weak ({_thumb_report.get('fails')}/8 checks failed) — likely low CTR")
    status = "degraded" if reasons else "ok"

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    deg = f" ({dropped} dropped, {filler} filler)" if (dropped or filler) else ""
    log(f"Complete — {size_mb:.1f} MB, {rendered} scenes{deg}, actual ${actual_cost:.2f} (est ${est:.2f})")
    if status == "degraded":
        log("⚠ DEGRADED: " + "; ".join(reasons))

    generation_manifest["actual_motion"] = [
        {
            "state_id": item.get("state_id"),
            "provider": item.get("provider"),
            "model_id": item.get("model_id"),
            "generation_status": item.get("generation_status"),
            "configured_provider_models": [
                {"provider": provider, "model_id": _motion_model_id(provider)}
                for provider in _I2V_CHAIN
            ],
            "provider_attempts": item.get("provider_attempts") or [],
        }
        for item in (motion_plan.get("candidates") or []) if item.get("selected")
    ]
    generation_manifest["status"] = "completed"
    generation_manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    generation_manifest["output_sha256"] = sha256_file(output_path)
    _write_generation_manifest(generation_manifest_path, generation_manifest)

    return {
        "output_path":   output_path,
        "script":        script,
        "title":         script.get("title", question),
        "hook":          script.get("hook", ""),
        "scene_count":   rendered,
        "video_format":  video_format,
        "motion_mode":   resolved_motion_mode,
        "dropped":       dropped,
        "filler":        filler,
        "duration_sec":  round(final_dur, 1),
        "est_cost":      est,
        "actual_cost":   actual_cost,
        "status":        status,        # "ok" | "degraded"
        "degraded_reasons": reasons,
        "transcript_path": transcript_path,
        "srt_path":         srt_path,
        "description_path": description_path,
        "thumbnail_path":   thumbnail_path,
        "grade_path":       grade_path,
        "retention_json_path": retention_json_path,
        "research_report_path": research_report_path,
        "claim_report_path": claim_report_path,
        "audio_timing_report_path": audio_timing_report_path,
        "generation_manifest_path": generation_manifest_path,
        "evidence_plan_path": evidence_plan_path,
        "evidence_validation_path": evidence_validation_path,
        "continuity_pack_path": continuity_pack_path,
        "motion_report_path": motion_report_path,
        "opening_freeze_path": opening_freeze_path,
        "animatic_report_path": animatic_report_path,
        "animatic_preview_path": animatic_preview_path,
        "rendered_contract_path": rendered_contract_path,
        "rendered_contact_sheet_path": rendered_contact_sheet_path,
        "human_review_path": human_review_path,
        "story_format_review_path": story_format_review_path,
        "diagnostic_preview_path": diagnostic_preview_path,
        "readiness_report_path": readiness_report_path,
        "readiness_json_path": readiness_json_path,
        "first_minute_preview_path": first_minute_preview_path,
        "retention_readiness": readiness,
        "rendered_contract": rendered_contract,
        "short_grade":      short_grade,
        "i2v_requested":    i2v_requested,        # evidence states (long-form) or scenes (social)
        "i2v_animated":     actual_motion_count,
        "shot_metrics":     shot_metrics,
    }
