"""YouTube metadata rules, applied as code rather than remembered.

From the optimization playbook. Only the parts that are mechanical live here -- the playbook's own
conclusion is that the cancer-video result was an encouraging signal from a 36-impression sample, not
proof, so nothing in this module should be read as a promise about ranking. What it does is stop the
avoidable mistakes: over-long titles, keyword-chain titles, chapter labels nobody searches for, tag
fields over budget, and descriptions missing the sections the playbook asks for.

The division of labour the playbook settles on, which is also how these functions are split:

    title       one primary query + one promise
    thumbnail   subject + a SEPARATE curiosity hook (never the title repeated)
    description semantic depth, questions, sources, disclosures
    chapters    subqueries in the language people actually search
    tags        close variations and misspellings only
"""
from __future__ import annotations
import re

TITLE_MIN, TITLE_MAX = 45, 65      # working range for search-led explainers, not a YouTube rule
TAGS_MAX = 500                     # hard field limit
DESC_MAX = 5000                    # hard field limit
HASHTAGS_IDEAL = 3

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")


def check_title(title):
    """Mechanical title problems only. Whether it is a GOOD title is not decidable here."""
    t = (title or "").strip()
    out = {"title": t, "chars": len(t), "problems": [], "notes": []}
    if len(t) > TITLE_MAX:
        out["problems"].append(f"{len(t)} chars, over the {TITLE_MAX} working max -- may truncate")
    elif len(t) < TITLE_MIN:
        out["notes"].append(f"{len(t)} chars, short; fine if the query is fully present")
    if _EMOJI.search(t):
        out["problems"].append("contains an emoji: adds no keyword value and costs display width")
    if t.count("|") or t.count("—") > 1:
        out["problems"].append("pipe or multiple dashes suggests a keyword chain; one promise only")
    if len(re.findall(r",", t)) >= 2:
        out["problems"].append("comma list reads as a keyword chain -- move secondaries to the "
                               "description")
    if t.isupper():
        out["problems"].append("all caps: capitalisation is presentation, not ranking")
    return out


def title_variants(primary_query, subject, surprise, promise=None, hybrid=None):
    """Three MEANINGFULLY different titles, labelled by strategy for a Title-only A/B test.

    The playbook is explicit that the variants must differ in approach rather than wording, and that
    YouTube picks the winner on watch time -- so the curiosity variant has to be honest or it wins the
    click and loses the session.
    """
    promise = promise or f"{subject} Explained"
    # The hybrid is AUTHORED, not spliced. Concatenating query + surprise overruns the budget, and
    # truncating the result produces fragments ("Lets You Keep The") that would burn a two-week test
    # slot. If no hybrid is supplied the slot is left explicitly empty rather than filled with noise.
    out = [
        {"strategy": "search-first", "title": f"{primary_query} {promise}".strip()},
        {"strategy": "curiosity-first", "title": surprise},
        {"strategy": "hybrid", "title": hybrid or "<author one: precise framing + curiosity>"},
    ]
    # A variant that violates the title rules is not a variant, it is a wasted test slot. The A/B
    # tool runs for up to two weeks on three titles; shipping an over-length one spends that window.
    for v in out:
        v["problems"] = [] if v["title"].startswith("<") else check_title(v["title"])["problems"]
    return out


def searchable_chapter(label, subject_hint=""):
    """Turn a bare noun chapter into something a person would type.

    'Titan' is not a search. 'How high you could jump on Titan' is. The playbook's own table makes
    exactly this swap ('Tumors Are Patchworks' -> 'Tumor Heterogeneity Explained'), and every chapter
    list this project has shipped so far was bare nouns.
    """
    lab = (label or "").strip()
    if len(lab.split()) >= 4 or "?" in lab:
        return lab                                   # already a phrase
    return f"{subject_hint} {lab}".strip() if subject_hint else lab


def tag_field(tags, primary_query=""):
    """Assemble the backend tag field within budget, with apostrophe variants.

    Apostrophe handling is the single highest-value tag trick the playbook names: 'why can't we cure
    cancer' and 'why cant we cure cancer' are different strings to the field, and viewers type both.
    """
    seen, out = set(), []
    def add(t):
        t = " ".join((t or "").lower().split())
        if t and t not in seen:
            seen.add(t); out.append(t)
    if primary_query:
        add(primary_query.rstrip("?"))
        if "'" in primary_query:
            add(primary_query.rstrip("?").replace("'", ""))
    for t in tags:
        add(t)
        if "'" in t:
            add(t.replace("'", ""))
    field, total = [], 0
    for t in out:
        add_len = len(t) + (2 if field else 0)
        if total + add_len > TAGS_MAX:
            break
        field.append(t); total += add_len
    return {"field": ", ".join(field), "chars": total, "used": len(field),
            "dropped": len(out) - len(field)}


