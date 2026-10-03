from copy import deepcopy
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from bolt_video.engines.catalog import list_capabilities
from bolt_video.engines.storyboard import Storyboard, import_vimax, review

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def draft():
    return json.loads((ROOT / "integrations/video_engines/examples/storyboard.json").read_text())

def test_valid_draft_has_no_spend_authority(draft):
    result=review(Storyboard.model_validate(draft))
    assert result["duration_seconds"] == 8
    assert result["spend_authorized"] is False
    assert result["production_enabled"] is False
    assert result["status"] == "draft"

def test_hash_is_stable_but_changes_with_the_story(draft):
    first=review(Storyboard.model_validate(draft))["plan_sha256"]
    assert first==review(Storyboard.model_validate(deepcopy(draft)))["plan_sha256"]
    draft["shots"][0]["change"]="Another visible change."
    assert first!=review(Storyboard.model_validate(draft))["plan_sha256"]

@pytest.mark.parametrize("value",[float("nan"),float("inf"),-1,0])
def test_invalid_end_is_rejected(draft,value):
    draft["shots"][0]["end"]=value
    with pytest.raises(ValidationError):Storyboard.model_validate(draft)

@pytest.mark.parametrize("change",["duplicate","gap","overlap","script","unknown_ref","unknown_claim","approval","extra"])
def test_contract_regressions(draft,change):
    if change=="duplicate":draft["shots"][1]["id"]=draft["shots"][0]["id"]
    if change=="gap":draft["shots"][1]["start"]=5
    if change=="overlap":draft["shots"][1]["start"]=3
    if change=="script":draft["narration_script"]="Not the approved narration."
    if change=="unknown_ref":draft["shots"][0]["reference_ids"]=["missing"]
    if change=="unknown_claim":draft["shots"][0]["claim_ids"]=["missing"]
    if change=="approval":draft["status"]="approved"
    if change=="extra":draft["api_key"]="not-accepted"
    with pytest.raises(ValidationError):Storyboard.model_validate(draft)

def test_repurpose_source_contract(draft):
    draft["flow"]="repurpose"
    with pytest.raises(ValidationError):Storyboard.model_validate(draft)
    draft["source"]={"finished_video_id":"finished-1","duration":100,"start":10,"end":18}
    assert review(Storyboard.model_validate(draft))["duration_seconds"]==8
    draft["source"]["layout"]="track"
    with pytest.raises(ValidationError):Storyboard.model_validate(draft)

def test_vimax_preserves_notes_not_narration():
    raw=json.loads((ROOT / "integrations/video_engines/examples/vimax-import.json").read_text())
    result=import_vimax(raw)
    assert result["storyboard"]["provenance"]=="vimax_import"
    shot=result["storyboard"]["shots"][0]
    assert shot["audio_notes"]==raw["shots"][0]["audio_desc"]
    assert shot["narration"]==raw["alignment"][0]["narration"]
    raw.pop("alignment")
    with pytest.raises(ValueError):import_vimax(raw)

def test_vimax_does_not_invent_first_or_last_frames():
    raw=json.loads((ROOT / "integrations/video_engines/examples/vimax-import.json").read_text())
    raw["shots"][0].pop("lf_desc")
    with pytest.raises(ValidationError):import_vimax(raw)

def test_catalog_roles_are_not_falsely_enabled():
    items=list_capabilities()
    assert all(not item["production_enabled"] for item in items)
    assert next(x for x in items if x["id"]=="motion_scene")["kind"]=="scene_feature"
    assert json.loads((ROOT / "static/video-engine-catalog.json").read_text())["capabilities"]==items
    items[0]["production_enabled"]=True
    assert not list_capabilities()[0]["production_enabled"]

def test_optional_dependencies_not_added_to_app():
    requirements=(ROOT / "requirements.txt").read_text()
    assert "ultralytics" not in requirements
    assert "moviepy==2" not in requirements
    package=json.loads((ROOT / "integrations/motion-canvas/package.json").read_text())
    assert "@motion-canvas/ffmpeg" not in package["dependencies"]
