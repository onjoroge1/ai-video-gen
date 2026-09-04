"""The finished library must not hide renders it can serve."""
import finished_api


def _db(*ids):
    return [{"id": i, "title": i, "created_at": f"2026-09-0{n+1}T00:00:00+00:00",
             "video_url": f"https://blob/{i}"} for n, i in enumerate(ids)]


def _local(*pairs):
    return [{"id": i, "title": i, "created_at": ts, "storage": "local", "_sort_key": 1.0}
            for i, ts in pairs]


def test_one_indexed_row_no_longer_hides_every_local_render():
    """The list fell back to local rows only when Postgres returned NOTHING, so a single uploaded
    video hid 154 local ones while the grid read "12 finished videos" and looked complete.

    A library that silently omits most of its contents is worse than an empty one, because nothing
    about it looks wrong.
    """
    merged = finished_api._merge_rows(
        _db("uploaded"), _local(("local-a", "2026-09-03T00:00:00+00:00")), limit=50, offset=0)
    assert {r["id"] for r in merged} == {"uploaded", "local-a"}


def test_postgres_wins_when_both_stores_know_an_id():
    """A row in both is the uploaded one, and that is the copy with durable URLs."""
    merged = finished_api._merge_rows(
        _db("shared"), _local(("shared", "2026-09-09T00:00:00+00:00")), limit=50, offset=0)
    assert len(merged) == 1
    assert merged[0].get("video_url") == "https://blob/shared", "the local copy shadowed the blob"


def test_a_fresh_local_render_outranks_a_stale_upload():
    """Both halves arrive newest-first within themselves, so without interleaving by timestamp a
    render finished minutes ago sorts below an upload from last month."""
    merged = finished_api._merge_rows(
        _db("old-upload"),                                    # 2026-09-01
        _local(("new-render", "2026-09-30T00:00:00+00:00")), limit=50, offset=0)
    assert [r["id"] for r in merged] == ["new-render", "old-upload"]


def test_paging_is_computed_from_the_whole_merge():
    """Merging two independently paged lists gives a page that is right by accident at most."""
    db_rows = _db("a", "b")
    local = _local(("c", "2026-09-05T00:00:00+00:00"), ("d", "2026-09-06T00:00:00+00:00"))
    first = finished_api._merge_rows(db_rows, local, limit=2, offset=0)
    second = finished_api._merge_rows(db_rows, local, limit=2, offset=2)
    assert len(first) == 2 and len(second) == 2
    assert not ({r["id"] for r in first} & {r["id"] for r in second}), "pages overlap"
    assert {r["id"] for r in first} | {r["id"] for r in second} == {"a", "b", "c", "d"}


def test_the_internal_sort_key_never_reaches_the_client():
    merged = finished_api._merge_rows(
        _db(), _local(("x", "2026-09-01T00:00:00+00:00")), limit=10, offset=0)
    assert merged and all("_sort_key" not in row for row in merged)
