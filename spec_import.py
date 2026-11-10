#!/usr/bin/env python3
"""Spec import: an operator-supplied research + narration document, verified and handed to render.

    python3 scripts/import_spec.py topics/specs/<slug>.md --out jobs/<slug>
    python3 scripts/import_spec.py topics/specs/<slug>.md --out jobs/<slug> --approve <narration sha256>

The operator (often with ChatGPT) writes the decision, the consequence, the question, the human,
the full narration and, for every factual sentence, the source URL and the exact quote that
supports it (docs/SPEC_IMPORT.md, topics/specs/TEMPLATE.md). ReelForge does not write anything:

1. it parses the spec and runs the World consequence check (a past DELIBERATE, named, dated
   decision -> a DOCUMENTED consequence, never a model or an interpretation -> a dated present-day
   sign it is still unfolding -> a question about that consequence, not a forward hypothetical);
2. it fetches every cited page itself (claim_verify's fetch path, PDFs and XML included) and
   locates each quote: exact, typography-normalised, recovered from the page's own sentences, not
   on the page, or unreachable;
3. it writes verification_report.md: one line per sentence, the consequence verdict and the voice
   metrics. Unsupported lines get a suggested rewording IN THE REPORT ONLY; the narration is never
   rewritten;
4. on `--approve <narration sha256>` (the hash in the report), it builds the research dossier and
   `_state.json` in the shape jobs/lionfish-v2/hand_build.py produced, and resumes the normal
   pipeline (claim ledger, storyboard, TTS, images, render), so the claim ledger stays hard.

This replaces a bespoke hand_build.py per film. Lionfish v2 is the worked case: its 16 claims c70-c86
were typed by hand with verbatim quotes, and the operator later ruled it is not a consequence video;
as a spec it verifies and FAILS the consequence check before any spend.

Reuse: the consequence rule and the narration segmenter live in the story-contract lane (PR #217,
story_contract.py / story_contract_segment.py). When those modules are importable they are used;
until then the rule below mirrors `story_contract.validate_consequence_model` code for code, and the
approved build stops with a clear message instead of guessing at a segmenter.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time

import claim_verify as cv

SPEC_VERSION = 1
REPORT_NAME = "verification_report.md"
RESULT_NAME = "spec_verification.json"
PAGES_DIR = "pages"
WORDS_PER_SECOND = 2.588           # longform_evidence.SLOWEST_MEASURED_WORDS_PER_SECOND
LONG_SENTENCE_WORDS = 25
RECOVER_MIN_OVERLAP = 0.7      # share of the operator quote's content words a recovered sentence carries
LEDGER_KINDS = ("event", "mechanism", "context", "outcome", "general_principle")
EVIDENCE_KINDS = ("documented", "model", "interpretation")
PARTS = ("opening", "attempt", "complication", "development", "ending")

# The World consequence model: the same constants as story_contract (PR #217).
WORLD_CHANNELS = ("", "world")
DECISION_KINDS = ("animal_introduced", "animal_removed", "animal_targeted", "invention_adopted",
                  "product_adopted", "rule_enforced")
CONSEQUENCE_LEDGER_KINDS = ("event", "outcome")
PRESENT_YEARS = 5
_HYPOTHETICAL_RE = re.compile(r"^\s*(what (happens|would happen|will happen|could happen|if)|"
                              r"what'?s next|imagine|suppose|could|would|will)\b|\bwhat if\b|"
                              r"\bwhat happens (when|if)\b", re.I)
_YEAR4 = re.compile(r"\b(1[5-9]\d\d|20\d\d)s?\b")

# A quote that reports a model's result, or hedges, cannot carry a consequence however the spec
# labels it: "our models projected" (lionfish c78) and "can make their harvest uneconomical" (c77)
# explain a mechanism; they do not document that it happened.
_MODEL_RE = re.compile(r"\b(models?|modell?ed|modell?ing|projected|projections?|simulat\w*|forecast\w*|"
                       r"predict\w*|scenarios?)\b", re.I)
_HEDGE_RE = re.compile(r"\b(may|might|could|would|can|potential(ly)?|speculat\w*|suggests?|likely|"
                       r"probabl[ey]|possibl[ey])\b", re.I)

_FENCE = re.compile(r"```[ \t]*(json|ya?ml|spec)?[^\n]*\n(.*?)\n```", re.S | re.I)
_SENT_SPLIT = re.compile(r"(?<=[.!?])[\"”’']?\s+(?=[\"“‘'(]?[A-Z0-9])")
_ATTRIBUTION = re.compile(r"\b(said|says|told|tells|according to|reported|reports|wrote|writes|found|"
                          r"researchers?|scientists?|study|studies|survey)\b", re.I)
_DIGITS = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve "
                                     "thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if i > 1}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000, "billion": 1_000_000_000}

ICON = {"exact": "✅", "normalized": "✅", "recovered": "⚠", "absent": "❌", "unreachable": "🚫"}
STATUS_TEXT = {"exact": "supported (exact quote on page)",
               "normalized": "supported (quote on page; typography normalised)",
               "recovered": "recovered: the quote is not on the page as written; the page's own sentence is used",
               "absent": "not on page",
               "unreachable": "page unreachable"}
_RANK = {"exact": 0, "normalized": 0, "recovered": 1, "absent": 3, "unreachable": 2}


class SpecError(ValueError):
    pass


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ("" if value is None else str(value).strip())


def normalize_narration(text: str) -> str:
    """The form the approval hash binds: whitespace collapsed, words and punctuation untouched
    (story_contract_policy.normalize_narration)."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── parsing ────────────────────────────────────────────────────────────────────────────────────

