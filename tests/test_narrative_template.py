"""Production contracts with fake provider responses, not claims of creative quality."""
from copy import deepcopy
import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

import explainer_pipeline as ep
import narrative_template as nt
import scene_expansion
import script_readiness
import script_revisions
import script_stages
import storyboard_repair
import durable_execution


def inputs():
    roles = ["setup", "intervention", "hinge", "mechanism", "escalation", "reversal", "tool"]
    beats = [{"n": i, "beat_id": f"event_{i:02d}", "role": role, "causal_role": role,
        "chapter": min(4, (i - 1) // 2 + 1), "scope": "primary_story",
        "event": {"text": f"Supported fact {i}.", "claim_refs": [f"c{i}"]},
        "_story_compiler_version": "story_compiler_v2",
        "caused_by": f"event_{i - 1:02d}" if i > 1 else ""}
        for i, role in enumerate(roles, 1)]
    beats[2].update(presentation_device="hinge", context_refs=["event_04"],
                    event={"text": "", "claim_refs": []})
    beats[-1].update(presentation_device="tool", context_refs=["event_01", "event_06"],
                    event={"text": "", "claim_refs": []})
    dossier = {"claims": [{"claim_id": f"c{i}", "claim": f"Supported fact {i}."} for i in range(1, 8)]}
    plan = {"title": "A supported story", "_spine": {"compiled": {"passed": True}, "beats": beats}}
    return plan, beats, dossier


def draft(beats):
    hook = "How did a rabbit remedy put kiwi chicks on the menu?"
    return {"hook_candidates": [hook, "The remedy came with an appetite.", "A pasture needed protecting."],
        "selected_hook": 0, "supported_answer": "Introduced predators also hunted native birds.",
        "callback_image": "kiwi chicks", "closing_question": "What else is on the menu?",
        "outline": [{"section": section, "new_contribution": purpose, "claim_ids": ["c1"]}
                    for section, purpose in nt.SECTIONS],
        "paragraphs": [{"paragraph_id": b["beat_id"], "narration": text} for b, text in zip(beats, [
            hook + " Rabbits ate the pasture.", "The settlers introduced predators.",
            "Those hunters ate more than rabbits.",
            "Predators moved into forests.  They found native birds there.\nThe forests held other prey.",
            "Researchers followed the chicks. Their observations documented the losses.",
            "The intervention exposed other wildlife to predation.",
            "A kiwi chick never ate the pasture. What else is on the menu?"])],
        "evidence_gaps": [], "editorial_weaknesses": []}


def generated(monkeypatch):
    plan, beats, dossier = inputs()
    value = draft(beats)
    create = Mock(return_value=NS(content=[NS(type="text", text=json.dumps(value))],
        stop_reason="end_turn", usage=NS(input_tokens=100, output_tokens=200)))
    monkeypatch.setattr(ep, "_claude", lambda: NS(messages=NS(create=create)))
    return nt.generate(plan, beats, dossier, "removed_keystone", "q", 180, 450), create


def test_continuous_writer_uses_one_call_and_original_evidence_units(monkeypatch):
    script, create = generated(monkeypatch)
    assert create.call_count == 1
    assert len(script["scenes"]) == 7 and script["_production_status"] == "unplanned"
    assert script["scenes"][0]["narration"].startswith(script["hook"])
    assert "_cold_open" not in script
    assert script["scenes"][0]["context_refs"] == ["event_02", "event_04", "event_06"]
    assert {r["claim_id"] for r in script["scenes"][0]["claim_refs"]} == {"c1", "c2", "c4", "c6"}
    assert len(script["_narrative_outline"]) == 7
    assert not ep._ensure_lead_spoken(script)
    assert all(b["beat_id"] for b in script["_story_contract"]["beats"])
    prompt = create.call_args.kwargs["messages"][0]["content"]
    assert all(b["beat_id"] in prompt for b in inputs()[1])
    assert "visual_beats" not in prompt and "production scenes" in prompt


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "reorder", "broken", "hook", "gap", "unknown_claim"])
def test_bad_drafts_cannot_look_complete(mutation):
    plan, beats, dossier = inputs()
    value = draft(beats)
    if mutation == "missing": value["paragraphs"].pop()
    if mutation == "duplicate": value["paragraphs"][-1] = value["paragraphs"][0]
    if mutation == "reorder": value["paragraphs"].reverse()
    if mutation == "broken": value["paragraphs"][3]["narration"] = "The hunters spread because."
    if mutation == "hook": value["paragraphs"][0]["narration"] = "Some other opening."
    if mutation == "gap": value["evidence_gaps"] = ["No outcome evidence"]
    if mutation == "unknown_claim": value["outline"][4]["claim_ids"] = ["invented"]
    with pytest.raises(ValueError, match="SEVEN_SECTION"):
        nt.validate_draft(value, nt.brief(plan, beats, dossier, "removed_keystone"))


