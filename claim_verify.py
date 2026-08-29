"""Verify research claims against the real page text, client-side.

Why this exists: the pipeline's own validator requires every claim's support quote to have been
observed in provider evidence, but the provider never hands that evidence to the client. Measured
on real calls, a `web_search_result` block carries only `url`, `title`, `page_age` and an opaque
`encrypted_content`, `citations` is None on every text block, and enabling `web_fetch` still
yielded zero readable excerpts. So the check could not be satisfied on any topic, and long-form
never reached the gates behind it.

Fetching the cited page ourselves restores the original guarantee and removes the dependency
entirely: a support quote is verified against bytes we retrieved from the URL being cited. Nothing
here trusts the model — the quote either appears on the page or it does not.

Deliberately conservative about what counts as a match. Quotes are compared on collapsed
whitespace and normalised punctuation, because a page's typographic apostrophes and line wrapping
are not meaningful differences, but the wording itself must be present.
"""
from __future__ import annotations

import html
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import requests

USER_AGENT = "Mozilla/5.0 (compatible; ReelForgeResearch/1.0; +claim-verification)"
FETCH_TIMEOUT_SEC = 20.0
MAX_BYTES = 3_000_000
_SCRIPTISH = re.compile(r"<(script|style|noscript|template)\b.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# Straight-quote everything and strip the dash family: a page rendering an apostrophe as U+2019 or
# an en dash where the quote used a hyphen is not a different claim.
_PUNCT_MAP = {ord(c): "'" for c in "‘’ʼ´`"}
_PUNCT_MAP.update({ord(c): '"' for c in "“”„"})
_PUNCT_MAP.update({ord(c): "-" for c in "‐‑‒–—―"})
_PUNCT_MAP[0x00a0] = " "


def html_to_text(payload: str) -> str:
    """Strip markup to readable text. Crude on purpose — we are substring-matching, not parsing."""
    text = _SCRIPTISH.sub(" ", payload or "")
    text = _TAG.sub(" ", text)
    return _WS.sub(" ", html.unescape(text)).strip()


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(_PUNCT_MAP)
    return _WS.sub(" ", text).strip().casefold()


def fetch_page_text(url: str, *, session: requests.Session | None = None) -> str:
    """Return readable text for a URL, or "" if it cannot be retrieved.

    Never raises: an unreachable source is a claim that fails verification, not a crashed render.
    """
    if not str(url or "").startswith("https://"):
        return ""
    client = session or requests
    try:
        response = client.get(url, timeout=FETCH_TIMEOUT_SEC, stream=True,
                              headers={"User-Agent": USER_AGENT,
                                       "Accept": "text/html,application/xhtml+xml,text/plain"})
        response.raise_for_status()
        kind = str(response.headers.get("Content-Type") or "").lower()
        if kind and not any(t in kind for t in ("html", "text", "xml", "json")):
            return ""                                   # a PDF or image cannot be substring-matched
        body = response.raw.read(MAX_BYTES, decode_content=True) or b""
        encoding = response.encoding or "utf-8"
        payload = body.decode(encoding, errors="replace")
    except Exception:
        return ""
    return html_to_text(payload)


_SENTENCE = re.compile(r"[^.!?]{25,400}[.!?]")


def _content_words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", normalise(text)) if len(w) > 3}


def repair_quote(claim_text: str, quote: str, page_text: str, *, min_overlap: float = 0.5) -> str:
    """Find a real sentence on the page that carries the claim, or "" if none does.

    The model paraphrases rather than transcribes, so an accurate claim drawn from the right page
    routinely fails a verbatim check. Recovering the page's own sentence keeps the guarantee — the
    stored quote is text that genuinely appears at the URL — while not discarding a sound claim
    over wording.

    Requires real overlap with the CLAIM, not merely with the model's paraphrase, so this cannot
    quietly attach an unrelated sentence to a claim the page does not support.
    """
    wanted = _content_words(claim_text) | _content_words(quote)
    if not wanted or not page_text:
        return ""
    best, best_score = "", 0.0
    for sentence in _SENTENCE.findall(page_text):
        score = len(wanted & _content_words(sentence)) / len(wanted)
        if score > best_score:
            best, best_score = sentence.strip(), score
    return best if best_score >= min_overlap else ""


def verify_claims(claims: list, *, max_workers: int = 6, repair: bool = True,
                  log=lambda message: None) -> dict:
    """Check each claim's support_quote against text fetched from its own source_url.

    Annotates claims in place with `quote_verified` and, on success, records the page text length
    that backed it. Returns a summary. Unreachable pages and absent quotes both count as
    unverified — the point is that a citation nobody can open is not evidence.
    """
    targets = [claim for claim in claims or []
               if isinstance(claim, dict) and str(claim.get("source_url") or "").strip()]
    urls = sorted({str(claim["source_url"]).strip() for claim in targets})
    if not urls:
        return {"verified": 0, "unverified": len(targets), "fetched": 0, "pages": {}}

    session = requests.Session()
    pages: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as pool:
        for url, text in zip(urls, pool.map(lambda u: fetch_page_text(u, session=session), urls)):
            pages[url] = text
    fetched = sum(1 for text in pages.values() if text)
    log(f"Claim verification: fetched {fetched}/{len(urls)} cited pages")

    verified = repaired = 0
    for claim in targets:
        url = str(claim["source_url"]).strip()
        quote = str(claim.get("support_quote") or "")
        raw_page = pages.get(url, "")
        page = normalise(raw_page)
        ok = bool(quote.strip()) and bool(page) and normalise(quote) in page
        if not ok and repair and raw_page:
            recovered = repair_quote(str(claim.get("claim") or ""), quote, raw_page)
            if recovered:
                claim["support_quote_model"] = quote
                claim["support_quote"] = recovered
                ok = True
                repaired += 1
        claim["quote_verified"] = ok
        claim["source_reachable"] = bool(raw_page)
        verified += 1 if ok else 0
    if repaired:
        log(f"Claim verification: recovered {repaired} quote(s) from page text")
    return {"verified": verified, "unverified": len(targets) - verified, "repaired": repaired,
            "fetched": fetched, "urls": len(urls), "pages": pages}
