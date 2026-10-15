"""The long-film description template, shared by the pipeline, the uploader and the re-describer.

Operator-approved 2026-10-14, after studying a 14M-view explainer whose description is
research-forward. In order:

    1-3 summary paragraphs          the first two lines show above the fold
    promise line                    only when the film's own sourcing record makes it true
    ⏱️ CHAPTERS                      as today
    📚 RESEARCH & SOURCES            one entry per source the narration drew on, most-used first:
                                     citation, link, and what the film took from it
    📍 PEOPLE & PLACES IN THIS FILM  3-7 named people/places/objects, one fact-checked line each
    Short link(s), channel CTA, hashtags, the AI disclosure line, and any operator lines, as found

Removed: "🔎 IN THIS VIDEO", "❓ QUESTIONS ANSWERED" and any "Tags:" line.

Everything here is deterministic except people_and_places(), which makes ONE model call through a
`complete(system, user) -> text` callable the caller supplies, and then keeps only the lines whose
every number, quantity word and proper noun appears in the film's transcript or in the claims it
cites, and whose every other content word appears in what the film says about that name.

Nothing in a citation is invented. The research artifacts hold a URL and the claims drawn from it,
not a title, author or date, so a citation is the operator's own label for that URL when the
description already carries one, else a publisher named by the URL's domain, else the site; a year
appears only when the URL path carries one (/2006/05/). A doi.org link is printed as its canonical
https://doi.org/ form.
"""
from __future__ import annotations

import datetime
import json
import re
import unicodedata
from typing import Callable
from urllib.parse import urlsplit

RESEARCH_HEADER = "📚 RESEARCH & SOURCES"
PEOPLE_HEADER = "📍 PEOPLE & PLACES IN THIS FILM"
CHAPTERS_HEADER = "⏱️ CHAPTERS"
FINDING_MARK = "↳ "
# YouTube's limit on snippet.description is 5000 BYTES, not characters (videos resource docs);
# the section emojis are four bytes each and an em dash three.
MAX_BYTES = 5000
MAX_FINDING_CHARS = 160           # a longer claim is shown only when its source has no shorter one
MIN_SOURCES_BEFORE_PEOPLE = 3      # trim sources to this many before touching People & Places
MIN_PEOPLE_LINES = 2               # fewer surviving lines than this and the section is omitted
MAX_PEOPLE_LINES = 7
MAX_PEOPLE_LINE_CHARS = 240
PEOPLE_MODEL = "claude-haiku-5-5"

# THE PROMISE IS PER FILM, AND ONLY AS STRONG AS THAT FILM'S RECORD. The pipeline's claim ledger
# (story_fact_model.validate_cascade via longform_research.validate_story_fact_model) judges every
# narrated event against the claims it cites -- each claim carrying a quoted passage from its
# source -- and then every scene's narration against that event and those claims, and re-runs on
# the final narration after TTS, refusing the render when it fails. A film whose ledger passed
# with no soft finding earns "every factual line was checked"; soft findings mean non-material
# overshoot was let through while numbers, dates and names still had to pass, so the line says
# exactly that; an older script validated by phrase-level joins is "tied to" a quoted passage. A
# film whose ledger did not pass, passed with a beat the judge never judged (retryable /
# ENTAILMENT_UNAVAILABLE), or whose transcript no longer matches the narration that was checked,
# gets no promise at all.
PROMISES = {
    "checked": "Every factual line in this film was checked against quoted passages from {where}.",
    "material": ("Every number, date and name in this film was checked against quoted passages "
                 "from {where}."),
    "tied": "Every factual line in this film is tied to a quoted passage from {where}.",
}
_WHERE_ALL = "the sources below"
_WHERE_SOME = "its sources; the most-cited are listed below"
_PROMISE_RE = re.compile(r"^every (factual line|number, date and name) in this film (was checked|is "
                         r"tied)\b", re.I)

_URL = re.compile(r"https?://[^\s<>\"]+")
_HEADER = re.compile(
    r"^[^\w#]*\s*(?P<name>chapters|in this video|questions answered|"
    r"research\s*(?:&|and)\s*sources|sources|research|references|further reading|"
    r"people\s*(?:&|and)\s*places(?:\s+in\s+this\s+film)?)\s*:?\s*$", re.I)
_HASHTAGS = re.compile(r"^\s*(#[^\s#]+\s*)+$")
_SHORT_LINK = re.compile(r"(youtube\.com/shorts/|youtu\.be/|youtube\.com/watch)", re.I)
# Any YouTube link (a playlist, the channel page) or an @handle is the operator's, never research.
_YOUTUBE_LINK = re.compile(r"(?:youtube\.com|youtu\.be)/|(?<![\w.])@[A-Za-z0-9_.-]{3,}", re.I)
_FOOTER_START = re.compile(r"^(short version|full film|watch the short|subscribe\b|🤖|music:)", re.I)
# Labels an operator wrote that say what kind of thing a source is, not which one.
_GENERIC_LABELS = {"research paper", "historical account", "source", "sources", "study", "paper",
                   "article", "report", "research", "reference", "website", "link", "read more"}

