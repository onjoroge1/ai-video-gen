"""Topics layer (GENERIC loader; each topic is pure config/data). A topic never contains rendering
code — it names formats, declares state variables + constraints, an entity graph, state→visual
bindings, and the sequence blocks. The generic orchestrator turns any topic dict into an animatic
(or, for a config-only topic, a planning report). Adding a topic = adding a data module here.

Canonical TOPIC schema (all topics return this from build()):
{
  "title": str, "subject": str, "duration_target_s": int,
  "formats": [format_name, ...],                     # -> formats.select()
  "narration_lines": [str, ...], "captions": [str, ...],
  "render": bool,                                    # False = config-only planning (train)
  "state_vars": {var: {"kind","start","end","note"}},
  "constraints": [ {kind, ...}, ... ],               # -> continuity (declarative)
  "entities": [ entity_dict, ... ],                  # -> scene_graph (global defs + asset specs)
  "bindings": [ {state, entity, channel, remap|map, ...}, ... ],   # -> bindings (state drives visuals)
  "blocks": [ {id, role, lines:[i,...], start_state:{}, end_state:{},
               entity_overrides:{eid:{...}}, overlays:[effect_entity,...]}, ... ],
  "acceptance": {perceptual thresholds + hard invariants},
}"""
from __future__ import annotations
import importlib

_TOPICS = {
    "cloud_landing": "bolt_seq.topics.cloud_landing",
    "oxygen_subscription": "bolt_seq.topics.oxygen_subscription",
    "train_stopping": "bolt_seq.topics.train_stopping",
}


def load(name):
    if name not in _TOPICS:
        raise KeyError(f"unknown topic '{name}'; known: {sorted(_TOPICS)}")
    return importlib.import_module(_TOPICS[name]).build()


def list_topics():
    return sorted(_TOPICS)
