"""The film description template (operator, 2026-10-14): order, citations, the per-film promise,
the 5000-byte budget, and the People & Places fact check. No network, no provider."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import description_template as dt  # noqa: E402

CLAIMS = [
    {"claim_id": "c1", "claim": "In 1957, 26 African queens escaped from an apiary near Rio Claro, Brazil.",
     "source_url": "https://www.ars.usda.gov/news/2006/05/bees-on-the-move/"},
    {"claim_id": "c2", "claim": "Warwick Kerr imported African queens to Brazil in 1956.",
     "source_url": "https://doi.org/10.1000/xyz.123"},
    {"claim_id": "c3", "claim": "Africanized bees reached Texas in 1990.",
     "source_url": "https://example.org/texas"},
    {"claim_id": "c4", "claim": "Research the film never used, about varroa mites.",
     "source_url": "https://unused.example/mites"},
]
SCENES = [
    {"narration": "In 1956 Warwick Kerr brought African queens to Brazil.",
     "claim_refs": [{"claim_id": "c2"}], "event": {"text": "Kerr imported queens.", "claim_refs": ["c2"]}},
    {"narration": "A year later, twenty-six queens escaped near Rio Claro.",
     "claim_refs": [{"claim_id": "c1"}], "event": {"text": "Queens escaped.", "claim_refs": ["c1"]}},
    {"narration": "By 1990 their descendants had reached Texas.",
     "claim_refs": [{"claim_id": "c3"}], "event": {"text": "They reached Texas.", "claim_refs": ["c3", "c1"]}},
]
TRANSCRIPT = " ".join(s["narration"] for s in SCENES)


def _script(passed=True, soft=False, **extra):
    return {"scenes": [dict(s) for s in SCENES], "_research_dossier": {"claims": CLAIMS},
            "_claim_validation": {"passed": passed, "structure_status": "STRUCTURE_PASS",
                                  "soft_findings": [{"scene": "event_02"}] if soft else []},
            **extra}


def _facts(**kwargs):
    return {"script": _script(**kwargs), "transcript": TRANSCRIPT}


LIVE = """Killer bees began as a breeding experiment. In 1957, 26 African queens escaped.

How did a plan for more honey become a danger?

⏱️ CHAPTERS
0:00 Why Brazil Wanted Different Bees
0:20 The Escape
0:54 The March North

🔎 IN THIS VIDEO
• Why the queens escaped
• How they spread

❓ QUESTIONS ANSWERED
Why did the bees escape? How far did they spread?

📚 SOURCES
USDA Agricultural Research Service:
https://www.ars.usda.gov/news/2006/05/bees-on-the-move/

Historical account:
https://unused.example/mites

What other animal introduction backfired? Tell us in the comments!

Short version: https://youtube.com/shorts/abc123
Subscribe to Bolt Explains the World for illustrated true stories of fixes that backfired.

Tags: killer bees, africanized bees

#KillerBees #Bees

