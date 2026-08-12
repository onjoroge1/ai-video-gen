"""Turn per-block shot POOLS into a per-segment shot playlist.

Keyed on the storyboard BLOCK, never on segment ids. Scripts get split during correction passes
(hidden_heir became hidden_heir_a/_b/_c), so a per-id playlist has to be rewritten every time the
script changes shape. A pool survives any amount of splitting: a segment just draws the next shots
from its block's pool and the cursor carries across the split.

Shot kinds:
    ("plate", loc)                     full-bleed location + rail
    ("card",  card, bg_loc)            one card over a dimmed plate + rail
    ("cards", [card, card], bg_loc)    two stacked cards + rail
    ("full",  diagram)                 diagram, full-bleed, NO rail
    ("map",   map_asset)               supplied map, full-bleed, no rail
"""
from __future__ import annotations
import re

SEC_PER_SHOT = 6.5
MIN_SHOTS, MAX_SHOTS = 3, 6
OPENER_FORBIDDEN = ("full", "map", "cards")   # "figure" and "plate" and "card" may open


def block_of(seg_id, pools, aliases=None):
    """Resolve a segment id to its storyboard block.

    Longest-prefix match first, so any a/b/c split resolves to its block. Then ALIASES, because the
    script author names segments for readability while block names come from the spec's headings --
    `six_crises_a` and `the_six_active_crises` are the same block and neither is wrong.
    """
    best = None
    for b in pools:
        if seg_id == b or seg_id.startswith(b + "_"):
            if best is None or len(b) > len(best):
                best = b
    if best:
        return best
    for pre, block in (aliases or {}).items():
        if (seg_id == pre or seg_id.startswith(pre + "_")) and block in pools:
            return block
    return None


def shot_subjects(shot):
    """The asset names a shot puts on screen, whatever its kind."""
    if shot[0] == "cards":
        return list(shot[1])
    return [shot[1]]


def _named(text, subject_words, portraits):
    """Portraits for the people this text actually names, in the order it names them."""
    t = text.lower()
    hits = []
    for slug in portraits:
        w = subject_words.get(slug)
        if not w:
            continue
        at = min((t.find(x) for x in w if x in t), default=-1)
        if at >= 0:
            hits.append((at, slug))
    return [slug for _, slug in sorted(hits)]


def retarget(shots, text, subject_words, portraits, prev=None):
    """Point each portrait slot at someone this segment actually names. Returns (shots, changed).

    Shots come out of a pool in cursor order, which guarantees variety and legality but says nothing
    about relevance: measured on a finished render, 49% of character shots showed someone the segment
    never named -- Largent while the narration discussed Baela and Addam.

    Only the SUBJECT of an existing portrait slot is rewritten. The slot's kind, its background plate
    and the shot mix are all left alone, because ranking whole shots by relevance starves the kinds
    that can never match a name: it cut the diagrams from 19 to 4. Relevance is worth having, but not
    at the price of the art direction.
    """
    want = [s for s in _named(text, subject_words, portraits)
            if s not in {n for it in shots for n in shot_subjects(it)}]
    if not want:
        return shots, 0
    out, changed, k = ([prev] if prev else []), 0, 0
    for it in shots:
        if it[0] == "figure" and k < len(want):
            words = subject_words.get(it[1])
            if not (words and words & set(_words(text))):     # already on topic: leave it
                new = (it[0], want[k], *it[2:])
                k += 1
                # a retarget must not undo the no-repeat rule the pool cursor just satisfied
                if out and new == out[-1] and k < len(want):
                    new = (it[0], want[k], *it[2:]); k += 1
                if not (out and new == out[-1]):
                    it = new; changed += 1
        out.append(it)
    if prev:
        out = out[1:]
    return out, changed


def _words(text):
    return re.findall(r"[a-z]+", text.lower())


