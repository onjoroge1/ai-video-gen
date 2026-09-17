"""A page nobody could open and a page that does not say it are different findings.

Measured on the cane-toad topic before this change: of 16 claims that failed the quote check, 13
were transport failures — nma.gov.au returns 403 to any non-browser client (its homepage too),
dcceew.gov.au refuses the connection, wiley and britannica 403 — and only 3 were pages that were
actually read and did not contain the quote. The 13 were the spine of the story: the 1935
Gordonvale release, the Hawaii provenance, the Bureau of Sugar Experiment Stations, the untested
assumption that the toads would eat the beetles, Froggatt's warning.

All 16 were dropped identically, leaving 11 claims, and three separate downstream gates then
failed on the same hole in three different vocabularies.
"""
import copy

import claim_verify
import explainer_pipeline as ep
from longform_research import quarantine_contradicted_claims, validate_research_dossier


def _dossier(rows):
    """A dossier shaped like the one `_verify_claims_against_sources` receives."""
    return {
        "version": 1,
        "topic": "cane toads",
        "claims": [dict(row) for row in rows],
        "citation_urls": [row["source_url"] for row in rows],
        "citation_records": [{"url": row["source_url"], "cited_text": row["support_quote"]}
                             for row in rows if row.get("_fetched")],
    }


def _claim(cid, url, quote, *, fetched, found):
    return {"claim_id": cid, "claim": f"Documented fact {cid}.", "source_url": url,
            "support_quote": quote, "source_type": "authoritative_secondary",
            "confidence": "high", "geographic_scope": "Queensland",
            "timescale": "1935", "assumptions": [], "allowed_exaggeration": False,
            "material": True, "_fetched": fetched, "_found": found}


def _replay(monkeypatch, rows):
    """Run the real function with the fetch layer replaced by recorded reachability."""
    def fake_verify(claims, **_kwargs):
        for claim in claims:
            row = next(r for r in rows if r["claim_id"] == claim["claim_id"])
            claim["source_reachable"] = bool(row["_fetched"])
            claim["quote_verified"] = bool(row["_fetched"] and row["_found"])
        return {"verified": sum(1 for r in rows if r["_fetched"] and r["_found"]),
                "unverified": sum(1 for r in rows if not (r["_fetched"] and r["_found"])),
                "repaired": 0, "fetched": sum(1 for r in rows if r["_fetched"]),
                "urls": len(rows), "pages": {}}
    monkeypatch.setattr(claim_verify, "verify_claims", fake_verify)
    return ep._verify_claims_against_sources(_dossier(rows), log=lambda _m: None)


def test_an_unreachable_source_is_carried_with_its_provenance_not_deleted(monkeypatch):
    rows = [
        _claim("c01", "https://example.org/read", "we read this", fetched=True, found=True),
        _claim("c02", "https://blocked.example/403", "the model cited this",
               fetched=False, found=False),
        _claim("c03", "https://example.org/read2", "not on the page", fetched=True, found=False),
    ]
    out = _replay(monkeypatch, rows)

    assert [c["claim_id"] for c in out["claims"]] == ["c01", "c02"]
    assert [c["claim_id"] for c in out["unverified_claims"]] == ["c03"]
    assert [c["claim_id"] for c in out["attested_unfetchable_claims"]] == ["c02"]

    carried = next(c for c in out["claims"] if c["claim_id"] == "c02")
    assert carried["support_provenance"] == "provider_attested_unfetchable"
    assert carried["quote_verified"] is False, "carried is not promoted to verified"

    # A page we could not read contributes no citation record: its quote is the model's, not the
    # page's. Minting one would make the excerpt check circular.
    assert [r["url"] for r in out["citation_records"]] == ["https://example.org/read"]


def test_the_validator_exempts_only_the_explicitly_tagged_claim(monkeypatch):
    rows = [
        _claim("c01", "https://example.org/read", "we read this", fetched=True, found=True),
        _claim("c02", "https://blocked.example/403", "the model cited this",
               fetched=False, found=False),
    ]
    out = _replay(monkeypatch, rows)
    assert validate_research_dossier(out)["passed"], validate_research_dossier(out)["errors"]

    # Strip the tag and the same claim must fail again — the exemption is granted by an explicit
    # provenance value, never by an absent field.
    stripped = copy.deepcopy(out)
    for claim in stripped["claims"]:
        claim.pop("support_provenance", None)
    codes = {e["code"] for e in validate_research_dossier(stripped)["errors"]}
    assert "unverified_support_quote" in codes