def parse_block(markdown: str) -> dict:
    """The spec's fenced block (```json, or ```yaml when PyYAML is installed). The first block that
    parses to an object with a `narration` list wins; prose around it is the operator's notes."""
    errors = []
    for lang, body in _FENCE.findall(markdown or ""):
        lang = (lang or "").lower()
        data = None
        try:
            if lang in ("yaml", "yml"):
                try:
                    import yaml  # noqa: PLC0415 - optional dependency
                except ImportError:
                    errors.append("a ```yaml block needs PyYAML (pip install pyyaml); use ```json instead")
                    continue
                data = yaml.safe_load(body)
            else:
                data = json.loads(body)
        except Exception as exc:  # noqa: BLE001 - every parse failure is reported, none crash
            errors.append(f"{lang or 'unlabelled'} block does not parse: {exc}")
            continue
        if isinstance(data, dict) and isinstance(data.get("narration"), list):
            return data
    raise SpecError("no fenced ```json block with a `narration` list" + (": " + "; ".join(errors) if errors else ""))


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(normalize_narration(text)) if s.strip()]


def load_spec(path: str) -> dict:
    raw_text = open(path, encoding="utf-8").read()
    spec = normalize_spec(parse_block(raw_text))
    spec["spec_path"] = os.path.abspath(path)
    spec["spec_sha256"] = sha256_text(raw_text)
    return spec


def _source_url(ref: str, sources: dict) -> str:
    ref = _text(ref)
    return _text(sources.get(ref)) if ref in sources else ref


def normalize_spec(raw: dict) -> dict:
    """Entries, claims and structural problems. Never raises on content: a problem is reported."""
    problems: list[dict] = []

    def problem(code, message, entry=None):
        problems.append({"code": code, "message": message, **({"entry": entry} if entry else {})})

    sources = raw.get("sources") if isinstance(raw.get("sources"), dict) else {}
    claims: dict[str, dict] = {}
    entries = []
    for i, row in enumerate(raw.get("narration") or [], 1):
        if isinstance(row, str):
            row = {"say": row}
        if not isinstance(row, dict) or not _text(row.get("say")):
            problem("EMPTY_LINE", f"narration line {i} has no `say` text", i)
            continue
        say = normalize_narration(row["say"])
        ids = []
        refs = list(row.get("claims") or []) + list(row.get("cite") or [])
        for k, c in enumerate(refs):
            if isinstance(c, str):                       # a reference to a claim defined elsewhere
                ids.append(_text(c))
                continue
            if not isinstance(c, dict):
                problem("BAD_CLAIM", f"line {i}: a claim must be an object or an id", i)
                continue
            cid = _text(c.get("id")) or f"s{i:02d}{chr(ord('a') + k)}"
            url = _source_url(c.get("source") or c.get("url"), sources)
            quote = normalize_narration(c.get("quote"))
            kind = _text(c.get("kind") or "event").lower()
            evidence = _text(c.get("evidence") or "documented").lower()
            claim = {"claim_id": cid, "claim": normalize_narration(c.get("claim")) or say, "source_url": url,
                     "support_quote": quote, "claim_kind": kind, "evidence": evidence,
                     "source_type": _text(c.get("source_type")) or "authoritative_secondary",
                     "confidence": _text(c.get("confidence")) or "high",
                     "geographic_scope": _text(c.get("scope")) or "regional",
                     "timescale": _text(c.get("timescale")) or "other explicit value",
                     "first_line": i}
            if not url.startswith("https://"):
                problem("NO_SOURCE_URL", f"line {i}, claim {cid}: source {c.get('source') or c.get('url')!r} "
                        "is not an https URL or a key of `sources`", i)
            if not quote:
                problem("NO_QUOTE", f"line {i}, claim {cid}: no exact quote", i)
            if kind not in LEDGER_KINDS:
                problem("BAD_KIND", f"line {i}, claim {cid}: kind {kind!r} is not one of {', '.join(LEDGER_KINDS)}", i)
            if evidence not in EVIDENCE_KINDS:
                problem("BAD_EVIDENCE", f"line {i}, claim {cid}: evidence {evidence!r} is not one of "
                        f"{', '.join(EVIDENCE_KINDS)}", i)
            if cid in claims:
                old = claims[cid]
                if (old["source_url"], old["support_quote"]) != (url, quote):
                    problem("CLAIM_REDEFINED", f"line {i}: claim {cid} was defined on line {old['first_line']} "
                            "with a different source or quote; give it a new id", i)
            else:
                claims[cid] = claim
            ids.append(cid)
        part = _text(row.get("part")).lower()
        entries.append({"line": i, "say": say, "claim_ids": list(dict.fromkeys(ids)),
                        "part": part, "picture": _text(row.get("picture")),
                        "sentences": split_sentences(say)})
    # Parts carry forward: a line without one belongs to the previous line's part.
    current = "opening"
    for e in entries:
        if e["part"] and e["part"] not in PARTS:
            problem("BAD_PART", f"line {e['line']}: part {e['part']!r} is not one of {', '.join(PARTS)}", e["line"])
        current = e["part"] if e["part"] in PARTS else current
        e["part"] = current
    for e in entries:
        for cid in e["claim_ids"]:
            if cid not in claims:
                problem("UNKNOWN_CLAIM", f"line {e['line']} cites {cid!r}, which no line defines", e["line"])
    for key in ("decision", "consequence", "still_unfolding"):
        block = raw.get(key) if isinstance(raw.get(key), dict) else {}
        for cid in block.get("cite") or block.get("claim_ids") or []:
            if _text(cid) not in claims:
                problem("UNKNOWN_CLAIM", f"{key} cites {cid!r}, which no narration line defines")
    if not entries:
        problem("NO_NARRATION", "the narration is empty")

    human = raw.get("human") if isinstance(raw.get("human"), dict) else {}
    return {
        "spec_version": raw.get("spec_version") or SPEC_VERSION,
        "slug": _text(raw.get("slug")),
        "title": _text(raw.get("title")) or _text(raw.get("central_question")),
        "channel": _text(raw.get("channel") or "world").lower(),
        "duration_sec": int(raw.get("duration_sec") or raw.get("duration_target_sec") or 300),
        "decision": raw.get("decision") if isinstance(raw.get("decision"), dict) else {},
        "consequence": raw.get("consequence") if isinstance(raw.get("consequence"), dict) else {},
        "still_unfolding": raw.get("still_unfolding") if isinstance(raw.get("still_unfolding"), dict) else {},
        "central_question": _text(raw.get("central_question")),
        "ending_answer": _text(raw.get("ending_answer")),
        "human": {"person": _text(human.get("person")), "want": _text(human.get("want")),
                  "detail": _text(human.get("detail"))},
        "forbidden_claims": [_text(x) for x in raw.get("forbidden_claims") or raw.get("claims_we_cannot_make") or []
                             if _text(x)],
        "recurring_image": _text(raw.get("recurring_image")),
        "render": raw.get("render") if isinstance(raw.get("render"), dict) else {},
        "sources": sources,
        "entries": entries,
        "claims": claims,
        "problems": problems,
    }


