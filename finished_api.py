"""Finished-videos wall: every render in one place, joined to what it did.

Two halves that were never connected. `finished_videos/` and `renders/` hold the artifacts; `db.py`
holds `video_metrics` (views, stayed_pct, pct_viewed) and now `render_scenes` (per-scene prompts,
timings, measured motion). Neither answers "what works" alone -- the scene table records what we
ASKED for, the metrics record what HAPPENED, and the join is the only reason to have built either.

Deliberately read-mostly: the one write is a metrics form, because retention numbers arrive by hand
from the platform and there is nowhere to put them today.

A caution worth keeping in the code: with a handful of published videos, any per-scene correlation
here is noise wearing a lab coat. Log now, conclude later.
"""
from __future__ import annotations
import glob
import json
import os
import re
import subprocess

from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.abspath(__file__))
FINISHED = os.path.join(ROOT, "finished_videos")
RENDERS = os.path.join(ROOT, "renders")


class MetricsIn(BaseModel):
    slug: str
    title: str | None = None
    views: int | None = None
    stayed_pct: float | None = None          # the hook: share still watching at ~3s
    pct_viewed: float | None = None          # whether it holds
    avg_view_dur_sec: float | None = None
    impressions: int | None = None
    ctr: float | None = None
    subs_gained: int | None = None
    published_at: str | None = None
    notes: str | None = None


def _dur(p):
    try:
        return round(float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p],
            capture_output=True, text=True, timeout=8).stdout.strip()), 1)
    except Exception:
        return None


# Work artifacts share a directory with the finished file. Per-scene clips (c01.mp4), raw provider
# returns (.raw.mp4), the muxless assembly (video_silent.mp4), concat intermediates and the free
# stills preview are all real mp4s -- and none of them is a video anyone finished.
_ARTIFACT = re.compile(
    r"(^c\d+$|^shot_\d+|^scene_?\d+|\.raw$|^video_silent$|^_?concat|^silent$|^narration$"
    r"|preview|_preaudit$|^v_ambient$|^bg_|^ambient$|^travel$|^music_"
    r"|^_batch|^_|^tmp|^test_|^out$|^final_silent$)", re.I)


def _is_artifact(stem, path):
    if _ARTIFACT.search(stem):
        return True
    # anything nested below the render dir is intermediate by construction
    return os.path.basename(os.path.dirname(path)) in ("work", "clips", "plates", "physics")


def _image_type(p):
    """Sniff the real type: finished thumbnails are JPEGs saved as `.thumb`, and FileResponse
    cannot guess a content type from that extension, so every one of them served as a blank card."""
    try:
        with open(p, "rb") as f:
            head = f.read(12)
    except Exception:
        return "application/octet-stream"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _read(p, n=4000):
    try:
        return open(p, encoding="utf8", errors="replace").read()[:n]
    except Exception:
        return ""