def questions_block(questions):
    """The QUESTIONS ANSWERED section. The playbook wants 5-8 questions the video GENUINELY answers --
    a question here that the video does not address is the kind of mismatch that wins a click and
    loses the retention that YouTube actually ranks on."""
    qs = [q.strip().rstrip("?") + "?" for q in questions if q and q.strip()]
    return "QUESTIONS ANSWERED\n" + "\n".join(f"- {q}" for q in qs[:8]), len(qs)


def check_description(text, chapters=(), hashtags=()):
    """The publishing gate, as far as it can be mechanised."""
    t = text or ""
    out = {"chars": len(t), "problems": [], "notes": []}
    if len(t) > DESC_MAX:
        out["problems"].append(f"{len(t)} chars, over the {DESC_MAX} field limit")
    first = " ".join(t.strip().split("\n")[:2])
    if len(first) < 40:
        out["problems"].append("first two lines are thin: they must carry the primary query and the "
                               "promise, since that is what shows above the fold")
    if "QUESTIONS ANSWERED" not in t.upper():
        out["notes"].append("no QUESTIONS ANSWERED section")
    if "SOURCE" not in t.upper():
        out["notes"].append("no SOURCES section -- for science claims this is credibility, not SEO")
    if "0:00" not in t:
        out["notes"].append("no chapters; the first must be 0:00 or YouTube ignores the list")
    elif chapters and not str(chapters[0]).startswith("0:00"):
        out["problems"].append("first chapter is not 0:00, so YouTube will not render the list")
    n_hash = t.count("#")
    if n_hash > 5:
        out["problems"].append(f"{n_hash} hashtags; the playbook settles on about {HASHTAGS_IDEAL}")
    bare = [c for c in chapters if len(str(c).split()) <= 2]
    if bare:
        out["notes"].append(f"{len(bare)} chapter(s) are bare labels rather than search phrases")
    return out


def report(title_res, desc_res, tag_res):
    L = [f"TITLE   {title_res['chars']:>3d} chars  {title_res['title'][:66]}"]
    L += [f"  PROBLEM {p}" for p in title_res["problems"]]
    L += [f"  note    {n}" for n in title_res["notes"]]
    L.append(f"DESC    {desc_res['chars']:>4d} chars")
    L += [f"  PROBLEM {p}" for p in desc_res["problems"]]
    L += [f"  note    {n}" for n in desc_res["notes"]]
    L.append(f"TAGS    {tag_res['chars']:>3d}/{TAGS_MAX} chars, {tag_res['used']} tags"
             + (f", {tag_res['dropped']} dropped over budget" if tag_res["dropped"] else ""))
    ok = not (title_res["problems"] or desc_res["problems"])
    L.append(f"GATE    {'PASS' if ok else 'FAIL'}")
    return "\n".join(L)


# ---------------------------------------------------------------------------------------------
# Assembly. The playbook's long-form structure, in its order, so a package cannot silently omit a
# section. Sources sit above the CTA because for a physics channel they are the credibility claim.
def build_description(primary_query, answer, body, table, questions, chapters, sources,
                      hashtags, cta=None, disclosure=None):
    """Assemble a description in the playbook's order and return (text, gate_result)."""
    P = [f"{primary_query.rstrip('?')}? {answer}".strip(), "", body.strip()]
    if table:
        P += ["", table.strip()]
    qblock, _ = questions_block(questions)
    P += ["", qblock, "", "CHAPTERS", "\n".join(chapters)]
    if sources:
        P += ["", "SOURCES", "\n".join(sources)]
    if cta:
        P += ["", cta]
    if disclosure:
        P += ["", disclosure]
    P += ["", " ".join("#" + h.lstrip("#") for h in hashtags[:HASHTAGS_IDEAL])]
    text = "\n".join(P)
    return text, check_description(text, chapters, hashtags)


def build_title_file(chosen, variants):
    """Title file laid out for a Title-only A/B test: the strategy is recorded, because a test whose
    variants are unlabelled teaches you which STRING won and not which APPROACH won."""
    L = [chosen, "", f"chars: {len(chosen)}", "",
         "A/B VARIANTS (YouTube Studio > Test & compare > Title only; hold thumbnail and",
         "description constant, and let YouTube pick on watch time, not CTR)"]
    for v in variants:
        L.append(f"  [{v['strategy']:<16}] ({len(v['title']):>2d}) {v['title']}")
        L += [f"       PROBLEM {p}" for p in v.get("problems", [])]
    return "\n".join(L)
