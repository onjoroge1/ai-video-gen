"""Spec import (scripts/import_spec.py): verify an operator's research + narration, then build.

No network and no provider calls: lionfish v2 reads trimmed copies of its real cited pages
(tests/fixtures/spec_import/pages), and the synthetic specs get their pages from a dict.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import spec_import as si  # noqa: E402

LIONFISH_SPEC = os.path.join(ROOT, "topics", "specs", "lionfish-v2.md")
LIONFISH_PAGES = os.path.join(ROOT, "tests", "fixtures", "spec_import", "pages")
TEMPLATE = os.path.join(ROOT, "topics", "specs", "TEMPLATE.md")
YEAR = 2026

FWC = "https://myfwc.com/wildlifehabitats/nonnatives/python/"
ROUTE = "https://www.route-fifty.com/emerging-tech/2025/08/pythons-everglades/"
USGS = "https://www.usgs.gov/publications/marsh-rabbit-mortalities"
PAGES = {
    FWC: "Burmese Python | FWC. Python removal programs. Florida began paying contracted hunters to remove "
         "pythons. After this program launched in spring 2017, the number and rate of Burmese pythons removed "
         "from the wild increased. As of April 2025, over 23,500 pythons have been removed from natural areas "
         "in the state of Florida. Report sightings to the hotline.",
    ROUTE: "August 2025. Burmese pythons are not native to Florida; they were brought through the exotic pet "
           "trade and escaped their enclosures or were released. The pythons have reduced the population of "
           "fur-bearing animals by up to 95% in parts of the Everglades.",
    USGS: "Marsh rabbit mortalities. Pythons accounted for 77% of rabbit mortalities within 11 months of their "
          "translocation to Everglades National Park.",
}


def pythons_spec() -> dict:
    return {
        "spec_version": 1, "slug": "pythons", "channel": "world", "duration_sec": 60,
        "title": "Florida's Pet Pythons Got Loose. Why Are Hunters Still Pulling Them Out by the Thousand?",
        "decision": {"what": "Burmese pythons imported through the exotic pet trade, released or escaped",
                     "who": "pet owners and the exotic pet trade", "when": "1980s-1990s",
                     "kind": "animal_introduced", "cite": ["p1"]},
        "consequence": {"what": "fur-bearing mammals down by up to 95%", "cite": ["p2", "p3"]},
        "still_unfolding": {"what": "over 23,500 pythons removed as of April 2025", "as_of": "2025", "cite": ["p4"]},
        "central_question": "Florida let pet pythons into the Everglades; why are hunters still pulling them out "
                            "by the thousand?",
        "ending_answer": "Because the pets that escaped are still eating the Everglades.",
        "human": {"person": "a contracted python hunter", "want": "paid removals", "detail": "night hunts"},
        "forbidden_claims": ["pythons can be eradicated"],
        "sources": {"fwc": FWC, "route": ROUTE, "usgs": USGS},
        "narration": [
            {"say": "Picture a pet snake that outgrew its tank.", "part": "opening"},
            {"say": "Burmese pythons came to Florida through the pet trade, and some escaped or were released.",
             "claims": [{"id": "p1", "source": "route", "kind": "event",
                         "quote": "they were brought through the exotic pet trade and escaped their enclosures or "
                                  "were released"}]},
            {"say": "In parts of the Everglades, fur-bearing animals fell by up to 95 percent.", "part": "development",
             "claims": [{"id": "p2", "source": "route", "kind": "outcome",
                         "quote": "The pythons have reduced the population of fur-bearing animals by up to 95%"}]},
            {"say": "Pythons caused 77 percent of the rabbit deaths in one study.",
             "claims": [{"id": "p3", "source": "usgs", "kind": "outcome",
                         "quote": "Pythons accounted for 77% of rabbit mortalities within 11 months of their "
                                  "translocation to Everglades National Park"}]},
            {"say": "In spring 2017, Florida started paying hunters to remove them.", "part": "attempt",
             "claims": [{"id": "p5", "source": "fwc", "kind": "event",
                         "quote": "After this program launched in spring 2017, the number and rate of Burmese "
                                  "pythons removed from the wild increased"}]},
            {"say": "As of April 2025, they had pulled out more than 23,500.", "part": "ending",
             "claims": [{"id": "p4", "source": "fwc", "kind": "event",
                         "quote": "As of April 2025, over 23,500 pythons have been removed from natural areas in "
                                  "the state of Florida"}]},
            {"say": "And the snakes are still out there."},
        ],
    }


def write_spec(tmp_path, spec: dict, name="spec.md") -> str:
    path = tmp_path / name
    path.write_text("# Spec\n\nNotes.\n\n```json\n" + json.dumps(spec, indent=1) + "\n```\n")
    return str(path)


def run(tmp_path, spec: dict, pages=PAGES):
    path = write_spec(tmp_path, spec)
    out = tmp_path / "job"
    return si.run_verification(path, str(out), fetch=lambda url: pages.get(url, ""), this_year=YEAR), out


# ── lionfish v2: verifies, and is not a consequence video ─────────────────────────────────────

def lionfish_run(tmp_path):
    return si.run_verification(LIONFISH_SPEC, str(tmp_path / "lionfish"), offline=True,
                               pages_dir=LIONFISH_PAGES, this_year=YEAR)


def test_lionfish_v2_spec_imports_and_its_hand_typed_quotes_verify(tmp_path):
    r = lionfish_run(tmp_path)
    assert not r["spec"]["problems"]
    hand = ["c70", "c71", "c72", "c73", "c74", "c75", "c76", "c77", "c78", "c79", "c80", "c81", "c82",
            "c83", "c85", "c86"]        # hand_build.py's 16 new claims (there is no c84)
    for cid in hand:
        assert r["results"]["claims"][cid]["status"] in ("exact", "normalized"), cid
    assert r["summary"]["lines"]["not_on_page"] == 0
    assert r["summary"]["lines"]["unreachable"] == 0


def test_lionfish_v2_fails_the_consequence_check(tmp_path):
    r = lionfish_run(tmp_path)
    codes = {e["code"] for e in r["consequence"]["errors"]}
    assert not r["consequence"]["passed"]
    assert {"CONSEQUENCE_NOT_DOCUMENTED", "QUESTION_HYPOTHETICAL"} <= codes
    assert r["consequence"]["claim_kinds"]["c78"] == "model"          # "Our models projected"
    assert not r["summary"]["ready_to_approve"]
    report = (tmp_path / "lionfish" / si.REPORT_NAME).read_text()
    assert "Consequence model: **FAIL**" in report and "Ready to approve: NO" in report
    assert "CONSEQUENCE_NOT_DOCUMENTED" in report


def test_lionfish_v2_report_metrics_and_the_unsourced_repeat(tmp_path):
    r = lionfish_run(tmp_path)
    m = r["metrics"]
    assert m["words"] == len(si.narration(r["spec"]).split())
    assert m["target_words"] == int(300 * si.WORDS_PER_SECOND)
    assert m["sentences_over_25_words"] == len(m["long_sentences"]) >= 1
    unsourced = [row["say"] for row in r["results"]["lines"] if row["status"] == "unsourced"]
    assert unsourced == ["Seventy-three trips, and a full freezer."]


# ── a pythons-style spec passes ──────────────────────────────────────────────────────────────

def test_a_pythons_style_spec_passes_and_offers_the_approval(tmp_path):
    r, out = run(tmp_path, pythons_spec())
    assert r["consequence"]["passed"], r["consequence"]["errors"]
    assert r["summary"]["ready_to_approve"]
    assert all(c["status"] == "exact" for c in r["results"]["claims"].values())
    report = (out / si.REPORT_NAME).read_text()
    assert f"--approve {si.narration_sha256(r['spec'])}" in report
    saved = json.loads((out / si.RESULT_NAME).read_text())
    assert saved["narration_sha256"] == si.narration_sha256(r["spec"])


def test_a_fabricated_quote_is_not_on_the_page(tmp_path):
    spec = pythons_spec()
    spec["narration"][2]["claims"][0]["quote"] = "Pythons have eaten every raccoon in the Everglades"
    spec["narration"][2]["say"] = "Pythons have eaten every raccoon in the Everglades."
    r, out = run(tmp_path, spec)
    assert r["results"]["claims"]["p2"]["status"] == "absent"
    line = next(row for row in r["results"]["lines"] if "p2" in row["claim_ids"])
    assert line["status"] == "absent" and line["suggestions"]
    assert not r["summary"]["ready_to_approve"]
    report = (out / si.REPORT_NAME).read_text()
    assert "❌" in report and "Pythons have eaten every raccoon in the Everglades." in report


def test_an_unreachable_page_is_its_own_state(tmp_path):
    pages = dict(PAGES)
    pages.pop(USGS)
    r, _ = run(tmp_path, pythons_spec(), pages)
    assert r["results"]["claims"]["p3"]["status"] == "unreachable"
    assert r["summary"]["lines"]["unreachable"] == 1 and not r["summary"]["ready_to_approve"]


def test_a_paraphrased_quote_is_recovered_from_the_page_and_flagged(tmp_path):
    spec = pythons_spec()
    spec["narration"][3]["claims"][0]["quote"] = "Pythons were responsible for 77% of rabbit mortalities in Everglades National Park"
    r, _ = run(tmp_path, spec)
    p3 = r["results"]["claims"]["p3"]
    assert p3["status"] == "recovered" and p3["page_quote"].startswith("Pythons accounted for 77%")
    dossier = si.build_dossier(r["spec"], r["results"])
    claim = next(c for c in dossier["claims"] if c["claim_id"] == "p3")
    assert claim["support_quote"] == p3["page_quote"] and claim["support_provenance"] == "page_recovered"
    assert claim["support_quote_operator"].startswith("Pythons were responsible")


def test_the_pipelines_dossier_check_shows_in_the_report(tmp_path):
    spec = pythons_spec()       # the page's "are not native" against a claim with no negation
    spec["narration"][1]["claims"][0]["quote"] = ("Burmese pythons are not native to Florida; they were brought "
                                                  "through the exotic pet trade and escaped their enclosures or were released")
    r, out = run(tmp_path, spec)
    assert r["results"]["claims"]["p1"]["status"] == "exact"
    assert [e["code"] for e in r["dossier_check"]] == ["support_contradicts_claim"]
    assert not r["summary"]["ready_to_approve"]
    assert "support_contradicts_claim" in (out / si.REPORT_NAME).read_text()


def test_a_number_the_quote_does_not_carry_is_flagged(tmp_path):
    spec = pythons_spec()
    spec["narration"][3]["say"] = "Pythons caused 87 percent of the rabbit deaths in one study."
    r, _ = run(tmp_path, spec)
    line = next(row for row in r["results"]["lines"] if "p3" in row["claim_ids"])
    assert line["status"] == "recovered" and any("87" in n for n in line["notes"])


def test_a_model_quote_cannot_be_the_consequence_whatever_its_label(tmp_path):
    spec = pythons_spec()
    pages = dict(PAGES)
    pages[USGS] = "Our models projected that pythons could remove most marsh rabbits from the park."
    spec["consequence"]["cite"] = ["p3"]
    spec["narration"][3]["claims"][0].update(quote="Our models projected that pythons could remove most marsh rabbits",
                                            evidence="documented")
    spec["narration"][3]["say"] = "Models projected that pythons could remove most marsh rabbits."
    r, _ = run(tmp_path, spec, pages)
    assert r["results"]["claims"]["p3"]["story_kind"] == "model"
    assert "CONSEQUENCE_NOT_DOCUMENTED" in {e["code"] for e in r["consequence"]["errors"]}


@pytest.mark.parametrize("mutate, code", [
    (lambda s: s["decision"].update(kind="accident"), "DECISION_NOT_DELIBERATE"),
    (lambda s: s["decision"].update(when="", what="pythons were imported"), "DECISION_UNDATED"),
    (lambda s: s["decision"].update(who=""), "DECISION_UNNAMED"),
    (lambda s: s["still_unfolding"].update(cite=["p5"]), "STILL_UNFOLDING_NOT_PRESENT"),
    (lambda s: s.update(central_question="What happens when Florida runs out of hunters?"), "QUESTION_HYPOTHETICAL"),
    (lambda s: s.update(central_question="Why do tourists love airboats?"), "QUESTION_NOT_CONSEQUENCE"),
    (lambda s: s.update(ending_answer=""), "ENDING_MISSING"),
])
def test_each_consequence_failure_is_named(tmp_path, mutate, code):
    spec = pythons_spec()
    mutate(spec)
    r, _ = run(tmp_path, spec)
    assert code in {e["code"] for e in r["consequence"]["errors"]}


def test_a_history_spec_is_not_judged_by_the_world_rule(tmp_path):
    spec = pythons_spec()
    spec.update(channel="history", decision={}, consequence={}, still_unfolding={})
    r, _ = run(tmp_path, spec)
    assert not r["consequence"]["applies"] and r["consequence"]["passed"]


# ── parsing and the narration ────────────────────────────────────────────────────────────────

def test_spec_problems_are_reported_not_raised(tmp_path):
    spec = pythons_spec()
    spec["narration"].append({"say": "Hunters keep going.", "cite": ["p9"]})
    spec["narration"].append({"say": "A line.", "claims": [{"id": "p6", "source": "nowhere", "quote": ""}]})
    r, _ = run(tmp_path, spec)
    codes = {p["code"] for p in r["spec"]["problems"]}
    assert {"UNKNOWN_CLAIM", "NO_SOURCE_URL", "NO_QUOTE"} <= codes
    assert not r["summary"]["ready_to_approve"]


def test_no_json_block_is_refused(tmp_path):
    path = tmp_path / "bad.md"
    path.write_text("# Spec\n\nno block here\n")
    with pytest.raises(si.SpecError):
        si.load_spec(str(path))


def test_the_narration_is_never_rewritten(tmp_path):
    spec = pythons_spec()
    spec["narration"][2]["claims"][0]["quote"] = "a quote that is not on the page"
    path = write_spec(tmp_path, spec)
    before = open(path).read()
    r = si.run_verification(path, str(tmp_path / "job"), fetch=lambda u: PAGES.get(u, ""), this_year=YEAR)
    assert open(path).read() == before
    assert si.narration(r["spec"]) == " ".join(row["say"] for row in spec["narration"])


def test_spelled_numbers():
    assert si.numbers_in("seventy-three dive trips") == [73.0]
    assert si.numbers_in("more than fifteen hundred lionfish") == [1500.0]
    assert 36187.0 in si.numbers_in("a record 36,187 fish")
    assert si.number_mismatches("more than fifteen hundred", ["removing 1,542 lionfish"]) == []


def test_the_template_parses():
    spec = si.load_spec(TEMPLATE)
    assert spec["entries"] and spec["claims"] and not spec["problems"]


# ── approval ─────────────────────────────────────────────────────────────────────────────────

def test_approval_needs_the_current_hash(tmp_path):
    path = write_spec(tmp_path, pythons_spec())
    with pytest.raises(si.SpecError, match="not this narration"):
        si.approve(path, str(tmp_path / "job"), "0" * 64, max_cost=3, fetch=lambda u: PAGES.get(u, ""), this_year=YEAR)
    assert not (tmp_path / "job" / "_state.json").exists()


def test_approval_refuses_a_spec_that_is_not_ready(tmp_path):
    spec = pythons_spec()
    spec["central_question"] = "What happens when the hunters stop?"
    path = write_spec(tmp_path, spec)
    sha = si.narration_sha256(si.load_spec(path))
    with pytest.raises(si.SpecError, match="not ready"):
        si.approve(path, str(tmp_path / "job"), sha, max_cost=3, fetch=lambda u: PAGES.get(u, ""), this_year=YEAR)


def test_the_built_dossier_passes_the_pipelines_dossier_check(tmp_path):
    import longform_research as lr
    r, _ = run(tmp_path, pythons_spec())
    dossier = si.build_dossier(r["spec"], r["results"])
    checked = lr.validate_research_dossier(dossier)
    assert checked["passed"], checked["errors"]
    assert {c["claim_id"] for c in dossier["claims"]} == {"p1", "p2", "p3", "p4", "p5"}
    assert all(c["quote_verified"] and c["support_provenance"] == "operator_spec" for c in dossier["claims"])


def _has_segmenter() -> bool:
    try:
        import story_contract_segment  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(_has_segmenter(), reason="story_contract_segment is installed")
def test_approval_without_the_segmenter_writes_the_dossier_and_stops(tmp_path):
    path = write_spec(tmp_path, pythons_spec())
    sha = si.narration_sha256(si.load_spec(path))
    with pytest.raises(si.SpecError, match="PR #217"):
        si.approve(path, str(tmp_path / "job"), sha, max_cost=3, fetch=lambda u: PAGES.get(u, ""), this_year=YEAR)
    assert (tmp_path / "job" / "research_dossier.json").exists()
    assert not (tmp_path / "job" / "_state.json").exists()


@pytest.mark.skipif(not _has_segmenter(), reason="needs story_contract_segment (PR #217)")
def test_approval_builds_a_state_with_the_words_unchanged(tmp_path):
    path = write_spec(tmp_path, pythons_spec())
    sha = si.narration_sha256(si.load_spec(path))
    built = si.approve(path, str(tmp_path / "job"), sha, max_cost=3, fetch=lambda u: PAGES.get(u, ""), this_year=YEAR)
    state = json.loads((tmp_path / "job" / "_state.json").read_text())
    script = state["script"]
    assert si.normalize_narration(" ".join(s["narration"] for s in script["scenes"])) == si.narration(si.load_spec(path))
    assert script["_spec_import"]["narration_sha256"] == sha
    assert "--resume" in built["command"] and "3.00" in built["command"]
    assert (tmp_path / "job" / "run_command.txt").exists()


def test_resume_command_carries_the_render_flags():
    spec = si.normalize_spec(dict(pythons_spec(), render={"palette": "natural", "music": True}))
    cmd = si.resume_command(spec, "jobs/pythons", 4.5)
    assert cmd[cmd.index("--palette") + 1] == "natural" and "--music" in cmd and "--resume" in cmd
    assert cmd[cmd.index("--max-cost") + 1] == "4.50"


def test_cli_dry_run_exit_codes(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import import_spec
    out = tmp_path / "cli"
    assert import_spec.main([LIONFISH_SPEC, "--out", str(out), "--offline"]) == 1      # pages not cached there
    assert (out / si.REPORT_NAME).exists()
