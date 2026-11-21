"""Deterministic rules of scripts/produce_fg_short.py (no Claude, no YouTube)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import produce_fg_short as p  # noqa: E402

DESC = ("A fully grown axolotl keeps the gills it hatched with.\n\n"
        "So by never growing up, axolotls keep regrowing fast.\n\n"
        "Would you rather stay young? Tell us in the comments.\n\n#axolotl #salamander #shorts")
TAGS = ["axolotl", "axolotls", "axolotl regeneration", "neoteny", "axolotl thyroid", "salamander",
        "amphibians", "morphed axolotl", "why axolotls never grow up", "axolotl metamorphosis",
        "animal facts", "wild field guide"]


def _job(tmp_path, lines, meta=None):
    spec = {"beats": [{"text": t, "pictures": []} for t in lines]}
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    if meta is not None:
        (tmp_path / "meta.json").write_text(json.dumps(meta))
    return str(tmp_path)


def _rules(rep):
    return {k: v["status"] for k, v in rep.data["rules"].items()}


def test_hedge_words_in_ending():
    assert p.HEDGES.search("But in one species, by one count, a few woke up anyway.")
    assert p.HEDGES.search("Maybe it never lands at all.")
    assert not p.HEDGES.search("So space itself wasn't what killed them. The sun was.")


def test_good_metadata_passes(tmp_path):
    job = _job(tmp_path, ["This axolotl is fully grown.", "It never grows up."],
               {"title": "Axolotls Keep Their Baby Gills Forever. In One Lab, They Lost Them 🦎",
                "description": DESC, "tags": TAGS, "animal": "axolotl", "approved": True})
    rep = p.Report(job, {})
    p.stage_meta(job, rep)
    assert rep.blocked == [], _rules(rep)


def test_bad_metadata_blocks(tmp_path):
    job = _job(tmp_path, ["These tiny animals rode outside a spacecraft."],
               {"title": "#tardigrade Survived Space And Then Something Amazing Happened To Them All Wow",
                "description": "Just one paragraph.", "tags": ["tardigrade"], "animal": "tardigrade"})
    rep = p.Report(job, {})
    p.stage_meta(job, rep)
    assert {"title-shape", "title-matches-line1", "description-shape", "tags"} <= set(rep.blocked)


def test_override_is_recorded_not_blocking(tmp_path):
    job = _job(tmp_path, ["These tiny animals rode outside a spacecraft."],
               {"title": "Tardigrades Survived Space. The Sun Nearly Killed Them 🌞",
                "description": DESC.replace("axolotl", "tardigrade"), "tags": TAGS[:10] + [
                    "tardigrade", "animal facts", "wild field guide"][-3:], "animal": "tardigrade"})
    rep = p.Report(job, {"title-matches-line1": "line 2 names it"})
    p.stage_meta(job, rep)
    assert rep.data["rules"]["title-matches-line1"]["status"] == "override"
    assert "title-matches-line1" not in rep.blocked