def narration(spec: dict) -> str:
    return normalize_narration(" ".join(e["say"] for e in spec["entries"]))


def narration_sha256(spec: dict) -> str:
    return sha256_text(narration(spec))


# ── fetching ───────────────────────────────────────────────────────────────────────────────────

class PageCache:
    """Cited pages read once and kept under <out>/pages/ (index.json + one .txt per URL), so a
    re-run, the approval and the tests read the same bytes. `fetch(url) -> text` defaults to
    claim_verify's document fetch (PDF and XML included), then its page fetch. An empty text is an
    unreachable page; it is not cached, so the next run tries again."""

    def __init__(self, directory: str, fetch=None, offline: bool = False):
        self.directory = directory
        self.fetch = fetch or _default_fetch
        self.offline = offline
        self.index_path = os.path.join(directory, "index.json")
        try:
            self.index = json.load(open(self.index_path))
        except (OSError, ValueError):
            self.index = {}

    def get(self, url: str) -> str:
        row = self.index.get(url)
        if row:
            try:
                return open(os.path.join(self.directory, row["file"]), encoding="utf-8").read()
            except OSError:
                pass
        if self.offline:
            return ""
        text = self.fetch(url) or ""
        if text:
            os.makedirs(self.directory, exist_ok=True)
            name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt"
            with open(os.path.join(self.directory, name), "w", encoding="utf-8") as handle:
                handle.write(text)
            self.index[url] = {"file": name, "chars": len(text),
                               "fetched_at": dt.datetime.now().isoformat(timespec="seconds")}
            with open(self.index_path, "w") as handle:
                json.dump(self.index, handle, indent=1, sort_keys=True)
        return text


def _default_fetch(url: str) -> str:
    return cv.fetch_document_text(url, min_words=40) or cv.fetch_page_text(url)


# ── verification ───────────────────────────────────────────────────────────────────────────────

def locate_quote(quote: str, claim_text: str, page: str) -> dict:
    """exact | normalized | recovered | absent | unreachable, with the page text that backs it."""
    if not page:
        return {"status": "unreachable", "page_quote": ""}
    if quote and normalize_narration(quote) in normalize_narration(page):
        return {"status": "exact", "page_quote": quote}
    if quote and cv.normalise(quote) in cv.normalise(page):
        return {"status": "normalized", "page_quote": quote}
    # The operator typed a quote, so a recovered page sentence must carry most of THAT quote's words
    # and all of its numbers. repair_quote's default (half the words of claim and quote together)
    # accepted "Pythons have eaten every raccoon in the Everglades" for a page sentence about
    # fur-bearing animals, the 403-wall failure of research recovery.
    recovered = cv.repair_quote("", quote, page, min_overlap=RECOVER_MIN_OVERLAP) if quote else ""
    if recovered and not number_mismatches(quote, [recovered]):
        return {"status": "recovered", "page_quote": recovered}
    return {"status": "absent", "page_quote": "",
            "passages": cv.candidate_passages(f"{claim_text} {quote}", page, limit=2)}


def _word_numbers(text: str) -> list[float]:
    """Spelled-out numbers ("seventy-three", "fifteen hundred", "36,187") as values."""
    out, cur, total, seen = [], 0, 0, False
    for tok in re.findall(r"[a-z]+", text.lower().replace("-", " ")) + ["."]:
        if tok in _UNITS:
            cur += _UNITS[tok]
            seen = True
        elif tok in _TENS:
            cur += _TENS[tok]
            seen = True
        elif tok in _SCALES and seen:
            if tok == "hundred":
                cur *= 100
            else:
                total += cur * _SCALES[tok]
                cur = 0
        elif tok == "and" and seen:
            continue
        else:
            if seen:
                out.append(float(total + cur))
            cur, total, seen = 0, 0, False
    return out


def numbers_in(text: str) -> list[float]:
    vals = [float(m.replace(",", "")) for m in _DIGITS.findall(text or "")]
    return vals + _word_numbers(text or "")


def number_mismatches(sentence: str, quotes: list[str], pages: list[str] = ()) -> list[float]:
    """Numbers above ten in a sentence that none of its quotes carries (within 5%: "more than fifteen
    hundred" for 1,542 is fine). Ten and under are left alone: "One fish." is rhetoric. A year
    may come from the cited page instead (a dateline, "this year's" under a 2026 headline)."""
    have = [v for q in quotes for v in numbers_in(q)]
    page_years = {int(y) for p in pages for y in _YEAR4.findall(p or "")}
    missing = []
    for v in numbers_in(sentence):
        if v <= 10:
            continue
        if any(abs(v - h) <= 0.05 * max(abs(h), 1) for h in have):
            continue
        if v == int(v) and 1500 <= v <= 2099 and int(v) in page_years:
            continue
        missing.append(v)
    return missing


def _looks_factual(say: str) -> bool:
    """An unsourced line that states a number, a year or an attribution probably needs a source."""
    return any(v > 10 for v in numbers_in(say)) or bool(_ATTRIBUTION.search(say))


def _content(text: str) -> set:
    stop = {"that", "this", "with", "from", "they", "them", "their", "there", "what", "when", "were",
            "have", "been", "into", "than", "then", "your", "about", "would", "could", "which", "people"}
    return {w[:6] for w in re.findall(r"[a-z]+", _text(text).lower()) if len(w) > 3 and w not in stop}


