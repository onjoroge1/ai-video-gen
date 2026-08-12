"""Cut where the SUBJECT changes, not on a clock.

WHY THIS REPLACES A FIXED SHOT LENGTH
Shots used to be a constant ~6.5s drawn from a per-block pool. Two rounds of measurement on a
finished fourteen-minute render showed what that costs:

  * 49% of character shots showed someone the segment never mentioned at all. Fixed by choosing the
    portrait from the segment's own narration -- which raised the SEGMENT-level score to 78%.
  * That was the wrong metric. Scored against the sentences actually HEARD while each shot is on
    screen, only 29% were right. A segment is ~20s covering 3-4 shots, so putting the right cast in
    the right chapter still lands the wrong face on the wrong sentence.

The cause was never pace. Cutting on subject change yields a 6.6s median against the 6.2s the fixed
clock produced -- practically identical. The cuts were simply in the wrong places, so a new face
arrived while the narration was still finishing with the previous one. Slowing the transitions down
would hold the wrong face for LONGER, and would walk back into the held-image failure that made S3E2
unwatchable.

HOW A RUN BECOMES A SHOT
A run is a stretch of narration with one stable subject. Runs shorter than MIN_SHOT_S are merged into
their neighbour, and the merged run carries BOTH subjects -- which is where the ensemble panel comes
from: when the narration genuinely discusses two people at once, one portrait is 50% wrong by
construction and the only honest picture has both faces in it.

Runs longer than MAX_SHOT_S are split with a plate or diagram inserted between the halves. Splitting
is safe precisely because a run has one subject throughout, so both halves stay on topic -- and it is
what keeps diagrams in rotation and stops any single portrait sitting static too long.
"""
from __future__ import annotations
import math
import re

MIN_SHOT_S = 2.8          # under this a face cannot be read, so merge rather than flash it
MAX_SHOT_S = 9.0          # over this a still portrait reads as a freeze
MAX_ENSEMBLE = 3          # measured sizes were 2 and 3; more panels than that is unreadable
MAX_PORTRAIT_RUN = 4      # every portrait shares one layout, so a long streak reads as one shot
# a self-titled diagram and a stacked card pair both fill the frame, so neither can lead a segment
OPENERLESS = ("map",)


def _tokens(text):
    for i, w in enumerate(re.findall(r"\S+", text)):
        yield i, w.lower().strip(".,;:?!\"'()[]")


def word_to_person(subject_words, person_of):
    """word -> {canonical person}. Folds a character's card stem and portrait slug into one person.

    Without the fold, "aemond" matches both `22_char_aemond` and `aemond-targaryen` and a single
    mention looks like two people being discussed -- which would fire the ensemble panel constantly.
    """
    out = {}
    for asset, words in subject_words.items():
        for w in words:
            out.setdefault(w, set()).add(person_of(asset))
    return out