def test_missing_consequence_fails_before_any_provider(monkeypatch):
    plan, beats, dossier = inputs()
    beats = [b for b in beats if b["role"] != "escalation"]
    provider = Mock(side_effect=AssertionError("must not spend"))
    monkeypatch.setattr(ep, "_claude", provider)
    with pytest.raises(ValueError, match="EVIDENCE_GAP.*consequences"):
        nt.generate(plan, beats, dossier, "removed_keystone", "q", 180, 450)
    assert not provider.called


def test_explicit_context_claims_are_in_the_brief():
    plan, beats, dossier = inputs()
    evidence = nt.brief(plan, beats, dossier, "removed_keystone")
    assert evidence["paragraphs"][2]["claim_ids"] == ["c4"]
    assert evidence["paragraphs"][-1]["claim_ids"] == ["c1", "c6"]


def test_lossless_split_keeps_punctuation_whitespace_ids_and_source_bindings(monkeypatch):
    script, _ = generated(monkeypatch)
    original = deepcopy(script)
    candidate = nt.split_for_production(script, max_words=7)
    nt.verify_projection(candidate)
    assert len(candidate["scenes"]) > len(script["scenes"])
    assert candidate["_narrative_document"]["text"] == "\n\n".join(s["narration"] for s in original["scenes"])
    assert len(set(s["scene_id"] for s in candidate["scenes"])) == len(candidate["scenes"])
    for scene in candidate["scenes"]:
        parent = next(s for s in original["scenes"] if s["paragraph_id"] == scene["paragraph_id"])
        assert scene["event"] == parent["event"]
        assert scene.get("context_refs", []) == parent.get("context_refs", [])
        assert scene["narration"][-1] in ".!?"


@pytest.mark.parametrize("mutation", ["rewrite", "omit", "duplicate", "reorder", "source", "span", "paragraph"])
def test_production_cannot_silently_change_approved_narration(monkeypatch, mutation):
    script, _ = generated(monkeypatch)
    candidate = nt.split_for_production(script, max_words=7)
    if mutation == "rewrite": candidate["scenes"][0]["narration"] += " More words."
    if mutation == "omit": candidate["scenes"].pop()
    if mutation == "duplicate": candidate["scenes"].insert(1, deepcopy(candidate["scenes"][0]))
    if mutation == "reorder": candidate["scenes"].reverse()
    if mutation == "source": candidate["_narrative_document"]["text"] += " More words."
    if mutation == "span": candidate["scenes"][0]["narration_span"]["end"] += 1
    if mutation == "paragraph": candidate["scenes"][0]["paragraph_id"] = "event_02"
    with pytest.raises(ValueError, match="NARRATION_PROJECTION_CHANGED"):
        nt.verify_projection(candidate)


def test_freeze_refuses_to_reseal_an_edit_or_missing_paragraph(monkeypatch):
    script, _ = generated(monkeypatch)
    nt.freeze(script)
    script["scenes"][0]["narration"] += " A change."
    with pytest.raises(ValueError, match="PROJECTION_CHANGED"):
        nt.freeze(script)
    script.pop("_narrative_document")
    script["scenes"].pop()
    with pytest.raises(ValueError, match="COVERAGE"):
        nt.freeze(script)


def test_frozen_visual_response_retries_only_the_changed_span():
    rows = [{"scene_id": "a", "narration": "The original line."},
            {"scene_id": "b", "narration": "The other line."}]
    seen = []
    def request(prompt, tool):
        seen.append(prompt)
        result = [rows[1], {**rows[0], "narration": "A rewrite."}] if len(seen) == 1 else [rows[0]]
        return NS(content=[NS(type="tool_use", name=scene_expansion.TOOL, input={"scenes": result})],
                  stop_reason="tool_use"), .01
    result, cost = scene_expansion.expand(rows, "visuals", request, preserve_narration=True)
    assert result == rows and cost == pytest.approx(.02)
    assert '"requested_scene_ids": ["a"]' in seen[1]


def test_completed_draft_is_reused_across_workers(tmp_path, monkeypatch):
    worker = NS(output_dir=str(tmp_path), checkpoint=Mock())
    monkeypatch.setattr(durable_execution, "current", lambda: worker)
    first, create = generated(monkeypatch)
    second = nt.generate(*inputs(), "removed_keystone", "q", 180, 450)
    assert second == first and create.call_count == 1


