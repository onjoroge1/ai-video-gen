"""Studio-owned immutable asset catalog; metadata in Postgres, bytes in existing Blob.

Uploads are explicit operator-reviewed source material. Nothing here generates art or
asserts that a checksum proves creative consistency. These endpoints use studio auth.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import uuid

from .media import inspect_asset, sha256

SUFFIX = {"image/png":".png", "image/jpeg":".jpg", "audio/wav":".wav",
          "audio/mpeg":".mp3", "video/mp4":".mp4"}


@contextmanager
def transaction():
    import db
    conn = db._conn()
    if conn is None:
        raise RuntimeError("Kids asset/review persistence requires Postgres")
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS kids_assets (
                id text PRIMARY KEY, sha256 text NOT NULL, metadata jsonb NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now())""")
            cur.execute("""CREATE TABLE IF NOT EXISTS kids_editorial_reviews (
                id text PRIMARY KEY, job_id text NOT NULL, video_sha256 text NOT NULL,
                metadata jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now())""")
            yield cur
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


class Catalog:
    def add(self, path, *, mime_type, license_info, origin, reviewer, name, blob):
        if mime_type not in SUFFIX:
            raise ValueError("Unsupported Kids asset MIME")
        if not license_info.strip() or license_info.casefold() in {"unknown","tbd","unresolved","verify"}:
            raise ValueError("Resolve usage rights before adding an asset")
        info = inspect_asset(path,mime_type)
        asset_id = uuid.uuid4().hex
        digest = sha256(path)
        # Establish persistence first; do not upload if the database is unavailable.
        with transaction() as cur:
            artifact = blob.upload(str(path),f"kids/library/{asset_id}{SUFFIX[mime_type]}")
            metadata = {"id":asset_id,"name":name,"sha256":digest,"mime_type":mime_type,
                        "size_bytes":Path(path).stat().st_size,"origin":origin,"license":license_info,
                        "reviewer":reviewer,"review_status":"operator_approved_source",
                        "artifact":artifact,**info}
            try:
                cur.execute("INSERT INTO kids_assets(id,sha256,metadata) VALUES (%s,%s,%s::jsonb)",
                            (asset_id,digest,json.dumps(metadata)))
            except BaseException:
                # Best-effort cleanup only; original transaction error remains authoritative.
                try: blob.delete(artifact["url"])
                except Exception: pass
                raise
        return self.public(metadata)

    def get(self, asset_id):
        if not re.fullmatch(r"[0-9a-f]{32}",asset_id): raise ValueError("Invalid library asset ID")
        with transaction() as cur:
            cur.execute("SELECT metadata FROM kids_assets WHERE id=%s",(asset_id,))
            row = cur.fetchone()
        if not row: raise ValueError("Kids library asset is unavailable")
        return row[0]

    def list(self):
        with transaction() as cur:
            cur.execute("SELECT metadata FROM kids_assets ORDER BY created_at DESC LIMIT 200")
            return [self.public(row[0]) for row in cur.fetchall()]

    @staticmethod
    def public(row):
        return {key:row[key] for key in ("id","name","sha256","mime_type","license","origin","review_status")}

    def review(self, job_id, video_sha256, payload):
        with transaction() as cur:
            cur.execute("INSERT INTO kids_editorial_reviews(id,job_id,video_sha256,metadata) VALUES (%s,%s,%s,%s::jsonb)",
                        (uuid.uuid4().hex,job_id,video_sha256,json.dumps(payload)))
        return payload

    def latest_review(self, job_id, video_sha256):
        with transaction() as cur:
            cur.execute("SELECT metadata FROM kids_editorial_reviews WHERE job_id=%s AND video_sha256=%s ORDER BY created_at DESC LIMIT 1",
                        (job_id,video_sha256))
            row=cur.fetchone()
        return row[0] if row else None


def resolve_references(episode, destination, blob, catalog=None, asset_root=None):
    catalog = catalog or Catalog()
    root = Path(asset_root or Path(__file__).resolve().parents[2]/"assets").resolve()
    destination=Path(destination); destination.mkdir(parents=True,exist_ok=True)
    resolved={}
    for ref in episode.references:
        target = destination / (ref.id+SUFFIX[ref.mime_type])
        if ref.uri.startswith("asset://"):
            source=(root/ref.uri[8:]).resolve()
            if not source.is_relative_to(root) or not source.is_file():
                raise ValueError(f"Reference {ref.id} is unavailable or outside the asset root")
            if source.stat().st_size > 32*1024*1024: raise ValueError("Reference is too large")
            shutil.copyfile(source,target)
        else:
            row=catalog.get(ref.uri[10:])
            if (row.get("sha256")!=ref.sha256 or row.get("mime_type")!=ref.mime_type
                    or row.get("license")!=ref.license or row.get("origin")!=ref.origin
                    or row.get("review_status")!="operator_approved_source"):
                raise ValueError(f"Reference {ref.id} differs from the operator-reviewed library record")
            blob.download(row["artifact"],str(target))
        if sha256(target)!=ref.sha256:
            raise ValueError(f"Reference {ref.id} checksum mismatch")
        inspect_asset(target,ref.mime_type)
        resolved[ref.id]=str(target)
    return resolved