def test_the_exemption_cannot_carry_a_whole_dossier(monkeypatch):
    """Zero is the only non-arbitrary threshold: nothing read at any URL is an outage, not a ledger."""
    rows = [
        _claim("c01", "https://blocked.example/a", "model text a", fetched=False, found=False),
        _claim("c02", "https://blocked.example/b", "model text b", fetched=False, found=False),
    ]
    # One page fetched (so the "no page retrieved" early return does not fire), but no claim
    # verified against it.
    def fake_verify(claims, **_kwargs):
        for claim in claims:
            claim["source_reachable"] = False
            claim["quote_verified"] = False
        return {"verified": 0, "unverified": len(claims), "repaired": 0,
                "fetched": 1, "urls": 2, "pages": {}}
    monkeypatch.setattr(claim_verify, "verify_claims", fake_verify)
    out = ep._verify_claims_against_sources(_dossier(rows), log=lambda _m: None)

    report = validate_research_dossier(out)
    assert not report["passed"]
    assert "no_fetched_evidence" in {e["code"] for e in report["errors"]}


def test_other_guards_still_apply_to_a_carried_claim(monkeypatch):
    """The exemption covers the excerpt check only. Provenance and domain rules are untouched."""
    rows = [_claim("c01", "https://example.org/read", "we read this", fetched=True, found=True),
            _claim("c02", "https://www.reddit.com/r/x", "model text", fetched=False, found=False)]
    out = _replay(monkeypatch, rows)
    codes = {e["code"] for e in validate_research_dossier(out)["errors"]}
    assert "weak_source_domain" in codes, "a blocked reddit link is still a weak source"

    # And a URL the provider never cited still fails provenance even when unfetchable.
    out["citation_urls"] = ["https://example.org/read"]
    codes = {e["code"] for e in validate_research_dossier(out)["errors"]}
    assert "unverified_source" in codes


def test_the_real_cane_toad_dossier_recovers_its_spine(monkeypatch, request):
    """The regression this exists for, replayed against the recorded live dossier if present."""
    import json
    from pathlib import Path
    saved = Path(__file__).parent / "fixtures" / "cane_toad_dossier.json"
    if not saved.is_file():
        import pytest
        pytest.skip("recorded live dossier not present")
    recorded = json.loads(saved.read_text(encoding="utf-8"))
    verified_ids = {c["claim_id"] for c in recorded["claims"]}
    claims = copy.deepcopy(recorded["claims"] + recorded["unverified_claims"])
    reach = {c["claim_id"]: c.get("source_reachable") for c in claims}

    def fake_verify(cl, **_kwargs):
        for claim in cl:
            claim["source_reachable"] = bool(reach.get(claim["claim_id"]))
            claim["quote_verified"] = claim["claim_id"] in verified_ids
        return {"verified": len(verified_ids), "unverified": len(cl) - len(verified_ids),
                "repaired": 0, "fetched": 10, "urls": 16, "pages": {}}
    monkeypatch.setattr(claim_verify, "verify_claims", fake_verify)

    out = ep._verify_claims_against_sources({**copy.deepcopy(recorded), "claims": claims},
                                            log=lambda _m: None)
    out = quarantine_contradicted_claims(out)          # production order
    report = validate_research_dossier(out)
    assert len(recorded["claims"]) == 11, "fixture drifted"
    assert len(out["claims"]) >= 23, f"expected the spine back, got {len(out['claims'])}"
    assert report["passed"], report["errors"]


def test_changing_the_retention_rule_invalidates_its_own_cache():
    """The stored dossier is the post-verification ledger, so a retention change must re-key it.

    The request fingerprint covers what was ASKED for, not what is kept from the answer. Without
    this, the next run of an already-cached topic would be served the pre-change ledger and the
    fix would look inert — measured: 11 retained claims instead of 23.
    """
    question = "Why Australia's Beetle Fix Became a Toad Problem"
    before = ep._research_cache_path(question, "prompt")
    original = ep.RESEARCH_RETENTION_CONTRACT
    try:
        ep.RESEARCH_RETENTION_CONTRACT = "retention_v1_drop_everything"
        assert ep._research_cache_path(question, "prompt") != before
    finally:
        ep.RESEARCH_RETENTION_CONTRACT = original
    assert ep._research_cache_path(question, "prompt") == before