def subject_runs(narration, target_s, w2p, min_shot=MIN_SHOT_S, w2p_weak=None):
    """[(subjects, seconds)] for one segment. Subject-stable stretches, short ones merged.

    Duration comes from word position: TTS rate is near constant, so a word's index is a good proxy
    for when it is heard.

    Names are the strong signal. Roles are a WEAK one and only take effect inside a stretch where
    nobody has been named for at least `min_shot` -- which is the difference between two real cases
    measured on a finished render:

      * "her Watch commander lies dead at his own table" names nobody, and the only correct picture is
        Luthor Largent, Commander of the Watch. Roles are the only way to know that.
      * "Sabitha Frey comes to collect the Harrenhal Jacaerys promised her house" names Sabitha, and
        letting Alys Rivers' role ("At Harrenhal") compete put the wrong woman on screen.

    A role reference also has to be far enough into a run to be about someone new rather than a
    description of whoever was just named.
    """
    words = re.findall(r"\S+", narration)
    if not words:
        return [(frozenset(), target_s, 0, 0)]
    sec = target_s / len(words)
    marks = [(i, w2p[w]) for i, w in _tokens(narration) if w in w2p]
    if not marks:
        marks = [(i, w2p_weak[w]) for i, w in _tokens(narration) if w in (w2p_weak or {})]
    elif w2p_weak:
        gap = max(2, int(min_shot / sec))                 # words a role hint must clear
        starts = [i for i, _ in marks]
        for i, w in _tokens(narration):
            if w not in w2p_weak:
                continue
            prev = max([p for p in starts if p <= i], default=None)
            if prev is not None and (i - prev) >= gap and i not in starts:
                marks.append((i, w2p_weak[w]))
        marks.sort()
    if not marks:
        return [(frozenset(), target_s, 0, len(words))]

    runs = []
    if marks[0][0] > 0:                                  # narration before anyone is named
        runs.append((frozenset(), marks[0][0] * sec, 0, marks[0][0]))
    for j, (i, who) in enumerate(marks):
        end = marks[j + 1][0] if j + 1 < len(marks) else len(words)
        runs.append((frozenset(who), (end - i) * sec, i, end))

    merged = []
    for who, dur, w0, w1 in runs:
        if merged and (dur < min_shot or merged[-1][1] < min_shot):
            pw, pd, pw0, _ = merged[-1]
            merged[-1] = (pw | who, pd + dur, pw0, w1)   # both subjects survive -> ensemble
        else:
            merged.append((who, dur, w0, w1))
    return merged


def subjects_lookup(narration, w2p, w2p_weak=None):
    """(w0, w1) -> the people named in that word span. Used to give each PIECE of a split run its own
    subjects.

    Without this, every piece of a run inherits the whole run's subject set, so a merged run whose two
    people are named at opposite ends shows both in both halves -- and each half is then half wrong.
    Measured cost of the coarse version: six points of per-window relevance.
    """
    toks = list(_tokens(narration))

    def at(w0, w1):
        found = set()
        for i, w in toks:
            if w0 <= i < w1:
                if w in w2p:
                    found |= w2p[w]
                elif w2p_weak and w in w2p_weak:
                    found |= w2p_weak[w]
        return found
    return at