def verify(spec: dict, cache: PageCache) -> dict:
    """Per-claim and per-line results. No provider calls: pages are fetched (or read from cache)
    and quotes located deterministically."""
    claims, pages = {}, {}
    for cid, c in spec["claims"].items():
        page = cache.get(c["source_url"]) if c["source_url"].startswith("https://") else ""
        pages[cid] = page
        found = locate_quote(c["support_quote"], c["claim"], page)
        claims[cid] = {**found, "claim_id": cid, "url": c["source_url"], "quote": c["support_quote"],
                       "story_kind": story_kind(c), "page_chars": len(page)}
    lines = []
    for e in spec["entries"]:
        refs = [claims[c] for c in e["claim_ids"] if c in claims]
        notes, suggestions = [], []
        if refs:
            status = max((r["status"] for r in refs), key=lambda s: _RANK[s])
            quotes = [r["page_quote"] or r["quote"] for r in refs if r["status"] != "unreachable"]
            missing = number_mismatches(e["say"], quotes, [pages.get(r["claim_id"], "") for r in refs])
            if missing:
                notes.append("number(s) not in any quote: " + ", ".join(f"{v:g}" for v in missing))
                suggestions.append("use the figure the source gives, or cite the source that gives "
                                   + ", ".join(f"{v:g}" for v in missing))
                if status in ("exact", "normalized"):
                    status = "recovered"
            for r in refs:
                if r["status"] == "absent":
                    if r.get("passages"):
                        suggestions.append(f"{r['claim_id']}: the page does not say this; closest page text: "
                                           f"“{r['passages'][0][:300]}”. Reword to what it says, or cite "
                                           "another source")
                    else:
                        suggestions.append(f"{r['claim_id']}: nothing on the page carries this claim; cite a "
                                           "source that does, or cut the line")
                elif r["status"] == "unreachable":
                    suggestions.append(f"{r['claim_id']}: the page could not be read ({r['url']}); cite a "
                                       "readable copy (an official PDF, a Europe PMC full text, an archive)")
                elif r["status"] == "recovered":
                    notes.append(f"{r['claim_id']}: quote recovered from page text")
        elif _looks_factual(e["say"]):
            status = "unsourced"
            notes.append("states a number or an attribution with no source")
            suggestions.append("add the source URL and exact quote, or make the line framing only")
        else:
            status = "framing"
        lines.append({"line": e["line"], "say": e["say"], "part": e["part"], "status": status,
                      "claim_ids": e["claim_ids"], "notes": notes, "suggestions": suggestions})
    # A forbidden claim is matched on its own words, not the film's topic words: "lionfish can be
    # eradicated from Florida" is about "eradicated", which no line about Florida's lionfish says.
    topic = _content(" ".join([spec["title"], spec["central_question"], spec["slug"].replace("-", " ")]))
    for f in spec["forbidden_claims"]:
        fw = _content(f) - topic
        for row in lines:
            if fw and len(fw & _content(row["say"])) / len(fw) >= 0.6:
                row["notes"].append(f"may assert a claim the spec says we cannot make: “{f}”")
                row["suggestions"].append("cut or reword: it overlaps a forbidden claim")
    return {"claims": claims, "lines": lines}


def story_kind(claim: dict) -> str:
    """event | model | interpretation, as story_contract's story_kind. The spec's own label is kept,
    except that a quote reporting a model result is a model, and a hedged quote is an
    interpretation: neither may BE the consequence however it is labelled."""
    declared = _text(claim.get("evidence")).lower()
    quote = _text(claim.get("support_quote"))
    if declared == "model" or _MODEL_RE.search(quote):
        return "model"
    if declared == "interpretation" or _HEDGE_RE.search(quote):
        return "interpretation"
    return "event"


# ── the World consequence check ────────────────────────────────────────────────────────────────

def _years(*texts) -> list[int]:
    return [int(y) for t in texts for y in _YEAR4.findall(_text(t))]


def is_hypothetical_question(question: str) -> bool:
    return bool(_HYPOTHETICAL_RE.search(_text(question)))


def _documented(claim: dict) -> bool:
    story = _text(claim.get("story_kind")).lower()
    if story and story != "event":
        return False
    return _text(claim.get("claim_kind")).lower() in CONSEQUENCE_LEDGER_KINDS


def _mirror_validate_consequence_model(contract: dict, claims: dict, this_year: int) -> list[dict]:
    """story_contract.validate_consequence_model (PR #217), for when that module is not installed."""
    errors = []

    def err(code, message):
        errors.append({"code": code, "message": message})

    decision = contract.get("decision") or {}
    d_ids = [c for c in decision.get("claim_ids") or [] if c in claims]
    if not _text(decision.get("what")) or not d_ids:
        err("DECISION_MISSING", "name the past deliberate decision or fix, with the claims that document it")
    kind = _text(decision.get("kind")).lower()
    if kind not in DECISION_KINDS:
        err("DECISION_NOT_DELIBERATE", f"decision.kind {kind or '(none)'!r} is not a deliberate fix "
            f"({', '.join(DECISION_KINDS)}); an accident with no fix behind it is not a World film")
    if not _years(decision.get("when"), decision.get("what")):
        err("DECISION_UNDATED", "the decision needs a date (decision.when, a year)")
    cons = contract.get("consequence") or {}
    c_ids = [c for c in cons.get("claim_ids") or [] if c in claims]
    if not _text(cons.get("what")) or not c_ids:
        err("CONSEQUENCE_MISSING", "name the documented consequence of the decision, with its claims")
    elif not any(_documented(claims[c]) for c in c_ids):
        kinds = ", ".join(f"{c} ({_text(claims[c].get('story_kind')) or _text(claims[c].get('claim_kind'))})" for c in c_ids)
        err("CONSEQUENCE_NOT_DOCUMENTED", f"the consequence rests only on {kinds}: a model result or an "
            "interpretation may explain the mechanism but may not BE the consequence; cite a documented "
            "event or outcome")
    now = contract.get("still_unfolding") or {}
    n_ids = [c for c in now.get("claim_ids") or [] if c in claims]
    recent = [c for c in n_ids if _documented(claims[c]) and any(
        y >= this_year - PRESENT_YEARS for y in _years(claims[c].get("claim"), claims[c].get("support_quote")))]
    if not _text(now.get("what")) or not n_ids:
        err("STILL_UNFOLDING_MISSING", "name the documented, dated sign that the consequence is still unfolding today")
    elif not recent:
        err("STILL_UNFOLDING_NOT_PRESENT", f"no cited claim is a documented event dated within {PRESENT_YEARS} "
            f"years ({this_year - PRESENT_YEARS} or later): the film must be told from today")
    question = _text(contract.get("central_question"))
    if is_hypothetical_question(question):
        err("QUESTION_HYPOTHETICAL", f"{question!r} is a forward hypothetical; ask about the decision's consequence")
    return errors


