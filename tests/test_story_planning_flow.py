"""Production compiler and expansion wiring with explicit, deterministic provider responses.

These tests establish control flow, not real-model accuracy or historical sourcing quality.
"""
from collections import Counter
from copy import deepcopy
import json
import re
from types import SimpleNamespace

import pytest

import claim_entailment as ce
from cost_ledger import CostLedger
import event_functions as ef
import explainer_pipeline as ep
import illustrated_story
import longform_research as research
import story_compiler as compiler
import story_fact_model as facts
import story_planning


def factual_fixture(*, wrong_citation=False, narrow=False):
    texts = ["Hanoi had an unwanted rat infestation.",
             "Authorities introduced a bounty for rat tails.",
             "Tail submissions climbed into the thousands.",
             "Residents cut tails from living rats and released them.",
             "People bred rats to earn the tail bounty.",
             "Officials intended to reduce the rat population.",
             "Payment required a rat tail as proof."]
    claims = {f"c{i}": {"claim_id": f"c{i}", "claim": text, "support_quote": text,
                       "claim_kind": "context" if i == 6 else "event",
                       "claim_kind_confidence": .99, "confidence": "high",
                       "source_url": f"https://fixture.example.edu/hanoi/{i}",
                       "source_type": "primary", "geographic_scope": "Hanoi",
                       "timescale": "during the bounty", "assumptions": [],
                       "allowed_exaggeration": False, "material": True}
              for i, text in enumerate(texts, 1)}
    states = [("rats live in the city", "Hanoi has an unwanted rat infestation"),
              ("rats have no bounty", "rat tails carry a bounty"),
              ("few tail submissions", "thousands of tails are submitted"),
              ("rats are killed", "living rats are released after their tails are cut"),
              ("rats are unwanted", "people deliberately breed rats for the bounty")]
    beats = [{"beat_id": f"fact_{i}", "n": i, "beat": text, "event_function": function,
              "event": {"text": text, "claim_refs": [f"c{i}"]},
              "changes_state": {"from": states[i - 1][0], "to": states[i - 1][1]},
              "scope": "primary_story", "caused_by": i - 1}
             for i, (function, text) in enumerate(zip(ef.BACKFIRING_SOLUTION.required, texts), 1)]
    beats[1]["incentive"] = {"rewarded_measure": "a rat tail",
                             "measure_claim_refs": ["c3" if wrong_citation else "c7"],
                             "stated_policy_goal": "fewer rats",
                             "goal_claim_refs": ["c6"]}
    if narrow:
        beats[0]["event"]["text"] = beats[0]["beat"] = "In 1902, " + texts[0]
    return beats, claims


@pytest.fixture(autouse=True)
def _state_once_is_not_under_test(monkeypatch):
    """STATE-ONCE now runs on fact-model scripts, and these tests are about the fact flow.

    Left live it adds a provider call these fixtures do not stub, so the strict
    unexpected-request guard fires on a pass that has nothing to do with what they assert.
    """
    import explainer_pipeline
    monkeypatch.setattr(explainer_pipeline, "_dedupe_narration",
                        lambda scenes, beats, throughline: (scenes, 0.0))

class EvidenceFixture:
    def __init__(self, *, reject_relationship="", unavailable=False):
        self.calls = []
        self.reject_relationship = reject_relationship
        self.unavailable = unavailable

    def __call__(self, payload):
        self.calls.append({k: deepcopy(v) for k, v in payload.items() if k != "cost_sink"})
        if payload.get("cost_sink") is not None:
            payload["cost_sink"].append(.01)
        if self.unavailable:
            raise RuntimeError("fixture outage")
        if payload["kind"] == "relationship":
            rejected = self.reject_relationship and self.reject_relationship in payload["event"]
            return {"verdict": "unsupported" if rejected else "entailed",
                    "reason": "fixture relationship decision"}
        if payload["kind"] == "fidelity":
            return {"verdict": "unsupported" if "secret overnight" in payload["narration"]
                    else "entailed", "reason": "fixture fidelity decision"}
        if payload["event"].startswith("In 1902,"):
            return {"verdict": "partially_entailed", "supported_core": payload["event"][9:],
                    "unsupported_details": ["the year 1902"], "reason": "year is absent"}
        if payload["event"].startswith("The reward was paid"):
            supported = {c["claim_id"] for c in payload["claims"]} == {"c7"}
            return {"verdict": "entailed" if supported else "unsupported",
                    "reason": "tail counts do not evidence accepted proof"}
        return {"verdict": "entailed", "reason": "fixture factual decision"}


