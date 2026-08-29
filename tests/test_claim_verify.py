"""Client-side claim verification: real page text is the authority, nothing else."""
import claim_verify as cv


PAGE = ("<html><head><style>.x{color:red}</style></head><body>"
        "<h1>Peptic ulcer disease</h1>"
        "<p>Marshall developed histologically confirmed acute gastritis on day ten, and the same "
        "curved bacteria were recovered from a stomach that had been healthy before ingestion.</p>"
        "<script>var a=1;</script>"
        "<p>NSAID use remains a common cause of peptic ulcers and should not be overlooked.</p>"
        "</body></html>")


def test_markup_and_scripts_are_stripped():
    text = cv.html_to_text(PAGE)
    assert "var a=1" not in text and "color:red" not in text
    assert "acute gastritis on day ten" in text


def test_typography_differences_do_not_break_a_real_quote():
    """A page's curly apostrophes and line wrapping are not a different claim."""
    page = cv.html_to_text("<p>The stomach’s lining — once thought sterile — was not.</p>")
    assert cv.normalise("The stomach's lining - once thought sterile - was not.") in cv.normalise(page)


def test_a_quote_present_on_the_page_verifies(monkeypatch):
    monkeypatch.setattr(cv, "fetch_page_text", lambda url, session=None: cv.html_to_text(PAGE))
    claims = [{"claim": "Marshall developed acute gastritis.",
               "source_url": "https://example.org/a",
               "support_quote": "acute gastritis on day ten"}]
    summary = cv.verify_claims(claims)
    assert summary["verified"] == 1
    assert claims[0]["quote_verified"] is True


def test_a_paraphrase_is_repaired_to_the_pages_own_sentence(monkeypatch):
    """The common real case: accurate claim, right page, wording retyped rather than copied."""
    monkeypatch.setattr(cv, "fetch_page_text", lambda url, session=None: cv.html_to_text(PAGE))
    claims = [{"claim": "Marshall developed acute gastritis after ingesting the bacteria.",
               "source_url": "https://example.org/a",
               "support_quote": "he got gastritis about ten days after drinking it"}]
    summary = cv.verify_claims(claims)
    assert summary["repaired"] == 1
    assert claims[0]["quote_verified"] is True
    assert "day ten" in claims[0]["support_quote"], claims[0]["support_quote"]
    assert claims[0]["support_quote_model"], "the model's wording is kept for audit"
    assert cv.normalise(claims[0]["support_quote"]) in cv.normalise(cv.html_to_text(PAGE))


def test_a_claim_the_page_does_not_support_is_never_repaired(monkeypatch):
    """The property that must not regress: repair may not invent support.

    The page is about ulcers, so a stray sentence would share some words — recovery has to fail on
    a claim the page genuinely does not make, or this becomes a rubber stamp.
    """
    monkeypatch.setattr(cv, "fetch_page_text", lambda url, session=None: cv.html_to_text(PAGE))
    claims = [{"claim": "A randomised trial of two thousand patients proved stress causes ulcers.",
               "source_url": "https://example.org/a",
               "support_quote": "stress was shown to cause ulcers in a randomised trial"}]
    summary = cv.verify_claims(claims)
    assert summary["verified"] == 0 and summary["repaired"] == 0
    assert claims[0]["quote_verified"] is False


def test_an_unreachable_source_fails_rather_than_passing(monkeypatch):
    """A citation nobody can open is not evidence."""
    monkeypatch.setattr(cv, "fetch_page_text", lambda url, session=None: "")
    claims = [{"claim": "x", "source_url": "https://example.org/dead", "support_quote": "anything"}]
    summary = cv.verify_claims(claims)
    assert summary["verified"] == 0
    assert claims[0]["source_reachable"] is False


def test_fetch_never_raises_on_a_hostile_url():
    for url in ("", "not-a-url", "http://insecure.example", "https://[::bad"):
        assert cv.fetch_page_text(url) == ""