def _lane_validator():
    try:
        import story_contract  # noqa: PLC0415 - PR #217; absent until it merges
        return getattr(story_contract, "validate_consequence_model", None)
    except Exception:  # noqa: BLE001
        return None


def consequence_contract(spec: dict) -> dict:
    def ids(block):
        return [_text(c) for c in (block.get("cite") or block.get("claim_ids") or []) if _text(c)]
    d, c, n = spec["decision"], spec["consequence"], spec["still_unfolding"]
    return {
        "decision": {"what": _text(d.get("what")), "who": _text(d.get("who")), "when": _text(d.get("when")),
                     "kind": _text(d.get("kind")), "claim_ids": ids(d)},
        "consequence": {"what": _text(c.get("what")), "claim_ids": ids(c)},
        "still_unfolding": {"what": _text(n.get("what")), "as_of": _text(n.get("as_of")), "claim_ids": ids(n)},
        "central_question": spec["central_question"],
        "ending_answer": spec["ending_answer"],
    }


def consequence_check(spec: dict, results: dict, this_year: int | None = None) -> dict:
    """The World rule: decision -> documented consequence -> still unfolding -> a consequence
    question. Applies when the spec's channel is world (or unset); any other channel is reported
    as not applicable. Binding claims must also verify on their pages."""
    this_year = this_year or int(time.strftime("%Y"))
    contract = consequence_contract(spec)
    if spec["channel"] not in WORLD_CHANNELS:
        return {"applies": False, "passed": True, "errors": [], "contract": contract, "rule": "n/a",
                "claim_kinds": {}}
    claims = {cid: {**c, "story_kind": results["claims"][cid]["story_kind"]}
              for cid, c in spec["claims"].items() if cid in results["claims"]}
    lane = _lane_validator()
    try:
        errors = lane(contract, claims, this_year) if lane else None
        rule = "story_contract.validate_consequence_model"
    except Exception:  # noqa: BLE001 - a changed signature falls back to the mirror
        errors = None
    if errors is None:
        errors = _mirror_validate_consequence_model(contract, claims, this_year)
        rule = "spec_import mirror of story_contract.validate_consequence_model (PR #217)"
    errors = list(errors)
    d = contract["decision"]
    if not d["who"]:
        errors.append({"code": "DECISION_UNNAMED", "message": "name who made the decision (decision.who)"})
    question = contract["central_question"]
    if not question:
        errors.append({"code": "QUESTION_MISSING", "message": "the spec needs a central_question"})
    elif not is_hypothetical_question(question) and not (
            _content(question) & _content(" ".join([d["what"], d["who"], contract["consequence"]["what"]]))):
        errors.append({"code": "QUESTION_NOT_CONSEQUENCE", "message": "the question shares no word with the "
                       "decision or its consequence; it must name (or clearly imply) the decision and ask "
                       "about its consequence"})
    if not contract["ending_answer"]:
        errors.append({"code": "ENDING_MISSING", "message": "the spec needs the ending answer, told from today"})
    for key in ("decision", "consequence", "still_unfolding"):
        for cid in contract[key]["claim_ids"]:
            r = results["claims"].get(cid)
            if r and r["status"] in ("absent", "unreachable"):
                errors.append({"code": f"{key.upper()}_UNVERIFIED",
                               "message": f"{key} cites {cid}, which is {STATUS_TEXT[r['status']]}"})
    kinds = {cid: claims[cid]["story_kind"] for k in ("decision", "consequence", "still_unfolding")
             for cid in contract[k]["claim_ids"] if cid in claims}
    return {"applies": True, "passed": not errors, "errors": errors, "contract": contract, "rule": rule,
            "claim_kinds": kinds}


# ── voice ──────────────────────────────────────────────────────────────────────────────────────

def voice_metrics(spec: dict) -> dict:
    sentences = [s for e in spec["entries"] for s in e["sentences"]]
    words = sum(len(s.split()) for s in sentences)
    target = int(spec["duration_sec"] * WORDS_PER_SECOND)
    nums = sum(1 for s in sentences for v in numbers_in(s) if v > 10) + \
        sum(1 for s in sentences if any(0 < v <= 10 for v in numbers_in(s)) and "%" in s)
    attributions = sum(len(_ATTRIBUTION.findall(s)) for s in sentences)
    long = [s for s in sentences if len(s.split()) > LONG_SENTENCE_WORDS]
    per100 = (lambda n: round(100.0 * n / words, 2)) if words else (lambda n: 0.0)
    return {
        "words": words, "sentences": len(sentences),
        "duration_target_sec": spec["duration_sec"], "target_words": target,
        "words_vs_target_pct": round(100.0 * words / target, 1) if target else 0.0,
        "est_duration_sec": round(words / WORDS_PER_SECOND),
        "mean_sentence_words": round(words / len(sentences), 1) if sentences else 0.0,
        "sentences_over_25_words": len(long), "long_sentences": long,
        "numbers_per_100_words": per100(nums), "attributions_per_100_words": per100(attributions),
    }


# ── report ─────────────────────────────────────────────────────────────────────────────────────

LINE_ICON = {"exact": "✅", "normalized": "✅", "recovered": "⚠", "absent": "❌", "unreachable": "🚫",
             "unsourced": "⚠", "framing": "·"}