# Publisher named by a URL's domain. A fact about who runs the domain AND authored its pages,
# never a guess about the page; the most specific suffix wins. Hosts and multi-journal brands are
# not in it (_HOSTS): nature.com carries Scientific Reports and Nature Communications as well as
# Nature, PubMed Central (ncbi.nlm.nih.gov) hosts other journals' papers, and so on. Their
# citations print the site.
PUBLISHERS = {
    "nasa.gov": "NASA",
    "nps.gov": "U.S. National Park Service",
    "usgs.gov": "U.S. Geological Survey",
    "fws.gov": "U.S. Fish and Wildlife Service",
    "noaa.gov": "NOAA",
    "epa.gov": "U.S. Environmental Protection Agency",
    "usda.gov": "U.S. Department of Agriculture",
    "doi.gov": "U.S. Department of the Interior",
    "usace.army.mil": "U.S. Army Corps of Engineers",
    "nih.gov": "U.S. National Institutes of Health",
    "cdc.gov": "U.S. Centers for Disease Control and Prevention",
    "loc.gov": "Library of Congress",
    "archives.gov": "U.S. National Archives",
    "si.edu": "Smithsonian Institution",
    "smithsonianmag.com": "Smithsonian Magazine",
    "britannica.com": "Encyclopaedia Britannica",
    "wikipedia.org": "Wikipedia",
    "nationalgeographic.com": "National Geographic",
    "bbc.co.uk": "BBC",
    "bbc.com": "BBC",
    "theguardian.com": "The Guardian",
    "nytimes.com": "The New York Times",
    "reuters.com": "Reuters",
    "apnews.com": "Associated Press",
    "springer.com": "Springer",
    "frontiersin.org": "Frontiers",
    "plos.org": "PLOS",
    "nber.org": "National Bureau of Economic Research",
    "worldbank.org": "World Bank",
    "who.int": "World Health Organization",
    "fao.org": "Food and Agriculture Organization of the UN",
    "un.org": "United Nations",
    "unesco.org": "UNESCO",
    "unep.org": "UN Environment Programme",
    "reliefweb.int": "ReliefWeb",
    "iucnredlist.org": "IUCN Red List",
    "csiro.au": "CSIRO",
}
# Sites that host or brand other people's work: never named as its publisher (checked before
# PUBLISHERS, so a PMC paper does not fall through to nih.gov either).
_HOSTS = {"nature.com", "ncbi.nlm.nih.gov", "science.org", "sciencedirect.com", "jstor.org"}


def _s(value) -> str:
    return str(value or "").strip()


def utf8_len(text: str) -> int:
    return len((text or "").encode("utf-8"))


# ── sources ───────────────────────────────────────────────────────────────────────────────────────

def site_of(url: str) -> str:
    host = (urlsplit(_s(url)).netloc or "").lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def url_key(url: str) -> str:
    """The same page however it was written: no scheme, no www, no trailing slash or fragment."""
    parts = urlsplit(_s(url).rstrip(".,;)"))
    path = parts.path.rstrip("/")
    return site_of(url) + path + (f"?{parts.query}" if parts.query else "")


def publisher_of(url: str) -> str:
    host = site_of(url)
    if any(host == h or host.endswith("." + h) for h in _HOSTS):
        return ""
    for suffix in sorted(PUBLISHERS, key=len, reverse=True):
        if host == suffix or host.endswith("." + suffix):
            return PUBLISHERS[suffix]
    return ""


def doi_link(url: str) -> str:
    """https://doi.org/<doi> when the URL IS a DOI (doi.org, dx.doi.org, doi:..., bare 10.x/...)."""
    text = _s(url)
    bare = re.match(r"^(?:doi:\s*)?(10\.\d{4,9}/\S+)$", text, re.I)
    if bare:
        return f"https://doi.org/{bare.group(1)}"
    if site_of(text) in ("doi.org", "dx.doi.org"):
        found = re.search(r"(10\.\d{4,9}/\S+)", urlsplit(text).path)
        if found:
            return f"https://doi.org/{found.group(1)}"
    return ""


def year_of(url: str) -> str:
    """The year in a dated URL path (/2006/05/...), the only date the artifacts actually hold.

    Not a file-upload folder (/wp-content/uploads/2024/05/): that dates the upload, not the work."""
    path = urlsplit(_s(url)).path
    if "/uploads/" in path.lower():
        return ""
    found = re.search(r"/((?:19|20)\d{2})/(0[1-9]|1[0-2])(?:/|$)", path)
    if found and int(found.group(1)) <= datetime.date.today().year:
        return found.group(1)
    return ""


def source_labels(text: str) -> dict[str, str]:
    """{url_key: label} from the source lines already in a description: "Label: URL", "Label:" or
    this template's citation line above a bare URL. An operator's edit to a citation survives."""
    labels: dict[str, str] = {}
    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        for match in _URL.finditer(line):
            url = match.group(0).rstrip(".,;)")
            label = line[:match.start()].strip()
            if not label and index > 0:
                previous = lines[index - 1].strip()
                if (previous and not _URL.search(previous) and not _HEADER.match(previous)
                        and not previous.startswith(FINDING_MARK.strip())):
                    label = previous
            label = re.sub(r"^[^\w\"“'(]+", "", label).strip().rstrip(":").strip(" -—–").strip()
            if _HEADER.match(label) or label.lower() in _GENERIC_LABELS:
                continue
            if label and label.lower() != site_of(url) and len(label) <= 160:
                labels.setdefault(url_key(url), label)
    return labels


def _clean_text(text: str) -> str:
    # YouTube refuses "<" and ">" anywhere in a description.
    return re.sub(r"\s+", " ", _s(text).replace("<", "‹").replace(">", "›")).strip()


def _finding(text: str) -> str:
    """A claim as the finding, whole. Never shortened: a cut lands before the clause the film
    used ("..., but queens and drones escaped") or keeps only the false half of a claim that says
    it was false. MAX_FINDING_CHARS only decides which claim to show (source_entries); compose()
    drops whole least-used sources to stay under the byte limit."""
    return _clean_text(text)


def _claims_map(script: dict) -> dict[str, dict]:
    dossier = (script or {}).get("_research_dossier") or {}
    return {_s(c.get("claim_id")): c for c in (dossier.get("claims") or [])
            if isinstance(c, dict) and _s(c.get("claim_id"))}


def scene_claim_refs(scene: dict) -> tuple[list[str], list[str]]:
    """(claim ids the narration cites, claim ids its event and opening ceiling rest on)."""
    narration = [_s(r.get("claim_id") if isinstance(r, dict) else r)
                 for r in (scene.get("claim_refs") or [])]
    support = []
    event = scene.get("event")
    if isinstance(event, dict):
        support += [_s(r) for r in (event.get("claim_refs") or [])]
    opening = scene.get("opening_ceiling")
    if isinstance(opening, dict):
        support += [_s(r) for r in (opening.get("claim_refs") or [])]
    return [c for c in narration if c], [c for c in support if c]


