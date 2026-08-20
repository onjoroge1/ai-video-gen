"""
Story-board renderer for TV episode review videos.

Draws an always-on, code-drawn "state" rail (transparent PNG, right side) that composites
over any full-fidelity location card. Characters are text chips (name/role/status) — never
depictions of real actors or copyrighted character designs. Crests, dragon glyphs, and the
control bar are original vector marks. One PNG per chapter -> section-snapping video.

render_board(state, out_path) -> transparent 1920x1080 RGBA overlay.

state = {
  "title": "EPISODE REVIEW",
  "subtitle": "Example Show · S1E2 · Full spoilers",
  "left":  {"name": "SIDE A", "accent": "steel", "chips": [chip, ...]},
  "right": {"name": "SIDE B", "accent": "green", "chips": [chip, ...]},
  "control": {"label": "THE STAKES", "held_by": "left|contested|right", "text": "..."},
  "assets": {"left": 3, "right": 2, "right_dim": 1},
  "footer": "CH 2 / 12 · Where everyone stands",
  "changed": ["Aegon", "control", "dragons"],           # highlight what moved this chapter
}
chip = {"name","role","tag","tone"}  tone in {good, bad, neutral, dead, key}
"""
import os, json, re
from PIL import Image, ImageDraw
from font_utils import load_font

_SUP = "/System/Library/Fonts/Supplemental"
def _F(path, size, index=0):
    return load_font(path, size, index=index, bold="Bold" in path or path.endswith(".ttc"))
_COPPER = f"{_SUP}/Copperplate.ttc"; _GEO_B = f"{_SUP}/Georgia Bold.ttf"
_ARIAL = f"{_SUP}/Arial.ttf"; _ARIAL_B = f"{_SUP}/Arial Bold.ttf"

GOLD=(216,179,106); WHITE=(245,243,238); MUTE=(150,157,166)
STEEL=(150,170,192); GREEN=(102,175,108); RED=(210,72,72); DIM=(70,84,74)
CHIP=(21,25,33,235); PANEL=(11,14,20,226)
_ACCENT = {"steel": STEEL, "green": GREEN, "gold": GOLD}
_TONE = {"good": GREEN, "bad": RED, "neutral": STEEL, "dead": RED, "key": GOLD}

def _track(d, xy, text, fnt, fill, tr=0):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=fnt, fill=fill)
        b = d.textbbox((0, 0), ch, font=fnt); x += (b[2] - b[0]) + tr
    return x

def _tw(d, text, fnt):
    b = d.textbbox((0, 0), text, font=fnt); return b[2] - b[0]

def _crest(d, cx, cy, r, col, up=True):
    d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=col, width=3)
    pts = ([(cx-r*0.5, cy+r*0.35),(cx, cy-r*0.45),(cx+r*0.5, cy+r*0.35)] if up
           else [(cx-r*0.5, cy-r*0.35),(cx, cy+r*0.45),(cx+r*0.5, cy-r*0.35)])
    d.line(pts, fill=col, width=3, joint="curve")

def _dragon(d, cx, cy, s, col):
    d.polygon([(cx-1.6*s,cy),(cx-0.2*s,cy-0.5*s),(cx+1.2*s,cy-0.2*s),
               (cx+2.2*s,cy+0.4*s),(cx+1.1*s,cy+0.3*s),(cx-0.2*s,cy+0.5*s)], fill=col)
    d.polygon([(cx-0.3*s,cy-0.4*s),(cx+0.9*s,cy-1.5*s),(cx+1.0*s,cy-0.2*s)], fill=col)
    d.line([(cx-1.6*s,cy),(cx-2.6*s,cy+0.7*s)], fill=col, width=max(2,int(s*0.5)))

