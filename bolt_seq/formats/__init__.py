"""Formats layer (GENERIC). A FORMAT is a retention structure, independent of any topic: the palette
of beat ROLES it uses, which roles are mandatory, the default motion axis, and the entity kinds it
expects. Topics pick one or more formats and assign a role to each sequence block; the orchestrator
checks the block roles against the composed palette.

Cloud is `physical_experiment` (+ `mystery_reversal`); oxygen is `goal_chase` + `countdown`;
train is `physical_experiment` + `countdown`. None of that is topic-specific code — it is data."""
from __future__ import annotations

REGISTRY = {
    "physical_experiment": {
        "axis": "vertical",
        "roles": ["hook", "setup", "action", "result", "mechanism", "loop"],
        "required": ["hook", "result", "mechanism"],
        "entity_hints": ["character", "environment", "particles"],
        "note": "subject a thing to a force and show what physically happens",
    },
    "goal_chase": {
        "axis": "horizontal",
        "roles": ["hook", "pursuit", "obstacle", "near_miss", "resolution", "loop"],
        "required": ["hook", "pursuit", "resolution"],
        "entity_hints": ["character", "destination", "environment", "camera"],
        "note": "protagonist races toward a visible goal that grows closer",
    },
    "countdown": {
        "axis": "stationary",
        "roles": ["hook", "drain", "threshold_warning", "climax", "resolution"],
        "required": ["drain", "climax"],
        "entity_hints": ["meter"],
        "note": "a finite resource drains under time pressure (usually a HUD layer over another format)",
    },
    "mystery_reversal": {
        "axis": "stationary",
        "roles": ["hook", "obvious_answer", "but_wait", "reveal", "loop"],
        "required": ["hook", "reveal"],
        "entity_hints": ["character"],
        "note": "pose a question, tease the obvious answer, overturn it",
    },
    "escalation": {
        "axis": "radial",
        "roles": ["hook", "level1", "level2", "level3", "peak", "loop"],
        "required": ["hook", "peak"],
        "entity_hints": ["character", "effect"],
        "note": "same event repeated at rising intensity",
    },
    "transformation": {
        "axis": "stationary",
        "roles": ["hook", "before", "trigger", "change", "after", "loop"],
        "required": ["before", "after"],
        "entity_hints": ["character", "effect"],
        "note": "one subject visibly changes state over time",
    },
    "comparison": {
        "axis": "stationary",
        "roles": ["hook", "side_a", "side_b", "verdict", "loop"],
        "required": ["side_a", "side_b", "verdict"],
        "entity_hints": ["prop", "meter"],
        "note": "two options weighed side by side",
    },
    "quiz": {
        "axis": "stationary",
        "roles": ["question", "options", "guess_gate", "answer", "next"],
        "required": ["question", "answer"],
        "entity_hints": ["prop"],
        "note": "ask, invite a guess, reveal",
    },
}


def select(names):
    """Compose one or more formats → {axis, roles(palette), required, entity_hints, formats}.
    Axis comes from the first named format; palettes and requirements are unioned."""
    names = [names] if isinstance(names, str) else list(names)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise KeyError(f"unknown format(s): {unknown}")
    palette, required, hints = [], [], []
    for n in names:
        for r in REGISTRY[n]["roles"]:
            if r not in palette:
                palette.append(r)
        required += [r for r in REGISTRY[n]["required"] if r not in required]
        hints += [h for h in REGISTRY[n]["entity_hints"] if h not in hints]
    return {"formats": names, "axis": REGISTRY[names[0]]["axis"],
            "roles": palette, "required": required, "entity_hints": hints}


def validate_structure(blocks, structure):
    """Advisory retention check: every block role must be in the palette, and every required role must
    appear. Returns {ok, errors, used_roles, missing_required, unknown_roles}."""
    used = [b.get("role") for b in blocks if b.get("role")]
    unknown = sorted({r for r in used if r not in structure["roles"]})
    missing = [r for r in structure["required"] if r not in used]
    errs = []
    if unknown:
        errs.append(f"block roles not in palette {structure['formats']}: {unknown}")
    if missing:
        errs.append(f"required roles missing: {missing}")
    return {"ok": not errs, "errors": errs, "used_roles": used,
            "missing_required": missing, "unknown_roles": unknown}