def _scan():
    """Every finished MP4 we can find, from both conventions."""
    out = {}
    idx = {}
    try:
        idx = json.load(open(os.path.join(FINISHED, "index.json")))
    except Exception:
        pass
    for mp4 in sorted(glob.glob(os.path.join(FINISHED, "*.mp4"))):
        vid = os.path.basename(mp4)[:-4]
        meta = idx.get(vid) or {}
        out[vid] = {"id": vid, "source": "finished", "path": mp4,
                    "title": meta.get("title") or vid,
                    "format": meta.get("format") or meta.get("template"),
                    "published": bool(meta.get("published_at") or meta.get("youtube_id")),
                    "has_grade": os.path.exists(mp4[:-4] + ".grade"),
                    "has_srt": os.path.exists(mp4[:-4] + ".srt"),
                    "thumb": mp4[:-4] + ".thumb" if os.path.exists(mp4[:-4] + ".thumb") else None,
                    "size_mb": round(os.path.getsize(mp4) / 1e6, 1),
                    "mtime": os.path.getmtime(mp4)}
    for mp4 in sorted(glob.glob(os.path.join(RENDERS, "*", "*.mp4"))):
        base = os.path.basename(mp4)[:-4]
        if _is_artifact(base, mp4):
            continue
        slug = os.path.basename(os.path.dirname(mp4))
        vid = slug if base in (slug, slug.replace("_", " ")) else f"{slug}/{base}"
        d = os.path.dirname(mp4)
        thumb = next((t for t in (os.path.join(d, "thumbnail.jpg"),
                                  os.path.join(d, "thumbnail.png")) if os.path.exists(t)), None)
        out[vid] = {"id": vid, "source": "render", "path": mp4, "slug": slug,
                    "title": (_read(os.path.join(d, "title.txt"), 200).split("\n")[0] or base),
                    "format": None, "published": False,
                    "has_grade": False, "has_srt": bool(glob.glob(os.path.join(d, "*.srt"))),
                    "thumb": thumb, "size_mb": round(os.path.getsize(mp4) / 1e6, 1),
                    "mtime": os.path.getmtime(mp4),
                    "has_desc": os.path.exists(os.path.join(d, "description.txt")),
                    "has_scene_table": os.path.exists(os.path.join(d, "scene_table.md"))}
    return out


