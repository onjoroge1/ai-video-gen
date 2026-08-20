"""Neon Postgres persistence for the topic engine — BEST-EFFORT.

A DB outage, missing driver, or unset DATABASE_URL must NEVER break a render or a topic refresh:
every function swallows errors and degrades to a no-op. Gated on the DATABASE_URL env var.
"""
import os
import json


def db_enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL", "").strip())


def _conn():
    """Open a short-lived connection, or None if unavailable. Caller must close."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    import psycopg2
    return psycopg2.connect(url, connect_timeout=10)


def upsert_topics(channel: str, topics: list) -> int:
    """Insert/refresh curiosity-engine topics for a channel. Dedups on (channel, question):
    a re-seen topic updates its metrics and bumps times_seen/last_seen instead of duplicating.
    Returns the number written, or 0 on any failure (never raises)."""
    if not topics:
        return 0
    conn = None
    try:
        conn = _conn()
        if conn is None:
            return 0
        cur = conn.cursor()
        n = 0
        for q in topics:
            qt = (q.get("question") or "").strip()
            if not qt:
                continue
            cur.execute(
                """
                INSERT INTO topics (channel, question, curiosity, opportunity, pattern, outlier,
                    median_views, competition, relevant_count, recency_days, winning_titles, validated,
                    suggested_title)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (channel, question) DO UPDATE SET
                    curiosity      = EXCLUDED.curiosity,
                    opportunity    = EXCLUDED.opportunity,
                    pattern        = EXCLUDED.pattern,
                    outlier        = EXCLUDED.outlier,
                    median_views   = EXCLUDED.median_views,
                    competition    = EXCLUDED.competition,
                    relevant_count = EXCLUDED.relevant_count,
                    recency_days   = EXCLUDED.recency_days,
                    winning_titles = EXCLUDED.winning_titles,
                    validated      = EXCLUDED.validated OR topics.validated,
                    suggested_title = COALESCE(EXCLUDED.suggested_title, topics.suggested_title),
                    last_seen      = now(),
                    times_seen     = topics.times_seen + 1
                """,
                (channel, qt, q.get("curiosity_gap"), q.get("opportunity"), q.get("pattern"),
                 q.get("outlier"), q.get("median_views"), q.get("competition"),
                 q.get("relevant_count"), q.get("recency_days"),
                 json.dumps(q.get("winning_titles") or []), bool(q.get("validated")),
                 q.get("suggested_title")),
            )
            n += 1
        conn.commit()
        return n
    except Exception as e:
        print(f"[db] upsert_topics failed: {e}")
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def used_questions(channel: str, limit: int = 200) -> list:
    """Questions the USER has marked finished (status done/used/published) for a channel — fed back
    to the topic generator as an exclusion list so it stops resurfacing covered topics and generates
    NEWER angles. Marking is manual (a topic may become BOTH a long-form and a short, so it's not
    auto-marked on render). Best-effort: returns [] on any failure (DB never blocks a refresh)."""
    conn = None
    try:
        conn = _conn()
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT question FROM topics WHERE channel=%s AND status IN ('done','used','published','queued') "
            "ORDER BY last_seen DESC LIMIT %s",
            (channel, limit))
        return [r[0] for r in cur.fetchall() if r and r[0]]
    except Exception as e:
        print(f"[db] used_questions failed: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def queued_topics(channel: str) -> list:
    """Topics the user has PINNED (status='queued') for a channel — hand-picked, high-opportunity
    ideas to make next. Returned as dashboard-shaped dicts so _refresh_trending can pin them to the
    top of the cache and they survive the 12h regen. Best-effort ([] on any failure)."""
    conn = None
    try:
        conn = _conn()
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT question, curiosity, opportunity, pattern, outlier, median_views, competition, "
            "relevant_count, recency_days, winning_titles, suggested_title, validated "
            "FROM topics WHERE channel=%s AND status='queued' ORDER BY opportunity DESC NULLS LAST",
            (channel,))
        out = []
        for r in cur.fetchall():
            wt = r[9]
            if isinstance(wt, str):
                try:
                    wt = json.loads(wt)
                except Exception:
                    wt = []
            out.append({"question": r[0], "curiosity_gap": r[1], "opportunity": r[2],
                        "pattern": r[3], "outlier": r[4], "median_views": r[5], "competition": r[6],
                        "relevant_count": r[7], "recency_days": r[8], "winning_titles": wt or [],
                        "suggested_title": r[10], "validated": bool(r[11]),
                        "status": "queued", "queued": True})
        return out
    except Exception as e:
        print(f"[db] queued_topics failed: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def mark_topic_status(channel: str, question: str, status: str) -> bool:
    """Set a topic's status (e.g. 'done' when the user is finished with it, or 'new' to un-mark).
    'done'/'used'/'published' exclude it from future curiosity-engine generation. Best-effort."""
    conn = None
    try:
        conn = _conn()
        if conn is None:
            return False
        cur = conn.cursor()
        cur.execute("UPDATE topics SET status=%s, last_seen=now() WHERE channel=%s AND question=%s",
                    (status, channel, (question or "").strip()))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        print(f"[db] mark_topic_status failed: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ── Published-video metrics (manual entry) — the real-audience feedback loop ──────────
_METRICS_COLS = ("slug", "title", "format", "template", "question", "published_at", "video_len_sec",
                 "views", "engaged_views", "stayed_pct", "avg_view_dur_sec", "subs_gained",
                 "watch_hours", "notes", "tags", "shown_in_feed", "feed_pct", "search_pct",
                 "impressions", "ctr")


def _ensure_metrics_table(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS video_metrics (
            slug             text PRIMARY KEY,
            title            text,
            format           text,
            template         text,
            question         text,
            published_at     date,
            video_len_sec    numeric,
            views            bigint,
            engaged_views    bigint,
            stayed_pct       numeric,
            avg_view_dur_sec numeric,
            subs_gained      integer,
            watch_hours      numeric,
            notes            text,
            tags             text,
            shown_in_feed    bigint,
            feed_pct         numeric,
            search_pct       numeric,
            impressions      bigint,
            ctr              numeric,
            updated_at       timestamptz DEFAULT now()
        )""")
    # Migrate an existing table (created before the tags/traffic/impression fields) — idempotent.
    for col, typ in (("tags", "text"), ("shown_in_feed", "bigint"),
                     ("feed_pct", "numeric"), ("search_pct", "numeric"),
                     ("impressions", "bigint"), ("ctr", "numeric")):
        cur.execute(f"ALTER TABLE video_metrics ADD COLUMN IF NOT EXISTS {col} {typ}")