def recite(beats, concerns, claims, question, *, cost_sink):
    assert len(concerns) == 1 and "tail counts" in concerns[0]["why"]
    cost_sink.append(.03)
    next(b for b in beats if b["beat_id"] == concerns[0]["beat_id"])["incentive"][
        "measure_claim_refs"] = ["c7"]
    return beats, .03


def test_real_cascade_reaches_repair_rejudges_only_changed_inputs_and_accounts_once(tmp_path):
    beats, claims = factual_fixture(wrong_citation=True, narrow=True)
    untouched = deepcopy(beats)
    judge = EvidenceFixture()
    ledger = CostLedger(str(tmp_path / "cost.json"))
    result = story_planning.prepare(beats, "backfiring_solution", claims,
                                   judge=judge, repair=recite, cost_sink=ledger)
    compiled = result["compiled"]
    assert compiled["passed"], facts.spine_summary(result["beats"], compiled)
    assert beats == untouched
    assert compiled["citation_repairs"] == [dict(beat_id="fact_2", attempted=True, changed=True,
        reason="measure unsupported: tail counts do not evidence accepted proof ")]
    assert len({b["beat_id"] for b in result["beats"]}) == len(result["beats"]) == 6
    assert sum(b.get("derived", False) for b in result["beats"]) == 1
    assert result["beats"][0]["event"]["text"] == claims["c1"]["claim"]
    assert result["beats"][0]["beat"] == claims["c1"]["claim"]
    counts = Counter((c["kind"], c["event"]) for c in judge.calls)
    assert counts[("evidence", "The reward was paid for a rat tail.")] == 2
    assert counts[("evidence", "The goal was fewer rats.")] == 1
    assert sum(c["kind"] == "function" for c in judge.calls) == 1  # narrowed setup still does its job
    assert len(judge.calls) == 11  # events + assertions + changed assertion + relations + function
    assert result["cost_usd"] == pytest.approx(.14)
    assert ledger.by_stage() == {"boundary_a_evidence": .11, "causal_spine": .03}
    assert json.loads((tmp_path / "cost.json").read_text())["total_usd"] == .14
    replay = story_planning.prepare(result["beats"], "backfiring_solution", claims,
                                    judge=judge, cache=result["cache"])
    assert replay["compiled"]["passed"] and replay["cost_usd"] == 0
    assert len(replay["beats"]) == 6 and len(judge.calls) == 11


@pytest.mark.parametrize("state", ["Hanoi has an unwanted rat infestation near the river",
                                   "colonial budgets tightened"])
def test_different_words_do_not_certify_a_material_inversion(state):
    beats, claims = factual_fixture()
    beats[-1]["changes_state"]["to"] = state
    judge = EvidenceFixture(reject_relationship="material")
    result = story_planning.prepare(beats, "backfiring_solution", claims, judge=judge)
    assert not result["compiled"]["passed"]
    assert any(r["kind"] == "behavior_inversion" and not r["passed"]
               for r in result["compiled"]["relationships"])


def test_an_unavailable_judge_does_not_trigger_content_repair_or_pass():
    beats, claims = factual_fixture(wrong_citation=True)
    def forbidden(*args, **kwargs):
        pytest.fail("an outage must not purchase a rewrite")
    result = story_planning.prepare(beats, "backfiring_solution", claims,
                                   judge=EvidenceFixture(unavailable=True), repair=forbidden)
    assert not result["compiled"]["passed"]
    assert not result["compiled"]["coverage"]["covered"]
    assert result["compiled"]["cascade"]["unavailable"] and not result["cache"]


def test_a_contradicted_policy_assertion_stops_without_citation_shopping():
    beats, claims = factual_fixture(wrong_citation=True)
    fixture = EvidenceFixture()
    def judge(payload):
        result = fixture(payload)
        return ({"verdict": "contradicted", "reason": "policy purpose contradicts the claim"}
                if payload["event"].startswith("The goal was") else result)
    def forbidden(*args, **kwargs):
        pytest.fail("contradiction must stop without buying replacement citations")
    result = story_planning.prepare(beats, "backfiring_solution", claims, judge=judge, repair=forbidden)
    assert not result["compiled"]["passed"] and not result["compiled"]["citation_repairs"]


