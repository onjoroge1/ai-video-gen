"""A pending rendered-opening review blocks resume only when the run's gate was live.

Measured on the emperor penguin long-form (2026-09-24): the stable_standard_longform profile
logged "[HUMAN REVIEW, advisory] skipping editorial approval" and bought 31 of 45 images before
the Anthropic balance ran out; the resume endpoint then refused with "Complete and approve the
rendered-opening checklist" -- an approval the run itself had never waited for.
"""
import json
import os

import app


def _manifest(tmp_path, **fields):
    with open(os.path.join(tmp_path, "generation_manifest.json"), "w", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, **fields}, handle)


def test_advisory_profile_does_not_block(tmp_path, monkeypatch):
    monkeypatch.delenv("DIAGNOSTIC_RENDER", raising=False)
    _manifest(tmp_path, pipeline_profile="stable_standard_longform")
    assert app._pending_review_blocks_resume(str(tmp_path)) is False


def test_live_gate_profile_blocks(tmp_path, monkeypatch):
    monkeypatch.delenv("DIAGNOSTIC_RENDER", raising=False)
    _manifest(tmp_path, creative_lane="illustrated_story_v1")
    assert app._pending_review_blocks_resume(str(tmp_path)) is True


def test_missing_or_broken_manifest_blocks(tmp_path, monkeypatch):
    monkeypatch.delenv("DIAGNOSTIC_RENDER", raising=False)
    assert app._pending_review_blocks_resume(str(tmp_path)) is True
    with open(os.path.join(tmp_path, "generation_manifest.json"), "w") as handle:
        handle.write("{not json")
    assert app._pending_review_blocks_resume(str(tmp_path)) is True


def test_diagnostic_render_never_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_RENDER", "1")
    assert app._pending_review_blocks_resume(str(tmp_path)) is False
