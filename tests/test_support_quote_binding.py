"""Support-quote binding: repair honest paraphrases, never launder a fabricated citation."""
import explainer_pipeline as ep
from longform_research import validate_research_dossier


def _dossier(support_quote: str, excerpt: str = None) -> dict:
    excerpt = ("Marshall developed histologically confirmed acute gastritis on day ten, "
               "and the same curved bacteria were recovered from a stomach that had been "
               "healthy before ingestion." if excerpt is None else excerpt)
    return {
        "claims": [{
            "claim_id": "c01",
            "claim": "Marshall developed acute gastritis after drinking the culture.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/3982345/",
            "support_quote": support_quote,
            "source_type": "primary",
            "confidence": "high",
            "material": True,
            "geographic_scope": "global",
            "timescale": "immediate",
        }],
        "citation_urls": ["https://pubmed.ncbi.nlm.nih.gov/3982345/"],
        "citation_records": [{"url": "https://pubmed.ncbi.nlm.nih.gov/3982345/",
                              "cited_text": excerpt}],
    }


def test_a_retyped_paraphrase_is_bound_to_the_provider_text():
    """The failure that motivated this: true claim, right source, imperfect retyping.

    The model drops a clause and normalises wording, so the verbatim check fails even though the
    provider excerpt plainly supports the claim.
    """
    dossier = _dossier("Marshall developed acute gastritis on day ten, and the same curved "
                       "bacteria were recovered from a stomach healthy before ingestion")
    assert not validate_research_dossier(dossier)["passed"], "precondition: should fail unbound"

    ep._bind_support_quotes(dossier)
    claim = dossier["claims"][0]
    assert dossier["support_quote_binding"]["bound"] == 1
    assert claim["support_quote"] == dossier["citation_records"][0]["cited_text"]
    assert claim["support_quote_model"], "the model's own wording must be kept for audit"
    assert validate_research_dossier(dossier)["passed"]


def test_a_fabricated_quote_is_never_bound():
    """The property that must not regress.

    A support quote resembling nothing the provider returned has to keep failing — otherwise the
    check stops protecting against an invented citation, which is the only reason it exists.
    """
    dossier = _dossier("A double-blind trial of two thousand patients proved stress causes "
                       "ulcers, contradicting the bacterial hypothesis entirely")
    ep._bind_support_quotes(dossier)
    claim = dossier["claims"][0]
    assert dossier["support_quote_binding"]["unbindable"] == 1
    assert "support_quote_model" not in claim, "must not have substituted"
    assert not validate_research_dossier(dossier)["passed"]


def test_binding_requires_the_url_to_have_provider_evidence():
    """A cited URL the provider never returned evidence for stays a failure."""
    dossier = _dossier("Marshall developed acute gastritis on day ten")
    dossier["citation_records"] = []
    ep._bind_support_quotes(dossier)
    assert dossier["support_quote_binding"]["bound"] == 0
    assert not validate_research_dossier(dossier)["passed"]


def test_an_already_verbatim_quote_is_left_untouched():
    excerpt = "Colonies were visible after five days of incubation."
    dossier = _dossier("visible after five days", excerpt=excerpt)
    ep._bind_support_quotes(dossier)
    claim = dossier["claims"][0]
    assert claim["support_quote"] == "visible after five days"
    assert "support_quote_model" not in claim
    assert dossier["support_quote_binding"]["bound"] == 0
    assert validate_research_dossier(dossier)["passed"]


def test_binding_survives_malformed_input():
    for junk in ({}, {"claims": [None, "x"]}, {"claims": [{}], "citation_records": [None]}):
        ep._bind_support_quotes(dict(junk))