def pipeline_dossier_check(spec: dict, results: dict) -> list[dict]:
    """The pipeline's own dossier validator on the dossier approval would build, run now so a claim
    it refuses (a quote whose negation disagrees with the claim, a weak domain) shows in the report
    instead of at approval."""
    try:
        import longform_research as lr  # noqa: PLC0415
        checked = lr.validate_research_dossier(build_dossier(spec, results))
    except Exception as exc:  # noqa: BLE001 - reported, never a crash
        return [{"code": "dossier_check_unavailable", "message": str(exc)[:200]}]
    if not [c for c in spec["claims"] if results["claims"][c]["status"] not in ("absent", "unreachable")]:
        return []                                # nothing verified yet: the line statuses say why
    return [e for e in checked.get("errors") or [] if e.get("severity") != "soft"]


def summarize(spec: dict, results: dict, consequence: dict, dossier_check: list | None = None) -> dict:
    counts = {k: 0 for k in ("supported", "paraphrased_or_recovered", "not_on_page", "unreachable",
                             "unsourced", "framing")}
    key = {"exact": "supported", "normalized": "supported", "recovered": "paraphrased_or_recovered",
           "absent": "not_on_page", "unreachable": "unreachable", "unsourced": "unsourced", "framing": "framing"}
    for row in results["lines"]:
        counts[key[row["status"]]] += 1
    claim_counts = {s: sum(1 for r in results["claims"].values() if r["status"] == s) for s in ICON}
    blocking = [p for p in spec["problems"]]
    ready = (not blocking and counts["not_on_page"] == 0 and counts["unreachable"] == 0
             and consequence["passed"] and not dossier_check)
    return {"lines": counts, "claims": claim_counts, "structural_problems": len(blocking),
            "dossier_errors": len(dossier_check or []), "ready_to_approve": ready}


def report_markdown(spec: dict, results: dict, consequence: dict, metrics: dict, summary: dict,
                    job_dir: str = "", dossier_check: list | None = None) -> str:
    sha = narration_sha256(spec)
    L = [f"# Spec verification: {spec['title'] or spec['slug']}", "",
         f"- Spec: `{spec.get('spec_path', '')}` (sha256 `{spec.get('spec_sha256', '')[:16]}`)",
         f"- Narration sha256: `{sha}`",
         f"- Channel: {spec['channel'] or 'world'}; checked {dt.date.today().isoformat()}; no provider calls", ""]
    c = summary["lines"]
    L += ["## Verdict", "",
          f"- **Ready to approve: {'YES' if summary['ready_to_approve'] else 'NO'}**",
          f"- Consequence model: **{'PASS' if consequence['passed'] else 'FAIL'}**"
          + ("" if consequence["applies"] else " (not applicable: channel is not World)"),
          f"- Lines: ✅ {c['supported']} supported · ⚠ {c['paraphrased_or_recovered']} paraphrased/recovered · "
          f"❌ {c['not_on_page']} not on page · 🚫 {c['unreachable']} unreachable · "
          f"⚠ {c['unsourced']} unsourced factual · {c['framing']} framing",
          f"- Claims: {len(results['claims'])} ({', '.join(f'{ICON[s]} {s} {n}' for s, n in summary['claims'].items() if n)})",
          ""]
    if spec["problems"]:
        L += ["## Spec problems (fix the spec)", ""] + [f"- `{p['code']}` {p['message']}" for p in spec["problems"]] + [""]
    if dossier_check:
        L += ["## Pipeline dossier check (the render would refuse these claims)", ""] + [
            f"- `{e.get('code')}` {e.get('claim_id', '')}: {e.get('message', '')}" for e in dossier_check] + [""]
    k = consequence["contract"]
    cites = lambda ids: (" — " + ", ".join(f"{i} ({consequence['claim_kinds'].get(i, '?')}, "
                                           f"{ICON.get(results['claims'].get(i, {}).get('status'), '?')})"
                                           for i in ids)) if ids else " — no claims cited"
    L += ["## World consequence model", "",
          f"Rule: {consequence['rule']}", "",
          f"- **Decision:** {k['decision']['what'] or '(missing)'} — who: {k['decision']['who'] or '(missing)'}; "
          f"when: {k['decision']['when'] or '(missing)'}; kind: {k['decision']['kind'] or '(missing)'}"
          + cites(k["decision"]["claim_ids"]),
          f"- **Documented consequence:** {k['consequence']['what'] or '(missing)'}" + cites(k["consequence"]["claim_ids"]),
          f"- **Still unfolding:** {k['still_unfolding']['what'] or '(missing)'} (as of "
          f"{k['still_unfolding']['as_of'] or '?'})" + cites(k["still_unfolding"]["claim_ids"]),
          f"- **Question:** {k['central_question'] or '(missing)'}",
          f"- **Ending answer:** {k['ending_answer'] or '(missing)'}",
          f"- **Human:** {spec['human']['person'] or '(none)'} — wants {spec['human']['want'] or '?'}; "
          f"detail: {spec['human']['detail'] or '?'}", ""]
    if consequence["errors"]:
        L += ["Fails:", ""] + [f"- `{e['code']}` {e['message']}" for e in consequence["errors"]] + [""]
    m = metrics
    L += ["## Voice", "",
          "| measure | value |", "|---|---|",
          f"| words vs target | {m['words']} / {m['target_words']} ({m['words_vs_target_pct']}%; "
          f"~{m['est_duration_sec']} s at {WORDS_PER_SECOND} w/s vs {m['duration_target_sec']} s) |",
          f"| sentences | {m['sentences']} |",
          f"| mean sentence length | {m['mean_sentence_words']} words |",
          f"| sentences over {LONG_SENTENCE_WORDS} words | {m['sentences_over_25_words']} |",
          f"| numbers per 100 words | {m['numbers_per_100_words']} |",
          f"| attributions per 100 words | {m['attributions_per_100_words']} |", ""]
    if m["long_sentences"]:
        L += ["Long sentences:", ""] + [f"- ({len(s.split())}w) {s}" for s in m["long_sentences"]] + [""]
    L += ["## Sentences", "", "✅ supported · ⚠ paraphrased, recovered or unsourced · ❌ not on page · "
          "🚫 unreachable · · framing (no factual claim)", ""]
    for row in results["lines"]:
        L.append(f"{row['line']}. {LINE_ICON[row['status']]} [{row['part']}] {row['say']}")
        for cid in row["claim_ids"]:
            r = results["claims"].get(cid)
            if not r:
                continue
            L.append(f"    - {ICON[r['status']]} `{cid}` {STATUS_TEXT[r['status']]} — {r['url']}")
            if r["status"] == "recovered":
                L.append(f"      - spec quote: “{r['quote'][:300]}”")
                L.append(f"      - page sentence used: “{r['page_quote'][:300]}”")
        for n in row["notes"]:
            L.append(f"    - note: {n}")
    L.append("")
    flagged = [r for r in results["lines"] if r["suggestions"]]
    L += ["## Suggested rewording (report only — the narration is not changed)", ""]
    if flagged:
        for r in flagged:
            L.append(f"- line {r['line']}: “{r['say']}”")
            L += [f"    - {s}" for s in r["suggestions"]]
    else:
        L.append("- none")
    L += ["", "## Approve", ""]
    if summary["ready_to_approve"]:
        L += ["This exact narration is ready. To build the dossier and state and resume the normal pipeline:", "",
              "```bash",
              f"python3 scripts/import_spec.py {spec.get('spec_path', '<spec>')} --out {job_dir or 'jobs/<slug>'} "
              f"--approve {sha} --max-cost <ceiling>",
              "```", "",
              "Any edit to the narration changes the hash and needs a new report."]
    else:
        L.append("Not ready: fix the spec (❌/🚫 lines, spec problems, dossier check, consequence failures) and re-run. "
                 "Nothing has been built or spent.")
    return "\n".join(L) + "\n"


