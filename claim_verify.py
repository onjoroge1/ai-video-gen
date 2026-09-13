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

# Words that reverse or hollow out a sentence's commitment. `_content_words` drops anything four
# characters or shorter, so "not"/"no"/"nor" are invisible to the overlap score by construction —
# and several of these ("never", "failed", "unable") survive the length filter but are then just
# one more matching token, no different from "beetle". Overlap cannot see meaning; this set is how
# the repair path is told that two sentences saying opposite things are not the same evidence.
_POLARITY = frozenset("""
no not nor none never neither nothing without cannot cant dont doesnt didnt
isnt arent wasnt werent wont wouldnt couldnt shouldnt hasnt havent hadnt
failed failure fail fails unsuccessful ineffective unable refuted disproved
disproven debunked myth incorrectly wrongly falsely contrary despite however
although whereas unlike rather instead little negligible minimal barely
hardly scarcely rarely seldom unproven untested inconclusive disputed
contested alleged supposedly reportedly claimed purported
""".split())


def _content_words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", normalise(text)) if len(w) > 3}


def _is_negated(text: str) -> bool:
    """Does this text carry a negation or hedge, read WITHOUT the content-word length filter?

    Boolean, not a set. An earlier version compared marker SETS for equality, which rejected the
    honest repair too: the model wrote "did not reduce" and the page said "never reduced", so
    {not} != {never} and a correct recovery was thrown away. What matters is direction, and
    direction is one bit.
    """
    return any(w in _POLARITY for w in re.findall(r"[a-z0-9]+", normalise(text)))


def candidate_passages(query: str, page_text: str, *, limit: int = 3) -> list[str]:
    """Return a few exact page passages most likely to answer a factual gap.

    This is retrieval, not verification. It only ranks one- and two-sentence windows copied
    from bytes we fetched; Boundary A must still decide whether a returned passage entails the
    gap. Keeping the shortlist small prevents source reuse from becoming unbounded judge calls.
    """
    wanted = _content_words(query)
    sentences = [sentence.strip() for sentence in _SENTENCE.findall(page_text or "")]
    if not wanted or not sentences or limit <= 0:
        return []
    ranked = []
    for index, sentence in enumerate(sentences):
        for width in (1, 2):
            window = " ".join(sentences[index:index + width]).strip()
            if not window or len(window) > 800:
                continue
            shared = wanted & _content_words(window)
            if len(shared) < min(2, len(wanted)):
                continue
            ranked.append((len(shared) / len(wanted), -len(window), window))
    ranked.sort(reverse=True)
    passages = []
    for _, _, passage in ranked:
        if passage not in passages:
            passages.append(passage)
        if len(passages) >= limit:
            break
    return passages


def repair_quote(claim_text: str, quote: str, page_text: str, *, min_overlap: float = 0.5) -> str:
    """Find a real sentence on the page that carries the claim, or "" if none does.

    The model paraphrases rather than transcribes, so an accurate claim drawn from the right page
    routinely fails a verbatim check. Recovering the page's own sentence keeps the guarantee — the
    stored quote is text that genuinely appears at the URL — while not discarding a sound claim
    over wording.

    Requires real overlap with the CLAIM, not merely with the model's paraphrase, so this cannot
    quietly attach an unrelated sentence to a claim the page does not support.

    Overlap alone was not enough, and the failure was not theoretical. Measured against this
    function on a two-sentence page:

        page   "Introduced to Australia in 1935, the cane toad was brought in to control the
                greyback cane beetle in Queensland sugar plantations.
                The beetle population was never reduced by the toads."
        claim  "The 1935 introduction of cane toads to Queensland successfully controlled the
                greyback cane beetle."

    The page's STATEMENT OF INTENT scored 0.583 and was substituted; the page's own refutation
    scored 0.167 and was discarded.

    Polarity matching is a partial answer and it is worth being exact about what it does and does
    not buy. It refuses a candidate that NEGATES a claim the page appears to make positively (and
    vice versa), which is a real class of failure. It does NOT catch the case above, where the
    substituted sentence states an INTENT and the claim asserts an OUTCOME: both are positive, so
    both pass. No word-overlap rule can separate "was brought in to control" from "controlled".
    That case is caught downstream instead, by giving the evidence judge the quote and URL to look
    at (see `claim_entailment`), which is the only stage that can read for meaning. What this
    function guarantees is narrower than it used to claim: the returned sentence appears verbatim
    on the page and does not contradict the claim's direction.
    """
    wanted = _content_words(claim_text) | _content_words(quote)
    if not wanted or not page_text:
        return ""
    # The claim's own hedges count: a claim that already says "failed" may legitimately match a
    # sentence that says "failed". Only a mismatch in DIRECTION is disqualifying.
    claim_negated = _is_negated(claim_text) or _is_negated(quote)
    best, best_score = "", 0.0
    for sentence in _SENTENCE.findall(page_text):
        if _is_negated(sentence) != claim_negated:
            continue
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
        # A recovered quote is weaker evidence than a verbatim one: it is a sentence from the right
        # page that shares the claim's words and direction, not the sentence the model said it was
        # quoting. Downstream judges are shown this, so "verified" can stop meaning one thing when
        # it is two.
        if ok:
            claim["support_provenance"] = ("page_recovered"
                                           if claim.get("support_quote_model") else "verbatim")
        verified += 1 if ok else 0
    if repaired:
        log(f"Claim verification: recovered {repaired} quote(s) from page text")
    return {"verified": verified, "unverified": len(targets) - verified, "repaired": repaired,
            "fetched": fetched, "urls": len(urls), "pages": pages}
