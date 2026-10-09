"""A script that passed the pre-spend gates is reused on the causal lane instead of rewritten.

Measured 2026-09-22: five consecutive 300s renders of one question each rewrote the script from
scratch, three of them dying on a gate the previous draft had already cleared.
"""
import json

import explainer_pipeline as ep


def test_the_cache_is_on_for_the_causal_lane_and_off_elsewhere(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("SCRIPT_CACHE", raising=False)
    assert ep._script_cache_enabled(causal_lane=True) is True
    assert ep._script_cache_enabled(causal_lane=False) is False
    monkeypatch.setenv("SCRIPT_CACHE", "1")
    assert ep._script_cache_enabled(causal_lane=False) is True
    monkeypatch.setenv("SCRIPT_CACHE", "0")
    assert ep._script_cache_enabled(causal_lane=True) is False, "SCRIPT_CACHE=0 forces a fresh draft"


def test_it_stays_off_under_pytest_whatever_the_lane(monkeypatch):
    monkeypatch.setenv("SCRIPT_CACHE", "1")
    assert ep._script_cache_enabled(causal_lane=True) is False


def test_a_stored_script_records_the_gates_it_passed(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("SCRIPT_CACHE_DIR", str(tmp_path))
    script = {"scenes": [{"narration": "One."}]}
    ep._store_graded_script("q", "fp", script, causal_lane=True, gate="claim ledger")
    ep._store_graded_script("q", "fp", script, causal_lane=True, gate="storyboard")
    ep._store_graded_script("q", "fp", script, causal_lane=True, gate="storyboard")
    stored = json.load(open(ep._script_cache_path("q", "fp")))
    assert stored["_gates_passed"] == ["claim ledger", "storyboard"], "each gate once, in order"
    logs = []
    back = ep._cached_graded_script("q", "fp", logs.append, causal_lane=True)
    assert back["scenes"] == script["scenes"]
    assert "already past claim ledger, storyboard" in logs[0]


def test_a_cached_script_is_not_fact_checked_twice():
    """The fact-check rewrites narration the ledger has already bound, so a cached script
    carries a marker and the pass is skipped."""
    import inspect
    src = inspect.getsource(ep.run_explainer_pipeline)
    marker = src.index('script.get("_fact_checked")')
    call = src.index("factcheck_script(script, question, research_dossier)")
    assert marker < call
    assert 'script["_fact_checked"] = True' in src


def test_the_repaired_script_is_stored_after_the_storyboard_gate():
    import inspect
    src = inspect.getsource(ep.run_explainer_pipeline)
    gate = src.index("Illustrated storyboard: PASS")
    store = src.index('gate="storyboard"')
    assert gate < store
    assert "if not resumed and script_fingerprint:" in src, "a resumed script is never re-stored"