def test_a_paid_json_repair_is_recorded_even_when_its_reply_is_unusable(monkeypatch, tmp_path):
    from cost_ledger import StageCostSink, BEAT_SHEET
    response = SimpleNamespace(content=[SimpleNamespace(text="still not JSON")],
                               usage=SimpleNamespace(input_tokens=100, output_tokens=100))
    monkeypatch.setattr(ep, "_claude", lambda: SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kwargs: response)))
    ledger = CostLedger(str(tmp_path / "failed.json"))
    with pytest.raises(json.JSONDecodeError):
        ep._parse_script_json("not JSON", cost_sink=StageCostSink(ledger, BEAT_SHEET))
    assert ledger.total() == pytest.approx(ep._msg_cost(response.usage))
    assert json.loads((tmp_path / "failed.json").read_text())["total_usd"] == ledger.total()


def test_an_invalid_judge_response_is_not_cached(monkeypatch):
    replies = iter([{}, {"verdict": "entailed"}])
    cache = {}
    _, claims = factual_fixture()
    judge = lambda payload: next(replies)
    args = ([claims["c1"]], claims["c1"]["claim"])
    assert ce.evidence_entailment(*args, judge=judge, cache=cache)["verdict"] == "invalid_response"
    assert not cache
    assert ce.evidence_entailment(*args, judge=judge, cache=cache)["passed"]


def expanded_fixture(monkeypatch, *, wrong_citation=True, narrow=True, judge_fixture=None):
    """Run the real planner caller and expansion, replacing only provider responses."""
    beats, claims = factual_fixture(wrong_citation=wrong_citation, narrow=narrow)
    dossier = {"version": 1, "topic": "Hanoi rat bounty", "claims": list(claims.values()),
               "citation_urls": [c["source_url"] for c in claims.values()],
               "citation_records": [{"url": c["source_url"], "cited_text": c["claim"]}
                                    for c in claims.values()]}
    judge = judge_fixture or EvidenceFixture()
    prompts = []

    def create(**call):
        prompt = call["messages"][0]["content"]
        prompts.append(prompt)
        if "Plan the sourced factual events" in prompt:
            value = {"title": "Hanoi rat bounty", "hook": "Why did Hanoi's rat bounty backfire?",
                     "throughline": "Rat tails versus rats", "opening_object": "rat tail",
                     "recurring_location": "Hanoi",
                     "final_callback_object": "rat tail", "accepted_belief": "Rats should be eliminated.",
                     "subject_goal": "Reduce the rat population", "beats": beats}
        elif "THE FULL CLAIM LEDGER:" in prompt:
            assert "the goal was: fewer rats" in prompt
            assert "tail counts do not evidence accepted proof" in prompt
            value = {"measure_claim_refs": ["c7"], "goal_claim_refs": ["c6"]}
        elif "NOW WRITE scenes" in prompt:
            assert not judge.unavailable, "expansion was purchased without an evidence verdict"
            sheet = [json.loads(line) for line in prompt.splitlines()
                     if line.startswith('{"n":')]
            sheet = list({b["n"]: b for b in sheet}.values())
            lo, hi = map(int, re.search(r"NOW WRITE scenes (\d+)-(\d+)", prompt).groups())
            value = {"scenes": []}
            for b in sheet:
                if not lo <= b["n"] <= hi:
                    continue
                text = b["event"].get("text") or {
                    "hinge": "Except the reward could preserve the problem.",
                    "tool": "Look at that rat tail. What does your reward actually measure, and "
                            "could someone collect it while leaving the problem alive?"}[b["presentation_device"]]
                text += {
                    "mechanism": " A tail was the proof that earned payment. Fewer rats was the "
                        "intended result. Those are different things: a tail can be handed over "
                        "while the animal that grew it remains alive.",
                    "escalation": " A living rat could lose its tail and still be released. "
                        "The proof went one way; the living animal went another. A submitted "
                        "tail therefore did not necessarily mean a rat had been eliminated.",
                    "reversal": " Breeding rats produced animals whose tails could earn a bounty. "
                        "The policy began with a rat problem that officials wanted reduced. "
                        "Now people were deliberately producing the very animals that the "
                        "programme was intended to remove.",
                }.get(b["causal_role"], "")
                value["scenes"].append({"narration": text, "image_prompt": "A rat beside a tail counter.",
                    "scene_type": "real_world_example", "environment_type": "city",
                    "text_overlay": "", "text_sub": "", "shot_type": "medium"})
        else:
            pytest.fail("unexpected language-model request: " + prompt[:100])
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(value))],
                               usage=SimpleNamespace(input_tokens=10, output_tokens=10))

    monkeypatch.setattr(ep, "_claude", lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))
    monkeypatch.setattr(ce, "_default_judge", judge)
    ledger = CostLedger()
    script = ep._generate_script_chunked("Hanoi rat bounty", 90, "engaging", "", 8,
        causal_lane=True, pinned_engine="backfiring_solution", research_dossier=dossier,
        cost_sink=ledger)
    return script, dossier, judge, prompts, ledger


