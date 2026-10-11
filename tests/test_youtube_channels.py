"""Each pipeline channel has its own token, and nothing uploads to the operator's personal channel."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import youtube_channels as yc  # noqa: E402

POLITICS = "UClUGfSF39lhWu2M7eDvxObg"


def test_each_channel_accepts_only_its_own_token():
    for name, spec in yc.CHANNELS.items():
        assert yc.check_bound(name, spec["id"]) is None
        others = [s["id"] for n, s in yc.CHANNELS.items() if n != name]
        for other in others:
            assert "not " + spec["title"] in yc.check_bound(name, other, "x")


def test_the_personal_politics_channel_is_refused_for_every_slot():
    for name in yc.CHANNELS:
        assert "personal" in yc.check_bound(name, POLITICS, "Bolt Explains Politics")
    assert POLITICS not in {spec["id"] for spec in yc.CHANNELS.values()}


def test_token_slots_are_distinct_and_world_keeps_its_existing_name():
    slots = [spec["token_env"] for spec in yc.CHANNELS.values()]
    assert len(set(slots)) == len(slots)
    assert yc.CHANNELS["world"]["token_env"] == "YOUTUBE_OAUTH_REFRESH_TOKEN"
