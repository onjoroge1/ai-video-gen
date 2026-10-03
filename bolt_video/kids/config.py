"""Immutable provider manifest and conservative allowances, not invoice price claims."""
from __future__ import annotations
import math
import os
from .models import Episode, OPERATION, POLICY_VERSION, canonical_hash


def providers():
    import fal_models
    endpoint = fal_models.resolve(os.environ.get("FAL_MODEL") or "kling-2.1-standard")
    if not fal_models.is_registered(endpoint):
        raise ValueError("Bolt Kids requires a registered motion model with a known cost allowance")
    # V1 supports one explicit motion provider. No model/provider fallback chain.
    return {"speech": "gpt-4o-mini-tts-2025-12-15", "song": "music_v2_5",
            "judge": "gpt-4.1-mini", "transcription": "whisper-1",
            "image": "gpt-image-2", "motion_provider": "fal", "motion": endpoint,
            "motion_resolution": os.environ.get("FAL_I2V_RESOLUTION") or "720p",
            "motion_rate_allowance": fal_models.rate_usd_per_sec(endpoint, os.environ.get("FAL_I2V_RESOLUTION") or "720p")}


def cost_cap():
    values = [float(os.environ.get(k) or d) for k,d in (
        ("KIDS_MAX_COST_USD","10"),("DURABLE_JOB_MAX_COST_USD",os.environ.get("MAX_VIDEO_COST_USD") or "10"))]
    if any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("Invalid deployment cost cap")
    return min(25, *values)


def build_payload(spec, ceiling):
    episode = Episode.model_validate(spec)
    if isinstance(ceiling, bool) or not math.isfinite(ceiling) or not 0 < ceiling <= cost_cap():
        raise ValueError("Kids cost ceiling exceeds the deployment limit")
    manifest = providers()
    speech = [c for b in episode.beats for c in b.audio if c.kind == "speech"]
    generated = [a for a in episode.assets if not a.reference_id]
    motion = [a for a in generated if a.mode == "motion"]
    import fal_models
    motion_calls = [fal_models.estimate_clip_usd(manifest["motion"], a.motion_seconds, manifest["motion_resolution"]) for a in motion]
    speech_calls = [max(.02,len(c.text)*.00004 + .002) for c in speech if not c.reference_id]
    song_calls = [max(.10, s.duration_sec/60*.50) for s in episode.songs if not s.reference_id]
    single_cap = float(os.environ.get("DURABLE_MAX_INFLIGHT_CALL_USD") or "1")
    if not math.isfinite(single_cap) or single_cap <= 0 or max([.15, *motion_calls, *speech_calls, *song_calls]) > single_cap:
        raise ValueError("Kids required provider call exceeds the deployment per-call reservation cap; select a supported model/budget before approval")
    allowances = {
        "speech": sum(speech_calls),
        "songs": sum(song_calls),
        "transcription": .012*(len(speech)+len(episode.songs)),
        "images": len(generated)*.10,
        "motion": sum(motion_calls),
        "reviews": .15*(2+len(episode.assets)+sum(a.mode=="motion" for a in episode.assets)+
                              sum(s.requires_motion for b in episode.beats for s in b.shots)),
    }
    estimate = round(sum(allowances.values()), 4)
    if estimate > ceiling:
        raise ValueError(f"Kids planning allowance ${estimate:.4f} exceeds the selected ceiling")
    return {"operation":OPERATION, "schema":"kids_authorization_v1", "policy_version":POLICY_VERSION,
            "scope":"single-120-second-kids-episode", "spec":episode.model_dump(mode="json"),
            "providers":manifest, "cost_ceiling_usd":ceiling, "max_inflight_call_usd":single_cap,
            "estimated_cost_usd":estimate, "allowances_usd":allowances,
            "estimate_basis":"Conservative provider allowances; no invoice precision or finished-video guarantee. Reused assets are not repurchased. Hosting is separate.",
            "repair_policy":"No automatic content regeneration. Infrastructure replay reuses completed stages; changed content requires a new approval.",
            "editorial_approval_required":True, "publish_to_youtube":False}


def authorize(envelope, expected_sha256, ceiling):
    if canonical_hash(envelope) != expected_sha256:
        raise ValueError("Kids authorization hash changed")
    rebuilt = build_payload(envelope.get("spec",{}),ceiling)
    if envelope != rebuilt:
        raise ValueError("Kids policy, provider configuration, content or budget changed; new approval required")
    return Episode.model_validate(envelope["spec"])


def readiness(episode=None):
    import blob_compat
    from media_binaries import ffmpeg, ffprobe
    missing = []
    needs = ["OPENAI_API_KEY", "DATABASE_URL"]
    if episode is not None:
        if any(not s.reference_id for s in episode.songs): needs.append("ELEVENLABS_API_KEY")
        if any(a.mode=="motion" and not a.reference_id for a in episode.assets): needs.append("FAL_KEY")
    for key in needs:
        if not os.environ.get(key," ").strip(): missing.append(key)
    if not blob_compat.enabled(): missing.append("Blob storage")
    try: ffmpeg(); ffprobe()
    except Exception: missing.append("FFmpeg/ffprobe")
    return {"configured":not missing, "missing_configuration":missing,
            "provider_quota_verified":False, "live_render_verified":False}