def used_claims(script: dict) -> list[dict]:
    """The claims the film used, in story order, each with how it was used.

    Only claims a scene cites count -- its narration's claim_refs, its event's, and the opening
    ceiling's -- so research the film never drew on is never presented as a source of it.
    """
    claims = _claims_map(script)
    rows: dict[str, dict] = {}
    for index, scene in enumerate((script or {}).get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        narration, support = scene_claim_refs(scene)
        for claim_id in dict.fromkeys(narration + support):
            if claim_id not in claims:
                continue
            row = rows.setdefault(claim_id, {"claim": claims[claim_id], "first_scene": index,
                                             "scenes": set(), "narrated": False})
            row["scenes"].add(index)
            row["narrated"] = row["narrated"] or claim_id in narration
    return sorted(rows.values(), key=lambda r: r["first_scene"])


def source_entries(script: dict, labels: dict[str, str] | None = None) -> list[dict]:
    """One entry per source the film used, most-used first (scenes drawing on it), then by first
    appearance. `finding` is a claim the film took from the source, preferring one its narration
    cites, then the most-cited, then the earliest, and one of at most MAX_FINDING_CHARS over a
    longer one -- a whole claim, never a paraphrase or a cut of one."""
    labels = labels or {}
    by_url: dict[str, dict] = {}
    for row in used_claims(script):
        url = _s(row["claim"].get("source_url"))
        if not url.startswith("http"):
            continue
        key = url_key(url)
        entry = by_url.setdefault(key, {"url": url, "scenes": set(), "first_scene": row["first_scene"],
                                        "claims": []})
        entry["scenes"] |= row["scenes"]
        entry["claims"].append(row)
    entries = []
    for key, entry in by_url.items():
        ranked = sorted(entry["claims"], key=lambda r: (not r["narrated"], -len(r["scenes"]),
                                                        r["first_scene"]))
        pick = ranked[0]
        if len(_clean_text(pick["claim"].get("claim"))) > MAX_FINDING_CHARS:
            # Any shorter claim the film used from this source, narrated or not, before a long
            # one; with none, the long claim whole.
            short = [r for r in ranked if len(_clean_text(r["claim"].get("claim"))) <= MAX_FINDING_CHARS]
            pick = short[0] if short else pick
        url = entry["url"]
        entries.append({
            "url": url,
            "link": doi_link(url) or url,
            "site": site_of(url),
            "label": labels.get(key, ""),
            "publisher": publisher_of(url),
            "year": year_of(url),
            "uses": len(entry["scenes"]),
            "first_scene": entry["first_scene"],
            "claim_ids": [_s(r["claim"].get("claim_id")) for r in ranked],
            "finding": _finding(pick["claim"].get("claim")),
        })
    entries.sort(key=lambda e: (-e["uses"], e["first_scene"], e["url"]))
    return entries


def entries_from_pairs(pairs) -> list[dict]:
    """Entries for callers that only hold (label, url) pairs: no finding, label only if real."""
    out = []
    for index, (label, url) in enumerate(pairs or []):
        url = _s(url)
        if not url.startswith("http"):
            continue
        label = _s(label)
        out.append({"url": url, "link": doi_link(url) or url, "site": site_of(url),
                    "label": "" if label.lower() in (site_of(url), *_GENERIC_LABELS) else label,
                    "publisher": publisher_of(url), "year": year_of(url), "uses": 0,
                    "first_scene": index, "claim_ids": [], "finding": ""})
    return out


def citation_line(entry: dict) -> str:
    """title/label -- publisher/site (year): only fields the artifacts or the operator supplied."""
    label, publisher, site, year = (_s(entry.get(k)) for k in ("label", "publisher", "site", "year"))
    if label:
        line = label
        if publisher and publisher.lower() not in label.lower() and site.lower() not in label.lower():
            line += f" — {publisher}"
    else:
        line = publisher or site
    if year and year not in line:
        line += f" ({year})"
    return _clean_text(line)


def entry_text(entry: dict) -> str:
    lines = [citation_line(entry), _s(entry.get("link") or entry.get("url"))]
    if _s(entry.get("finding")):
        lines.append(FINDING_MARK + _s(entry["finding"]))
    return "\n".join(lines)


def research_block(entries: list[dict]) -> str:
    return RESEARCH_HEADER + "\n" + "\n\n".join(entry_text(e) for e in entries)


# ── the promise ───────────────────────────────────────────────────────────────────────────────────

def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", text or "").lower())


def promise_kind(script: dict, transcript: str = "") -> str:
    """"checked", "material", "tied", or "" -- see PROMISES."""
    validation = (script or {}).get("_claim_validation")
    if not isinstance(validation, dict) or validation.get("passed") is not True:
        return ""
    # validate_story_fact_model passes a ledger whose judge was unavailable or gave an invalid
    # response for some beat (ENTAILMENT_UNAVAILABLE is retryable, so not blocking): that beat
    # was never judged, and the film earns no promise.
    if validation.get("retryable") or validation.get("skipped_for_structure") or any(
            isinstance(e, dict) and (e.get("retryable") or e.get("code") == "ENTAILMENT_UNAVAILABLE")
            for e in (validation.get("errors") or [])):
        return ""
    scenes = [s for s in ((script or {}).get("scenes") or []) if isinstance(s, dict)]
    if transcript:
        narration = " ".join(_s(s.get("narration")) for s in scenes)
        if _words(narration) != _words(transcript):
            return ""                 # the film says something the ledger did not check
    has_events = any(isinstance(s.get("event"), dict) and _s(s["event"].get("text")) for s in scenes)
    if has_events or "structure_status" in validation:
        # A soft overshoot outside the fidelity rows (the cold open's) is carried in errors only.
        soft = validation.get("soft_findings") or any(
            isinstance(e, dict) and e.get("severity") == "soft" for e in (validation.get("errors") or []))
        return "material" if soft else "checked"
    return "tied"


def promise_line(kind: str, all_listed: bool = True) -> str:
    template = PROMISES.get(kind or "")
    return template.format(where=_WHERE_ALL if all_listed else _WHERE_SOME) if template else ""


# ── People & Places ───────────────────────────────────────────────────────────────────────────────

PEOPLE_SYSTEM = (
    "You write the 'People & places in this film' list for a documentary's YouTube description. "
    "Use ONLY the transcript and the cited research claims you are given. Pick 3 to 7 people, "
    "places or objects that the TRANSCRIPT names and that matter to the story; give each name "
    "exactly as the transcript spells it. For each, write ONE plain sentence (at most 25 words) "
    "that retells its part in this story, reusing the words of the transcript sentence or claim "
    "that names it (a line whose words the film does not use about that name is discarded). "
    "Every number, date and name you write must appear in "
    "the transcript or the claims. Say only what a single transcript sentence or a single claim "
    "says about that name: never join two facts into a new one (where, when, by whom or why "
    "something happened), never add a motive, a judgement or a label such as a job or an "
    "epithet the transcript and claims do not use, and never describe a real person beyond the "
    "cited facts. Return ONLY JSON: {\"entries\": [{\"name\": \"...\", \"line\": \"...\"}]}")

_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
         "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
         "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
         "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
         "seventeenth": 17, "eighteenth": 18, "nineteenth": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90, "twentieth": 20, "thirtieth": 30, "fortieth": 40,
         "fiftieth": 50, "sixtieth": 60, "seventieth": 70, "eightieth": 80, "ninetieth": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9,
           "hundredth": 100, "thousandth": 1000}