def run_verification(spec_path: str, out_dir: str, *, fetch=None, offline: bool = False,
                     this_year: int | None = None, pages_dir: str = "") -> dict:
    spec = load_spec(spec_path)
    os.makedirs(out_dir, exist_ok=True)
    cache = PageCache(pages_dir or os.path.join(out_dir, PAGES_DIR), fetch=fetch, offline=offline)
    results = verify(spec, cache)
    consequence = consequence_check(spec, results, this_year)
    metrics = voice_metrics(spec)
    dossier_check = pipeline_dossier_check(spec, results)
    summary = summarize(spec, results, consequence, dossier_check)
    report = report_markdown(spec, results, consequence, metrics, summary, job_dir=out_dir,
                             dossier_check=dossier_check)
    with open(os.path.join(out_dir, REPORT_NAME), "w", encoding="utf-8") as handle:
        handle.write(report)
    record = {"spec_path": spec["spec_path"], "spec_sha256": spec["spec_sha256"],
              "narration_sha256": narration_sha256(spec), "summary": summary,
              "consequence": consequence, "metrics": metrics, "lines": results["lines"],
              "claims": results["claims"], "problems": spec["problems"], "dossier_check": dossier_check}
    with open(os.path.join(out_dir, RESULT_NAME), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=1, ensure_ascii=False, default=str)
    return {"spec": spec, "results": results, "consequence": consequence, "metrics": metrics,
            "summary": summary, "report": report, "cache": cache, "dossier_check": dossier_check}


# ── the approved build ─────────────────────────────────────────────────────────────────────────

def build_dossier(spec: dict, results: dict) -> dict:
    """The research dossier in the shape the pipeline resumes on (hand_build's new claims): every
    claim carries the quote observed on its page and a citation record for its URL, so
    longform_research.validate_research_dossier checks it like any other ledger."""
    claims, records, urls = [], [], []
    for cid, c in spec["claims"].items():
        r = results["claims"][cid]
        if r["status"] in ("absent", "unreachable"):
            continue
        quote = r["page_quote"] or c["support_quote"]
        claim = {"claim_id": cid, "claim": c["claim"], "source_url": c["source_url"], "support_quote": quote,
                 "source_type": c["source_type"], "claim_kind": c["claim_kind"], "claim_kind_confidence": 0.85,
                 "runner_up_kind": "", "runner_up_confidence": 0.5, "calculation": "", "assumptions": [],
                 "geographic_scope": c["geographic_scope"], "timescale": c["timescale"],
                 "confidence": c["confidence"], "allowed_exaggeration": False, "material": True,
                 "quote_verified": True, "source_reachable": True,
                 "support_provenance": "operator_spec" if r["status"] != "recovered" else "page_recovered",
                 "story_kind": r["story_kind"]}
        if r["status"] == "recovered":
            claim["support_quote_operator"] = c["support_quote"]
        claims.append(claim)
        records.append({"url": c["source_url"], "cited_text": quote})
        if c["source_url"] not in urls:
            urls.append(c["source_url"])
    return {
        "topic": spec["title"], "research_summary": spec["ending_answer"], "research_status": "complete",
        "claims": claims, "version": 1, "citation_records": records, "citation_urls": list(urls),
        "operator_source_urls": list(urls), "provider": "operator_spec",
        "spec_import": {"spec_sha256": spec["spec_sha256"], "narration_sha256": narration_sha256(spec)},
        "excluded_claims": [], "unverified_claims": [], "attested_unfetchable_claims": [],
        "claim_verification": {"verified": len(claims), "unverified": 0,
                               "repaired": sum(1 for c in claims if c["support_provenance"] == "page_recovered"),
                               "fetched": len(urls), "urls": len(urls)},
    }