def _chip(d, x, y, w, h, accent, c, changed):
    d.rounded_rectangle([x, y, x+w, y+h], radius=10, fill=CHIP)
    d.rounded_rectangle([x, y, x+6, y+h], radius=3, fill=accent)
    name = c["name"]; dead = c.get("tone") == "dead"
    d.text((x+22, y+12), name, font=_F(_GEO_B, 28), fill=(200,200,200) if dead else WHITE)
    if dead:
        b = d.textbbox((x+22, y+12), name, font=_F(_GEO_B, 28))
        d.line([(x+20, (b[1]+b[3])//2),(b[2]+2, (b[1]+b[3])//2)], fill=RED, width=3)
    # tag pill first, so the role can be clipped to never collide with it
    tag = c.get("tag"); pill_left = x + w - 12
    if tag:
        tc = _TONE.get(c.get("tone"), STEEL); tf = _F(_ARIAL_B, 16)
        twp = _tw(d, tag, tf); pill_w = twp + 20; px = x+w-12-pill_w; py = y+h-34
        d.rounded_rectangle([px, py, px+pill_w, py+26], radius=6, outline=tc, width=2)
        d.text((px+10, py+4), tag, font=tf, fill=tc)
        pill_left = px
    if c.get("role"):
        rf = _F(_ARIAL, 17); role = c["role"]; max_w = pill_left - 12 - (x+22)
        if _tw(d, role, rf) > max_w:
            while role and _tw(d, role + "…", rf) > max_w:
                role = role[:-1]
            role = (role + "…") if role else ""
        d.text((x+22, y+h-30), role, font=rf, fill=MUTE)
    if changed:
        d.rounded_rectangle([x-3, y-3, x+w+3, y+h+3], radius=12, outline=GOLD, width=3)
        d.polygon([(x-3,y+14),(x-3,y+30),(x+9,y+22)], fill=GOLD)   # little gold ▸ marker

def render_board(state, out_path, w=1920, h=1080):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    rail_x0 = 1206
    # scrim so text is legible over any card
    sc = Image.new("RGBA", (w, h), (0,0,0,0)); sd = ImageDraw.Draw(sc)
    for x in range(rail_x0-120, w):
        a = int(150 * min(1, (x-(rail_x0-120))/120))
        sd.line([(x,0),(x,h)], fill=(6,8,12,a))
    img = Image.alpha_composite(img, sc); d = ImageDraw.Draw(img)
    # glass panel
    gl = Image.new("RGBA", (w, h), (0,0,0,0)); gd = ImageDraw.Draw(gl)
    gd.rounded_rectangle([rail_x0, 26, w-26, h-26], radius=18, fill=PANEL)
    img = Image.alpha_composite(img, gl); d = ImageDraw.Draw(img)

    px = rail_x0 + 40; rx = w - 66
    _track(d, (px, 54), state.get("title","EPISODE REVIEW"), _F(_COPPER, 36), GOLD, tr=5)
    if state.get("subtitle"):
        d.text((px, 108), state["subtitle"], font=_F(_ARIAL, 18), fill=MUTE)
    d.line([(px, 144),(rx, 144)], fill=GOLD, width=2)

    colw = (rx - px - 22)//2; c1 = px; c2 = px + colw + 22
    L = state["left"]; R = state["right"]
    _crest(d, c1+15, 182, 14, _ACCENT[L["accent"]], up=False)
    d.text((c1+40, 169), L["name"], font=_F(_COPPER, 22), fill=_ACCENT[L["accent"]])
    _crest(d, c2+15, 182, 14, _ACCENT[R["accent"]], up=True)
    d.text((c2+40, 169), R["name"], font=_F(_COPPER, 22), fill=_ACCENT[R["accent"]])

    changed = set(state.get("changed", []))
    y0 = 214; ch = 84; gap = 13
    for i, c in enumerate(L["chips"]):
        _chip(d, c1, y0+i*(ch+gap), colw, ch, _ACCENT[L["accent"]], c, c["name"] in changed)
    for i, c in enumerate(R["chips"]):
        _chip(d, c2, y0+i*(ch+gap), colw, ch, _ACCENT[R["accent"]], c, c["name"] in changed)

    n = max(len(L["chips"]), len(R["chips"]))
    by = y0 + n*(ch+gap) + 16
    ctrl = state.get("control")
    if ctrl:
        _track(d, (px, by), ctrl.get("label","KING'S LANDING"), _F(_COPPER, 22), GOLD, tr=3)
        bar = [px, by+34, rx, by+34+38]
        d.rounded_rectangle(bar, radius=9, fill=(28,32,40))
        held = {"blacks": "left", "greens": "right"}.get(ctrl.get("held_by"), ctrl.get("held_by", "contested"))
        if held == "left":
            d.rounded_rectangle(bar, radius=9, fill=(46,58,74))
        elif held == "right":
            d.rounded_rectangle(bar, radius=9, fill=(40,74,44))
        else:  # contested — split
            mid = (bar[0]+bar[2])//2
            d.rounded_rectangle([bar[0],bar[1],mid+10,bar[3]], radius=9, fill=(46,58,74))
            d.rounded_rectangle([mid-10,bar[1],bar[2],bar[3]], radius=9, fill=(40,74,44))
        if "control" in changed:
            d.rounded_rectangle([bar[0]-3,bar[1]-3,bar[2]+3,bar[3]+3], radius=11, outline=GOLD, width=3)
        t = ctrl.get("text",""); tf=_F(_ARIAL_B,18)
        d.text(((bar[0]+bar[2])//2 - _tw(d,t,tf)//2, bar[1]+8), t, font=tf, fill=WHITE)
        by = bar[3] + 26

    dr = state.get("assets") or state.get("dragons")  # legacy manifests remain renderable
    if dr:
        _track(d, (px, by), dr.get("label", "ASSETS IN PLAY"), _F(_COPPER, 22), GOLD, tr=3)
        if "assets" in changed or "dragons" in changed:
            d.polygon([(px-14,by+4),(px-14,by+18),(px-4,by+11)], fill=GOLD)
        dy = by + 40
        d.text((px, dy-2), L["name"][:12], font=_F(_ARIAL_B, 17), fill=STEEL)
        for k in range(dr.get("left",0)): _dragon(d, px+104+k*30, dy+8, 9, STEEL)
        d.text((c2, dy-2), R["name"][:12], font=_F(_ARIAL_B, 17), fill=GREEN)
        rn = dr.get("right",0); rdim = dr.get("right_dim",0)
        for k in range(rn):
            _dragon(d, c2+104+k*30, dy+8, 9, DIM if k >= rn-rdim else GREEN)
        by = dy + 44

    if state.get("footer"):
        d.text((px, h-70), state["footer"], font=_F(_ARIAL, 17), fill=MUTE)

    img.save(out_path)
    return out_path


# ─── Auto-extraction (for a UI mode): narration -> per-chapter state timeline ──────
_EXTRACT_SYSTEM = """You turn a TV-review narration into a per-chapter STORY-BOARD timeline.
The panel should help a viewer follow the review's argument: two meaningful sides, theories, groups,
or story threads and a small fixed roster of key characters. Do not force a faction conflict when the
episode is better represented by two plotlines or competing interpretations.

STRICT RULES — accuracy over completeness:
- Use ONLY facts stated in the narration. NEVER invent a status, outcome, or fact. If a player's
  situation is not addressed in a chapter, carry forward their most recent known status unchanged.
- Pick at most 4 players PER SIDE — the ones whose situation actually MOVES across the recap. Drop minor mentions.
- Tags: <= 12 characters, UPPERCASE, concrete ("ESCAPED","KILLED","CAPTURED","MARCHING"). role: <= 16 chars.
- tone ∈ {good, bad, neutral, dead, key}: dead=died/executed; bad=lost/captured/wounded/fleeing;
  good=survived/gained; key=pivotal move this recap; neutral=in play / unchanged.
- "changed" per chapter = the player NAMES (and "control"/"assets") whose status CHANGED vs the previous
  chapter. First chapter: [].
- control (optional): a place, goal, mystery, relationship, or advantage with held_by ∈
  {left,right,contested} + short text. Omit it when the script does not support it.
- assets (optional): only a genuinely countable item per side. Omit rather than estimate.
- Respect the supplied SPOILER SCOPE. Do not introduce facts beyond the pasted narration or scope.

Return STRICT JSON, no prose, no code fences:
{"title": "...", "subtitle": "...",
 "left": {"name":"...","accent":"steel"}, "right": {"name":"...","accent":"green"},
 "control_label": "..." (optional), "assets_label": "..." (optional),
 "chapters": [
   {"left":[{"name","role","tag","tone"}...], "right":[...],
    "control": {"held_by","text"} (optional),
    "assets": {"left":N,"right":M,"right_dim":K} (optional),
    "location": "short GENERIC backdrop descriptor for this chapter — the TYPE of place, e.g.
                 'a great cliffside capital at dusk', 'a volcanic island citadel', 'a colossal ruined
                 castle', 'a candlelit war-council chamber'. NEVER name a copyrighted/proper-noun place
                 or a real location; describe the kind of place so original art can be painted.",
    "changed": [...], "footer": "CH n / N · ..."} ...]}
The chapters array MUST have exactly one entry per input chapter, in order.
Keep a FIXED roster: choose the key players ONCE and show the SAME names every chapter (status changes,
the lineup does not). Limit "changed" to the 1-2 things that actually moved this chapter."""


def build_tv_review_extraction_prompt():
    """Render extraction instructions with the same precedence contract as simulations."""
    from bolt_video.prompts.builder import PromptBuilder, PromptPriority
    return (PromptBuilder("Extract a spoiler-scoped TV-review story-board timeline.")
            .add("Safety and accuracy", "Use only the supplied narration. Never invent events, statuses, "
                 "spoilers, actor likenesses, copyrighted location designs, or count estimates.",
                 PromptPriority.SAFETY)
            .add("Output contract", "Return strict JSON only. The chapters array must contain exactly "
                 "one entry per input chapter, in the original order.", PromptPriority.OUTPUT_CONTRACT)
            .add("Format rules", _EXTRACT_SYSTEM, PromptPriority.FORMAT)
            .render())

def extract_state_timeline(blocks, topic="", model="claude-opus-4-8", cost_sink=None,
                           review_context=None):
    """Best-effort: read narration blocks -> list of render_board() state dicts.
    Returns None on failure. Intended for a UI mode; validate output before trusting it."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    chapters = "\n\n".join(f"[CHAPTER {i+1}] {b.get('title','')}\n{b.get('narration','')}"
                           for i, b in enumerate(blocks))
    resp = client.messages.create(
        model=model, max_tokens=8000, system=build_tv_review_extraction_prompt(),
        messages=[{"role": "user", "content":
                   f"REVIEW CONTEXT: {json.dumps(review_context or {}, ensure_ascii=False)}\n"
                   f"TOPIC: {topic}\n\n{chapters}"}])
    txt = resp.content[0].text.strip()
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    title = data.get("title", "EPISODE REVIEW"); sub = data.get("subtitle", topic)
    left_meta = data.get("left", {"name": "SIDE A", "accent": "steel"})
    right_meta = data.get("right", {"name": "SIDE B", "accent": "green"})
    states = []
    for ch in data.get("chapters", []):
        st = {"title": title, "subtitle": sub,
              "left": {"name": left_meta.get("name", "SIDE A"),
                       "accent": left_meta.get("accent", "steel"), "chips": ch.get("left", [])},
              "right": {"name": right_meta.get("name", "SIDE B"),
                        "accent": right_meta.get("accent", "green"), "chips": ch.get("right", [])},
              "changed": ch.get("changed", []), "footer": ch.get("footer", "")}
        if ch.get("control"):
            st["control"] = {"label": data.get("control_label", "CONTROL"),
                             "held_by": ch["control"].get("held_by", "contested"),
                             "text": ch["control"].get("text", "")}
        if ch.get("assets"):
            st["assets"] = {**ch["assets"], "label": data.get("assets_label", "ASSETS IN PLAY")}
        st["_location_art"] = ch.get("location", "")
        states.append(st)
    return states