def test_the_production_caller_refuses_expansion_when_the_judge_is_unavailable(monkeypatch):
    with pytest.raises(facts.StorySpineUnsupported):
        expanded_fixture(monkeypatch, judge_fixture=EvidenceFixture(unavailable=True))


def test_accepted_facts_reach_expansion_fidelity_and_storyboard(monkeypatch):
    script, dossier, judge, prompts, ledger = expanded_fixture(monkeypatch)
    assert script["_compiled_story"]
    scenes = script["scenes"]
    assert [s["causal_role"] for s in scenes] == ["setup", "intervention", "false_resolution",
                                                  "hinge", "mechanism", "escalation", "reversal", "tool"]
    assert "1902" not in prompts[-1] and "1902" not in scenes[0]["event"]["text"]
    assert {r["claim_id"] for r in scenes[4]["claim_refs"]} == {"c2", "c4", "c6", "c7"}
    assert scenes[4]["derivation"]["source_ids"] == ["fact_2"]
    assert scenes[4]["caused_by"] == scenes[1]["scene_id"]
    assert scenes[3]["context_refs"] == [scenes[4]["beat_id"], scenes[5]["beat_id"]]
    assert all(s["caused_by"] in {b["scene_id"] for b in scenes[:i]}
               for i, s in enumerate(scenes) if i)
    cascade = research.validate_story_fact_model(script, dossier, judge=judge,
                                                 cache=script["_entailment_cache"])
    assert cascade["passed"], cascade
    # One per scene, plus the hook — which is judged against the union of the supported events
    # rather than against whichever beat it happens to be prepended to.
    assert len([c for c in judge.calls if c["kind"] == "fidelity"]) == len(scenes) + 1
    board = illustrated_story.build_storyboard(script, script["title"])
    assert board["validation"]["passed"], board["validation"]
    assert script["_script_cost_usd"] == pytest.approx(ledger.script_stage_total())
    scenes[3]["narration"] = "Hundreds of secret overnight rat farms appeared."
    rejected = research.validate_story_fact_model(script, dossier, judge=judge,
                                                  cache=script["_entailment_cache"])
    assert not rejected["passed"] and any(e["code"] == "NARRATION_EXCEEDS_EVENT"
                                          for e in rejected["errors"])


def test_acceptance_requires_positive_current_evidence_and_relationships(monkeypatch):
    from scripts.role_variance import acceptance_rows
    beats, claims = factual_fixture()
    prepared = story_planning.prepare(beats, "backfiring_solution", claims, judge=EvidenceFixture())
    payload = {"samples": [{"sample": 1, "spine": {
        "beats": prepared["beats"], "compiled": prepared["compiled"]}}]}
    rows, _ = acceptance_rows([payload])
    assert rows[0]["joint"]
    stale = deepcopy(payload)
    stale["samples"][0]["spine"]["compiled"]["effective_beats"][0]["event"]["text"] += " overnight"
    rows, _ = acceptance_rows([stale])
    assert not rows[0]["joint"]
    stale_state = deepcopy(payload)
    stale_state["samples"][0]["spine"]["compiled"]["effective_beats"][-1]["changes_state"][
        "to"] = "rats are unwanted near the river"
    assert not acceptance_rows([stale_state])[0][0]["joint"]
    unavailable = deepcopy(payload)
    unavailable["samples"][0]["spine"]["compiled"]["passed"] = False
    unavailable["samples"][0]["spine"]["compiled"]["cascade"]["unavailable"] = [{"beat_id": "fact_1"}]
    assert not acceptance_rows([unavailable])[0][0]["joint"]