def mount(app):
    @app.get("/api/finished/list")
    async def finished_list(with_duration: bool = False, with_db: bool = False,
                            page: int = 1, per_page: int = 24, q: str = ""):
        # The DB join is OPT-IN and off by default. Neon is serverless: a cold connection blocks for
        # the full connect_timeout, and two of them in series left the wall spinning on "loading..."
        # with no error. The artifacts are on local disk and always available; performance data is
        # an enrichment and must never gate the page rendering.
        vids = _scan()
        metrics, scenes = {}, {}
        try:
            import db
            if with_db and db.db_enabled():
                for m in db.metrics_all():
                    metrics[(m.get("slug") or "").strip()] = m
                for s in db.scenes_all(limit=4000):
                    k = s.get("slug")
                    d = scenes.setdefault(k, {"scenes": 0, "renders": set(), "cost": 0.0,
                                              "animated": 0})
                    d["scenes"] += 1
                    d["renders"].add(s.get("render_id"))
                    d["cost"] += float(s.get("cost_usd") or 0)
                    d["animated"] += 1 if s.get("animated") else 0
        except Exception:
            pass
        rows = []
        for v in vids.values():
            key = v.get("slug") or v["id"]
            sc = scenes.get(key)
            rows.append({**v,
                         "metrics": metrics.get(key) or metrics.get(v["id"]),
                         "scene_count": sc["scenes"] if sc else None,
                         "render_count": len(sc["renders"]) if sc else None,
                         "animated": sc["animated"] if sc else None,
                         "cost_usd": round(sc["cost"], 2) if sc else None})
        rows.sort(key=lambda r: r["mtime"], reverse=True)
        if q:
            ql = q.lower()
            rows = [r for r in rows if ql in (r.get("title") or "").lower()
                    or ql in (r.get("id") or "").lower()]
        total = len(rows)
        per_page = max(1, min(per_page, 96))
        page = max(1, page)
        start = (page - 1) * per_page
        page_rows = rows[start:start + per_page]
        # duration is an ffprobe subprocess per file, so it runs on the PAGE, never the whole library
        for r in page_rows:
            r["duration_s"] = _dur(r["path"]) if with_duration else None
        for r in page_rows:
            r.pop("mtime", None)
            r.pop("path", None)
        return {"total": total, "page": page, "per_page": per_page,
                "pages": max(1, (total + per_page - 1) // per_page),
                "count": len(page_rows), "videos": page_rows,
                "db": bool(metrics or scenes), "db_requested": with_db,
                "note": "scene_count comes from render_scenes; metrics are hand-entered"}

    @app.get("/api/finished/file/{kind}/{vid:path}")
    async def finished_file(kind: str, vid: str):
        v = _scan().get(vid)
        if not v:
            raise HTTPException(404, f"no video {vid}")
        if kind == "video":
            return FileResponse(v["path"], media_type="video/mp4")
        if kind == "thumb":
            if not v.get("thumb"):
                raise HTTPException(404, "no thumbnail")
            return FileResponse(v["thumb"], media_type=_image_type(v["thumb"]))
        raise HTTPException(400, "kind must be video or thumb")

    @app.get("/api/finished/detail/{vid:path}")
    async def finished_detail(vid: str):
        v = _scan().get(vid)
        if not v:
            raise HTTPException(404, f"no video {vid}")
        d = os.path.dirname(v["path"])
        out = {**v, "duration_s": _dur(v["path"])}
        out.pop("mtime", None)
        if v["source"] == "finished":
            out["grade"] = _read(v["path"][:-4] + ".grade", 4000)
        for name, f in (("description", "description.txt"), ("tags", "tags.txt"),
                        ("transcript", "transcript.txt"), ("scene_table", "scene_table.md")):
            p = os.path.join(d, f)
            if os.path.exists(p):
                out[name] = _read(p, 20000)
        if v["source"] == "finished":
            out["description"] = _read(v["path"][:-4] + ".desc", 8000) or out.get("description")
            out["transcript"] = _read(v["path"][:-4] + ".txt", 20000) or out.get("transcript")
        try:
            import db
            if db.db_enabled():
                out["scenes"] = db.scenes_all(slug=v.get("slug") or vid, limit=200)
        except Exception:
            pass
        return out

    @app.post("/api/finished/metrics")
    async def finished_metrics(m: MetricsIn):
        try:
            import db
            if not db.db_enabled():
                return {"ok": False, "error": "DATABASE_URL not set"}
            ok = db.metrics_upsert({k: v for k, v in m.dict().items() if v is not None})
            return {"ok": bool(ok)}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @app.get("/finished", response_class=HTMLResponse)
    async def finished_page():
        return HTMLResponse(_PAGE)


_PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>Finished videos</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0b0d11;--card:#141821;--line:#232a36;--tx:#e8ecf2;--dim:#8b93a1;--gold:#e8cd94;
--good:#67c98b;--bad:#e2685f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:20px 26px;border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:baseline}
h1{margin:0;font-size:19px;letter-spacing:.02em}
.sub{color:var(--dim);font-size:13px}
.wrap{padding:22px 26px;display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;
cursor:pointer;transition:border-color .15s}
.card:hover{border-color:var(--gold)}
.thumb{width:100%;aspect-ratio:16/9;object-fit:cover;background:#0f1218;display:block}
.thumb.p{aspect-ratio:9/16}
.meta{padding:11px 13px}
.t{font-weight:600;font-size:14px;margin-bottom:5px;line-height:1.35}
.row{display:flex;gap:9px;flex-wrap:wrap;color:var(--dim);font-size:12px}
.pill{background:#1c222d;border-radius:5px;padding:1px 7px}
.pill.g{color:var(--good)}.pill.b{color:var(--bad)}.pill.k{color:var(--gold)}
dialog{background:var(--card);color:var(--tx);border:1px solid var(--line);border-radius:14px;
max-width:1000px;width:94vw;padding:0}
dialog::backdrop{background:#000a}
.dh{padding:16px 20px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between}
.db{padding:18px 20px;max-height:74vh;overflow:auto}
video{width:100%;max-height:52vh;background:#000;border-radius:8px}
pre{white-space:pre-wrap;font:12px/1.55 ui-monospace,Menlo,monospace;color:#c3cad6;
background:#0f1218;padding:12px;border-radius:8px;border:1px solid var(--line);max-height:280px;overflow:auto}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);margin:18px 0 7px}
table{width:100%;border-collapse:collapse;font-size:12px}
td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:600}
input{background:#0f1218;border:1px solid var(--line);color:var(--tx);border-radius:6px;
padding:7px 9px;width:100%;font-size:13px}
label{display:block;font-size:11px;color:var(--dim);margin:0 0 3px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
button{background:var(--gold);color:#141821;border:0;border-radius:7px;padding:9px 16px;
font-weight:650;cursor:pointer;font-size:13px}
button.x{background:#1c222d;color:var(--tx)}
.warn{color:var(--dim);font-size:12px;margin-top:9px;line-height:1.5}
</style></head><body>
<header><h1>Finished videos</h1><span class="sub" id="sub">loading…</span>
<input id="q" placeholder="search titles…" style="margin-left:auto;max-width:260px">
</header>
<div class="wrap" id="wall"></div>
<div id="pager" style="padding:6px 26px 30px;display:flex;gap:8px;align-items:center;
flex-wrap:wrap"></div>
<dialog id="dlg"><div class="dh"><strong id="dt"></strong>
<button class="x" onclick="dlg.close()">close</button></div>
<div class="db" id="dbody"></div></dialog>
<script>
const $=s=>document.querySelector(s);let VIDS=[],PAGE=1,PAGES=1,Q='';
const pct=v=>v==null?null:(+v).toFixed(0)+'%';
function card(v){
  const m=v.metrics||{};
  const bits=[];
  if(v.duration_s)bits.push(`<span class="pill">${v.duration_s}s</span>`);
  if(v.has_grade)bits.push(`<span class="pill">graded</span>`);
  if(v.scene_count)bits.push(`<span class="pill">${v.scene_count} scenes</span>`);
  if(v.cost_usd)bits.push(`<span class="pill">$${v.cost_usd}</span>`);
  if(m.stayed_pct!=null)bits.push(`<span class="pill ${m.stayed_pct>=50?'g':'b'}">hook ${pct(m.stayed_pct)}</span>`);
  if(m.pct_viewed!=null)bits.push(`<span class="pill k">held ${pct(m.pct_viewed)}</span>`);
  if(m.views!=null)bits.push(`<span class="pill">${(+m.views).toLocaleString()} views</span>`);
  if(!m.views)bits.push(`<span class="pill">no metrics</span>`);
  const th=v.thumb?`<img class="thumb ${v.source==='render'?'p':''}" loading="lazy"
      src="/api/finished/file/thumb/${encodeURIComponent(v.id)}">`
    :`<div class="thumb"></div>`;
  return `<div class="card" onclick="open_('${v.id.replace(/'/g,"\\'")}')">${th}
    <div class="meta"><div class="t">${v.title||v.id}</div><div class="row">${bits.join('')}</div></div></div>`;
}
function qs(extra){return `page=${PAGE}&per_page=24&q=${encodeURIComponent(Q)}${extra||''}`;}
function pager(total){
  const b=[];
  b.push(`<button class="x" ${PAGE<=1?'disabled':''} onclick="go(${PAGE-1})">← prev</button>`);
  b.push(`<span class="sub">page ${PAGE} of ${PAGES} · ${total} videos</span>`);
  b.push(`<button class="x" ${PAGE>=PAGES?'disabled':''} onclick="go(${PAGE+1})">next →</button>`);
  $('#pager').innerHTML=b.join(' ');
}
function go(p){PAGE=Math.max(1,Math.min(p,PAGES));load();window.scrollTo(0,0);}
async function load(){
  // page 1 is the newest 24. The library is 800+ videos; sending them all returned 200 server-side
  // and never finished transferring, which looked exactly like a hang.
  const r=await (await fetch('/api/finished/list?'+qs())).json();
  VIDS=r.videos;PAGES=r.pages;
  $('#sub').textContent=`${r.total} videos · loading metrics…`;
  $('#wall').innerHTML=VIDS.map(card).join('');pager(r.total);
  // enrich after the wall is up: durations are one ffprobe per file and the DB is a slow
  // serverless hop -- neither may gate rendering
  try{
    const e=await (await fetch('/api/finished/list?'+qs('&with_duration=true&with_db=true'))).json();
    VIDS=e.videos;$('#wall').innerHTML=VIDS.map(card).join('');pager(e.total);
    $('#sub').textContent=`${e.total} videos · ${e.db?'db connected':'no metrics recorded yet'}`;
  }catch(err){$('#sub').textContent=`${r.total} videos · metrics unavailable`;}
}
async function open_(id){
  const v=await (await fetch('/api/finished/detail/'+encodeURIComponent(id))).json();
  const m=v.metrics||{};
  $('#dt').textContent=v.title||v.id;
  const f=(k,l,val)=>`<div><label>${l}</label><input id="f_${k}" value="${val??''}"></div>`;
  let h=`<video controls preload="metadata" src="/api/finished/file/video/${encodeURIComponent(id)}"></video>`;
  h+=`<h3>Performance — entered by hand from the platform</h3><div class="grid">
    ${f('views','Views',m.views)}${f('stayed_pct','Hook % (still watching ~3s)',m.stayed_pct)}
    ${f('pct_viewed','Held % (avg viewed)',m.pct_viewed)}${f('avg_view_dur_sec','Avg view (s)',m.avg_view_dur_sec)}
    ${f('impressions','Impressions',m.impressions)}${f('ctr','CTR %',m.ctr)}
    ${f('subs_gained','Subs',m.subs_gained)}${f('published_at','Published (YYYY-MM-DD)',m.published_at)}</div>
    <div style="margin-top:12px"><button onclick="save('${id}')">Save metrics</button>
    <span id="msg" class="sub" style="margin-left:10px"></span></div>
    <div class="warn">Hook % and Held % are the two that matter: a weak opening is invisible in a view
    count and obvious in a 3-second drop-off. With only a few published videos, treat any per-scene
    pattern here as provisional — log now, conclude later.</div>`;
  if(v.scenes&&v.scenes.length){
    h+=`<h3>Scenes (${v.scenes.length}) — what we asked for</h3><table>
      <tr><th>#</th><th>scene</th><th>s</th><th>narration</th><th>i2v prompt</th><th>motion</th></tr>`;
    for(const s of v.scenes)h+=`<tr><td>${s.scene_idx}</td><td>${s.scene_id}</td>
      <td>${(s.dur_s??'')}</td><td>${(s.narration||'').slice(0,110)}</td>
      <td>${(s.i2v_prompt||'—').slice(0,140)}</td><td>${s.motion_measured??''}</td></tr>`;
    h+=`</table>`;
  }
  if(v.description)h+=`<h3>Description</h3><pre>${esc(v.description)}</pre>`;
  if(v.tags)h+=`<h3>Tags</h3><pre>${esc(v.tags)}</pre>`;
  if(v.grade)h+=`<h3>Self-grade</h3><pre>${esc(v.grade)}</pre>`;
  $('#dbody').innerHTML=h;$('#dlg').showModal();
}
const esc=s=>(s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function save(id){
  const g=k=>{const e=document.getElementById('f_'+k);const v=e&&e.value.trim();return v===''?null:v;};
  const v=VIDS.find(x=>x.id===id)||{};
  const body={slug:v.slug||id,title:v.title,views:num(g('views')),stayed_pct:num(g('stayed_pct')),
    pct_viewed:num(g('pct_viewed')),avg_view_dur_sec:num(g('avg_view_dur_sec')),
    impressions:num(g('impressions')),ctr:num(g('ctr')),subs_gained:num(g('subs_gained')),
    published_at:g('published_at')};
  const r=await (await fetch('/api/finished/metrics',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
  $('#msg').textContent=r.ok?'saved':('failed: '+(r.error||'?'));
  if(r.ok)load();
}
const num=v=>v==null?null:(isNaN(+v)?null:+v);
let t;$('#q').addEventListener('input',e=>{clearTimeout(t);
  t=setTimeout(()=>{Q=e.target.value.trim();PAGE=1;load();},250);});
load();
</script></body></html>"""
