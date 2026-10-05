"""RESEARCH_CACHE=0 means refresh the cache, not bypass it (2026-10-05)."""
import json
import os

import explainer_pipeline as ep


def test_a_forced_fresh_search_replaces_the_cache_instead_of_discarding_it(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("RESEARCH_CACHE", "0")          # force a fresh search
    ep._store_research_dossier("q", {"claims": [{"claim_id": "c1"}]}, "r")
    path = ep._research_cache_path("q", "r")
    assert os.path.isfile(path), "a forced-fresh dossier must still be written"
    assert len(json.load(open(path))["claims"]) == 1
    # And the read is still skipped, so the next forced run searches again.
    assert ep._cached_research_dossier("q", "r", lambda *_: None) is None


def test_the_explicit_no_write_switch_still_suppresses_the_write(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("RESEARCH_CACHE_WRITE", "0")
    ep._store_research_dossier("q", {"claims": []}, "r")
    assert not os.path.isfile(ep._research_cache_path("q", "r"))