_VAGUE = {"dozens", "hundreds", "thousands", "millions", "billions"}
# Words that state a quantity without a number (a dozen, half, twice, doubled, tenfold): a People &
# Places line may use one only when the transcript or the claims do, compared by root so that
# double / doubled / doubling are one. "score" is left out: its everyday sense is not a number.
_QUANTITY_ROOTS = {
    "dozen": "dozen", "half": "half", "halves": "half", "halved": "half", "halving": "half",
    "quarter": "quarter", "quarters": "quarter", "quartered": "quarter",
    "twice": "twice", "thrice": "thrice",
    "double": "double", "doubles": "double", "doubled": "double", "doubling": "double",
    "triple": "triple", "triples": "triple", "tripled": "triple", "tripling": "triple",
    "quadruple": "quadruple", "quadruples": "quadruple", "quadrupled": "quadruple",
    "quadrupling": "quadruple", "pair": "pair", "pairs": "pair", "couple": "couple",
    "couples": "couple"}
_DIGITS = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


def _plain(text: str) -> str:
    """Accents folded and curly apostrophes straightened, for comparison only."""
    folded = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in folded if not unicodedata.combining(ch)).replace("’", "'")


def _num_str(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def numbers_in(text: str) -> set[str]:
    """Every number the text states, digits or words, as a canonical string.

    "60,000", "sixty thousand" and "60 thousand" are all "60000"; "twenty-four" is "24"; "2.5
    million" is "2500000" (and not also "2.5"); "1960s" is "1960"; "hundreds" stays "hundreds"."""
    text = _plain(text).lower()
    found: set[str] = set()
    for match in _DIGITS.finditer(text):
        value = float(match.group(0).replace(",", ""))
        after = re.match(r"\s*(hundred|thousand|million|billion)\b", text[match.end():])
        found.add(_num_str(value * _SCALES[after.group(1)]) if after else _num_str(value))
    tokens = re.findall(r"[a-z]+", text.replace("-", " "))
    current, total, last = 0, 0, ""          # last: "", "unit", "tens", "scale"

    def flush():
        if last:
            found.add(str(total + current))

    for index, token in enumerate(tokens + [""]):
        nxt = tokens[index + 1] if index + 1 < len(tokens) else ""
        kind = "unit" if token in _ONES else "tens" if token in _TENS else ""
        if kind:
            # "two three-year-olds" is two numbers, and so is "nineteen fifty"; "twenty four" and
            # "hundred five" are one.
            if (kind == "unit" and last == "unit") or (kind == "tens" and last in ("unit", "tens")):
                flush()
                current, total = 0, 0
            current += _ONES.get(token, _TENS.get(token, 0))
            last = kind
        elif token == "a" and nxt in _SCALES and not last:
            current, last = 1, "unit"
        elif token in _SCALES and last:
            if _SCALES[token] == 100:
                current = (current or 1) * 100
            else:
                total += (current or 1) * _SCALES[token]
                current = 0
            last = "scale"
        elif token == "and" and last and (nxt in _ONES or nxt in _TENS):
            continue
        else:
            flush()
            current, total, last = 0, 0, ""
            if token in _VAGUE:
                found.add(token)
    return found


def quantity_words_in(text: str) -> set[str]:
    """The quantity words a text uses (see _QUANTITY_ROOTS), by root, plus any "<number>fold"."""
    found: set[str] = set()
    for token in re.findall(r"[a-z]+", _plain(text).lower()):
        if token in _QUANTITY_ROOTS:
            found.add(_QUANTITY_ROOTS[token])
        elif token.endswith("fold") and (token[:-4] in _ONES or token[:-4] in _TENS
                                         or token[:-4] in _SCALES or token[:-4] == "many"):
            found.add(token)
    return found


_FUNCTION_WORDS = {
    "a", "an", "the", "in", "on", "at", "by", "for", "from", "after", "before", "when", "its", "his",
    "her", "their", "this", "that", "these", "those", "with", "as", "under", "over", "during",
    "until", "while", "where", "once", "then", "but", "and", "or", "so", "to", "of", "it", "they",
    "he", "she", "we", "there", "here", "now", "today", "later", "only", "some", "many", "most",
    "all", "every", "each", "no", "not", "despite", "within", "without", "between", "into",
    "across", "along", "through", "because", "although", "though", "since", "who", "which", "what",
    "how", "why", "once", "still", "even", "also", "both", "former", "local", "native",
}
_TOKEN = re.compile(r"[^\W\d_](?:[\w'’\-]|\.(?=\w))*")


def _present(phrase: str, support: str, *, case: bool) -> bool:
    pattern = r"(?<![\w])" + re.escape(phrase) + r"(?![\w])"
    return re.search(pattern, support, 0 if case else re.I) is not None


def proper_noun_runs(text: str) -> list[tuple[list[str], bool]]:
    """Capitalised word runs as (tokens, starts_a_sentence). A possessive ends a run."""
    text = _plain(text)
    runs: list[tuple[list[str], bool]] = []
    current: list[str] = []
    initial = current_closed = False
    last_end = 0
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        gap = text[last_end:match.start()]
        before = text[:match.start()].rstrip()
        starts = not before or before[-1] in ".!?:;—–-(\"“'‘"
        if token[0].isupper():
            possessive = re.search(r"'s?$", token) is not None
            word = re.sub(r"'s?$", "", token)
            if current and gap == " " and not current_closed:
                current.append(word)
            else:
                if current:
                    runs.append((current, initial))
                current, initial = [word], starts
            current_closed = possessive
        else:
            if current:
                runs.append((current, initial))
            current, current_closed = [], False
        last_end = match.end()
    if current:
        runs.append((current, initial))
    return runs


# Words the wording gate does not ask the support for: grammar, not facts. Numbers and quantity
# words are left to their own checks.
_GRAMMAR_WORDS = _FUNCTION_WORDS | {
    "is", "are", "was", "were", "be", "been", "being", "has", "have", "had", "did", "does", "do",
    "him", "them", "our", "your", "would", "could", "should", "will", "can", "may", "might",
    "must", "near", "who", "whom", "whose"}
# Every content word of a line must be supported. A coverage allowance (one word in seven) was
# tried and let "Alvaro Molina -- fishing near Puerto Triunfo when a female hippo moved beneath his
# canoe, which killed him." through: the one unsupported word was the false one.
WORDING_MIN_COVERAGE = 1.0


def _stem(word: str) -> str:
    for suffix in ("ings", "ing", "edly", "ed", "es", "s", "ly"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[:-len(suffix)]
            break
    if word.endswith("i"):
        word = word[:-1] + "y"                       # studied, studies -> study
    elif word.endswith("e") and len(word) > 3:
        word = word[:-1]                             # escape, escaped -> escap
    if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "aeiou":
        word = word[:-1]                             # killed -> kill -> kil, kill -> kil
    return word


def _forms(word: str) -> set[str]:
    once = _stem(word)
    return {once, _stem(once)}


def _content_words(text: str) -> list[str]:
    out = []
    for word in re.findall(r"[a-z]+", _plain(text).lower()):
        if (len(word) < 3 or word in _GRAMMAR_WORDS or word in _ONES or word in _TENS
                or word in _SCALES or word in _VAGUE or quantity_words_in(word)):
            continue
        out.append(word)
    return out


def _sentences(text: str) -> list[str]:
    return [u for u in re.split(r"(?<=[.!?])[\"”’']?\s+", text or "") if u.strip()]


def wording_support(line: str, transcript: str, claims: list) -> tuple[float, list[str]]:
    """(coverage, unsupported words) of a People & Places line's wording.

    The support is only what the film says about THAT name: the transcript sentences and cited
    claims that mention one of the name's words (3+ letters). Every content word of the line (its
    grammar, numbers and the name itself aside) must occur there, compared by a light stem. A
    line can therefore not move a fact from one name to another ("killed" from Escobar's sentence
    to Molina's) or add a label, motive or outcome ("kingpin", "murderous") the film never says."""
    name, _, body = _s(line).partition(" — ")
    keys = {w for w in re.findall(r"[a-z]+", _plain(name).lower())
            if len(w) >= 3 and w not in _FUNCTION_WORDS}
    claim_texts = [_s(c.get("claim") if isinstance(c, dict) else c) for c in (claims or [])]
    units = [u for u in _sentences(transcript) + claim_texts
             if keys & set(re.findall(r"[a-z]+", _plain(u).lower()))]
    have: set[str] = set()
    for unit in units:
        for word in _content_words(unit):
            have |= _forms(word)
    name_forms = set().union(*(_forms(k) for k in keys)) if keys else set()
    words = [w for w in _content_words(body) if not _forms(w) & name_forms]
    missing = [w for w in words if not _forms(w) & have]
    return (1 - len(missing) / len(words)) if words else 1.0, missing


def check_people_line(line: str, transcript: str, claims: list) -> list[str]:
    """Why a People & Places line cannot be published; [] when it can.

    Every number, quantity word, year and proper noun in the line must appear in the transcript
    or in the claims the film cites, and every other content word in what the film says about
    that name (wording_support). Nothing else is accepted as evidence -- not the dossier's unused
    research, not the model's knowledge."""
    problems = []
    line = _s(line)
    if " — " not in line or not line.split(" — ", 1)[0].strip() or not line.split(" — ", 1)[1].strip():
        problems.append("not 'Name — line'")
    if len(line) > MAX_PEOPLE_LINE_CHARS:
        problems.append(f"over {MAX_PEOPLE_LINE_CHARS} characters")
    claim_texts = [_s(c.get("claim") if isinstance(c, dict) else c) for c in (claims or [])]
    support = _plain(" \n".join([transcript or ""] + claim_texts))
    name = line.split(" — ", 1)[0].strip()
    if name and transcript and not _present(_plain(name), _plain(transcript), case=False):
        # The section lists who and what the FILM names, not what its research mentions.
        problems.append(f"{name!r} is not named in the narration")
    missing = numbers_in(line) - numbers_in(support)
    if missing:
        problems.append(f"unsupported numbers {sorted(missing)}")
    quantities = quantity_words_in(line) - quantity_words_in(support)
    if quantities:
        problems.append(f"unsupported quantity {sorted(quantities)}")
    for tokens, initial in proper_noun_runs(line):
        if initial and tokens and tokens[0].lower() in _FUNCTION_WORDS:
            tokens = tokens[1:]
            initial = False
        if not tokens:
            continue
        phrase = " ".join(tokens)
        if len(tokens) == 1:
            ok = _present(phrase, support, case=not initial)
        else:
            ok = _present(phrase, support, case=False)
        if not ok:
            problems.append(f"unsupported name {phrase!r}")
    if " — " in line:
        coverage, unsupported = wording_support(line, transcript, claims)
        if coverage < WORDING_MIN_COVERAGE:
            problems.append(f"unsupported wording {sorted(set(unsupported))} "
                            f"(coverage {coverage:.2f})")
    return problems


def _parse_entries(raw: str) -> list[dict]:
    match = re.search(r"\{.*\}", raw or "", re.S)
    try:
        data = json.loads(match.group(0) if match else raw)
    except (ValueError, TypeError):
        return []
    rows = data.get("entries") if isinstance(data, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict)]


def people_and_places(transcript: str, claims: list, complete: Callable[[str, str], str]
                      ) -> tuple[list[str], dict]:
    """(publishable lines, report) from ONE model call over the transcript and cited claims only."""
    claim_texts = [_s(c.get("claim") if isinstance(c, dict) else c) for c in (claims or [])]
    user = json.dumps({"transcript": _s(transcript), "cited_claims": [c for c in claim_texts if c]},
                      ensure_ascii=False)
    report: dict = {"generated": 0, "kept": [], "dropped": []}
    try:
        raw = complete(PEOPLE_SYSTEM, user)
    except Exception as exc:  # noqa: BLE001 - the section is optional; the description is not
        report["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return [], report
    seen: set[str] = set()
    lines: list[str] = []
    rows = _parse_entries(raw)
    report["generated"] = len(rows)
    for row in rows:
        name = _clean_text(row.get("name")).strip(" —-:")
        body = _clean_text(row.get("line")).lstrip("—-: ")
        if not name or not body or name.lower() in seen:
            continue
        line = f"{name} — {body}"
        problems = check_people_line(line, transcript, claims)
        if problems:
            report["dropped"].append({"line": line, "problems": problems})
            continue
        seen.add(name.lower())
        lines.append(line)
    lines = lines[:MAX_PEOPLE_LINES]
    if len(lines) < MIN_PEOPLE_LINES:
        report["omitted"] = f"{len(lines)} line(s) survived the fact check; the section needs {MIN_PEOPLE_LINES}"
        lines = []
    report["kept"] = lines
    return lines, report


def recheck_people(lines: list[str], transcript: str, claims: list) -> tuple[list[str], list]:
    """Existing People & Places lines that still pass, and the ones that no longer do."""
    kept, dropped = [], []
    for line in lines:
        problems = check_people_line(line, transcript, claims)
        (dropped.append({"line": line, "problems": problems}) if problems else kept.append(line))
    if len(kept) < MIN_PEOPLE_LINES:
        kept = []
    return kept[:MAX_PEOPLE_LINES], dropped


def people_block(lines: list[str]) -> str:
    return PEOPLE_HEADER + "\n" + "\n".join(lines)


def anthropic_complete(cost_sink: list | None = None, model: str = PEOPLE_MODEL):
    """A `complete` for scripts: the Anthropic client with the workspace header, metered, cheap."""
    import os

    import anthropic

    import usage_ledger
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    client = usage_ledger.meter(anthropic.Anthropic(
        default_headers={"anthropic-workspace-id": workspace} if workspace else {}, timeout=120.0))

    def complete(system: str, user: str) -> str:
        response = client.messages.create(model=model, max_tokens=1500, system=system,
                                          thinking={"type": "disabled"},
                                          messages=[{"role": "user", "content": user}])
        if cost_sink is not None:
            cost_sink.append(usage_ledger.anthropic_cost(model, response.usage))
        return next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    return complete


# ── parse and compose ─────────────────────────────────────────────────────────────────────────────

def _blocks(text: str) -> list[str]:
    return [b.strip("\n") for b in re.split(r"\n[ \t]*\n", (text or "").strip()) if b.strip()]


def _header_kind(line: str) -> str:
    match = _HEADER.match(line.strip())
    if not match:
        return ""
    name = re.sub(r"\s+", " ", match.group("name").lower())
    if name == "chapters":
        return "chapters"
    if name in ("in this video", "questions answered"):
        return "drop"
    if name.startswith("people"):
        return "people"
    return "sources"


def _is_footer(lines: list[str]) -> bool:
    first = lines[0].strip()
    return bool(_FOOTER_START.match(first) or _HASHTAGS.match(first) or _SHORT_LINK.search(first))


def _is_source_continuation(lines: list[str]) -> bool:
    """A block that may still belong to a sources section: it carries a URL, and nothing in it is
    a footer line (a Short link, the CTA, hashtags, the AI line) or any YouTube link or @handle (a
    playlist or channel line). rebuild() still keeps such a block when none of its URLs is in the
    film's research (a ko-fi or newsletter line looks just like 'site: URL')."""
    if any(_FOOTER_START.match(l.strip()) or _HASHTAGS.match(l.strip()) or _SHORT_LINK.search(l)
           or _YOUTUBE_LINK.search(l) for l in lines):
        return False
    return any(_URL.search(l) for l in lines)


def _source_shaped(lines: list[str]) -> bool:
    """A block written the way a source list is: every line a bare URL, a "↳" finding, a citation
    or "Label:" line directly above a bare URL, or "site: URL" whose label is the URL's own site.
    "Support the channel: https://ko-fi.com/..." is not: its label is not its site."""
    lines = [l.strip() for l in lines if l.strip()]
    for n, line in enumerate(lines):
        if re.fullmatch(r"https?://\S+", line) or line.startswith(FINDING_MARK.strip()):
            continue
        if not _URL.search(line):
            if n + 1 < len(lines) and re.fullmatch(r"https?://\S+", lines[n + 1]):
                continue
            return False
        label, _, rest = line.partition(": ")
        url = _URL.search(rest)
        if not (url and rest.strip() == url.group(0)):
            return False
        site = site_of(url.group(0))
        if label.strip().lower().removeprefix("www.") not in (site, site.split(".", 1)[-1]):
            return False
    return bool(lines)


def parse(text: str) -> dict:
    """Split a description into what the template manages and what it keeps as found.

    summary   the leading paragraphs, before the first managed section or footer line
    chapters  the ⏱️ CHAPTERS block, verbatim
    sources   the raw text of any SOURCES / RESEARCH section (labels are harvested from it)
    source_blocks  that section's blocks after its header block, with their tail position
    people    existing People & Places lines
    tail      every other block after the summary, in its original order (Short links, CTA,
              hashtags, the AI line, music credits, operator lines)
    removed   the IN THIS VIDEO / QUESTIONS blocks, Tags: lines and promise lines dropped
    """
    out = {"summary": [], "chapters": "", "sources": "", "people": [], "tail": [], "removed": [],
           "source_blocks": []}
    section = ""
    in_tail = False
    for block in _blocks(text):
        lines = []
        for line in block.split("\n"):
            probe = line.strip()
            if probe.lower().startswith("tags:") or _PROMISE_RE.match(probe):
                out["removed"].append(line)
                in_tail = True
                continue
            lines.append(line)
        if not lines:
            continue
        kind = _header_kind(lines[0])
        if kind:
            in_tail = True
            section = kind
            if kind == "chapters":
                out["chapters"] = out["chapters"] or "\n".join(lines)
            elif kind == "people":
                out["people"] += [l.strip() for l in lines[1:] if l.strip()]
            elif kind == "sources":
                out["sources"] += "\n".join(lines) + "\n\n"
            else:
                out["removed"].append("\n".join(lines))
            continue
        if section == "sources" and _is_source_continuation(lines):
            out["sources"] += "\n".join(lines) + "\n\n"
            # (where it would sit in the tail, the block): rebuild() puts it back there when it
            # turns out to be the operator's, not research.
            out["source_blocks"].append((len(out["tail"]), "\n".join(lines)))
            continue
        section = ""
        if not in_tail and not _is_footer(lines):
            out["summary"].append("\n".join(lines))
        else:
            in_tail = True
            out["tail"].append("\n".join(lines))
    return out


def strip_retired(text: str) -> str:
    """The description with only the retired parts removed (IN THIS VIDEO, QUESTIONS ANSWERED,
    Tags: lines), everything else where it was. For a job with no research artifacts to rebuild
    from, where rebuild() refuses."""
    kept = []
    for block in _blocks(text):
        lines = [l for l in block.split("\n") if not l.strip().lower().startswith("tags:")]
        if lines and _header_kind(lines[0]) != "drop":
            kept.append("\n".join(lines))
    return "\n\n".join(kept)


def compose(summary: list[str], *, promise: str = "", chapters: str = "", entries=(),
            people=(), tail=(), limit: int = MAX_BYTES) -> tuple[str, dict]:
    """The description in template order, trimmed to `limit` UTF-8 bytes.

    Trimming order: least-used sources (down to MIN_SOURCES_BEFORE_PEOPLE), then People & Places
    lines from the end (the section goes below MIN_PEOPLE_LINES), then the remaining sources. The
    summary, chapters, Short links, CTA, hashtags, AI line and operator lines are never cut. When
    sources are trimmed the promise says the list is partial; with none listed it is omitted.
    """
    entries, people = list(entries), list(people)
    n_src, n_people = len(entries), len(people) if len(people) >= MIN_PEOPLE_LINES else 0

    def build(ns: int, npl: int) -> str:
        parts = [p for p in summary if _s(p)]
        line = promise_line(promise, all_listed=ns == len(entries)) if (promise and ns) else ""
        if line:
            parts.append(line)
        if _s(chapters):
            parts.append(chapters)
        if ns:
            parts.append(research_block(entries[:ns]))
        if npl:
            parts.append(people_block(people[:npl]))
        parts += [t for t in tail if _s(t)]
        return "\n\n".join(p.strip("\n") for p in parts)

    text = build(n_src, n_people)
    while utf8_len(text) > limit:
        if n_src > MIN_SOURCES_BEFORE_PEOPLE:
            n_src -= 1
        elif n_people > MIN_PEOPLE_LINES:
            n_people -= 1
        elif n_people:
            n_people = 0
        elif n_src:
            n_src -= 1
        else:
            break
        text = build(n_src, n_people)
    report = {"bytes": utf8_len(text), "chars": len(text), "over_limit": utf8_len(text) > limit,
              "sources_listed": n_src, "sources_used": len(entries),
              "sources_trimmed": [e["url"] for e in entries[n_src:]],
              "people_listed": n_people, "promise": bool(promise and n_src)}
    return text, report


# ── a job's artifacts ─────────────────────────────────────────────────────────────────────────────

def load_job(job: str, recut: bool | None = None) -> dict:
    """{"script", "transcript", "recut"} from a finished job directory (no network, no provider).

    A re-cut opening (scripts/recut_opening.py: recut_opening.json beside explainer.recut.mp4)
    put narration in the film that the claim ledger never judged, in place of the original
    scenes before its splice. `recut` None detects it; when it applies, the film is the opening
    plus the original scenes from the splice on (_recut_film): their claims count as used, their
    narration is the transcript the People & Places lines are checked against, and the promise is
    withheld (rebuild). Raises ValueError when the recut cannot be laid out exactly."""
    import os
    state_path = os.path.join(job, "_state.json")
    script: dict = {}
    if os.path.isfile(state_path):
        with open(state_path, encoding="utf-8") as handle:
            script = (json.load(handle) or {}).get("script") or {}
    if script and not _claims_map(script):
        dossier_path = os.path.join(job, "research_dossier.json")
        if os.path.isfile(dossier_path):
            with open(dossier_path, encoding="utf-8") as handle:
                script = {**script, "_research_dossier": json.load(handle)}
    transcript = ""
    transcript_path = os.path.join(job, "transcript.txt")
    if os.path.isfile(transcript_path):
        with open(transcript_path, encoding="utf-8") as handle:
            transcript = handle.read().strip()
    if recut is None:
        recut = has_recut(job)
    if recut and script:
        script, transcript = _recut_film(job, script)
    return {"script": script, "transcript": transcript, "recut": bool(recut)}


def has_recut(job: str) -> bool:
    import os
    return (os.path.isfile(os.path.join(job, "recut_opening.json"))
            and os.path.isfile(os.path.join(job, "explainer.recut.mp4")))


def _recut_film(job: str, script: dict) -> tuple[dict, str]:
    """(script, transcript) of the re-cut film: the new opening, then only the original scenes
    that start at or after the splice. recut_opening.py replaces film time 0..splice_sec, so the
    original scenes before it are not in the film, and their names and claims are not either.
    Scene start times come from audio_timing_report.json; without it, or when it does not match
    the script, the job is refused as a recut rather than guessed at."""
    import os
    spec_path = os.path.join(job, "recut_opening.json")
    timing_path = os.path.join(job, "audio_timing_report.json")
    if not os.path.isfile(spec_path):
        raise ValueError(f"{job}: no recut_opening.json, so there is no re-cut film")
    with open(spec_path, encoding="utf-8") as handle:
        spec = json.load(handle) or {}
    opening = [s for s in (spec.get("scenes") or []) if isinstance(s, dict)]
    splice = float(spec.get("splice_sec") or 0)
    if not os.path.isfile(timing_path):
        raise ValueError(f"{job}: no audio_timing_report.json, so the original scenes the re-cut "
                         "opening replaced cannot be told apart; refusing to treat it as a recut")
    with open(timing_path, encoding="utf-8") as handle:
        timing = [t for t in ((json.load(handle) or {}).get("scenes") or []) if isinstance(t, dict)]
    timing.sort(key=lambda t: t.get("scene") if isinstance(t.get("scene"), int) else 0)
    scenes = list(script.get("scenes") or [])
    if splice <= 0 or not opening or len(timing) != len(scenes) or any(
            not isinstance(t.get("start_sec"), (int, float)) for t in timing):
        raise ValueError(f"{job}: recut_opening.json (splice {splice}, {len(opening)} opening "
                         f"scenes) and audio_timing_report.json ({len(timing)} timed scenes for "
                         f"{len(scenes)} script scenes) do not line up; refusing to guess the recut")
    kept = [scene for scene, t in zip(scenes, timing) if float(t["start_sec"]) >= splice - 0.05]
    film = opening + kept
    transcript = " ".join(_s(s.get("narration")) for s in film if _s(s.get("narration")))
    return {**script, "scenes": film}, transcript


def cited_claims(script: dict) -> list[dict]:
    return [row["claim"] for row in used_claims(script)]


def film_research(script: dict, transcript: str = "", labels: dict | None = None) -> dict:
    """What a new film's description needs from its script: sources, cited claims, promise."""
    entries = source_entries(script, labels)
    return {"entries": entries, "claims": cited_claims(script),
            "promise": promise_kind(script, transcript) if entries else ""}


def rebuild(text: str, facts: dict, people: list[str] | None = None,
            limit: int = MAX_BYTES) -> tuple[str, dict]:
    """`text` re-laid in the template from the film's own artifacts.

    The summary, chapters and every non-managed line are kept as found. The promise and the
    research section are rebuilt from `facts` (load_job), with the operator's existing source
    labels reused as citations. `people`: lines to use; None keeps the existing section's lines
    that still pass the fact check.
    """
    script, transcript = facts.get("script") or {}, facts.get("transcript") or ""
    if not _claims_map(script):
        # Rebuilding SOURCES from nothing would delete the live list. Refuse instead.
        raise ValueError("no research artifacts (no dossier claims in the job's _state.json or "
                         "research_dossier.json): cannot rebuild the sources")
    parsed = parse(text)
    labels = source_labels(parsed["sources"])
    entries = source_entries(script, labels)
    claims = cited_claims(script)
    dropped_people: list = []
    if people is None:
        people, dropped_people = recheck_people(parsed["people"], transcript, claims)
    # A block after the sources header that is not written like a source entry and none of whose
    # URLs is in the film's research (used or not) is the operator's -- a ko-fi, newsletter or
    # website line -- and goes back where it was. An old "Label:\nURL" entry the research does not
    # hold is a source the film did not use: dropped and reported, like any other.
    research_keys = {url_key(c.get("source_url")) for c in _claims_map(script).values()
                     if _s(c.get("source_url")).startswith("http")}
    tail, custom, custom_keys = list(parsed["tail"]), [], set()
    for position, block in parsed["source_blocks"]:
        keys = {url_key(m.group(0)) for m in _URL.finditer(block)}
        if keys and not keys & research_keys and not _source_shaped(block.split("\n")):
            tail.insert(position + len(custom), block)
            custom.append(block)
            custom_keys |= keys
    # A re-cut opening's narration was never judged by the ledger: no promise for that film.
    kind = promise_kind(script, transcript) if entries and not facts.get("recut") else ""
    new, report = compose(parsed["summary"], promise=kind, chapters=parsed["chapters"],
                          entries=entries, people=people, tail=tail, limit=limit)
    live_urls = {url_key(m.group(0)): m.group(0).rstrip(".,;)")
                 for m in _URL.finditer(parsed["sources"])}
    used_keys = {url_key(e["url"]) for e in entries}
    report.update({
        "promise_kind": kind,
        "recut": bool(facts.get("recut")),
        "removed": parsed["removed"],
        "kept_custom_blocks": custom,
        "live_sources_dropped": [u for k, u in live_urls.items()
                                 if k not in used_keys and k not in custom_keys],
        "people_dropped": dropped_people,
        "summary_paragraphs": len(parsed["summary"]),
    })
    return new, report