def plan_segment(runs, pool, cursor, figure_of, max_shot=MAX_SHOT_S, subjects_in=None):
    """Runs -> ([shot, ...], [seconds, ...]). Mutates `cursor` so inserts rotate across the block.

    A run with one subject becomes a portrait, two or three become an ensemble panel, and none at all
    becomes a plate or diagram -- which is the honest picture when the narration names nobody, and is
    a large part of what previously looked like a random face.
    """
    inserts = [it for it in pool if it[0] not in ("figure", "figures")]
    bgs = [it[1] for it in pool if it[0] == "plate"] or \
          [it[-1] for it in pool if len(it) > 2] or [None]
    if not inserts:                                      # a pool must be able to host an insert
        inserts = [("plate", bgs[0])] if bgs[0] else []

    def next_insert():
        """Least-recently-used, so every diagram in a block's pool appears before any insert repeats.

        A plain rotating cursor dropped the diagram count from 19 to 13 across the episode, because
        inserts are only requested when a run has no subject or needs splitting -- far fewer requests
        than the fixed clock made.
        """
        if not inserts:
            return None
        seen = cursor.setdefault("used", {})
        # A heraldic card puts a FACE on screen, and an insert is used precisely when the narration
        # names nobody -- so cards are the last resort, after plates and diagrams. Left unranked they
        # produced misses like a Baela-and-Moondancer pair over a sentence about Aemond.
        it = min(inserts, key=lambda x: (x[0] in ("card", "cards"),
                                         seen.get(repr(x), 0), inserts.index(x)))
        seen[repr(it)] = seen.get(repr(it), 0) + 1
        return it

    def push(shot, dur):
        """Append one shot, never twice in a row, and count the portrait streak.

        The streak matters because every portrait shares one layout -- panel, name plate, status pill.
        Nine in a row measured 51 seconds of identical furniture, and the only thing changing was the
        face inside it.
        """
        if shots and shot == shots[-1]:
            # Ask for a DIFFERENT insert, not just the next one: the least-recently-used pick is often
            # the same plate again, and taking it on faith let a segment open on the exact frame the
            # previous one ended on -- the caption then changes under a picture that does not.
            seen = cursor.setdefault("used", {})
            # Search the WHOLE pool, not just the inserts. In the Joffrey block the only non-card
            # alternatives are portraits, so restricting the search left the same plate on screen for
            # 11.6s and 13.0s across a cut -- the held-image failure this module exists to prevent. A
            # portrait of the block's own subject is a better answer than a frame that does not change.
            alt = min((x for x in pool
                       if x != shots[-1] and x[0] not in ("card", "cards")
                       and x[0] not in OPENERLESS),
                      key=lambda x: (x[0] in ("figure", "figures"), seen.get(repr(x), 0)),
                      default=None)
            if alt is not None:
                seen[repr(alt)] = seen.get(repr(alt), 0) + 1
                shot = alt
        if shot[0] in ("figure", "figures"):
            cursor["prun"] = cursor.get("prun", 0) + 1
        else:
            cursor["prun"] = 0
        shots.append(shot); secs.append(dur)

    def emit(shot_at, dur):
        """Append one run's shots, splitting anything longer than max_shot. `shot_at(k)` supplies the
        k-th piece, so a long stretch alternates its subject with an insert instead of holding."""
        n = max(1, math.ceil(dur / max_shot))
        for k in range(n):
            push(shot_at(k), dur / n)
        return n - 1

    shots, secs = [], []
    if cursor.get("tail") is not None:
        shots.append(cursor["tail"]); secs.append(0.0)   # sentinel: lets push() see the block's
        head = 1                                          # previous shot, popped before returning
    else:
        head = 0
    for who, dur, w0, w1 in runs:
        people = [p for p in sorted(who) if p in figure_of][:MAX_ENSEMBLE]
        if not people:
            if not inserts:
                continue
            # a long stretch naming nobody still cannot be one held frame: 20s inserts were the
            # single worst shot in the first beats build
            cursor["split"] = cursor.get("split", 0) + emit(lambda k: next_insert(), dur)
            continue
        bg = bgs[cursor["b"] % len(bgs)]; cursor["b"] += 1

        def portrait(k, n):
            """The k-th piece of this run shows whoever is named in the k-th piece's OWN words.

            A run is split for length, but its subjects may be named at opposite ends of it. Giving
            every piece the whole run's set makes each piece partly wrong.
            """
            sub = people
            if subjects_in is not None and n > 1:
                a = w0 + (w1 - w0) * k // n
                b = w0 + (w1 - w0) * (k + 1) // n
                own = [p for p in sorted(subjects_in(a, b)) if p in figure_of][:MAX_ENSEMBLE]
                if own:
                    sub = own
            return ("figure", sub[0], bg) if len(sub) == 1 else ("figures", sub, bg)

        # a long run alternates portrait / insert / portrait: both halves keep the same subject, so
        # nothing goes off topic and no single frame is held past MAX_SHOT_S
        n = max(1, math.ceil(dur / max_shot))
        if cursor.get("prun", 0) >= MAX_PORTRAIT_RUN and dur >= 2 * MIN_SHOT_S and inserts:
            # break the dossier rhythm with a location or a diagram, then return to the subject.
            # Relevance still wins on a run too short to split: a face the narration is naming beats
            # a prettier rhythm.
            n = max(2, n)
            for k in range(n):
                push((next_insert() or portrait(k, n)) if k == 0 else portrait(k, n), dur / n)
            cursor["split"] = cursor.get("split", 0) + n - 1
        else:
            cursor["split"] = cursor.get("split", 0) + emit(
                lambda k: portrait(k, n) if k % 2 == 0 else (next_insert() or portrait(k, n)), dur)
    shots, secs = shots[head:], secs[head:]
    if shots:
        cursor["tail"] = shots[-1]
    return shots, secs