def test_child_draft_is_bound_to_parent_evidence_operation_and_cap(monkeypatch):
    script, _ = generated(monkeypatch)
    row = {"id": "parent", "kind": "explainer", "status": "error",
        "checkpoint": {"sha256": "checkpoint"},
        "request": {"question": "q", "duration_sec": 180, "visual_style": "illustrated_story"}}
    saved = {"script": script, "checkpoint_sha256": "checkpoint"}
    args = {"checkpoint_sha256": "checkpoint", "content_sha256": script_readiness.content_hash(script),
            "cost_ceiling_usd": 5}
    ident, request = script_revisions.prepare(row, saved, mode="redraft", **args)
    assert request["narrative_mode"] == nt.MODE and request["stop_after_script"]
    assert request["script_revision"]["script"] == script
    assert script_revisions.prepare(row, saved, mode="redraft", **args)[0] == ident
    assert script_revisions.prepare(row, saved, mode="evaluate", **args)[0] != ident
    assert script_revisions.prepare(row, saved, mode="redraft", **{**args, "cost_ceiling_usd": 4})[0] != ident
    request["script_revision"]["script"]["_research_dossier"]["claims"].pop()
    with pytest.raises(ValueError, match="content changed"):
        script_revisions.restore(request["script_revision"], stop_after_script=True)


def test_projection_preserves_an_editorial_review_only_for_the_same_text(monkeypatch):
    script, _ = generated(monkeypatch)
    nt.freeze(script)
    script["_final_retention_review"] = {"passed": True,
        "narration_sha256": storyboard_repair.story_identity(script)}
    def expand(rows, prompt, request, **kwargs):
        assert kwargs["preserve_narration"]
        return [{**r, "event": {"text": "untrusted rewrite"}, "image_prompt": "A supported illustration."}
                for r in rows], .1
    monkeypatch.setattr(scene_expansion, "expand", expand)
    candidate = nt.realize(script)
    nt.verify_projection(candidate)
    assert candidate["_final_retention_review"]["narration_sha256"] == storyboard_repair.story_identity(candidate)
    assert candidate["scenes"][0]["event"] == script["scenes"][0]["event"]
    script["_final_retention_review"]["narration_sha256"] = "stale"
    with pytest.raises(ValueError, match="REVIEW_STALE"):
        nt.realize(script)


def test_studio_pipeline_reviews_paragraphs_without_buying_shots_or_media(tmp_path, monkeypatch):
    import illustrated_story
    from test_script_contract_revisions import source
    script, _ = generated(monkeypatch)
    row, saved, args = source(script)
    _, request = script_revisions.prepare(row, saved, mode="evaluate", **args)
    forbidden = Mock(side_effect=AssertionError("Script-only attempted research, writing, visuals or media"))
    for name in ("_claude", "generate_research_dossier", "generate_graded_script", "compile_evidence_plan",
                 "compile_motion_plan", "generate_tts"):
        monkeypatch.setattr(ep, name, forbidden)
    monkeypatch.setattr(nt, "realize", forbidden)
    monkeypatch.setattr(ep, "factcheck_script", lambda script, *a: (script, [], 0))
    monkeypatch.setattr(ep, "_validate_claims", lambda *a, **k: {"passed": True, "errors": []})
    monkeypatch.setattr(ep, "duplicate_narration", lambda *a: [])
    monkeypatch.setattr(ep, "grade_script", lambda *a, **k: {"overall": 80,
        "scores": dict.fromkeys(("hook", "story", "ending", "repetition", "cadence"), 80)})
    monkeypatch.setattr(illustrated_story, "build_storyboard", lambda *a:
        {"validation": {"passed": True, "errors": []}, "beats": [], "visual_bible": {}})
    monkeypatch.setenv("RUNTIME_HARD", "0")
    with pytest.raises(ep.ScriptApprovalRequired):
        ep.run_explainer_pipeline("q", str(tmp_path), duration_sec=180, visual_style="illustrated_story",
            stop_after_script=True, narrative_mode="seven_section", script_revision=request["script_revision"])
    result = json.loads((tmp_path / "_state.json").read_text())["script"]
    assert result["_script_readiness"]["passed"]
    assert result["_script_readiness"]["production_planned"] is False
    nt.verify_projection(result)
    assert not forbidden.called


