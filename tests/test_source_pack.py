"""Operator source packs reach research (2026-10-18): built from a research audit, fetched by us
(PDFs included), mined for verbatim passages, listed in the request, used as read by quote
verification, and accepted as observed sources. Without a pack, the request is byte-identical.
No network: fetches are faked.
"""
import json
import shutil

import pytest

import claim_verify
import explainer_pipeline as ep
import longform_research
import source_pack

PAGE = ("The Board of Trade boat scale stopped increasing above 10,000 tons and remained unchanged "
        "as ships grew larger every year. The survey of 3 April 1912 recorded fourteen lifeboats with "
        "910 places on the vessel. " + "Further unrelated inquiry text about other ships. " * 40)

AUDIT = {"E": {
    "research_cutoff_utc": "2026-10-18",
    "topics": [{"topic": "Titanic lifeboats", "readiness": "Ready evergreen", "decision": "1894 boat scale",
                "human": "Charles Lightoller", "current_type": "legacy", "angle": "Why Titanic Passed Inspection"}],
    "requirement_qa": {"Titanic lifeboats": {"legacy_only": True}},
    "sources": [
        {"id": "T04", "topic": "Titanic lifeboats", "url": "https://example.gov/survey",
         "final_url": "https://example.gov/survey", "title": "Report of Survey", "publisher": "Board of Trade",
         "date": "1912-04-03", "kind": "inquiry appendix", "content_type": "text/html; charset=utf-8",
         "selected_core": "True",
         "fact_location_map": [{"location": "HTML P18", "supported_fact_or_limit":
                                "The 3 April 1912 survey recorded fourteen lifeboats with 910 places."}]},
        {"id": "T01", "topic": "Titanic lifeboats", "url": "https://example.gov/truncated", "status": "200",
         "selected_core": "False", "manual_content_review": {"note": "local read cap truncated the download"}},
    ]}}


def test_build_from_audit_keeps_core_sources_and_records_the_rest():
    packs = source_pack.build_from_audit(AUDIT)
    pack = packs["titanic-lifeboat-rules"]
    assert pack["human"] == "Charles Lightoller" and pack["gaps"] == {"legacy_only": True}
    assert [s["id"] for s in pack["sources"]] == ["T04"] and pack["sources"][0]["content_type"] == "text/html"
    assert pack["sources"][0]["facts"][0] == {"location": "HTML P18", "fact":
                                              "The 3 April 1912 survey recorded fourteen lifeboats with 910 places."}
    assert pack["excluded"][0]["id"] == "T01" and "truncated" in pack["excluded"][0]["reason"]


def test_load_pack_by_slug_or_path(tmp_path):
    pack = source_pack.build_from_audit(AUDIT)["titanic-lifeboat-rules"]
    (tmp_path / "titanic-lifeboat-rules.json").write_text(json.dumps(pack))
    assert source_pack.load_pack("titanic-lifeboat-rules", str(tmp_path))["slug"] == "titanic-lifeboat-rules"
    assert source_pack.load_pack(str(tmp_path / "titanic-lifeboat-rules.json"))["slug"] == "titanic-lifeboat-rules"
    assert source_pack.load_pack("no-such-topic", str(tmp_path)) is None
    assert source_pack.load_pack("", str(tmp_path)) is None


def test_every_queued_pack_in_the_repo_loads():
    for slug in ("fukushima", "bhopal-disaster", "plastic-recycling", "great-pacific-garbage-patch",
                 "titanic-lifeboat-rules", "mkultra", "manhattan-project", "salem-witch-trials"):
        pack = source_pack.load_pack(slug)
        assert pack and pack["sources"] and all(s["url"].startswith("https://") for s in pack["sources"]), slug


def _prepared():
    pack = source_pack.build_from_audit(AUDIT)["titanic-lifeboat-rules"]
    pack["sources"].append({"id": "T99", "url": "https://example.gov/blocked", "title": "Blocked", "facts": []})
    return source_pack.prepare(pack, fetch=lambda url: PAGE if url.endswith("survey") else "")


def test_prepare_mines_verbatim_passages_and_leaves_out_unreadable_documents():
    prepared = _prepared()
    assert prepared["observed_urls"] == ["https://example.gov/survey"]
    assert prepared["unreadable"] == ["https://example.gov/blocked"]
    passages = prepared["sources"][0]["facts"][0]["passages"]
    assert passages and all(p in PAGE for p in passages), "passages are copied from the document, not written"
    assert any("fourteen lifeboats with 910 places" in p for p in passages)
    assert prepared["pages"]["https://example.gov/survey"] == PAGE


def test_prompt_paragraph_lists_documents_and_verbatim_passages():
    text = source_pack.prompt_paragraph(_prepared())
    assert text.startswith("OPERATOR SOURCE PACK") and "count as observed sources" in text
    assert "https://example.gov/survey" in text and "fourteen lifeboats with 910 places" in text
    assert "https://example.gov/blocked" not in text, "an unreadable document is not offered"
    assert source_pack.prompt_paragraph({"sources": []}) == ""


