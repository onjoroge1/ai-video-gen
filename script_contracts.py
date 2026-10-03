"""Identity of the actual text provider and the acceptance policy. No provider calls."""


def model_identity():
    import explainer_pipeline as ep
    import script_provider
    provider = script_provider.active_provider()
    return {"provider": provider, "model": (script_provider.openai_script_model()
            if provider == script_provider.OPENAI else ep.ANTHROPIC_MODEL)}


def acceptance_policy():
    import claim_entailment
    import explainer_pipeline as ep
    import hook_callback
    import script_cadence
    import script_integrity
    return {"version": "script_acceptance_v2", **model_identity(),
            "entailment": claim_entailment.ENTAILMENT_CONTRACT_VERSION,
            "integrity": script_integrity.VERSION, "cadence": script_cadence.VERSION,
            "hook": hook_callback.VERSION, "grade_target": ep._SCRIPT_GATE_PASS,
            "grade_floor": ep._SCRIPT_GATE_FLOOR, "runtime_hard": ep._runtime_is_enforced()}
