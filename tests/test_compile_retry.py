"""The beat sheet gets one retry for mechanical compile failures, and only those.

compile_roles is arithmetic over the planner's declared event functions. Both codes it can emit
are the planner mislabelling a beat, and neither was retried anywhere: explainer_pipeline tested
only `compiled`, so a sheet with compiled=True/passed=False reached story_planning.prepare, which
re-checked and raised -- above prepare's own `for attempt in range(2)` loop, making the retry it
advertises unreachable for exactly these failures.

Measured cost: MULTIPLE_INCENTIVE_CHANGES killed a run at 59s; UNKNOWN_EVENT_FUNCTION killed
another at 464s for ~$5.56, on one bad label on one beat of eight, on the same topic and engine as
a run that completed minutes earlier.
"""
import event_functions as ef
import story_compiler as sc


def _result(*codes, engine="removed_keystone", compiled=True):
    return {"compiled": compiled, "engine": engine, "passed": not codes,
            "issues": [{"code": code, "message": f"beat event_05 {code.lower()}"}
                       for code in codes]}


def _codes_compile_roles_can_emit() -> set:
    """Every _issue() code in compile_roles, read from its own AST.

    Deliberately not a hand-written list. MECHANICAL_COMPILE_CODES was first written with two
    entries because a line-ranged grep missed MISSING_EVENT_FUNCTION, and a code absent from that
    set is not a misbehaving retry -- it is a run that dies with no path forward, which is the
    exact failure this whole change exists to remove. So the test derives the truth from the
    compiler and the constant has to match it.
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(sc))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "compile_roles":
            return {call.args[0].value
                    for call in ast.walk(node)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute) and call.func.attr == "_issue"
                    and call.args and isinstance(call.args[0], ast.Constant)}
    raise AssertionError("compile_roles not found")


def test_every_code_compile_roles_can_emit_is_retryable():
    """A code the compiler raises but nobody classified kills runs with no recovery."""
    emitted = _codes_compile_roles_can_emit()
    assert emitted, "AST walk found no codes — the walk itself is broken"
    assert emitted == set(sc.MECHANICAL_COMPILE_CODES), (
        f"compile_roles emits {sorted(emitted)} but MECHANICAL_COMPILE_CODES holds "
        f"{sorted(sc.MECHANICAL_COMPILE_CODES)}. Classify the difference: retryable means the "
        f"planner can fix it from the same facts.")
    for code in sorted(emitted):
        assert sc.compile_correction(_result(code)), f"{code} must be retryable"


def test_the_correction_quotes_the_failure_and_the_legal_vocabulary():
    """The retry has to tell the model which beat is wrong and what the legal values are.

    A correction that merely says "it did not compile" re-rolls the same dice. This is the whole
    reason the retry is worth its extra planner call.
    """
    correction = sc.compile_correction(_result("UNKNOWN_EVENT_FUNCTION"))
    assert "event_05" in correction
    legal = ef.map_for("removed_keystone").to_role
    for function in legal:
        assert function in correction, f"{function} missing from the legal vocabulary"
    # The single-incentive rule is stated too. It lives ONLY in the compile error and in
    # factual_plan_prompt's silence about it, which is how a run died at 59 seconds.
    assert "Exactly one beat may declare changes_incentive" in correction


def test_the_correction_forbids_rewriting_anything_else():
    """A retry that re-writes the story is not a repair, it is a second draft.

    The sheet already passed topic fit, engine selection and the word budget. Only the labels are
    wrong, so only the labels may move -- otherwise the retry silently discards work that was
    paid for and validated.
    """
    correction = sc.compile_correction(_result("MULTIPLE_INCENTIVE_CHANGES"))
    assert "byte-identical" in correction
    assert "Do not add, remove or reorder beats" in correction


def test_a_passing_sheet_is_never_retried():
    assert sc.compile_correction(_result()) == ""


def test_an_unrecognised_code_fails_closed():
    """Fail closed, because the cheap direction here is the dangerous one.

    Retrying an editorial objection by re-asking the same model is how a real finding gets
    sampled away. A code nobody has classified must stop the run, not get re-rolled.
    """
    assert sc.compile_correction(_result("SOME_FUTURE_EDITORIAL_CODE")) == ""


def test_a_mechanical_code_mixed_with_an_unknown_one_fails_closed():
    """The dangerous middle case: retry the pair and the unknown objection rides along silently."""
    assert sc.compile_correction(
        _result("UNKNOWN_EVENT_FUNCTION", "SOME_FUTURE_EDITORIAL_CODE")) == ""


def test_an_engine_that_compiles_nothing_is_not_retried():
    """compiled=False means the engine labels its own roles; there is no vocabulary to correct."""
    assert sc.compile_correction(
        {"compiled": False, "reason": "engine still assigns roles itself", "issues": []}) == ""


def test_the_real_run_12_failure_produces_a_correction():
    """The exact shape that cost $5.56 and produced nothing: one bad label among valid ones.

    Built through the real compiler on a sheet that supplies every required function, so the only
    complaint is the invented one. That is what the live run looked like -- its error carried
    UNKNOWN_EVENT_FUNCTION and nothing else -- and it is what makes the retry worth its call.
    """
    mapping = ef.map_for("removed_keystone")
    beats = [{"n": i + 1, "beat": f"beat {i}", "beat_id": f"event_{i:02d}",
              "event_function": function}
             for i, function in enumerate(mapping.required)]
    beats.append({"n": len(beats) + 1, "beat": "bad", "beat_id": "event_05",
                  "event_function": "declare"})
    roles = sc.compile_roles(beats, "removed_keystone", {})
    assert roles["compiled"] and not roles["passed"]
    assert [issue["code"] for issue in roles["issues"]] == ["UNKNOWN_EVENT_FUNCTION"], \
        roles["issues"]
    correction = sc.compile_correction(roles)
    assert correction and "event_05" in correction


def test_a_sheet_the_compiler_accepts_needs_no_correction():
    """Round-trip against the real compiler, so the fixtures above cannot drift from it."""
    mapping = ef.map_for("removed_keystone")
    beats = [{"n": i + 1, "beat": f"beat {i}", "beat_id": f"event_{i:02d}",
              "event_function": function}
             for i, function in enumerate(mapping.required)]
    roles = sc.compile_roles(beats, "removed_keystone", {})
    assert roles["compiled"]
    assert sc.compile_correction(roles) == "", roles.get("issues")