def test_old_duplicate_reversal_replans_from_the_same_ledger(monkeypatch):
    plan, beats, dossier = inputs()
    beats.insert(-1, {**deepcopy(beats[-2]), "beat_id": "another_reversal"})
    script = {"_spine": plan["_spine"], "_story_engine": "removed_keystone", "_research_dossier": dossier}
    seen = []
    def replan(*args, **kwargs):
        seen.append((ep._NARRATIVE_MODE.get(), kwargs))
        return {"_narrative_mode": "seven_section"}
    monkeypatch.setattr(ep, "generate_graded_script", replan)
    monkeypatch.setattr(nt.compiler, "presentation_beats", lambda *a: beats)
    assert nt.from_saved(script, "q", 180)["_narrative_mode"] == "seven_section"
    assert seen[0][0] == "seven_section" and seen[0][1]["research_dossier"] == dossier


def test_request_mode_is_restored_even_when_a_job_fails(tmp_path):
    before = ep._NARRATIVE_MODE.get()
    with pytest.raises(ValueError, match="ordinary illustrated"):
        ep.run_explainer_pipeline("q", str(tmp_path), narrative_mode="seven_section")
    assert ep._NARRATIVE_MODE.get() == before


def test_invalid_template_settings_are_rejected_before_enqueue(monkeypatch):
    import asyncio
    import app
    from fastapi import BackgroundTasks, HTTPException
    enqueue = Mock(side_effect=AssertionError("must not enqueue"))
    monkeypatch.setattr(app, "_enqueue_explainer_request", enqueue)
    with pytest.raises(HTTPException) as error:
        asyncio.run(app.explainer_generate(app.ExplainerRequest(question="q", narrative_mode="seven_section"),
                                          BackgroundTasks()))
    assert error.value.status_code == 400 and not enqueue.called


@pytest.mark.parametrize("yield_after_projection", [False, True])
@pytest.mark.parametrize("child_revision", [False, True])
def test_render_child_and_worker_resume_keep_approved_words(tmp_path, monkeypatch, yield_after_projection, child_revision):
    from test_script_contract_revisions import source
    realize = nt.realize
    test_studio_pipeline_reviews_paragraphs_without_buying_shots_or_media(tmp_path, monkeypatch)
    parent = json.loads((tmp_path / "_state.json").read_text())["script"]
    row, saved, args = source(parent, "awaiting_script_approval")
    row["request"]["narrative_mode"] = "seven_section"
    _, request = script_revisions.prepare(row, saved, mode="render", **args)
    monkeypatch.setattr(nt, "realize", realize)
    expansion = Mock(side_effect=lambda rows, *a, **k: (deepcopy(rows), .01))
    monkeypatch.setattr(scene_expansion, "expand", expansion)
    # This orchestration fixture uses symbolic claims; semantic provider/source
    # behavior is covered separately, not asserted by these transport tests.
    monkeypatch.setattr(ep, "validate_research_dossier", lambda *a: {"passed": True})
    monkeypatch.setattr(ep, "compile_evidence_plan", lambda *a:
        {"validation": {"passed": True}, "continuity_pack": {}, "scenes": []})
    monkeypatch.setattr(ep, "evidence_asset_counts", lambda *a: dict.fromkeys(
        ("planned_state_count", "distinct_source_count", "reframe_count", "exact_reuse_count"), 0))
    class AtMedia(Exception): pass
    class Yield(BaseException): pass
    monkeypatch.setattr(ep, "compile_motion_plan", Mock(side_effect=AtMedia))
    original_save = ep._save_script_checkpoint
    def save(*args, **kwargs):
        original_save(*args, **kwargs)
        if yield_after_projection and kwargs.get("label") == "narrative-production-planned":
            raise Yield()
    monkeypatch.setattr(ep, "_save_script_checkpoint", save)
    child = tmp_path / "render"
    if not child_revision:
        child.mkdir()
        (child / "_state.json").write_text(json.dumps({"script": parent, "style_mode": "educational"}))
    def run(resume=False):
        return ep.run_explainer_pipeline("q", str(child), duration_sec=180, max_cost_usd=10,
            visual_style="illustrated_story", narrative_mode="seven_section", resume=resume or not child_revision,
            script_revision=request["script_revision"] if child_revision else None)
    if yield_after_projection:
        with pytest.raises(Yield): run()
        calls = expansion.call_count
    with pytest.raises(AtMedia): run(resume=yield_after_projection)
    if yield_after_projection:
        assert expansion.call_count == calls
    result = json.loads((child / "_state.json").read_text())["script"]
    nt.verify_projection(result)
    assert result["_narrative_document"] == parent["_narrative_document"]
    assert result["_script_readiness"]["production_planned"] is True
    assert result["_script_readiness"]["passed"]
