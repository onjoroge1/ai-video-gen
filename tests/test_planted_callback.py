"""The close re-speaks the number the hook planted (change #6, 2026-10-06).

The reference explainer plants '50 degrees' at 9 s and re-speaks it at 509 s; V8's hook planted
'twenty-six' and its 18-word, one-sentence close re-spoke nothing. Scoped by a contract stamp so
the two reference fixtures whose closes never return a numeral validate as before.
"""
import causal_story as cs
import hook_patterns as hp
import storyboard_repair as repair


def test_one_normaliser_for_digits_words_and_scales():
    assert hp.planted_numbers("Your hive could face twenty-six escaped queens.") == {26}
    assert hp.planted_numbers("26 queens") == {26}
    assert hp.planted_numbers("twenty six queens and 2,000 pounds") == {26, 2000}
    assert hp.planted_numbers("Twenty-nine million people") == {29_000_000}
    assert hp.planted_numbers("one of them, her only egg") == set()      # 1 is a determiner
    assert hp.negation_nouns("No electricity, no fans, no ice.") == {"electricity", "fans", "ice"}


def _steps(close="When a useful introduction changes the living system, what else escapes?"):
    roles = ["setup", "intervention", "hinge", "mechanism", "escalation", "escalation",
             "reversal", "tool"]
    texts = ["European bees struggled in Brazil.", "Kerr brought African queens to Brazil.",
             "Except the queens did not stay.", "Queens and drones escaped and hybridized.",
             "A beekeeper removed the excluders and twenty-six queens left with swarms.",
             "Colonies grew and swarmed more often.",
             "Brazilian beekeeping shifted to Africanized bees.", close]
    return [{"step_id": f"s{i}", "role": r, "situation": t, "chapter": 1 + i // 3,
             "caused_by": f"s{i - 1}" if i else "", "start_sec": i * 30.0}
            for i, (r, t) in enumerate(zip(roles, texts))]


def _payload(steps, contract=True, hook="Your hive could face twenty-six escaped queens."):
    return {"runtime_sec": 300.0, "steps": steps, "opening_object": "the bee colonies",
            "start_state": "low honey", "hook": {"line": hook, "cold_open": ""},
            "close_contract": cs.CLOSE_CONTRACT if contract else ""}


def _codes(report):
    return {i["code"] for i in report["errors"]}, {i["code"] for i in report["warnings"]}


def test_v8_shaped_close_fails_both_codes_only_under_the_contract():
    errors, _ = _codes(cs.validate_causal_story(_payload(_steps())))
    assert {"NO_NUMBER_CALLBACK", "CLOSE_SENTENCE_COUNT"} <= errors
    errors, _ = _codes(cs.validate_causal_story(_payload(_steps(), contract=False)))
    assert not ({"NO_NUMBER_CALLBACK", "CLOSE_SENTENCE_COUNT"} & errors)
    # Short form never carries the contract's checks.
    short = _payload(_steps()); short["runtime_sec"] = 60.0
    errors, _ = _codes(cs.validate_causal_story(short))
    assert not ({"NO_NUMBER_CALLBACK", "CLOSE_SENTENCE_COUNT"} & errors)


def test_a_compliant_close_passes_and_the_number_may_sit_anywhere_in_the_span():
    good = ("Twenty-six queens were the whole surprise. The bee colonies in that forest are the "
            "plan's other half.")
    errors, _ = _codes(cs.validate_causal_story(_payload(_steps(good))))
    assert not ({"NO_NUMBER_CALLBACK", "CLOSE_SENTENCE_COUNT"} & errors)
    # Digits in the close match words in the hook through the one normaliser.
    digits = "26 queens were the whole surprise. The bee colonies are the plan's other half."
    errors, _ = _codes(cs.validate_causal_story(_payload(_steps(digits))))
    assert "NO_NUMBER_CALLBACK" not in errors
    # A hook with no number asks nothing of the close but the sentence band.
    errors, _ = _codes(cs.validate_causal_story(_payload(_steps(good), hook="Your hive could face trouble.")))
    assert "NO_NUMBER_CALLBACK" not in errors
    assert cs.lead_numbers({"line": "Explained like you are five.", "format_tag": "explained like you are five"}) == set()


def test_closing_span_is_everything_after_the_last_reversal():
    steps = cs._normalize_steps(_steps())
    assert [s["role"] for s in cs.closing_span(steps)] == ["tool"]
    steps = cs._normalize_steps(_steps()[:-1] + [
        {"step_id": "g", "role": "generalization", "situation": "Elsewhere the same happened.",
         "chapter": 3, "caused_by": "s6", "start_sec": 240.0}, _steps()[-1]])
    assert [s["role"] for s in cs.closing_span(steps)] == ["generalization", "tool"]


def test_a_denied_list_the_close_never_returns_is_a_warning_not_a_block():
    hook = "No fans, no ice, no electricity kept the hive cool; twenty-six queens left anyway."
    good = "Twenty-six queens were the whole surprise. The bee colonies are the plan's other half."
    report = cs.validate_causal_story(_payload(_steps(good), hook=hook))
    errors, warnings = _codes(report)
    assert "NEGATION_LIST_UNRETURNED" in warnings and "NEGATION_LIST_UNRETURNED" not in errors


def test_the_repair_selects_the_close_and_re_measures_the_number():
    script = {"hook": "Your hive could face twenty-six escaped queens.", "_cold_open": "",
              "_close_contract": cs.CLOSE_CONTRACT, "_story_engine": "removed_keystone",
              "_story_contract": {"opening_object": "the bee colonies"},
              "scenes": [{"scene_id": f"scene_{i}", "causal_role": s["role"], "narration": s["situation"],
                          "chapter": s["chapter"], "caused_by": s["caused_by"]} for i, s in enumerate(_steps())]}
    errors = ["NO_NUMBER_CALLBACK: the hook planted [26] and the closing span re-speaks no number",
              "CLOSE_SENTENCE_COUNT: the closing step is 1 sentence(s)"]
    assert repair.repairable_errors(errors)
    edit = repair.plan(script, {"validation": {"errors": errors}})
    assert edit["scene_ids"] == ["scene_7"] and edit["planted_numbers"] == [26]
    assert "twenty-six" in repair.prompt(script, edit)
    try:
        repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_7",
                              "narration": "The bee colonies stayed where the plan left them. "
                                           "Nothing else about that forest changed at all."}]})
    except ValueError as exc:
        assert "planted number" in str(exc)
    else:
        raise AssertionError("a close that re-speaks no number was accepted")
    fixed = repair.apply_response(script, edit, {"scenes": [{"scene_id": "scene_7",
                "narration": "Twenty-six queens were the whole surprise. The bee colonies in that "
                             "forest are the plan's other half, still."}]})
    assert fixed["scenes"][-1]["narration"].startswith("Twenty-six")