def test_a_role_contract_failure_gets_the_sentence_repair_not_the_citation_one(monkeypatch):
    """The two complaints need opposite edits, and only one repair can make either.

    Measured on Macquarie: the mechanism "bundles in an unrelated peak-population figure not needed
    for the function" and the reversal "does not specify the new ecological state". The first needs
    the sentence trimmed, the second extended. Neither is a question about which claim was cited,
    so the citation repair buys a call that cannot answer them.
    """
    import explainer_pipeline as ep

    claims = {"m1": {"claim": "Cats preyed on the island's rabbits as well as its seabirds.",
                     "verified": True, "quote_verified": True}}
    beats = [{"beat_id": "k3", "role": "mechanism",
              "event": {"text": "Cats had also preyed on rabbits, which peaked at 130,000 in 1978.",
                        "claim_refs": ["m1"]},
              "incentive": {}}]
    concerns = [{"beat_id": "k3", "role": "mechanism",
                 "why": "bundles in an unrelated peak-population figure"}]
    seen = {}

    class _Messages:
        def create(self, **call):
            seen["prompt"] = call["messages"][0]["content"]
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 300, "output_tokens": 40})(),
                "content": [type("C", (), {
                    "text": '{"text":"Cats had also preyed on the rabbits.","unchanged":false}'})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    out, cost = ep._repair_event_text(beats, concerns, claims, "Why?")
    assert cost > 0
    assert out[0]["event"]["text"] == "Cats had also preyed on the rabbits."
    assert out[0]["event"]["claim_refs"] == ["m1"], "citations are frozen while prose is repaired"
    assert "bundles in an unrelated peak-population figure" in seen["prompt"]
    assert "THE ONLY CLAIMS THIS BEAT STANDS ON" in seen["prompt"]
    assert "Prefer cutting" in seen["prompt"]


def test_the_sentence_repair_will_not_invent_what_no_claim_states(monkeypatch):
    """Where the complaint is that something is MISSING, adding it needs a claim that says it."""
    import explainer_pipeline as ep

    claims = {"m1": {"claim": "The programme removed the cats.", "verified": True}}
    beats = [{"beat_id": "k5", "role": "reversal",
              "event": {"text": "The programme ended.", "claim_refs": ["m1"]}}]
    seen = {}

    class _Messages:
        def create(self, **call):
            seen["prompt"] = call["messages"][0]["content"]
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 200, "output_tokens": 20})(),
                "content": [type("C", (), {"text": '{"text":"","unchanged":true}'})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    out, _ = ep._repair_event_text(
        beats, [{"beat_id": "k5", "role": "reversal", "why": "does not name the new state"}],
        claims, "Why?")
    assert out[0]["event"]["text"] == "The programme ended.", "unchanged, not invented"
    assert "if none does, return the sentence unchanged" in seen["prompt"].lower()


def test_only_the_event_text_survives_a_sentence_repair(monkeypatch):
    """A provider that edits a role, a citation or a state transition must not smuggle it through."""
    import re
    from pathlib import Path
    import story_planning

    body = Path(story_planning.__file__).read_text(encoding="utf-8")
    block = body[body.index("A ROLE CONTRACT FAILURE IS A SENTENCE PROBLEM"):]
    block = block[:block.index("source = mechanism[")]
    assert "working = original" in block, "everything but the text is restored"
    assert re.search(r'beat\["event"\] = dict\(beat\.get\("event"\) or \{\}, text=text\)', block)


def test_a_beat_research_can_still_fix_is_not_sent_to_the_sentence_repair():
    """The cane-toad fixture is exactly this case, and it caught the mistake.

    Its intervention beat carries "Cane toads were introduced to control cane beetles" while citing
    a claim about the ABSENCE of impact studies. What it needs is the claim saying the toads were
    introduced -- a fact no rewording can add, because the sentence repair may only work inside the
    citations the beat already has. Firing there spends a call that cannot help AND consumes the
    round that would have bought the research that could.
    """
    import re
    from pathlib import Path
    import story_planning

    body = Path(story_planning.__file__).read_text(encoding="utf-8")
    block = body[body.index("A beat research can still help"):]
    block = block[:block.index("if role_issues")]
    assert "_coverage.evidence_gaps(compiled, effective)" in block
    assert re.search(r'issue\["beat_id"\] not in gapped', body)
