"""Non-spending configuration checks for topic-based illustrated generation.

Credentials being present proves neither model access nor available quota. These
checks never instantiate a provider client or submit a generation request. Their
scope is the illustrated still-image path, which also requires native Anthropic
research when script generation has been switched to OpenAI.
"""

from __future__ import annotations

import os


def illustrated_provider_manifest() -> dict:
    """Return the actual pipeline's provider/model choices, without credentials.

    Import the renderer lazily so model IDs have one source of truth. Callers can
    bind this manifest to an approved request; configuration status and key values
    are deliberately absent because they are not part of the creative contract.
    """
    import explainer_pipeline as pipeline
    import script_provider

    selected = script_provider.active_provider()
    script = {
        "provider": selected,
        "model": (script_provider.openai_script_model()
                  if selected == script_provider.OPENAI else pipeline.ANTHROPIC_MODEL),
    }
    if selected == script_provider.OPENAI:
        script.update(reasoning_effort=script_provider.reasoning_effort(),
                      reasoning_headroom=script_provider.reasoning_headroom())
    return {
        "research": {"provider": "anthropic", "model": pipeline.ANTHROPIC_MODEL},
        "script": dict(script),
        "visual_qa": dict(script),
        "images": {"provider": "openai", "model": pipeline.IMAGE_MODEL},
        "narration": {"provider": "openai", "model": pipeline.TTS_MODEL},
        "word_timing": {"provider": "openai", "model": pipeline.TRANSCRIPTION_MODEL},
    }


def illustrated_provider_readiness() -> dict:
    """Report missing configuration without implying a paid render was verified."""
    report = {
        "configured": False,
        "scope": "topic_illustrated_stills",
        "readiness_scope": "configuration_only",
        "generation_verified": False,
        "model_access": "not_checked",
        "quota": "not_checked",
        "stages": {},
        "missing_configuration": [],
        "warnings": [],
    }
    try:
        manifest = illustrated_provider_manifest()
    except Exception as exc:
        # Invalid renderer configuration or a missing packaged dependency must
        # block readiness. Avoid returning exception messages containing paths,
        # credentials or other private deployment data.
        report["missing_configuration"] = ["illustrated_pipeline"]
        report["pipeline_error"] = type(exc).__name__
        return report

    required_keys = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
    missing = set()
    for purpose, choice in manifest.items():
        key_env = required_keys[choice["provider"]]
        credential_configured = bool(os.environ.get(key_env, "").strip())
        model_configured = bool(str(choice.get("model") or "").strip())
        if not credential_configured:
            missing.add(key_env)
        if not model_configured:
            missing.add(f"{purpose}.model")
        report["stages"][purpose] = {
            **choice,
            "key_env": key_env,
            "credential_configured": credential_configured,
            "model_configured": model_configured,
            "configured": credential_configured and model_configured,
            "model_access": "not_checked",
            "quota": "not_checked",
        }

    requested = os.environ.get("SCRIPT_PROVIDER", "").strip().lower()
    if requested and requested not in required_keys:
        # active_provider() intentionally falls back to Anthropic. Surface that
        # behavior without copying arbitrary environment values into the response.
        report["warnings"].append("Unrecognized SCRIPT_PROVIDER falls back to anthropic.")
    report["missing_configuration"] = sorted(missing)
    report["configured"] = not missing
    return report
