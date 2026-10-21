"""Impression risk (operator, 2026-10-21): a band with reasons from our own films' first week, the
measured market and our Shorts on the topic. No API calls."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import impression_risk as ir  # noqa: E402


def _film(i, title, rec, fmt="long", views=None, tags=()):
    return {"id": f"v{i}", "title": title, "format": fmt, "recommended_views_7d": rec,
            "views": views if views is not None else (rec or 0), "tags": list(tags)}


def _history():
    films = [_film(1, "The Cane Toad Mistake That Poisoned Australia", 2100),
             _film(2, "The Elk Mistake That Ate Yellowstone", 700),
             _film(3, "The Failed Experiment That Created Killer Bees", 180),
             _film(4, "The Sparrow Mistake That Starved a Nation", 4),
             _film(5, "Why Can't Anyone Live at Chernobyl", 2),
             _film(6, "Chernobyl's Elephant's Foot Is Still Deadly", 1),
             _film(7, "Chernobyl Firefighters Who Saved Europe", 0),
             _film(8, "Asian Carp Took Over America's Rivers", 3)]
    shorts = [_film(20, "What Happened to Chernobyl's Animals?", None, "short", 1200, ["chernobyl wildlife"]),
              _film(21, "Chernobyl's Wolves Today", None, "short", 900)]
    return films + shorts


def test_similarity_is_topic_coverage_not_jaccard():
    cand = ir.words("Why Did the Animals Move Into Chernobyl?")
    short = ir.words("chernobyl animals " + " ".join(f"tag{i}" for i in range(30)))
    assert ir.similarity(cand, short) >= 0.5, "a Short's many tags must not hide a topic match"
    assert ir.similarity(set(), short) == 0


def test_low_line_is_our_bottom_quarter_and_needs_eight_films():
    assert ir.low_threshold([1, 2, 3]) is None
    assert ir.low_threshold([0, 1, 2, 3, 4, 180, 700, 2100]) == 2


def test_metric_switches_to_impressions_when_enough_films_have_them():
    films = [dict(f, impressions_7d=100) for f in _history()[:8]]
    assert ir.outcome_metric(films) == "impressions_7d"
    assert ir.outcome_metric(_history()) == "recommended_views_7d"


def test_similar_films_mostly_low_and_weak_market_is_high_risk():
    r = ir.assess("Chernobyl today", _history(),
                  {"search": "x", "median_views": 90_000, "n_100k": 2, "small_breakouts": 0}, [])
    assert r["band"] == "high risk" and r["score"] <= -1
    assert any("bottom quarter" in x for x in r["reasons"])


def test_strong_market_and_seeding_shorts_lift_the_band():
    films = _history()
    r = ir.assess("Cane Toad Elk mistake Yellowstone Australia", films,
                  {"search": "x", "median_views": 400_000, "n_100k": 12, "small_breakouts": 5},
                  [f for f in films if f["format"] == "short"])
    assert r["band"] in ("low risk", "uncertain")
    assert any(x.startswith("+ market") for x in r["reasons"])


def test_too_few_films_reports_evidence_but_no_band():
    few = _history()[:4] + _history()[8:]
    r = ir.assess("What happened to Chernobyl's animals", few,
                  {"search": "x", "median_views": 300_000, "n_100k": 9, "small_breakouts": 4},
                  [f for f in few if f["format"] == "short"])
    assert r["band"] == "insufficient data"
    assert any("Shorts share the topic" in x for x in r["reasons"]), "the evidence is still shown"
    assert "no band" in ir.text_report("t", r).lower() or r["band"] == "insufficient data"


def test_unmeasured_market_says_so():
    score, text = ir.demand(None)
    assert score == 0 and "market check" in text