def resolve_beats(script, pools, block_state, aliases, subject_words, figures, person_of,
                  role_words=None):
    """Playlists cut on subject change, with per-shot durations. See hotd.beats for the reasoning.

    Returns (playlists, seg_state, report) where report["weights"] holds each segment's shot lengths
    in seconds. The old fixed-clock path stays in `resolve` and is still what episodes without a
    portrait library use.
    """
    from hotd import beats as B
    w2p = B.word_to_person(subject_words, person_of)
    w2p_weak = B.word_to_person(role_words or {}, person_of)
    playlists, seg_state, weights = {}, {}, {}
    cursors, stats = {}, {"ensemble": 0, "solo": 0, "insert": 0, "split": 0}
    for s in script["segments"]:
        b = block_of(s["id"], pools, aliases)
        if b is None:
            raise SystemExit(f"no shot pool for segment {s['id']}")
        cur = cursors.setdefault(b, {"i": 0, "b": 0})
        runs = B.subject_runs(s["narration"], s["target_s"], w2p, w2p_weak=w2p_weak)
        shots, secs = B.plan_segment(runs, pools[b], cur, figures,
                                     subjects_in=B.subjects_lookup(s["narration"], w2p, w2p_weak))
        if not shots:
            raise SystemExit(f"segment {s['id']} produced no shots")
        # a caption is drawn on the first shot, so that slot has to be able to host one
        if shots[0][0] in OPENER_FORBIDDEN:
            j = next((i for i in range(1, len(shots))
                      if shots[i][0] not in OPENER_FORBIDDEN), None)
            if j:
                shots[0], shots[j] = shots[j], shots[0]
                secs[0], secs[j] = secs[j], secs[0]
        for it in shots:
            stats["ensemble" if it[0] == "figures" else
                  "solo" if it[0] == "figure" else "insert"] += 1
        stats["split"] += cur.pop("split", 0)
        playlists[s["id"]], weights[s["id"]] = shots, secs
        seg_state[s["id"]] = block_state[b]
    # Every diagram in a block's pool must appear in that block. Inserts are only requested when a
    # run names nobody or needs splitting, so two diagrams went unused -- and they were the
    # show-versus-book and scoreboard graphics, in the two blocks where the diagram IS the argument and
    # the planner was listing five portraits instead. The longest portrait shot in the block gives up
    # half its time, so the portrait survives and the diagram gets the reading time it needs.
    by_block = {}
    for s in script["segments"]:
        by_block.setdefault(block_of(s["id"], pools, aliases), []).append(s["id"])
    for b, sids in by_block.items():
        want = [it for it in pools[b] if it[0] == "full"]
        have = {it[1] for sid in sids for it in playlists[sid] if it[0] == "full"}
        for dia in [it for it in want if it[1] not in have]:
            # Aim at the middle of the block's longest portrait STREAK, not at its longest single
            # shot. Every portrait shares one layout, so nine in a row is 48s of identical furniture
            # with only the face changing -- and an analysis block listing five names is exactly where
            # the comparison graphic belongs.
            flat = [(sid, i, w, it[0] in ("figure", "figures"))
                    for sid in sids
                    for i, (it, w) in enumerate(zip(playlists[sid], weights[sid]))]
            runs, cur = [], []
            for row in flat:
                if row[3] and row[1] > 0:
                    cur.append(row)
                else:
                    runs.append(cur); cur = []
            runs.append(cur)
            longest = max(runs, key=len, default=[])
            pick = [r for r in longest if r[2] >= 2 * B.MIN_SHOT_S]
            best = (max(pick, key=lambda x: x[2]) if pick else
                    max((r for r in flat if r[3] and r[1] > 0 and r[2] >= 2 * B.MIN_SHOT_S),
                        key=lambda x: x[2], default=None))
            best = best and (best[0], best[1], best[2])
            if best is None or best[2] < 2 * B.MIN_SHOT_S:
                stats["diagram_unplaced"] = stats.get("diagram_unplaced", 0) + 1
                continue
            sid, i, w = best
            playlists[sid].insert(i, dia)
            weights[sid][i] = w / 2.0
            weights[sid].insert(i, w / 2.0)
            stats["diagram_forced"] = stats.get("diagram_forced", 0) + 1

    # A caption is drawn on its segment's first shot, so the picture MUST change there. Where a block
    # has only one usable insert there is no alternative frame to reach for, so the fix is to reorder
    # within the segment rather than substitute: swap the opener with a later shot that differs and can
    # still host a caption.
    # Two ways an opener goes wrong, and both need the same repair: it repeats the previous segment's
    # last shot (the caption changes under a frame that does not), or it is a self-titled diagram,
    # which cannot host a caption at all. A segment whose narration names nobody can be a SINGLE
    # insert shot, so there is often nothing inside it to swap with.
    ids = [s["id"] for s in script["segments"] if s["id"] in playlists]
    for k, b in enumerate(ids):
        prev = playlists[ids[k - 1]][-1] if k else None
        if not playlists[b]:
            continue
        bad = playlists[b][0][0] in OPENER_FORBIDDEN or playlists[b][0] == prev
        if not bad:
            continue
        j = next((i for i in range(1, len(playlists[b]))
                  if playlists[b][i] != prev
                  and playlists[b][i][0] not in OPENER_FORBIDDEN), None)
        if j:
            playlists[b][0], playlists[b][j] = playlists[b][j], playlists[b][0]
            weights[b][0], weights[b][j] = weights[b][j], weights[b][0]
            stats["opener_swapped"] = stats.get("opener_swapped", 0) + 1
            continue
        # Borrow a caption-legal shot from the block's own pool and give it half the opener's time.
        # Preferring a plate keeps the location honest; a portrait of the block's subject is the
        # fallback when the pool has no other plate.
        blk = block_of(b, pools, aliases)
        cand = [it for it in pools[blk] if it != prev and it[0] not in OPENER_FORBIDDEN]
        alt = next((it for it in cand if it[0] == "plate"), None) or (cand[0] if cand else None)
        if alt:
            playlists[b].insert(0, alt)
            weights[b][0] /= 2.0
            weights[b].insert(0, weights[b][0])
            stats["opener_borrowed"] = stats.get("opener_borrowed", 0) + 1

    # Break any portrait streak that survives, including one spanning a block boundary -- the worst
    # case measured was five shots ending one block and four opening the next, which no per-block rule
    # can see. Nine dossier panels in a row is 48s of identical furniture with only the face changing.
    order = [s["id"] for s in script["segments"] if s["id"] in playlists]
    for _ in range(40):
        flat = [(sid, i, playlists[sid][i], weights[sid][i])
                for sid in order for i in range(len(playlists[sid]))]
        streak, cut = [], None
        for row in flat:
            if row[2][0] in ("figure", "figures"):
                streak.append(row)
                if len(streak) > B.MAX_PORTRAIT_RUN:
                    ok = [r for r in streak if r[1] > 0 and r[3] >= 2 * B.MIN_SHOT_S]
                    if ok:
                        cut = max(ok, key=lambda r: r[3]); break
            else:
                streak = []
        if cut is None:
            break
        sid, i, _, w = cut
        b = block_of(sid, pools, aliases)
        alts = [it for it in pools[b] if it[0] not in ("figure", "figures")]
        if not alts:
            break
        pick = min(alts, key=lambda x: sum(1 for v in playlists.values() for y in v if y == x))
        playlists[sid].insert(i, pick)
        weights[sid][i] = w / 2.0
        weights[sid].insert(i, w / 2.0)
        stats["streak_broken"] = stats.get("streak_broken", 0) + 1

    nostate = sorted(set(seg_state.values()) - set(block_state.values()))
    if nostate:
        raise SystemExit(f"rail state missing: {nostate}")
    report = {"segments": len(script["segments"]),
              "shots": sum(len(v) for v in playlists.values()),
              "weights": weights, "mix": stats, "cycles": {}}
    return playlists, seg_state, report