🤖 Created with AI assistance, including synthetic narration and AI-generated illustrations. Disclosed as altered/synthetic content."""


# --- order and removals --------------------------------------------------------------------------

def test_rebuild_lays_out_the_template_in_order_and_removes_the_retired_sections():
    people = ["Warwick Kerr — Brought African queens to Brazil in 1956.",
              "Rio Claro — Where twenty-six queens escaped a year later."]
    new, report = dt.rebuild(LIVE, _facts(), people)
    order = [new.index(marker) for marker in (
        "Killer bees began", "How did a plan", dt.promise_line("checked"), "⏱️ CHAPTERS",
        dt.RESEARCH_HEADER, dt.PEOPLE_HEADER, "What other animal", "Short version:",
        "Subscribe to Bolt", "#KillerBees", "🤖 Created with AI assistance, including")]
    assert order == sorted(order)
    for retired in ("IN THIS VIDEO", "QUESTIONS ANSWERED", "Tags:", "📚 SOURCES\n"):
        assert retired not in new
    # The operator's lines are kept exactly, and the Short link stays on the CTA's block.
    assert ("Short version: https://youtube.com/shorts/abc123\nSubscribe to Bolt Explains the World "
            "for illustrated true stories of fixes that backfired.") in new
    assert new.endswith("Disclosed as altered/synthetic content.")
    assert report["summary_paragraphs"] == 2 and report["people_listed"] == 2


def test_rebuild_is_idempotent_on_its_own_output():
    people = ["Warwick Kerr — Brought African queens to Brazil in 1956.",
              "Rio Claro — Where twenty-six queens escaped a year later."]
    once, _ = dt.rebuild(LIVE, _facts(), people)
    twice, report = dt.rebuild(once, _facts())          # None: existing People lines re-checked
    assert twice == once and report["people_listed"] == 2


def test_compose_without_research_or_people_is_summary_chapters_and_footer():
    text, report = dt.compose(["Para one.", "Para two."], chapters="⏱️ CHAPTERS\n0:00 A",
                              tail=["#A #B", "🤖 AI line."])
    assert text == "Para one.\n\nPara two.\n\n⏱️ CHAPTERS\n0:00 A\n\n#A #B\n\n🤖 AI line."
    assert report["promise"] is False


def test_strip_retired_keeps_everything_else_in_place():
    out = dt.strip_retired(LIVE)
    assert "IN THIS VIDEO" not in out and "QUESTIONS" not in out and "Tags:" not in out
    assert "📚 SOURCES" in out and "Short version:" in out and out.startswith("Killer bees began")


# --- sources and citations -----------------------------------------------------------------------

def test_only_sources_the_film_used_are_listed_most_used_first():
    entries = dt.source_entries(_script())
    assert [e["url"] for e in entries] == [CLAIMS[0]["source_url"], CLAIMS[1]["source_url"],
                                           CLAIMS[2]["source_url"]]
    assert entries[0]["uses"] == 2                      # narrated in scene 2, event of scene 3
    assert "unused.example" not in json.dumps(entries)
    # The finding is the claim the narration cites, verbatim.
    assert entries[1]["finding"] == "Warwick Kerr imported African queens to Brazil in 1956."


def test_live_sources_the_film_did_not_use_are_dropped_and_reported():
    new, report = dt.rebuild(LIVE, _facts(), [])
    assert "unused.example" not in new
    assert report["live_sources_dropped"] == ["https://unused.example/mites"]


def test_an_operators_url_paragraphs_after_the_sources_are_kept_where_they_were():
    live = LIVE.replace("What other animal introduction backfired?", (
        "▶ All the backfire films: https://www.youtube.com/playlist?list=PLTMHWScI1ywg\n\n"
        "Support the channel: https://ko-fi.com/bolt\n\n"
        "🔔 Subscribe: https://www.youtube.com/@BoltExplainsTheWorld?sub_confirmation=1\n\n"
        "What other animal introduction backfired?"))
    # The ko-fi line looks exactly like a 'site: URL' source; it is kept because no claim in the
    # film's research cites it. The playlist and channel lines end the sources section outright.
    live = live.replace("Historical account:\nhttps://unused.example/mites",
                        "Historical account:\nhttps://unused.example/mites\n\n"
                        "Newsletter: https://bolt.example/newsletter")
    new, report = dt.rebuild(live, _facts(), [])
    for kept in ("▶ All the backfire films: https://www.youtube.com/playlist?list=PLTMHWScI1ywg",
                 "Support the channel: https://ko-fi.com/bolt",
                 "🔔 Subscribe: https://www.youtube.com/@BoltExplainsTheWorld?sub_confirmation=1",
                 "Newsletter: https://bolt.example/newsletter"):
        assert kept in new, kept
    assert new.index("Newsletter:") < new.index("▶ All the backfire films") < new.index("Short version:")
    assert report["live_sources_dropped"] == ["https://unused.example/mites"]
    assert report["kept_custom_blocks"] == ["Newsletter: https://bolt.example/newsletter"]
    again, _ = dt.rebuild(new, _facts(), [])
    assert again == new


def test_an_old_source_entry_outside_the_research_is_dropped_not_kept_as_a_custom_line():
    # The live carp film lists NPS and the Army Corps as "Label:\nURL" entries its dossier never
    # held: sources the film did not use, not operator lines to carry along headerless.
    live = LIVE.replace("Historical account:\nhttps://unused.example/mites",
                        "Historical account:\nhttps://unused.example/mites\n\n"
                        "National Park Service — Invasive Carp Overview:\n"
                        "https://www.nps.gov/miss/learn/nature/ascarpover.htm\n\n"
                        "example.org: https://www.example.org/old-page")
    new, report = dt.rebuild(live, _facts(), [])
    assert "nps.gov" not in new and "example.org/old-page" not in new
    assert report["kept_custom_blocks"] == []
    assert "https://www.nps.gov/miss/learn/nature/ascarpover.htm" in report["live_sources_dropped"]
    assert "https://www.example.org/old-page" in report["live_sources_dropped"]


def test_citation_with_label_publisher_year_and_doi():
    entries = {e["url"]: e for e in dt.source_entries(_script(), dt.source_labels(LIVE))}
    usda = entries[CLAIMS[0]["source_url"]]
    # The operator's label, the domain's publisher, and the year the URL path carries.
    assert dt.citation_line(usda) == ("USDA Agricultural Research Service — U.S. Department of "
                                      "Agriculture (2006)")
    doi = entries[CLAIMS[1]["source_url"]]
    assert doi["link"] == "https://doi.org/10.1000/xyz.123"
    assert dt.citation_line(doi) == "doi.org"           # no title, publisher or year invented
    plain = entries[CLAIMS[2]["source_url"]]
    assert dt.citation_line(plain) == "example.org" and plain["link"] == plain["url"]
    assert dt.entry_text(plain) == ("example.org\nhttps://example.org/texas\n"
                                    "↳ Africanized bees reached Texas in 1990.")


def test_citation_fields_are_only_what_the_url_or_operator_gives():
    assert dt.doi_link("http://dx.doi.org/10.3389/fmars.2023.1285618") == \
        "https://doi.org/10.3389/fmars.2023.1285618"
    assert dt.doi_link("doi:10.1000/abc") == "https://doi.org/10.1000/abc"
    assert dt.doi_link("https://www.frontiersin.org/articles/10.3389/x/full") == ""
    assert dt.year_of("https://retrospectjournal.com/2025/10/19/the-aral-sea/") == "2025"
    assert dt.year_of("https://nyis.info/wp-content/uploads/2024/05/facts.pdf") == "", \
        "an upload folder dates the upload, not the work"
    assert dt.year_of("https://example.org/report-2019") == ""
    assert dt.publisher_of("https://science.nasa.gov/earth/x") == "NASA"
    assert dt.citation_line({"label": "", "publisher": "", "site": "ua.news", "year": ""}) == "ua.news"
    # A label naming its publisher is not given the publisher twice.
    assert dt.citation_line({"label": "NASA Earth Observatory, World of Change", "publisher": "NASA",
                             "site": "earthobservatory.nasa.gov", "year": ""}) == \
        "NASA Earth Observatory, World of Change"


def test_a_host_or_multi_journal_brand_is_never_named_as_the_publisher():
    # nature.com/articles/s41598-... is Scientific Reports, not Nature; PubMed Central hosts other
    # journals' papers (and must not fall through to nih.gov either).
    for url, site in (("https://www.nature.com/articles/s41598-023-33028-y", "nature.com"),
                      ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3750330/", "ncbi.nlm.nih.gov"),
                      ("https://pmc.ncbi.nlm.nih.gov/articles/PMC5100683/", "pmc.ncbi.nlm.nih.gov"),
                      ("https://www.science.org/doi/10.1126/sciadv.abc", "science.org"),
                      ("https://www.sciencedirect.com/science/article/pii/S1", "sciencedirect.com"),
                      ("https://www.jstor.org/stable/123", "jstor.org")):
        assert dt.publisher_of(url) == "", url
        entry = dt.entries_from_pairs([("", url)])[0]
        assert dt.citation_line(entry) == site
    assert dt.publisher_of("https://www.nih.gov/news-events/x") == "U.S. National Institutes of Health"
    # An operator's own label still wins.
    entry = dt.entries_from_pairs([("Scientific Reports (2023)", "https://www.nature.com/articles/s41598-1")])[0]
    assert dt.citation_line(entry) == "Scientific Reports (2023)"


def test_source_labels_skip_generic_and_host_only_labels():
    labels = dt.source_labels("📚 SOURCES\nasianstudies.org: https://www.asianstudies.org/a\n"
                              "Research paper:\nhttps://ncbi.nlm.nih.gov/pmc/1\n"
                              "U.S. Department of the Interior — Asian Carp Control:\n"
                              "https://www.doi.gov/ocl/asian-carp-control-0\n")
    assert labels == {"doi.gov/ocl/asian-carp-control-0":
                      "U.S. Department of the Interior — Asian Carp Control"}


def test_a_finding_is_a_whole_claim_never_cut():
    # A cut at the last comma kept only the false half of a claim that says it was false.
    long = ("Officials reported the released toads had controlled the cane beetles in the sugar "
            "fields across the whole coastal district, a claim later research showed to be false.")
    assert len(long) > dt.MAX_FINDING_CHARS
    script = {"scenes": [{"narration": "x", "claim_refs": ["L"]}],
              "_research_dossier": {"claims": [{"claim_id": "L", "claim": long,
                                                "source_url": "https://a.example/1"}]}}
    assert dt.source_entries(script)[0]["finding"] == long
    assert "<" not in dt._finding("a < b and c > d")


def test_a_shorter_claim_from_the_same_source_is_preferred_even_if_not_narrated():
    long = "The breeding program meant to cross the bees with commercial stock " + "x " * 60 + \
        "but queens and drones escaped and hybridized."
    short = "Queens and drones escaped from the apiary and hybridized."
    script = {"scenes": [{"narration": "x", "claim_refs": ["L"], "event": {"text": "e", "claim_refs": ["S"]}}],
              "_research_dossier": {"claims": [
                  {"claim_id": "L", "claim": long, "source_url": "https://a.example/1"},
                  {"claim_id": "S", "claim": short, "source_url": "https://a.example/1"}]}}
    assert dt.source_entries(script)[0]["finding"] == short


# --- the promise ---------------------------------------------------------------------------------

def test_promise_is_present_only_when_the_films_ledger_earns_it():
    assert dt.promise_kind(_script(), TRANSCRIPT) == "checked"
    assert dt.promise_line("checked") == ("Every factual line in this film was checked against "
                                          "quoted passages from the sources below.")
    assert dt.promise_kind(_script(soft=True), TRANSCRIPT) == "material"
    assert "Every number, date and name" in dt.promise_line("material")
    assert dt.promise_kind(_script(passed=False), TRANSCRIPT) == ""
    assert dt.promise_kind(_script(), TRANSCRIPT + " A sentence nobody checked.") == "", \
        "a transcript that differs from the checked narration gets no promise"
    unjudged = _script()
    unjudged["_claim_validation"] = {"passed": True, "retryable": True,
                                     "structure_status": "STRUCTURE_PASS",
                                     "errors": [{"code": "ENTAILMENT_UNAVAILABLE", "retryable": True}]}
    assert dt.promise_kind(unjudged, TRANSCRIPT) == "", "a beat the judge never judged earns nothing"
    unjudged["_claim_validation"] = {"passed": True, "structure_status": "STRUCTURE_PASS",
                                     "errors": [{"code": "ENTAILMENT_UNAVAILABLE"}]}
    assert dt.promise_kind(unjudged, TRANSCRIPT) == ""
    soft_open = _script()
    soft_open["_claim_validation"]["errors"] = [{"code": "OPENING_OVERSHOOT", "severity": "soft"}]
    assert dt.promise_kind(soft_open, TRANSCRIPT) == "material"
    legacy = _script()
    legacy["scenes"] = [{k: v for k, v in s.items() if k != "event"} for s in legacy["scenes"]]
    legacy["_claim_validation"] = {"passed": True}
    assert dt.promise_kind(legacy, TRANSCRIPT) == "tied"
    new, _ = dt.rebuild(LIVE, _facts(passed=False), [])
    assert "Every factual line" not in new


# --- the byte budget -----------------------------------------------------------------------------

def _many_sources_script(n=20):
    claims, scenes = [], []
    for i in range(n):
        claims.append({"claim_id": f"c{i}", "source_url": f"https://source{i}.example/page/{i}",
                       "claim": f"Source {i} reports a finding that the narration used, " + "x" * 90})
        # Source i is cited by (n - i) scenes, so source 0 is the most used.
        for _ in range(n - i):
            scenes.append({"narration": "line", "claim_refs": [{"claim_id": f"c{i}"}]})
    return {"scenes": scenes, "_research_dossier": {"claims": claims},
            "_claim_validation": {"passed": True, "structure_status": "STRUCTURE_PASS"}}


def test_trimming_drops_least_used_sources_first_and_never_the_summary_or_footer():
    script = _many_sources_script()
    entries = dt.source_entries(script)
    summary = ["S" * 1200, "T" * 600]
    people = [f"Name{i} — " + "p" * 120 for i in range(6)]
    tail = ["Short version: https://youtube.com/shorts/abc", "Subscribe to the channel.",
            "#A #B", "🤖 AI line."]
    text, report = dt.compose(summary, promise="checked", chapters="⏱️ CHAPTERS\n0:00 A",
                              entries=entries, people=people, tail=tail)
    assert dt.utf8_len(text) <= dt.MAX_BYTES and not report["over_limit"]
    listed = report["sources_listed"]
    assert dt.MIN_SOURCES_BEFORE_PEOPLE <= listed < len(entries)
    # The least-used went first: what is listed is exactly the most-used prefix.
    assert report["sources_trimmed"] == [e["url"] for e in entries[listed:]]
    assert all(e["url"] in text for e in entries[:listed])
    assert report["people_listed"] == len(people), "people are cut only after sources reach the floor"
    for kept in summary + tail:
        assert kept in text
    assert "the most-cited are listed below" in text, "a partial list says so"


def test_people_go_before_the_last_sources_when_the_budget_is_tight():
    entries = dt.source_entries(_many_sources_script(8))
    people = [f"Name{i} — " + "p" * 150 for i in range(7)]
    summary = ["S" * 3700]
    text, report = dt.compose(summary, promise="checked", entries=entries, people=people,
                              tail=["🤖 AI line."])
    assert dt.utf8_len(text) <= dt.MAX_BYTES
    assert report["sources_listed"] == dt.MIN_SOURCES_BEFORE_PEOPLE
    assert report["people_listed"] < len(people)
    assert summary[0] in text and "🤖 AI line." in text
    # Tighter still: People & Places goes entirely, then sources fall below the floor.
    text, report = dt.compose(["S" * 4300], promise="checked", entries=entries, people=people,
                              tail=["🤖 AI line."])
    assert dt.utf8_len(text) <= dt.MAX_BYTES
    assert report["people_listed"] == 0 and 1 <= report["sources_listed"] < dt.MIN_SOURCES_BEFORE_PEOPLE


def test_the_limit_is_bytes_not_characters():
    entries = dt.source_entries(_many_sources_script(12))
    summary = ["é" * 1500]                              # 3000 bytes, 1500 characters
    text, report = dt.compose(summary, entries=entries, tail=["🤖 AI line."])
    assert report["bytes"] == dt.utf8_len(text) <= dt.MAX_BYTES < len(text) * 2


# --- People & Places -----------------------------------------------------------------------------

def test_people_lines_with_unsupported_numbers_or_names_are_dropped():
    claims = dt.cited_claims(_script())
    ok = "Warwick Kerr — Brought African queens to Brazil in 1956."
    assert dt.check_people_line(ok, TRANSCRIPT, claims) == []
    # Number words and digits are the same number: the transcript says "twenty-six".
    assert dt.check_people_line("Rio Claro — Where 26 queens escaped in 1957.", TRANSCRIPT, claims) == []
    bad_year = dt.check_people_line("Warwick Kerr — Brought queens to Brazil in 1952.", TRANSCRIPT, claims)
    assert any("1952" in p for p in bad_year)
    bad_count = dt.check_people_line("Rio Claro — Where thirty queens escaped.", TRANSCRIPT, claims)
    assert any("30" in p for p in bad_count)
    bad_name = dt.check_people_line("Warwick Kerr — Studied bees with Paulo Nogueira-Neto in Brazil.",
                                    TRANSCRIPT, claims)
    assert any("Paulo Nogueira-Neto" in p for p in bad_name)
    unnamed = dt.check_people_line("Hacienda Napoles — An estate in Colombia.", TRANSCRIPT, claims)
    assert any("not named in the narration" in p for p in unnamed)
    # Sentence-initial ordinary words and possessives are not mistaken for names.
    assert dt.check_people_line("Warwick Kerr — After 1956, Kerr's African queens were in Brazil.",
                                TRANSCRIPT, claims) == []
    # ...and a fact about one name is not moved onto another: nothing the film says about Texas
    # mentions Kerr or anyone living there.
    joined = dt.check_people_line("Texas — After 1990, Kerr's bees' descendants lived there.",
                                  TRANSCRIPT, claims)
    assert any("unsupported wording" in p and "lived" in p for p in joined)


# Real narration and claims from the hippos film (hFk6YVSa0xk, jobs/escobar-hippos).
HIPPO_TRANSCRIPT = (
    "The hippos descended from a small herd imported by Escobar now roam the Magdalena River "
    "basin. In 1981, four hippos — three females and one male — were shipped from a zoo in the "
    "United States to a private, open-door zoo on this estate. In 1993, Escobar was killed and the "
    "zoo closed. Most of the animals died or were shipped to zoos. The hippos stayed. Picture that "
    "doubling arriving at your own doorstep. Near Puerto Triunfo, Alvaro Molina was fishing when a "
    "female hippo that had recently given birth moved beneath his canoe. Downstream, that flood of "
    "waste rots, and fish die in sudden mass numbers along the current.")
HIPPO_CLAIMS = [
    {"claim": "Four hippos — three females and one male — were imported to Colombia in 1981 from a "
              "zoo in the United States for Pablo Escobar's private zoo at Hacienda Nápoles."},
    {"claim": "After Escobar was killed in a 1993 shootout with police, the hippos he imported were "
              "left to roam freely in a hot savanna region of Antioquia."},
    {"claim": "Álvaro Molina, a local near Puerto Triunfo, was attacked by a female hippo that had "
              "recently given birth, which moved beneath his canoe and spilled him into the water "
              "while he was fishing."},
]


def _hippo(line):
    return dt.check_people_line(line, HIPPO_TRANSCRIPT, HIPPO_CLAIMS)


def test_people_lines_may_not_change_what_happened_to_a_real_person():
    # Every name and number here is in the support; the words are not, for THAT person.
    killed = _hippo("Álvaro Molina — a fisherman near Puerto Triunfo who was killed by a hippo.")
    assert any("unsupported wording" in p and "killed" in p and "fisherman" in p for p in killed)
    longer = _hippo("Alvaro Molina — fishing near Puerto Triunfo when a female hippo moved beneath "
                    "his canoe, which killed him.")
    assert any("killed" in p for p in longer), "one false word in a long line is still false"
    epithet = _hippo("Escobar — the murderous cocaine kingpin who brought four hippos to his ranch.")
    assert any("kingpin" in p and "murderous" in p and "cocaine" in p for p in epithet)
    assert _hippo("Escobar — the cartel boss who smuggled four hippos to his ranch")
    # Faithful lines, in the film's own words, pass.
    assert _hippo("Alvaro Molina — fishing near Puerto Triunfo when a female hippo moved beneath "
                  "his canoe.") == []
    assert _hippo("Escobar — imported four hippos to his private zoo at Hacienda Nápoles in 1981.") == []
    assert _hippo("Escobar — killed in 1993, when the zoo closed.") == []


def test_quantity_words_need_support_like_numbers():
    assert dt.numbers_in("brought a dozen hippos, half the herd, twice, tenfold") == set()
    assert dt.quantity_words_in("a dozen, half, twice, doubled, tenfold, a pair, manifold") == \
        {"dozen", "half", "twice", "double", "tenfold", "pair"}
    dozen = _hippo("Escobar — imported a dozen hippos to his private zoo.")
    assert any("unsupported quantity ['dozen']" in p for p in dozen)
    tenfold = _hippo("Escobar — the hippos he imported grew tenfold.")
    assert any("unsupported quantity ['tenfold']" in p for p in tenfold)
    twice = _hippo("Escobar — imported four hippos twice.")
    assert any("unsupported quantity ['twice']" in p for p in twice)
    # "doubling" is in the narration, so "doubled" is not an unsupported quantity.
    assert not any("quantity" in p for p in _hippo("Escobar — his hippos doubled."))


def test_numbers_in_reads_digits_words_and_scales_alike():
    assert dt.numbers_in("sixty thousand jobs") == {"60000"}
    assert dt.numbers_in("60,000 jobs") == {"60000"}
    assert dt.numbers_in("2.5 million people") == {"2500000"}
    assert dt.numbers_in("twenty of twenty-four species") == {"20", "24"}
    assert dt.numbers_in("the 1960s") == {"1960"}
    assert dt.numbers_in("one hundred fifty to two hundred hippos") == {"150", "200"}
    assert dt.numbers_in("hundreds of boats") == {"hundreds"}


def test_people_and_places_keeps_checked_lines_and_omits_a_section_under_two():
    replies = {"entries": [
        {"name": "Warwick Kerr", "line": "Brought African queens to Brazil in 1956."},
        {"name": "Rio Claro", "line": "Where 26 queens escaped a year later."},
        {"name": "Texas", "line": "Reached by the bees in 1985."},              # wrong year
        {"name": "Warwick Kerr", "line": "Duplicate name, dropped."},
    ]}
    calls = []

    def complete(system, user):
        calls.append(json.loads(user))
        return "```json\n" + json.dumps(replies) + "\n```"

    lines, report = dt.people_and_places(TRANSCRIPT, dt.cited_claims(_script()), complete)
    assert len(calls) == 1, "one call per film"
    assert set(calls[0]) == {"transcript", "cited_claims"}
    assert "Research the film never used" not in json.dumps(calls[0]), "only the claims it cites"
    assert lines == ["Warwick Kerr — Brought African queens to Brazil in 1956.",
                     "Rio Claro — Where 26 queens escaped a year later."]
    assert report["dropped"][0]["line"].startswith("Texas")
    one = {"entries": [{"name": "Warwick Kerr", "line": "Brought queens to Brazil in 1956."},
                       {"name": "Texas", "line": "Reached in 1985."}]}
    lines, report = dt.people_and_places(TRANSCRIPT, [], lambda s, u: json.dumps(one))
    assert lines == [] and "omitted" in report


def test_a_failed_people_call_leaves_the_section_out():
    def boom(system, user):
        raise RuntimeError("provider down")
    lines, report = dt.people_and_places(TRANSCRIPT, [], boom)
    assert lines == [] and "provider down" in report["error"]


def test_load_job_reads_state_transcript_and_falls_back_to_the_dossier_file(tmp_path):
    script = _script()
    del script["_research_dossier"]
    (tmp_path / "_state.json").write_text(json.dumps({"script": script}))
    (tmp_path / "research_dossier.json").write_text(json.dumps({"claims": CLAIMS}))
    (tmp_path / "transcript.txt").write_text(TRANSCRIPT + "\n")
    facts = dt.load_job(str(tmp_path))
    assert facts["transcript"] == TRANSCRIPT
    assert [c["claim_id"] for c in dt.cited_claims(facts["script"])] == ["c2", "c1", "c3"]


def test_rebuild_refuses_without_research_rather_than_deleting_the_sources():
    try:
        dt.rebuild(LIVE, {"script": {}, "transcript": ""})
    except ValueError as exc:
        assert "no research artifacts" in str(exc)
    else:
        raise AssertionError("rebuild must refuse a job with no claims")


def _recut_job(tmp_path, timing=True):
    (tmp_path / "_state.json").write_text(json.dumps({"script": _script()}))
    (tmp_path / "transcript.txt").write_text(TRANSCRIPT)
    # The opening replaces film time 0..10 s: the original scenes 1-2 (0 s and 4 s) are cut.
    (tmp_path / "recut_opening.json").write_text(json.dumps({"splice_sec": 10.0, "scenes": [
        {"narration": "Research once ignored now opens the film.", "claim_refs": ["c4"]}]}))
    (tmp_path / "explainer.recut.mp4").write_bytes(b"")
    if timing:
        (tmp_path / "audio_timing_report.json").write_text(json.dumps({"scenes": [
            {"scene": 1, "start_sec": 0.0}, {"scene": 2, "start_sec": 4.0},
            {"scene": 3, "start_sec": 10.0}]}))


def test_a_recut_film_is_its_opening_plus_the_scenes_after_the_splice(tmp_path):
    _recut_job(tmp_path)
    facts = dt.load_job(str(tmp_path))
    assert facts["recut"]
    assert facts["transcript"] == ("Research once ignored now opens the film. "
                                   "By 1990 their descendants had reached Texas.")
    # The cut-out scenes are not spoken in the live film: their names are not "named in it".
    assert any("not named in the narration" in p for p in dt.check_people_line(
        "Warwick Kerr — Brought African queens to Brazil in 1956.", facts["transcript"],
        dt.cited_claims(facts["script"])))
    new, report = dt.rebuild(LIVE, facts, [])
    assert report["promise_kind"] == "" and "Every factual line" not in new
    assert "https://unused.example/mites" in new, "the recut opening cites it"
    assert "doi.org/10.1000/xyz.123" not in new, "only the cut-out scene cited Kerr's source"
    original = dt.load_job(str(tmp_path), recut=False)
    new, report = dt.rebuild(LIVE, original, [])
    assert report["promise_kind"] == "checked" and "unused.example/mites" not in new


def test_a_recut_without_scene_timings_is_refused_not_guessed(tmp_path):
    _recut_job(tmp_path, timing=False)
    try:
        dt.load_job(str(tmp_path))
    except ValueError as exc:
        assert "audio_timing_report.json" in str(exc)
    else:
        raise AssertionError("a recut whose splice cannot be placed must be refused")
    assert dt.load_job(str(tmp_path), recut=False)["recut"] is False
