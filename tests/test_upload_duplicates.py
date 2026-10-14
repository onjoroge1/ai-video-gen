"""The uploader refuses duplicates (2026-10-14).

The World channel had 27 uploads in 12 days -- review builds, and one cane toad Short uploaded
seven times -- while its reach collapsed. A file already uploaded, or a title already on the
channel in any privacy state, is refused unless the operator gives a reason. No provider is
called here.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import youtube_upload as yu  # noqa: E402

EXISTING = [{"id": "NIGiEV6xGSg", "title": "The 101-Cane-Toad Mistake That Poisoned Australia's Predators",
             "privacy": "public"},
            {"id": "QRfqURMMBvo", "title": "The Cane Toad Mistake #Shorts", "privacy": "public"},
            {"id": "x7", "title": "the cane toad mistake  #shorts #canetoads", "privacy": "private"}]


def test_title_key_ignores_hashtags_case_and_punctuation_but_keeps_the_kind():
    assert yu.title_key("The Cane Toad Mistake #Shorts") == ("the cane toad mistake", True)
    assert yu.title_key("the cane toad mistake!  #shorts #canetoads") == ("the cane toad mistake", True)
    assert yu.title_key("Escobar Brought Four Hippos. Colombia Cannot Stop Them.") == \
        ("escobar brought four hippos colombia cannot stop them", False)


def test_same_title_same_kind_is_refused_in_any_privacy_state():
    reasons = yu.duplicate_reasons("abc", "The Cane Toad Mistake #Shorts", "UC1", [], EXISTING)
    assert len(reasons) == 2 and "QRfqURMMBvo" in reasons[0] and "x7 (private)" in reasons[1]


def test_a_film_and_its_companion_short_may_share_a_title():
    film = "Escobar Brought Four Hippos to His Ranch. Colombia Cannot Stop Them."
    existing = [{"id": "hFk6YVSa0xk", "title": film, "privacy": "public"}]
    assert yu.duplicate_reasons("abc", film + " #Shorts", "UC1", [], existing) == []
    assert yu.duplicate_reasons("abc", film, "UC1", [], existing)


def test_the_same_file_is_refused_from_the_ledger(tmp_path):
    ledger = tmp_path / "ledger.json"
    yu.record_upload({"video_id": "abc123", "title": "Old", "channel_id": "UC1", "sha256": "f00d",
                      "uploaded_at": "2026-10-01T00:00:00+00:00"}, str(ledger))
    entries = yu.load_ledger(str(ledger))
    reasons = yu.duplicate_reasons("f00d", "A New Title", "UC1", entries, [])
    assert reasons and "abc123" in reasons[0]
    # A different channel's upload of the same file is not this channel's duplicate.
    assert yu.duplicate_reasons("f00d", "A New Title", "UC2", entries, []) == []
    assert yu.duplicate_reasons("beef", "A New Title", "UC1", entries, []) == []


def test_file_sha256_reads_the_bytes(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"same bytes")
    other = tmp_path / "copy.mp4"
    other.write_bytes(b"same bytes")
    assert yu.file_sha256(str(clip)) == yu.file_sha256(str(other))