def metrics_upsert(row: dict) -> bool:
    """Insert/update one published video's real stats, keyed on `slug`. Best-effort (False on any
    failure). Creates the table on first use so no manual migration is needed."""
    slug = (row.get("slug") or row.get("title") or "").strip()
    if not slug:
        return False
    conn = None
    try:
        conn = _conn()
        if conn is None:
            return False
        cur = conn.cursor()
        _ensure_metrics_table(cur)
        vals = [row.get(c) if c != "slug" else slug for c in _METRICS_COLS]
        placeholders = ",".join(["%s"] * len(_METRICS_COLS))
        updates = ",".join(f"{c}=EXCLUDED.{c}" for c in _METRICS_COLS if c != "slug")
        cur.execute(
            f"INSERT INTO video_metrics ({','.join(_METRICS_COLS)}) VALUES ({placeholders}) "
            f"ON CONFLICT (slug) DO UPDATE SET {updates}, updated_at=now()", vals)
        conn.commit()
        return True
    except Exception as e:
        print(f"[db] metrics_upsert failed: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def metrics_all() -> list:
    """All logged videos, newest publish first. Best-effort ([] on failure)."""
    conn = None
    try:
        conn = _conn()
        if conn is None:
            return []
        cur = conn.cursor()
        _ensure_metrics_table(cur)
        cur.execute(f"SELECT {','.join(_METRICS_COLS)} FROM video_metrics "
                    "ORDER BY published_at DESC NULLS LAST, updated_at DESC")
        rows = cur.fetchall()
        return [{c: (str(v) if c == "published_at" and v else v) for c, v in zip(_METRICS_COLS, r)}
                for r in rows]
    except Exception as e:
        print(f"[db] metrics_all failed: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ── Music assets (object-store metadata; MP3 bytes stay out of Postgres) ────────────
_MUSIC_ASSET_COLS = ("slug", "filename", "object_url", "sha256", "size_bytes", "mime_type",
                     "storage_provider", "license")


def _ensure_music_assets_table(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS music_assets (
            slug             text PRIMARY KEY,
            filename         text NOT NULL,
            object_url       text NOT NULL,
            sha256           text,
            size_bytes       bigint,
            mime_type        text DEFAULT 'audio/mpeg',
            storage_provider text,
            license          text,
            active           boolean DEFAULT true,
            updated_at       timestamptz DEFAULT now()
        )""")


def music_asset_upsert(asset: dict) -> bool:
    """Create/update one external music asset metadata row. Best-effort."""
    slug = (asset.get("slug") or "").strip()
    filename = (asset.get("filename") or "").strip()
    object_url = (asset.get("object_url") or "").strip()
    if not (slug and filename and object_url):
        return False
    conn = None
    try:
        conn = _conn()
        if conn is None:
            return False
        cur = conn.cursor()
        _ensure_music_assets_table(cur)
        vals = [asset.get(column) for column in _MUSIC_ASSET_COLS]
        placeholders = ",".join(["%s"] * len(_MUSIC_ASSET_COLS))
        updates = ",".join(f"{column}=EXCLUDED.{column}" for column in _MUSIC_ASSET_COLS
                           if column != "slug")
        cur.execute(
            f"INSERT INTO music_assets ({','.join(_MUSIC_ASSET_COLS)}) VALUES ({placeholders}) "
            f"ON CONFLICT (slug) DO UPDATE SET {updates}, active=true, updated_at=now()",
            vals,
        )
        conn.commit()
        return True
    except Exception as exc:
        print(f"[db] music_asset_upsert failed: {exc}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def music_asset_get(slug: str) -> dict | None:
    """Return active metadata for a music slug, or ``None`` on any failure."""
    conn = None
    try:
        conn = _conn()
        if conn is None:
            return None
        cur = conn.cursor()
        _ensure_music_assets_table(cur)
        cur.execute(
            f"SELECT {','.join(_MUSIC_ASSET_COLS)} FROM music_assets WHERE slug=%s AND active=true",
            ((slug or "").strip(),),
        )
        row = cur.fetchone()
        return dict(zip(_MUSIC_ASSET_COLS, row)) if row else None
    except Exception as exc:
        print(f"[db] music_asset_get failed: {exc}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