def _captured_prompt(monkeypatch, **kwargs):
    seen = {}

    def fake_cache(question, prompt, log):
        seen["prompt"] = prompt
        return {"claims": [{"claim_id": "c01", "claim": "stub"}]}

    monkeypatch.setattr(ep, "_cached_research_dossier", fake_cache)
    ep.generate_research_dossier("Why did Titanic pass inspection?", duration_sec=300, **kwargs)
    return seen["prompt"]


def test_the_pack_reaches_the_request_and_the_request_is_unchanged_without_it(monkeypatch):
    plain = _captured_prompt(monkeypatch)
    assert "OPERATOR SOURCE PACK" not in plain
    prepared = _prepared()
    monkeypatch.setattr(source_pack, "prepare", lambda pack, log=None: prepared)
    packed = _captured_prompt(monkeypatch, source_pack={"slug": "titanic-lifeboat-rules", "sources": [{}]})
    assert "OPERATOR SOURCE PACK" in packed and "fourteen lifeboats with 910 places" in packed
    start = packed.index("OPERATOR SOURCE PACK")
    assert packed[:start] + packed[packed.index("Ask for more", start):] == plain, "the paragraph is the only difference"
    # The run-level pack (the launcher's --source-pack) is read when no pack is passed.
    token = ep._SOURCE_PACK.set({"slug": "titanic-lifeboat-rules", "sources": [{}]})
    try:
        assert "OPERATOR SOURCE PACK" in _captured_prompt(monkeypatch)
    finally:
        ep._SOURCE_PACK.reset(token)


def _dossier(**extra):
    claim = {"claim_id": "c01", "claim": "The 3 April 1912 survey recorded fourteen lifeboats with 910 places.",
             "source_url": "https://example.gov/survey", "support_quote": "recorded fourteen lifeboats with 910 places",
             "source_type": "primary", "confidence": "high", "geographic_scope": "site-specific",
             "timescale": "immediate"}
    return {"claims": [claim], "citation_urls": [],
            "citation_records": [{"url": "https://example.gov/survey",
                                  "cited_text": "The survey of 3 April 1912 recorded fourteen lifeboats with 910 places on the vessel."}],
            **extra}


def test_pack_urls_count_as_observed_and_nothing_else_does():
    codes = {e["code"] for e in longform_research.validate_research_dossier(_dossier())["errors"]}
    assert "unverified_source" in codes, "without a pack, a URL search never returned still fails"
    ok = longform_research.validate_research_dossier(_dossier(operator_source_urls=["https://example.gov/survey"]))
    assert "unverified_source" not in {e["code"] for e in ok["errors"]}
    other = longform_research.validate_research_dossier(_dossier(operator_source_urls=["https://example.gov/other"]))
    assert "unverified_source" in {e["code"] for e in other["errors"]}


def test_verification_reads_prefetched_documents_instead_of_fetching(monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("a prefetched page must not be fetched again")

    monkeypatch.setattr(claim_verify, "fetch_page_text", no_network)
    claims = [{"claim": "fourteen lifeboats", "source_url": "https://example.gov/survey",
               "support_quote": "recorded fourteen lifeboats with 910 places"}]
    summary = claim_verify.verify_claims(claims, prefetched={"https://example.gov/survey": PAGE})
    assert summary["verified"] == 1 and claims[0]["quote_verified"] and claims[0]["support_provenance"] == "verbatim"


class _Raw:
    def __init__(self, body):
        self.body = body

    def read(self, n, decode_content=True):
        return self.body[:n]


class _Response:
    def __init__(self, body, kind):
        self.raw, self.headers, self.encoding = _Raw(body), {"Content-Type": kind}, "utf-8"

    def raise_for_status(self):
        pass


class _Session:
    def __init__(self, body, kind):
        self.body, self.kind = body, kind

    def get(self, url, **kwargs):
        assert "application/pdf" in kwargs["headers"]["Accept"]
        return _Response(self.body, self.kind)


def test_document_fetch_rejects_stub_pages_and_reads_full_html():
    stub = b"<html><body>Please enable JavaScript.</body></html>"
    assert claim_verify.fetch_document_text("https://x.gov/a", session=_Session(stub, "text/html")) == ""
    page = ("<html><body><p>" + PAGE + "</p></body></html>").encode()
    text = claim_verify.fetch_document_text("https://x.gov/a", session=_Session(page, "text/html"))
    assert "fourteen lifeboats with 910 places" in text
    assert claim_verify.fetch_document_text("http://x.gov/a", session=_Session(page, "text/html")) == ""


def _tiny_pdf(text: str) -> bytes:
    """A one-page PDF whose content stream draws `text` (for pdftotext)."""
    words = text.split()
    lines = [" ".join(words[i:i + 10]) for i in range(0, len(words), 10)]      # stay inside the page box
    stream = ("BT /F1 10 Tf 20 760 Td " + " ".join(f"({line}) Tj 0 -12 Td" for line in lines) + " ET").encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> "
               b"/Contents 4 0 R >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="poppler's pdftotext is not installed")
def test_document_fetch_reads_a_pdf():
    words = "The survey recorded fourteen lifeboats " * 40
    text = claim_verify.fetch_document_text("https://x.gov/r.pdf", session=_Session(_tiny_pdf(words), "application/pdf"))
    assert "fourteen lifeboats" in text
    assert claim_verify.fetch_document_text("https://x.gov/r.pdf", session=_Session(_tiny_pdf("short"), "application/pdf")) == ""