def segment_record(spec: dict, dossier: dict) -> dict:
    """The approved-narration record story_contract_segment.build_state takes."""
    sentences = [{"text": e["say"], "claim_ids": list(e["claim_ids"]), "part": e["part"],
                  "kind": "fact" if e["claim_ids"] else "framing"} for e in spec["entries"]]
    k = consequence_contract(spec)
    return {
        "question": spec["central_question"] or spec["title"], "sentences": sentences, "dossier": dossier,
        "sha256": narration_sha256(spec), "version": 1, "status": "approved_spec",
        "lane_version": f"spec_import_v{SPEC_VERSION}", "contract_sha256": spec["spec_sha256"],
        "contract": {"central_question": spec["central_question"], "ending_answer": spec["ending_answer"],
                     "human_perspective": {"person": spec["human"]["person"], "want": spec["human"]["want"]},
                     "recurring_image": {"image": spec["recurring_image"]} if spec["recurring_image"] else {},
                     "reasonable_attempt": {"why_it_made_sense": k["decision"]["what"]},
                     "decision": k["decision"], "consequence": k["consequence"],
                     "still_unfolding": k["still_unfolding"]},
    }


def visual_plan(spec: dict, segment) -> dict:
    """Pictures the spec gave (`picture` per line), placed on the segmenter's own scene groups and
    anchored on each line's first words. Scenes with none get the segmenter's defaults."""
    sentences = [{"text": e["say"], "claim_ids": e["claim_ids"], "part": e["part"]} for e in spec["entries"]]
    rows = []
    for group in segment.split_scenes(sentences):
        beats = []
        for j in group:
            e = spec["entries"][j]
            if e["picture"]:
                beats.append({"anchor_phrase": " ".join(e["say"].split()[:4]), "visual": e["picture"],
                              "required_objects": [], "human_visible": False, "shot_size": "medium"})
        rows.append({"image_prompt": beats[0]["visual"] if beats else "", "visual_beats": beats})
    return {"scenes": rows}


def build_state(spec: dict, dossier: dict) -> dict:
    try:
        import story_contract_segment as segment  # noqa: PLC0415 - PR #217
    except ImportError as exc:
        raise SpecError("the approved build needs story_contract_segment (story-contract lane, PR #217), "
                        "which is not on this branch yet; the dossier was written, the state was not") from exc
    state = segment.build_state(segment_record(spec, dossier), title=spec["title"],
                                visual_plan=visual_plan(spec, segment), duration_sec=spec["duration_sec"])
    state = segment.strip_private(state)
    script = state["script"]
    script["_topic_channel"] = spec["channel"] if spec["channel"] != "" else "world"
    script["_spec_import"] = {"spec_path": spec["spec_path"], "spec_sha256": spec["spec_sha256"],
                              "narration_sha256": narration_sha256(spec), "version": SPEC_VERSION}
    if normalize_narration(" ".join(s["narration"] for s in script["scenes"])) != narration(spec):
        raise SpecError("the segmenter changed the approved words; nothing was written")
    return state


def resume_command(spec: dict, out_dir: str, max_cost: float, python: str = "python3") -> list[str]:
    r = spec["render"]
    cmd = [python, "scripts/run_illustrated_local.py", "--question", spec["title"] or spec["central_question"],
           "--out", out_dir, "--duration", str(spec["duration_sec"]), "--max-cost", f"{max_cost:.2f}",
           "--topic-channel", spec["channel"] or "world", "--resume"]
    for flag, key in (("--voice", "voice"), ("--palette", "palette"), ("--music-mix", "music_mix"),
                      ("--packaging", "packaging")):
        if _text(r.get(key)):
            cmd += [flag, _text(r[key])]
    if r.get("music"):
        cmd.append("--music")
    return cmd


def approve(spec_path: str, out_dir: str, approved_sha: str, *, max_cost: float, fetch=None,
            offline: bool = False, this_year: int | None = None, force: bool = False) -> dict:
    """Re-verify, check the hash, build the dossier and state. Writes nothing paid for; the caller
    launches the resume."""
    run = run_verification(spec_path, out_dir, fetch=fetch, offline=offline, this_year=this_year)
    spec, summary = run["spec"], run["summary"]
    current = narration_sha256(spec)
    if approved_sha != current:
        raise SpecError(f"the approved hash {approved_sha[:12]} is not this narration's ({current[:12]}); "
                        f"read {os.path.join(out_dir, REPORT_NAME)} and approve the current hash")
    if not summary["ready_to_approve"]:
        raise SpecError("the spec is not ready (see the report's verdict); nothing was built")
    if max_cost <= 0:
        raise SpecError("--max-cost must be a positive hard ceiling")
    dossier = build_dossier(spec, run["results"])
    import longform_research as lr  # noqa: PLC0415
    checked = lr.validate_research_dossier(dossier)
    with open(os.path.join(out_dir, "research_dossier.json"), "w", encoding="utf-8") as handle:
        json.dump(dossier, handle, indent=1, ensure_ascii=False)
    if not checked.get("passed"):
        raise SpecError("the built dossier fails validate_research_dossier: "
                        + ", ".join(f"{e.get('code')} {e.get('claim_id', '')}" for e in checked.get("errors") or []))
    state = build_state(spec, dossier)
    state_path = os.path.join(out_dir, "_state.json")
    if os.path.exists(state_path) and not force:
        raise SpecError(f"{state_path} exists (a run already started); pass --force to replace it "
                        "(the old one is kept as _state.pre_spec_<time>.json)")
    if os.path.exists(state_path):
        os.replace(state_path, os.path.join(out_dir, f"_state.pre_spec_{dt.datetime.now():%Y%m%d_%H%M%S}.json"))
    with open(state_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1, ensure_ascii=False)
    cmd = resume_command(spec, out_dir, max_cost)
    import shlex  # noqa: PLC0415
    with open(os.path.join(out_dir, "run_command.txt"), "w") as handle:   # rescue_script reads this
        handle.write(" ".join(shlex.quote(a) for a in cmd) + "\n")
    with open(os.path.join(out_dir, "spec_approval.json"), "w") as handle:
        json.dump({"narration_sha256": current, "spec_sha256": spec["spec_sha256"], "max_cost_usd": max_cost,
                   "approved_at": dt.datetime.now().isoformat(timespec="seconds"),
                   "claims": len(dossier["claims"]), "scenes": len(state["script"]["scenes"])}, handle, indent=1)
    return {"state_path": state_path, "command": cmd, "scenes": len(state["script"]["scenes"]),
            "claims": len(dossier["claims"]), "summary": summary}