def resolve(script, pools, block_state, sec_per_shot=SEC_PER_SHOT, aliases=None,
            subject_words=None, portraits=None, opening=None):
    """-> (playlists, seg_state, report). Raises on an unmapped segment or an unusable pool.

    `subject_words` maps an asset name to the words that would name it in narration. When supplied,
    each segment prefers pool shots whose subject it actually mentions, falling back to pool order to
    fill. Pool order alone guarantees variety and legality but not relevance.

    `opening` is (segments, sec_per_shot) and cuts the first few segments faster. Measured on S3E5,
    the three longest shots in a fourteen-minute video were its first three, at 7.3s each: the episode
    cut most slowly exactly where a viewer decides whether to stay.
    """
    segs = script["segments"]
    unmapped = [s["id"] for s in segs if block_of(s["id"], pools, aliases) is None]
    if unmapped:
        raise SystemExit(f"no shot pool for segment(s): {unmapped}\nknown blocks: {sorted(pools)}")
    bad_pool = [b for b, v in pools.items()
                if not v or all(i[0] in OPENER_FORBIDDEN for i in v)]
    if bad_pool:
        raise SystemExit(f"pools with no shot that can host a caption: {bad_pool}")
    nostate = sorted({block_of(s["id"], pools, aliases) for s in segs} - set(block_state))
    if nostate:
        raise SystemExit(f"blocks with no rail state: {nostate}")

    cursor = {b: 0 for b in pools}
    retargeted = 0
    tail = None
    playlists, seg_state, per_block = {}, {}, {}
    for s in segs:
        b = block_of(s["id"], pools, aliases)
        pool = pools[b]
        spp = sec_per_shot
        if opening and len(playlists) < opening[0]:
            spp = opening[1]
        n = max(MIN_SHOTS, min(MAX_SHOTS, round(s["target_s"] / spp)))
        n = min(n, len(pool))
        # a segment's caption is drawn on its first shot, so that slot must be a plate or a card
        tries = 0
        while pool[cursor[b] % len(pool)][0] in OPENER_FORBIDDEN and tries < len(pool):
            cursor[b] += 1
            tries += 1
        shots, last = [], None
        while len(shots) < n:
            item = pool[cursor[b] % len(pool)]
            cursor[b] += 1
            if item == last and len(pool) > 1:          # never the same shot twice in a row
                continue
            shots.append(item)
            last = item
        if subject_words and portraits:
            shots, ch = retarget(shots, s.get("narration", "") + " " + s.get("caption", ""),
                                 subject_words, portraits, prev=tail)
            retargeted += ch
        # A segment's caption is drawn on its first shot, so the picture MUST change there. The cursor
        # only forbids repeats inside a segment, so it can hand a block's next segment the same shot
        # it just ended on -- the caption then swaps under a frame that never moves.
        if tail is not None and shots[0] == tail and len(shots) > 1:
            j = next((i for i in range(1, len(shots))
                      if shots[i] != tail and shots[i][0] not in OPENER_FORBIDDEN), None)
            if j:
                shots[0], shots[j] = shots[j], shots[0]
        tail = shots[-1]
        playlists[s["id"]] = shots
        seg_state[s["id"]] = block_state[b]
        per_block[b] = per_block.get(b, 0) + n

    report = {"segments": len(segs), "shots": sum(len(v) for v in playlists.values()),
              "retargeted_figures": retargeted,
              "cycles": {b: round(per_block.get(b, 0) / max(len(pools[b]), 1), 2)
                         for b in sorted(per_block)}}
    return playlists, seg_state, report


def thin_pools(report, limit=1.6):
    """Blocks whose pool is reused so often that shots visibly repeat inside one block."""
    return {b: c for b, c in report["cycles"].items() if c > limit}
