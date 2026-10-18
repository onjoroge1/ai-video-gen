#!/usr/bin/env python3
"""Source packs: primary sources for one topic that are known to load, handed to the research stage.

    python3 source_pack.py build --audit <consequence_research_audit.json> --out topics/source_packs
    python3 source_pack.py show fukushima
    python3 scripts/run_illustrated_local.py ... --source-pack fukushima

A pack is topics/source_packs/<slug>.json:
    {"slug", "topic", "decision", "human", "current_type", "angle", "gaps",
     "sources": [{"id", "url", "title", "publisher", "date", "kind", "content_type",
                  "facts": [{"location": "PDF p. 44", "fact": "..."}]}],
     "excluded": [{"id", "url", "status", "reason"}]}

Why: the research stage fetches every cited page itself and checks the quote against it, and museum,
publisher and news pages often block it (the 403 wall). A 10-18 research pass fetched 54 primary
documents for eight queued topics with a plain unauthenticated GET and kept the 42 that returned full
text, each mapped to the page or paragraph that supports each fact. A pack carries those so research
starts from sources it can read. The facts are leads, not claims: every claim still needs a quote
observed on the fetched page, and the fidelity judge still decides.

At research time (`prepare`) each document is fetched again, PDFs included, and for every fact the
exact sentences of the document that carry its words are copied out. The research request lists
them verbatim, so a claim built on one quotes the document word for word; the pages themselves are
handed to quote verification, and the pack's URLs count as observed sources. A document that no
longer loads, or loads as a challenge page, is left out of the request rather than trusted.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PACK_DIR = os.path.join(ROOT, "topics", "source_packs")

# Audit topic name -> queue slug (topics/schedule.json and topics/history_schedule.json).
SLUGS = {
    "Fukushima seawall": "fukushima",
    "Bhopal": "bhopal-disaster",
    "Plastic recycling": "plastic-recycling",
    "Great Pacific garbage patch": "great-pacific-garbage-patch",
    "Great Pacific Garbage Patch": "great-pacific-garbage-patch",
    "Titanic lifeboats": "titanic-lifeboat-rules",
    "MKUltra": "mkultra",
    "MKUltra / Montreal experiments": "mkultra",
    "Manhattan Project": "manhattan-project",
    "Manhattan Project / Trinity": "manhattan-project",
    "Salem witch trials": "salem-witch-trials",
}


def _truthy(value) -> bool:
    return str(value).strip().lower() == "true"


def build_from_audit(audit: dict, as_of: str = "") -> dict[str, dict]:
    """One pack per audit topic: the sources it selected as core full text, with their fact maps."""
    e = audit.get("E") or {}
    qa = e.get("requirement_qa") or {}
    topics = {t["topic"]: t for t in e.get("topics") or []}
    packs: dict[str, dict] = {}
    for src in e.get("sources") or []:
        name = src.get("topic", "")
        slug = SLUGS.get(name)
        if not slug:
            continue
        t = topics.get(name) or next((v for k, v in topics.items() if SLUGS.get(k) == slug), {})
        pack = packs.setdefault(slug, {
            "slug": slug, "topic": t.get("topic", name), "as_of": as_of or e.get("research_cutoff_utc", ""),
            "built_from": "ChatGPT consequence research audit, brief E",
            "readiness": t.get("readiness", ""), "decision": t.get("decision", ""), "human": t.get("human", ""),
            "current_type": t.get("current_type", ""), "angle": t.get("angle", ""),
            "gaps": (qa.get(t.get("topic", name)) or qa.get(name) or {}), "sources": [], "excluded": []})
        if _truthy(src.get("selected_core")):
            pack["sources"].append({
                "id": src.get("id", ""), "url": src.get("final_url") or src.get("url", ""), "title": src.get("title", ""),
                "publisher": src.get("publisher", ""), "date": src.get("date", ""), "kind": src.get("kind", ""),
                "content_type": (src.get("content_type") or "").split(";")[0],
                "facts": [{"location": f.get("location", ""), "fact": f.get("supported_fact_or_limit", "")}
                          for f in src.get("fact_location_map") or [] if isinstance(f, dict)]})
        else:
            pack["excluded"].append({"id": src.get("id", ""), "url": src.get("url", ""), "status": src.get("status", ""),
                                     "reason": str((src.get("manual_content_review") or {}).get("note", ""))[:240]
                                     if isinstance(src.get("manual_content_review"), dict) else ""})
    return packs


def load_pack(slug_or_path: str, pack_dir: str = PACK_DIR) -> dict | None:
    """A topic's pack by slug (topics/source_packs/<slug>.json) or by path; None when there is none."""
    ref = (slug_or_path or "").strip()
    if not ref:
        return None
    path = ref if ref.endswith(".json") else os.path.join(pack_dir, f"{ref}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


PASSAGES_PER_FACT = 2


def prepare(pack: dict, *, fetch=None, log=lambda message: None) -> dict:
    """Fetch every pack document and copy out the sentences that carry each fact.

    Returns {"slug", "sources": [{id, url, title, publisher, date, facts: [{fact, location,
    passages}]}], "pages": {url: text}, "observed_urls": [...], "unreadable": [...]}. Only documents
    that load as readable text, and facts with at least one passage, reach the request.
    """
    import claim_verify
    fetch = fetch or claim_verify.fetch_document_text
    out = {"slug": (pack or {}).get("slug", ""), "sources": [], "pages": {}, "observed_urls": [], "unreadable": []}
    for src in (pack or {}).get("sources") or []:
        url = str(src.get("url") or "").strip()
        text = fetch(url) if url else ""
        if not text:
            out["unreadable"].append(url)
            log(f"  Source pack: {src.get('id', '?')} did not load as readable text; left out — {url[:70]}")
            continue
        facts = []
        for fact in src.get("facts") or []:
            passages = claim_verify.candidate_passages(str(fact.get("fact") or ""), text, limit=PASSAGES_PER_FACT)
            if passages:
                facts.append({"fact": fact.get("fact", ""), "location": fact.get("location", ""), "passages": passages})
        out["pages"][url] = text
        out["observed_urls"].append(url)
        out["sources"].append({k: src.get(k, "") for k in ("id", "url", "title", "publisher", "date")} | {"facts": facts})
    log(f"Source pack {out['slug'] or '?'}: {len(out['observed_urls'])} of {len((pack or {}).get('sources') or [])} "
        f"documents readable, {sum(len(s['facts']) for s in out['sources'])} facts with verbatim passages")
    return out


def prompt_paragraph(prepared: dict) -> str:
    """The request paragraph: each readable document, and each fact with its verbatim passages."""
    sources = [s for s in (prepared or {}).get("sources") or [] if s.get("url")]
    if not sources:
        return ""
    lines = []
    for n, src in enumerate(sources, 1):
        lines.append(f"[{n}] {src['title']} ({src['publisher']}, {src['date']}) {src['url']}")
        for fact in src["facts"]:
            quoted = " | ".join(json.dumps(p, ensure_ascii=False) for p in fact["passages"])
            lines.append(f"  - lead ({fact['location']}): {fact['fact']} Verbatim: {quoted}")
    return ("OPERATOR SOURCE PACK -- primary documents the operator confirmed load as full text. Their "
            "URLs count as observed sources even if your search does not return them. Each passage "
            "below is copied verbatim from its document: when a claim rests on one, use that "
            "document's URL as source_url and copy the passage, or an exact contiguous part of it, as "
            "support_quote. The leads are a researcher's summary, not facts to accept: state only "
            "what the passage itself says, keep a claim's scope to its passage, and keep searching "
            "for everything else the question needs. " + " ".join(lines) + " ")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write one pack per topic from a research audit JSON")
    b.add_argument("--audit", required=True)
    b.add_argument("--out", default=PACK_DIR)
    s = sub.add_parser("show", help="print a topic's pack summary")
    s.add_argument("slug")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        with open(os.path.expanduser(args.audit), encoding="utf-8") as handle:
            packs = build_from_audit(json.load(handle))
        os.makedirs(args.out, exist_ok=True)
        for slug, pack in sorted(packs.items()):
            with open(os.path.join(args.out, f"{slug}.json"), "w", encoding="utf-8") as handle:
                json.dump(pack, handle, indent=1, ensure_ascii=False)
            print(f"{slug:<30} {len(pack['sources'])} sources, {sum(len(x['facts']) for x in pack['sources'])} facts, "
                  f"{len(pack['excluded'])} excluded")
        return 0
    pack = load_pack(args.slug)
    if not pack:
        print(f"no pack for {args.slug}")
        return 1
    print(f"{pack['topic']}: {pack['decision']}\nhuman: {pack['human']}\nangle: {pack['angle']}")
    for src in pack["sources"]:
        print(f"- {src['id']} {src['publisher']} {src['date']}: {src['title']} <{src['url']}>")
        for f in src["facts"]:
            print(f"    {f['location']}: {f['fact'][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
