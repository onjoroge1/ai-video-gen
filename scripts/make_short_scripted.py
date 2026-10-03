"""A Short with its own script, written from a delivered film's verified claims and pictures.

Not a clip of the film. The film opens on setup by engine contract; a Short is payoff-first:
a question the viewer can see, the human decision, what became of it, the backfire, a payoff,
one takeaway, and four spoken words pointing at the film. Every factual line cites a claim id
from the film's research ledger, so no new research or fact-check is bought. Every CLAUSE of
narration gets its own picture (v5): a sentence that names the elk and then the beaver shows
the elk and then the beaver, with a two-word beat label over each, so the pictures demonstrate
what the words say instead of illustrating the sentence's first half.

    python3 scripts/make_short_scripted.py jobs/wolves01 [--voice echo] [--speed 1.1]
                                            [--generate-images] [--reuse-script]

Writes <job>/short.mp4, <job>/short_package.json (script, visuals, claim ids, readiness
metrics) and <job>/short_audio.mp3. Costs: one text call, one TTS pass, one whisper pass, and a
vertical frame per visual that the film's own images cannot supply (about $0.04 each, cached).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from make_teaser_short import (  # noqa: E402
    FPS, H, SAFE_BOTTOM, W, WHITE, YELLOW, _font, _run, _text_png, _wrap, _duration)
from media_binaries import ffmpeg as _ffmpeg_bin  # noqa: E402

TARGET_SECONDS = 22.0
WORDS_MIN, WORDS_MAX = 56, 72
MIN_PICTURE_SECONDS = 1.1      # a slot shorter than this is a flash frame
MIN_NEW_SUBJECT_SECONDS = 0.85  # a clause that first shows a subject keeps its own picture down to this
MAX_VISUAL_SECONDS = 2.5       # a visual held longer than this gets a detail cut inside it
ROLES = ("hook", "decision", "mechanism", "consequence", "payoff", "takeaway", "cta")
LINE_WORD_CAPS = {"hook": 12, "decision": 9, "mechanism": 10, "consequence": 14, "payoff": 14,
                  "takeaway": 12, "cta": 5}
CTA_TEXT = re.compile(r"full story on the channel\.?", re.I)

_SCRIPT_SYSTEM = """You write 20-23 second vertical YouTube Shorts for a documentary channel about interventions that backfired. A Short tells ONE complete causal chain, and EVERY CLAUSE of narration has its own picture that demonstrates that clause: the viewer must SEE each thing the words name, at the moment the words name it. It must be TRUE to the film's verified claims and nothing else.

Return ONLY JSON:
{"openings": ["...", "...", "..."],
 "lines": [{"text": "...", "role": "hook|decision|mechanism|consequence|payoff|takeaway|cta",
            "claim_ids": ["c01"], "emphasis": ["one", "two"],
            "visuals": [{"clause": "exact clause text from this line", "shot": "close-up|medium|wide",
                         "subject": "...", "action": "...", "label": "TWO WORDS",
                         "state": "before|after|null", "picture": "state:s001:e01 or NEW: ..."}]}]}

Story shape: seven to nine lines in this order (the consequence may take up to three lines), 56 to 72 words in total.
1. hook: at most 12 words, may be a statement followed by a question ("They killed the wolves. Why did the beavers suffer?"), ending with "?". It names the removed or introduced animal AND the surprising thing that followed, so the viewer wants the connection. Its premise must be a DOCUMENTED ledger fact, never a cause the EDITORIAL CONSTRAINTS mark as contested. No place names, dates or numbers. Propose THREE candidate hooks in "openings" and use one verbatim.
2. decision: at most 9 words, who did it and what for, in the plainest words ("To protect livestock." / "Australia did it to kill sugar cane beetles."). Never an agency, bureau, department, official or government by name.
3. mechanism: at most 10 words, what BECAME of the plan as an outcome ("The elk had nothing left to fear." / "It barely helped the cane."), never a reason for it.
4. consequence: the backfire as a chain of clauses, each clause naming AT MOST ONE new thing (an animal, a plant, a place) and each clause getting its own visual ("Elk stripped the willows, and the beavers lost their food."). A clause with a change verb (climbed, recovered, returned, fell, grew, vanished, stripped, gone) must be drawn as its END STATE at glance scale ("young aspen standing above an elk's head", "a riverbank with no willows"), and the thing that changed must have been shown earlier so the viewer has the before.
5. payoff: a NEW fact that reframes the chain, drawn as the hook's LOCATION in its changed state (same river bend, later), not as the hook picture again.
6. takeaway: one insight sentence of at most 12 words that names nothing new ("The damage didn't stop with the wolves.").
7. cta: exactly "Full story on the channel." with no visual (visuals: []).

COHESION: every sentence follows from the one before, answering it, resulting from it or contrasting with it, and carries a word or idea from it. A listener must never need a fact that has not been said yet.

Visuals: one object per clause (split at commas and sentence ends), in order, covering the whole line. Each names the shot size, the subject and ONE action a single still can show; the picture must demonstrate the clause and never contradict the narration; only the animals, people and objects the clause names may appear; no silhouettes, outlines, montages, maps or symbols. The hook has exactly ONE visual whose clause is the whole hook. A clause shorter than four words ("Without wolves,", "and trees.") belongs to the clause it introduces or follows, not to its own visual. Lists of three are fine but each list item is not a clause. "label" is TWO words lifted from the clause, as a beat marker the viewer reads in passing (WOLVES KILLED, ELK MULTIPLY, WILLOWS STRIPPED, BEAVERS GONE). "state" is "before" or "after" for the two sides of a change, else null. Vary shot size: never the same size three visuals running; at least one close-up and one wide. Pictures: a state id from the available pictures only when that picture's own description names this clause's subject, otherwise "NEW: " plus a 12-25 word literal description in the film's real setting and period.

Language: spoken register, present tense where possible, no semicolons, dashes or parentheses, at most one comma per line, no lists of more than three, no research prose. Banned words: monitored, significantly, dramatically, documented, populations, estimated, reported, data, study, species-level, respectively. No quantity words anywhere: doubled, tripled, halved, percent, -fold, times as many. Say "climbed unchecked" and show a before and after instead. At most one number in the whole Short and only if a cited claim states it exactly; prefer none. Name at most 22 distinct things in the whole Short.

Facts: every line except the hook, takeaway and cta cites claim ids that actually state what the line says. Never invent a number, species, place, date or cause. Keep recovery wording as qualified as the ledger ("began to recover"), never "restored".

Emphasis: for each line, one or two words the captions should highlight: the danger or the twist, never a proper noun.
"""


def _load(job: str):
    rr = json.load(open(os.path.join(job, "run_result.json"))) if os.path.isfile(os.path.join(job, "run_result.json")) else {}
    dossier = json.load(open(os.path.join(job, "research_dossier.json")))
    plan = json.load(open(os.path.join(job, "evidence_asset_plan.json")))
    transcript = open(os.path.join(job, "transcript.txt"), encoding="utf-8").read() if os.path.isfile(os.path.join(job, "transcript.txt")) else ""
    state = json.load(open(os.path.join(job, "_state.json")))
    script = state.get("script") or {}
    claims = {}
    for c in dossier.get("claims") or []:
        cid = str(c.get("claim_id") or "").strip()
        if cid and (c.get("quote_verified") or c.get("support_provenance")):
            claims[cid] = str(c.get("claim") or "").strip()
    states = {}
    for sc in plan.get("scenes") or []:
        for st in sc.get("states") or []:
            if st.get("asset_status") not in ("accepted", "reused_exact"):
                continue
            path = st.get("asset_path") or ""
            for cand in (path, path.replace("/images/", "/images_keep/")):
                if cand and os.path.isfile(cand):
                    path = cand
                    break
            else:
                path = ""
            states[st["state_id"]] = {"visual": st.get("visual") or st.get("state_after") or "",
                                      "objects": st.get("required_objects") or [], "path": path,
                                      "scene": sc.get("scene_index")}
    title = rr.get("title") or script.get("title") or os.path.basename(job)
    brief = open(os.path.join(job, "direction.txt"), encoding="utf-8").read() if os.path.isfile(os.path.join(job, "direction.txt")) else ""
    cautions = [m.strip() for m in re.findall(r"(?:Do not say|Never say|Separate documented|Scope impacts|No unsupported|Reconcile)[^.]*\.", brief)]
    pack = plan.get("continuity_pack") or {}
    location = str((pack.get("first_act_location") or {}).get("label") or "")
    years = sorted(set(re.findall(r"\b(1[6-9]\d\d|20\d\d)\b", transcript)))
    era = f"{years[0]}s" if years else ""
    setting = ", ".join(x for x in (location, era) if x)
    return title, script.get("hook") or "", transcript, claims, states, setting, cautions


SHOTS = ("close-up", "medium", "wide")
# Things a picture can show and a viewer can miss: animals, plants, crops, livestock. Generic
# words (predator, park, valley, river) are deliberately absent; "the elk lost their main
# predator" needs no predator drawn, and "the park" is every frame.
SUBJECT_WORDS = ("wolf", "elk", "toad", "beetle", "quoll", "snake", "crocodile", "lizard", "beaver",
                 "aspen", "willow", "monitor", "bird", "rabbit", "cat", "rat", "livestock", "grub",
                 "cane", "mongoose", "stoat", "kiwi", "sparrow", "locust", "deer", "bison", "fox",
                 "cougar", "bear", "sheep", "goat", "pig", "frog", "fish", "perch", "snail", "moth",
                 "carp", "camel", "starling", "bee", "tree", "grass", "shrub")
CHANGE_VERBS = re.compile(r"\b(climbed|multiplied|multiply|recovered|recovering|returned|return|fell|rose|grew|"
                          r"vanished|disappeared|stripped|gone|away|thinned|spread|soared|collapsed|rebounded)\b", re.I)
QUANTITY = re.compile(r"\b(doubled|tripled|halved|quadrupled|percent|per cent|\w+fold|times as many|times more)\b", re.I)
JARGON = re.compile(r"\b(monitored|significantly|dramatically|documented|populations?|estimated|reported|data|study|species-level|respectively)\b", re.I)


def _numbers(text: str) -> set:
    return {t.replace(",", "") for t in re.findall(r"\$?\d[\d,]*(?:\.\d+)?%?", text)}


def _clauses(text: str) -> list[str]:
    """Clauses of a line: split after commas and sentence ends. Shared by the validator, the
    caption chunker and the visual timing, so picture cuts and caption chunks share boundaries."""
    return [c.strip() for c in re.split(r"(?<=[,.!?])\s+", str(text).strip()) if c.strip()]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", str(text).lower()).strip()


_ALIASES = {"wolve": "wolf", "wolv": "wolf", "wolves": "wolf", "cattle": "livestock", "cow": "livestock",
            "cows": "livestock", "calf": "livestock", "calves": "livestock", "stream": "river", "creek": "river"}


def _stem(word: str) -> str:
    w = re.sub(r"[^a-z]", "", word.lower())
    if w in _ALIASES:
        return _ALIASES[w]
    for suffix in ("ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suffix):
            w = w[: -len(suffix)]
            break
    return _ALIASES.get(w, w)


def _subject_words(text: str) -> set:
    """The animals, plants and places a text names, canonicalised ("wolves" -> "wolf")."""
    out = set()
    for raw in re.findall(r"[A-Za-z]+", text):
        s = _stem(raw)
        if s in SUBJECT_WORDS:
            out.add(s)
    return out


def _visual_clauses(text: str) -> list[str]:
    """Clauses that can each hold a picture: a lead-in shorter than three words ("Without
    wolves,") is folded into the clause it introduces, since no picture can hold on it."""
    parts = _clauses(text)
    merged: list[str] = []
    for part in parts:
        if merged and len(merged[-1].split()) < 4:
            merged[-1] = merged[-1] + " " + part
        else:
            merged.append(part)
    if len(merged) > 1 and len(merged[-1].split()) < 4:
        last = merged.pop()
        merged[-1] = merged[-1] + " " + last
    return merged


def _validate(lines: list[dict], claims: dict, states: dict, openings: list | None = None) -> list[str]:
    errs = []
    roles = [str(l.get("role")) for l in lines]
    # One or two consequence lines; everything else exactly once, in order.
    collapsed = [r for i, r in enumerate(roles) if not (r == "consequence" and i > 0 and roles[i - 1] == "consequence")]
    if collapsed != list(ROLES) or roles.count("consequence") > 3:
        errs.append(f"lines must be these roles in order: hook, decision, mechanism, consequence (one to three lines), payoff, takeaway, cta (got {', '.join(roles)})")
    words = sum(len(str(l.get("text", "")).split()) for l in lines)
    if not WORDS_MIN <= words <= WORDS_MAX:
        errs.append(f"{words} words; need {WORDS_MIN}-{WORDS_MAX}")
    if openings is not None and len([o for o in openings if str(o).strip()]) != 3:
        errs.append("propose exactly 3 openings")
    by_role = {str(l.get("role")): l for l in lines}
    hook = str(by_role.get("hook", {}).get("text", "")).strip()
    if hook:
        if len(hook.split()) > 12:
            errs.append(f"the hook is {len(hook.split())} words; max 12")
        if not hook.endswith("?"):
            errs.append("the hook must end with a question mark")
        if openings and hook not in [str(o).strip() for o in openings]:
            errs.append("the hook must be one of the proposed openings, verbatim")
        if _numbers(hook) or re.search(r"\b(1[6-9]\d\d|20\d\d)\b", hook):
            errs.append("the hook must contain no number or date")
    head = " ".join(str(l.get("text", "")) for l in lines[:3])
    if re.search(r"\b(bureau|department|agency|ministry|officials?|authorit(y|ies)|government)\b", head, re.I):
        errs.append("lines 1-3 must not name an agency, bureau, department, officials or government")
    decision = str(by_role.get("decision", {}).get("text", "")).strip()
    if decision and hook and (decision.split() or [""])[0].lower().strip(",.") == (hook.split() or [""])[0].lower().strip(",.?"):
        errs.append("the decision must not begin with the same word as the hook")
    mech = str(by_role.get("mechanism", {}).get("text", ""))
    if re.search(r"\b(because|beyond|lived|reach|reached|too high|since|instead of|so that|in order)\b", mech, re.I):
        errs.append("the mechanism must state what BECAME of the plan in plain words, not a reason for it")
    payoff = str(by_role.get("payoff", {}).get("text", ""))
    if hook and payoff:
        a = {w.lower().strip(",.?!") for w in hook.split() if len(w) > 3}
        b = {w.lower().strip(",.?!") for w in payoff.split() if len(w) > 3}
        if a and len(a & b) / len(a) > 0.5:
            errs.append("the payoff restates the hook; it must add a new fact")
    takeaway = str(by_role.get("takeaway", {}).get("text", ""))
    if takeaway:
        # "Names nothing new" means no new animal, plant or place and no proper noun; ordinary
        # words ("whole", "food") are the takeaway's job.
        earlier = set().union(*(_subject_words(str(l.get("text", ""))) for l in lines if l.get("role") not in ("takeaway", "cta")))
        new = _subject_words(takeaway) - earlier
        proper = [w for w in takeaway.split()[1:] if w[:1].isupper() and w.strip(".,?!").lower() not in ("i",)]
        if new:
            errs.append(f"the takeaway introduces {', '.join(sorted(new))}; it may only reflect on things already shown")
        if proper:
            errs.append(f"the takeaway names {', '.join(proper)}; no proper nouns in the takeaway")
        if re.search(r"\d", takeaway):
            errs.append("the takeaway may not contain digits")
    cta = str(by_role.get("cta", {}).get("text", "")).strip()
    if cta and not CTA_TEXT.fullmatch(cta):
        errs.append('the cta must be exactly "Full story on the channel."')

    all_numbers = set()
    shots: list[str] = []
    seen_subjects: set = set()
    hook_actions: set = set()
    for i, l in enumerate(lines, 1):
        role = str(l.get("role"))
        text = str(l.get("text", ""))
        cap = LINE_WORD_CAPS.get(role, 14)
        if len(text.split()) > cap:
            errs.append(f"line {i} ({role}) is {len(text.split())} words; max {cap}")
        if re.search(r"explained like you are five|in this video|let'?s dive|did not increase", text, re.I):
            errs.append(f"line {i} contains filler or research prose")
        m = JARGON.search(text)
        if m:
            errs.append(f"line {i} uses the banned word '{m.group(0)}'")
        q = QUANTITY.search(text)
        if q:
            errs.append(f"line {i} uses the quantity word '{q.group(0)}'; say what happened and show a before and after")
        if re.search(r"[;—–(]", text) or len(re.findall(r"(?<!\d),|,(?!\d)", text)) > 2:
            errs.append(f"line {i} uses semicolons, dashes, parentheses or more than two commas")
        ids = [str(c) for c in (l.get("claim_ids") or [])]
        if role not in ("hook", "takeaway", "cta"):
            if not ids:
                errs.append(f"line {i} cites no claim")
            for cid in ids:
                if cid not in claims:
                    errs.append(f"line {i} cites unknown claim {cid}")
        nums = _numbers(text)
        all_numbers |= nums
        for n in nums:
            if not any(n in _numbers(claims.get(cid, "")) for cid in ids):
                errs.append(f"line {i} states the number {n} that none of its cited claims states")
        visuals = l.get("visuals") if isinstance(l.get("visuals"), list) else None
        if role == "cta":
            if visuals:
                errs.append("the cta has no visual: visuals must be []")
            continue
        # The hook is a tease ("They killed the wolves. Why did the beavers suffer?") and gets
        # exactly ONE picture whose clause is the whole line. Every other line gets one picture
        # per clause, where a lead-in under three words folds into the clause it introduces.
        # The visuals must tile the line: each visual's clause is one or more CONSECUTIVE clauses
        # of the line, in order, covering all of it. The writer may give "Beavers left," its own
        # picture or fold it into the next clause; both are legitimate cuts.
        raw = _clauses(text)
        if role == "hook":
            raw = [text.strip()]
        if visuals is None:
            errs.append(f"line {i} needs visuals: one per clause, in order")
            continue
        clauses, ok, cursor = [], True, 0
        for v in visuals:
            target = _norm((v or {}).get("clause", "")) if isinstance(v, dict) else ""
            acc, j = "", cursor
            while j < len(raw) and _norm(acc) != target:
                acc = (acc + " " + raw[j]).strip()
                j += 1
            if _norm(acc) != target:
                ok = False
                break
            clauses.append(acc)
            cursor = j
        if not ok or cursor != len(raw):
            errs.append(f"line {i} visuals must tile its clauses in order; the clauses are: " + " | ".join(f'"{c}"' for c in raw)
                        + (" (the hook has ONE visual whose clause is the whole line)" if role == "hook" else ""))
            continue
        for k, (clause, v) in enumerate(zip(clauses, visuals), 1):
            if not isinstance(v, dict):
                errs.append(f"line {i} visual {k} is not an object")
                continue
            if _norm(v.get("clause", "")) != _norm(clause):
                errs.append(f"line {i} visual {k} clause must be exactly: \"{clause}\"")
            shot = str(v.get("shot", "")).strip().lower()
            if shot not in SHOTS or not str(v.get("subject", "")).strip() or not str(v.get("action", "")).strip():
                errs.append(f"line {i} visual {k} needs shot (close-up|medium|wide), subject and action")
            shots.append(shot)
            label = str(v.get("label", "")).strip()
            lw = label.split()
            if not 1 <= len(lw) <= 3:
                errs.append(f"line {i} visual {k} label must be 1-3 words")
            else:
                pool = {_stem(w) for w in (clause + " " + str(v.get("subject", "")) + " " + str(v.get("action", ""))).split()}
                for w in lw:
                    if not any(cs.startswith(_stem(w)[:4]) or _stem(w).startswith(cs[:4]) for cs in pool if cs):
                        errs.append(f"line {i} visual {k} label word '{w}' must come from its clause or its visual's subject/action")
            subj_here = _subject_words(clause)
            new_here = subj_here - seen_subjects
            vis_words = _subject_words(str(v.get("subject", "")) + " " + str(v.get("action", "")))
            missing = new_here - vis_words
            if missing:
                errs.append(f"line {i} clause \"{clause}\" names {', '.join(sorted(missing))} for the first time; its visual must show it")
            if CHANGE_VERBS.search(clause) and role != "hook":      # the hook may tease a change
                if str(v.get("state", "")).lower() != "after":
                    errs.append(f"line {i} clause \"{clause}\" describes a change; its visual must be the end state (state: after)")
                if subj_here and not (subj_here & seen_subjects):
                    errs.append(f"line {i} clause \"{clause}\" shows a change in {', '.join(sorted(subj_here))} before the viewer has seen it; show it in an earlier clause first")
            if role == "hook":
                hook_actions.add(_norm(v.get("action", "")))
            if role == "payoff":
                if str(v.get("state", "")).lower() != "after":
                    errs.append("the payoff visual must be state: after (the hook's location, changed)")
                if _norm(v.get("action", "")) in hook_actions:
                    errs.append("the payoff visual repeats a hook action; it must show the changed state")
            pic = str(v.get("picture") or "").strip()
            if not pic:
                errs.append(f"line {i} visual {k} names no picture")
            elif not pic.startswith("NEW:") and states and pic not in states:
                errs.append(f"line {i} visual {k} names unknown picture {pic}")
            seen_subjects |= subj_here
    nouns = content_nouns(lines)
    if len(nouns) > 26:
        errs.append(f"the Short names {len(nouns)} distinct things; at most 26 (drop a list or an adjective-noun)")
    if len(all_numbers) > 1:
        errs.append(f"{len(all_numbers)} different numbers ({', '.join(sorted(all_numbers))}); at most one")
    if shots and ("close-up" not in shots or "wide" not in shots):
        errs.append("use at least one close-up and one wide shot")
    for i in range(2, len(shots)):
        if shots[i] == shots[i - 1] == shots[i - 2] and shots[i]:
            errs.append(f"visuals {i - 1}-{i + 1} are all {shots[i]} shots; vary the size")
            break
    return errs


def write_script(title: str, hook: str, transcript: str, claims: dict, states: dict,
                 cost_sink: list, cautions: list[str] | None = None) -> tuple[list[dict], list[str]]:
    import explainer_pipeline as ep
    ledger = "\n".join(f"{cid}: {text}" for cid, text in list(claims.items())[:60])
    pictures = "\n".join(f"{sid}: {s['visual']} (shows: {', '.join(s['objects'][:3])})"
                         for sid, s in states.items()) or "(none on disk: describe every picture as NEW: ...)"
    constraints = "\n".join(f"- {c}" for c in (cautions or [])) or "- (none)"
    user = (f'FILM TITLE: "{title}"\nFILM HOOK: {hook}\n\nEDITORIAL CONSTRAINTS from the film brief (binding):\n{constraints}\n\n'
            f'TRANSCRIPT (for tone and order only; cite claims, not this):\n'
            f'{transcript[:3500]}\n\nCLAIM LEDGER (the only facts you may state):\n{ledger}\n\n'
            f'AVAILABLE PICTURES:\n{pictures}\n\nWrite the Short.')
    errors: list[str] = []
    lines: list[dict] = []
    openings: list[str] = []
    for attempt in range(7):
        prompt = user + (f"\n\nYOUR PREVIOUS DRAFT FAILED THESE CHECKS; fix every one:\n- " + "\n- ".join(errors)
                         + f"\n\nPrevious draft: {json.dumps(lines)}" if errors else "")
        response = ep._claude().messages.create(model=ep.ANTHROPIC_MODEL, max_tokens=2600,
                                                system=_SCRIPT_SYSTEM,
                                                messages=[{"role": "user", "content": prompt}])
        cost_sink.append(ep._msg_cost(response.usage))
        parsed, _ = ep._parse_script_json(response.content[0].text)
        lines = [l for l in ((parsed or {}).get("lines") or []) if isinstance(l, dict)]
        openings = [str(o) for o in ((parsed or {}).get("openings") or [])]
        errors = _validate(lines, claims, states, openings)
        if not errors:
            return lines, openings
        print(f"  script draft {attempt + 1} failed: {'; '.join(errors)[:600]}")
    raise SystemExit("the Short script did not pass its checks after 7 drafts: " + "; ".join(errors))


def _narrate(text: str, out_path: str, voice: str, speed: float) -> float:
    import explainer_pipeline as ep
    resp = ep._openai().audio.speech.create(model=ep.TTS_MODEL, voice=voice, input=text,
                                            speed=speed, response_format="mp3")
    with open(out_path, "wb") as handle:
        handle.write(resp.content)
    return _duration(out_path)


def align_words(script_text: str, whisper: list) -> list:
    """Give every SCRIPT word a (start, end) from whisper's words, by sequence alignment.

    Whisper does not return the script verbatim: on the second cane toad build it merged
    "sugar cane" into "sugarcane" and dropped an initial "The", 66 words for 68, and chunking
    by running count then drifted across sentence ends ("swallow it Australia"). Aligning on
    normalised tokens with difflib pins each script word to its spoken moment; a script word
    with no match takes the midpoint of its neighbours. Captions then show the script's own
    words with whisper's timing.
    """
    import difflib
    norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())
    sw = script_text.split()
    a = [norm(w) for w in sw]
    b = [norm(w[0]) for w in whisper]
    timing: list = [None] * len(sw)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                timing[i1 + k] = (float(whisper[j1 + k][1]), float(whisper[j1 + k][2]))
        elif tag == "replace" and (i2 - i1) and (j2 - j1):
            s0, e0 = float(whisper[j1][1]), float(whisper[j2 - 1][2])
            n = i2 - i1
            for k in range(n):
                timing[i1 + k] = (s0 + (e0 - s0) * k / n, s0 + (e0 - s0) * (k + 1) / n)
    for i in range(len(sw)):
        if timing[i] is None:
            prev_end = next((timing[j][1] for j in range(i - 1, -1, -1) if timing[j]), 0.0)
            next_start = next((timing[j][0] for j in range(i + 1, len(sw)) if timing[j]), prev_end + 0.3)
            timing[i] = (prev_end, max(prev_end + 0.05, next_start))
    matched = sum(1 for t in timing if t) and sum(
        1 for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
        if tag == "equal" for _ in range(i2 - i1))
    return [(sw[i], timing[i][0], timing[i][1]) for i in range(len(sw))], matched / max(1, len(sw))


def _line_spans(lines: list[dict], words: list) -> list[tuple[float, float]]:
    """(start, end) per line from whisper word timings, matched by running word count."""
    counts = [len(str(l["text"]).split()) for l in lines]
    spans, cursor = [], 0
    for n in counts:
        chunk = words[cursor:cursor + n]
        cursor += n
        if chunk:
            spans.append((float(chunk[0][1]), float(chunk[-1][2])))
        else:
            spans.append((spans[-1][1] if spans else 0.0, spans[-1][1] if spans else 0.0))
    out = []
    for i, (s, e) in enumerate(spans):
        nxt = spans[i + 1][0] if i + 1 < len(spans) else e
        out.append((s if i else 0.0, max(e, nxt)))
    return out


def _visual_spans(lines: list[dict], words: list, until: float) -> list[dict]:
    """One timed span per visual, cut on clause boundaries of the whisper-aligned script.

    Each visual owns the audio from its clause's first word to the next visual's first word. A
    span shorter than MIN_PICTURE_SECONDS steals time from a long predecessor, or merges into the
    neighbour that introduces no subject word, keeping the noun-bearing visual and its label.
    """
    spans, cursor = [], 0
    for li, l in enumerate(lines):
        visuals = l.get("visuals") if isinstance(l.get("visuals"), list) else []
        if not visuals:
            cursor += len(str(l["text"]).split())
            continue
        for vi, v in enumerate(visuals):
            n = len(str(v.get("clause", "")).split())
            chunk = words[cursor:cursor + n]
            cursor += n
            start = float(chunk[0][1]) if chunk else (spans[-1]["end"] if spans else 0.0)
            end = float(chunk[-1][2]) if chunk else start
            spans.append({"start": start, "end": end, "line": li, "visual": vi, "v": v,
                          "subjects": _subject_words(str(v.get("clause", "")))})
    for i, sp in enumerate(spans):
        sp["start"] = 0.0 if i == 0 else sp["start"]
        sp["end"] = spans[i + 1]["start"] if i + 1 < len(spans) else until
    # A span that shows a subject for the first time (the beaver under "so beavers left") may
    # run short rather than vanish: the first v5 build merged it into the elk picture and the
    # beaver was never seen, the exact gap the outside review had raised.
    seen: set = set()
    for sp in spans:
        sp["introduces"] = bool(sp["subjects"] - seen)
        seen |= sp["subjects"]
    # Repair short spans. The comparison carries a tolerance: a span lifted to exactly
    # MIN_PICTURE_SECONDS by stealing from its neighbour measures a hair under it in floating
    # point, and the first v5 build spun on that for three hours at 99% CPU (2026-10-02).
    changed, rounds = True, 0
    while changed and len(spans) > 1 and rounds < 4 * len(spans) + 8:
        changed = False
        rounds += 1
        for i, sp in enumerate(spans):
            length = sp["end"] - sp["start"]
            floor = MIN_NEW_SUBJECT_SECONDS if sp.get("introduces") else MIN_PICTURE_SECONDS
            if length >= floor - 1e-3:
                continue
            deficit = MIN_PICTURE_SECONDS - length
            prev = spans[i - 1] if i > 0 else None
            nxt = spans[i + 1] if i + 1 < len(spans) else None
            # Steal first: a donor may give anything above its own floor; stealing the full
            # deficit is preferred, the floor's worth is enough for a subject-introducing span.
            def spare(d):
                return (d["end"] - d["start"]) - (MIN_NEW_SUBJECT_SECONDS if d.get("introduces") else MIN_PICTURE_SECONDS) if d else 0.0
            need_min = floor - length
            if prev and spare(prev) >= need_min:
                take = min(deficit, spare(prev))
                prev["end"] -= take
                sp["start"] = prev["end"]
            elif nxt and spare(nxt) >= need_min:
                take = min(deficit, spare(nxt))
                nxt["start"] += take
                sp["end"] = nxt["start"]
            else:
                # Merge: keep the span that introduces a subject; failing that, the one with any
                # subject; failing that, the earlier one.
                partner_index = i - 1 if prev is not None else i + 1
                partner = spans[partner_index]
                def rank(x):
                    return (bool(x.get("introduces")), bool(x["subjects"]))
                keep, drop = (sp, partner) if rank(sp) > rank(partner) else (partner, sp)
                keep["start"] = min(keep["start"], drop["start"])
                keep["end"] = max(keep["end"], drop["end"])
                keep["subjects"] = keep["subjects"] | drop["subjects"]
                keep["introduces"] = keep.get("introduces") or drop.get("introduces")
                spans.remove(drop)
            changed = True
            break
    return spans


def _film_image_fits(visual: dict, state: dict) -> bool:
    """A film image may stand in for a clause only if its own plan names the clause's subject:
    the vision check at phone size waved through a valley with a speck of a wolf for "Why kill
    wolves" (Yellowstone, 2026-10-02)."""
    wanted = _subject_words(str(visual.get("subject", "")) + " " + str(visual.get("clause", "")))
    if not wanted:
        return True
    named = _subject_words(" ".join([state.get("visual", "")] + list(state.get("objects") or [])))
    return bool(wanted & named)


def _picture_for(visual: dict, narration: str, states: dict, job: str, style_suffix: str,
                 cost_sink: list, setting: str = "", feedback: str = "", force_new: bool = False) -> str:
    import explainer_pipeline as ep
    pic = str(visual.get("picture") or "")
    clause = str(visual.get("clause") or narration)
    if not force_new and not feedback and not pic.startswith("NEW:") and pic in states \
            and states[pic].get("path") and _film_image_fits(visual, states[pic]):
        return states[pic]["path"]
    desc = pic[4:].strip() if pic.startswith("NEW:") else ""
    desc = (f"{visual.get('shot', 'medium')} shot of {visual.get('subject', '')}: {visual.get('action', '')}. "
            f"{desc}")
    desc = re.sub(r"\b(fading|faint|faded|ghostly|ghosted|disappearing|vanishing|silhouettes?|outlines?|"
                  r"shadowy|translucent|declining|spreading across)\b", "", desc, flags=re.I)
    desc = re.sub(r"\s+", " ", desc).strip()
    names_people = bool(re.search(r"\b(farmer|worker|hunter|people|man|woman|men|women|official|scientist|"
                                  r"entomologist|crowd|settler|rancher|person|handler|trapper)s?\b",
                                  f"{clause} {visual.get('subject', '')} {visual.get('action', '')}", re.I))
    out_dir = os.path.join(job, "short_images")
    os.makedirs(out_dir, exist_ok=True)
    import hashlib
    key = hashlib.sha1((desc + "|" + setting + "|" + feedback).encode()).hexdigest()[:10]
    out = os.path.join(out_dir, f"pic_{key}.jpg")
    if os.path.isfile(out):
        return out
    after = str(visual.get("state", "")).lower() == "after"
    prompt = (f"Vertical 9:16 illustrated frame for a phone screen. {desc}. The named subject is the "
              f"dominant element, large and in focus, never a faint outline or background figure. "
              + (f"Setting: {setting}; the clothing, buildings, tools and landscape must belong to "
                 f"that real place and period, nothing ancient, biblical, fantasy or symbolic. " if setting else "")
              + ("This is the AFTER state of a change: draw the end result plainly and at a scale a "
                 "viewer reads in one glance. " if after else "")
              + "Subject centred in the middle third of the frame, large and readable at phone size. "
              + "No silhouettes, outlines, ghosted figures, montages, maps or charts: real, solid, "
                "fully drawn animals and objects in full colour with ink contour, like every other subject."
              + ("" if names_people else " No people in this frame at all; the narration names none.")
              + " Do not add any animal, person, vehicle or object the description does not name."
              + (f" A PREVIOUS ATTEMPT WAS REJECTED because: {feedback}. Fix exactly that." if feedback else "")
              + style_suffix)
    ep.generate_image(prompt, out, cost_sink=cost_sink, size="1024x1536")
    return out


def _check_picture(path: str, visual: dict, narration: str, cost_sink: list, setting: str = "",
                   reference: str = "") -> dict:
    """A vision check that the frame demonstrates its CLAUSE (not the whole sentence), does not
    contradict the narration, fills the frame, and -- for a payoff -- shows the hook's place changed."""
    import base64
    import explainer_pipeline as ep
    clause = str(visual.get("clause") or narration)
    wanted = f"{visual.get('shot', 'medium')} shot: {visual.get('subject', '')} — {visual.get('action', '')}"
    data = base64.b64encode(open(path, "rb").read()).decode()
    content = []
    if reference and os.path.isfile(reference):
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(open(reference, "rb").read()).decode()}})
        content.append({"type": "text", "text": "The image above is the Short's OPENING frame. The image below must show the SAME PLACE visibly changed."})
    content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    content.append({"type": "text", "text":
        f"This frame was commissioned to show: {wanted}. The clause spoken over it is: \"{clause}\" (within the sentence \"{narration}\"). "
        "Judge the commissioned beat: does the image clearly show that subject doing that action as the DOMINANT element of the frame, "
        "large, solid and in focus (not a faint outline, silhouette, background figure or small detail while a landscape fills the picture), "
        "literal rather than symbolic, with no text or labels? Separately, does anything in the image CONTRADICT the narration? "
        + ("The change must be legible at phone size against the opening frame: answer ok=false if the place is not recognisably the same or the change is not visible. "
           if reference else "")
        + "Answer ok=true only if the beat is shown and nothing contradicts the narration; a still cannot show a change over time, so do not "
        "reject it for failing to show the change itself when it shows the end state. Also estimate what fraction of the frame's area the "
        "named subject occupies and return it as subject_area (0 to 1)."
        + (f" The setting must read as {setting}: answer ok=false if the clothing, architecture or landscape belong to another era or region." if setting else "")})
    try:
        r = ep._claude().messages.create(model=ep.ANTHROPIC_MODEL, max_tokens=140,
            system='Answer ONLY JSON: {"ok": true|false, "reason": "...", "subject_area": 0.0-1.0}',
            messages=[{"role": "user", "content": content}])
        cost_sink.append(ep._msg_cost(r.usage))
        parsed, _ = ep._parse_script_json(r.content[0].text)
        if isinstance(parsed, dict):
            try:
                area = float(parsed.get("subject_area", 1.0))
            except (TypeError, ValueError):
                area = 1.0
            if parsed.get("ok") is True and area < 0.2:
                parsed = dict(parsed, ok=False, reason=f"the subject fills only about {int(area * 100)}% of the frame; it must dominate")
        return parsed if isinstance(parsed, dict) else {"ok": None, "reason": "unparsed"}
    except Exception as exc:
        return {"ok": None, "reason": f"{type(exc).__name__}"}


def _slots(vspans: list[dict], pictures: list[str]) -> list[tuple]:
    """(start, end, path, framing, visual_index). One full-frame slot per visual; only a visual
    held past MAX_VISUAL_SECONDS gets a detail cut inside it. Cuts land on clause boundaries."""
    slots = []
    for i, (sp, pic) in enumerate(zip(vspans, pictures)):
        d = sp["end"] - sp["start"]
        if d > MAX_VISUAL_SECONDS:
            mid = sp["start"] + d / 2
            slots.append((sp["start"], mid, pic, "full", i))
            slots.append((mid, sp["end"], pic, "detail", i))
        else:
            slots.append((sp["start"], sp["end"], pic, "full", i))
    return slots


def _render_slots(slots, out_path, tmp):
    parts = []
    for i, (s_, e_, path, framing, _vi) in enumerate(slots):
        d = max(MIN_PICTURE_SECONDS * 0.8, e_ - s_)
        n = max(1, int(round(d * FPS)))
        with Image.open(path) as im:
            iw, ih = im.size
        cw = min(iw, int(ih * 9 / 16))
        if framing == "detail":
            crop_w, crop_h = int(cw * 0.62), int(ih * 0.62)
            crop = f"crop={crop_w}:{crop_h}:(iw-{crop_w})/2:ih*0.14"
            z = f"max(1.10-0.10*on/{n},1.0)"
        else:
            crop = f"crop={cw}:{ih}:(iw-{cw})/2:0"
            z = f"min(1+0.16*on/{n},1.16)" if i % 2 == 0 else f"max(1.16-0.16*on/{n},1.0)"
        vf = (f"{crop},scale=2160:3840,"
              f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS},format=yuv420p")
        clip = os.path.join(tmp, f"slot_{i:03d}.mp4")
        _run([_ffmpeg_bin(), "-v", "error", "-y", "-loop", "1", "-i", path, "-t", f"{d:.3f}",
              "-vf", vf, "-r", str(FPS), "-an", clip])
        parts.append(clip)
    with open(os.path.join(tmp, "concat.txt"), "w") as handle:
        handle.write("".join(f"file '{p}'\n" for p in parts))
    _run([_ffmpeg_bin(), "-v", "error", "-y", "-f", "concat", "-safe", "0",
          "-i", os.path.join(tmp, "concat.txt"), "-c", "copy", out_path])


def _caption_chunks(words: list, until: float, lines: list[dict] | None = None, size: int = 3):
    """Caption chunks of 2-4 words that never cross a clause or sentence boundary."""
    chunks, cursor = [], 0
    for l in (lines or [{"text": " ".join(w[0] for w in words)}]):
        clause_lengths = [len(c.split()) for c in _clauses(str(l["text"]))]
        for n in clause_lengths:
            clause_words = words[cursor:cursor + n]
            cursor += n
            if n <= 4:
                groups = [clause_words]
            else:
                per = 4 if n % 4 == 0 or n % 3 == 1 else 3
                groups = [clause_words[i:i + per] for i in range(0, n, per)]
                if len(groups) > 1 and len(groups[-1]) == 1:
                    groups[-2] = groups[-2] + groups[-1]
                    groups.pop()
            for g in groups:
                if g:
                    chunks.append([w for w in g])
    out = []
    for i, group in enumerate(chunks):
        start = float(group[0][1])
        end = float(chunks[i + 1][0][1]) if i + 1 < len(chunks) else until
        out.append((start, min(end, until), [w[0] for w in group]))
    return out


_EMPHASIS_WORDS = re.compile(r"^(kill|kills|killed|killing|poison|poisons|poisonous|deadly|die|died|dies|dead|"
                             r"fail|failed|fails|backfired|toxic|toxin|swallow|swallowed|disappear|disappeared|"
                             r"vanished|never|nothing|every|worse|wrong|mistake|purpose|evolving|evolved|survive|"
                             r"stripped|gone|suffer|suffered|unchecked|starved|lost)$", re.I)
_EMPHASIS_EXTRA: set = set()


def _emphasis(word: str) -> tuple:
    bare = word.strip(".,;:!?").lower()
    if bare in _EMPHASIS_EXTRA or _EMPHASIS_WORDS.match(bare) or re.search(r"\d", bare):
        return YELLOW
    return WHITE


def _headline_from(title: str) -> str:
    """The Short's title carries no number the Short does not explain: "The 101-Cane-Toad
    Mistake" reads The Cane Toad Mistake."""
    head = re.sub(r"\s+That\s.*$", "", title, flags=re.I)
    head = re.sub(r"\$?\d[\d,.]*[kKmMbB]?[-\s]*", "", head)
    return re.sub(r"\s+", " ", head.replace("-", " ")).strip().upper()


def audit_export(lines: list[dict], chunks: list, until: float, claims: dict) -> dict:
    """Checks on what was actually rendered: caption chunks never straddle a clause, the last
    caption is on screen to the end, and no number reaches the screen unless a cited claim states it."""
    norm = lambda t: re.sub(r"[^a-z0-9%$ ]", "", t.lower())
    line_words = [norm(str(l["text"])).split() for l in lines]
    straddle = []
    cursor, li = 0, 0
    for _, _, group in chunks:
        g = [norm(w) for w in group]
        while li < len(line_words) and cursor >= len(line_words[li]):
            li += 1; cursor = 0
        if li < len(line_words) and line_words[li][cursor:cursor + len(g)] == g:
            cursor += len(g)
        else:
            straddle.append(" ".join(group))
            cursor += len(g)
    last_shown_to_end = bool(chunks) and chunks[-1][1] >= until - 0.1
    unsupported = []
    for l in lines:
        for n in _numbers(str(l["text"])):
            if not any(n in _numbers(claims.get(c, "")) for c in (l.get("claim_ids") or [])):
                unsupported.append(n)
    return {"caption_chunks_within_lines": (len(straddle) == 0, straddle[:5]),
            "last_caption_to_end": (last_shown_to_end, round(chunks[-1][1], 2) if chunks else None),
            "numbers_supported": (len(unsupported) == 0, unsupported)}


def _loudnorm_linear(src: str, dst: str, target_i: float, target_tp: float, extra: str = "",
                     pre_filter: str = "", lra: int = 20) -> tuple[str, str]:
    """Two-pass EBU R128 normalisation with linear gain: a single fixed gain for the whole file.

    One-pass loudnorm is dynamic: it rides the gain, so in every pause of the voice it lifted
    the music bed to within 1 dB of the speech (measured on v3). Fixed gain keeps the bed where
    it was mixed. The first pass measures the SAME chain (pre-filter included), and the loudness
    range is left wide, because linear mode is refused when measured LRA exceeds the target.
    """
    pre = (pre_filter + ",") if pre_filter else ""
    probe = subprocess.run([_ffmpeg_bin(), "-i", src, "-af", pre + f"loudnorm=I={target_i}:TP={target_tp}:LRA={lra}:print_format=json",
                            "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"\{[\s\S]*\}", probe)
    stats = json.loads(m.group(0)) if m else {}
    names = {"input_i": "I", "input_tp": "TP", "input_lra": "LRA", "input_thresh": "thresh"}
    measured = ":".join(f"measured_{names[k]}={stats[k]}" for k in names if k in stats)
    offset = f":offset={stats['target_offset']}" if "target_offset" in stats else ""
    af = (f"loudnorm=I={target_i}:TP={target_tp}:LRA={lra}:{measured}{offset}:linear=true:print_format=json" if measured
          else f"loudnorm=I={target_i}:TP={target_tp}:LRA={lra}:print_format=json")
    log = subprocess.run([_ffmpeg_bin(), "-y", "-i", src, "-af", pre + af + (("," + extra) if extra else ""),
                          "-ar", "48000", dst], capture_output=True, text=True).stderr
    kind = re.search(r'"normalization_type"\s*:\s*"(\w+)"', log)
    return dst, (kind.group(1) if kind else "unknown")


def _silence_fraction(audio: str) -> float:
    out = subprocess.run([_ffmpeg_bin(), "-i", audio, "-af", "silencedetect=n=-38dB:d=0.2", "-f", "null", "-"],
                         capture_output=True, text=True)
    pairs = re.findall(r"silence_start: ([0-9.]+)[\s\S]*?silence_duration: ([0-9.]+)", out.stderr)
    total = sum(float(d) for st, d in pairs if float(st) > 0.05)
    return total / max(0.1, _duration(audio))


_STOP = set("the a an of to in on for and or but with that this it its they them their from after then while is "
            "are was were be been by as at into did do does so than too very not no yes who what why how when "
            "would could should still some many most all any anyone someone there here now".split())


def content_nouns(lines: list[dict]) -> set:
    """A rough count of the distinct things a script names: content words over three letters that
    are not verbs or adverbs by their ending. Used as a density measure."""
    out = set()
    for l in lines:
        for w in str(l["text"]).split():
            w = w.strip(".,?!;:").lower()
            if w in _STOP or len(w) <= 3 or not w.isalpha() or w.endswith(("ly", "ed", "ing")):
                continue
            out.add(w)
    return out


def readiness(lines, spans, vspans, slots, pictures, words_total, until, whisper_words,
              export: dict | None = None, audio: str = "") -> dict:
    hook = str(lines[0]["text"]).strip()
    nouns = content_nouns(lines)
    first_consequence = next((spans[i][0] for i, l in enumerate(lines) if l.get("role") == "consequence"), until)
    distinct_pics = len(set(pictures))
    silence = _silence_fraction(audio) if audio else 0.0
    labels = [str(sp["v"].get("label", "")) for sp in vspans]
    hook_pic = next((p for sp, p in zip(vspans, pictures) if lines[sp["line"]].get("role") == "hook"), "")
    payoff_pics = [p for sp, p in zip(vspans, pictures) if lines[sp["line"]].get("role") == "payoff"]
    # Subject words the script names that no surviving picture carries (span repair may merge
    # a short clause away; the validator only saw the writer's visuals).
    wanted_subjects = _subject_words(" ".join(str(l["text"]) for l in lines if l.get("role") != "cta"))
    shown_subjects: set = set()
    for sp in vspans:
        v = sp["v"]
        shown_subjects |= _subject_words(f"{v.get('clause', '')} {v.get('subject', '')} {v.get('action', '')}")
    unshown = wanted_subjects - shown_subjects

    checks = {
        "hook_is_question": (hook[-1:], hook.endswith("?")),
        "words_before_twist_le_12": (len(hook.split()), len(hook.split()) <= 12),
        "seconds_to_twist_le_4": (round(spans[0][1], 2), spans[0][1] <= 4.0),
        f"words_{WORDS_MIN}_to_{WORDS_MAX}": (words_total, WORDS_MIN <= words_total <= WORDS_MAX),
        "distinct_content_nouns_le_26": (len(nouns), len(nouns) <= 26),
        "first_consequence_le_10s": (round(first_consequence, 2), first_consequence <= 10.0),
        "spoken_cta": (str(lines[-1]["text"]).strip(), lines[-1].get("role") == "cta" and bool(CTA_TEXT.fullmatch(str(lines[-1]["text"]).strip()))),
        "silence_fraction_le_0_14": (round(silence, 3), silence <= 0.14),
        "distinct_visuals_ge_8": (len(vspans), len(vspans) >= 8),
        "visual_interval_le_2_5s": (round(until / max(1, len(vspans)), 2), until / max(1, len(vspans)) <= 2.5),
        "words_per_second_2_9_to_3_4": (round(words_total / until, 2), 2.9 <= words_total / until <= 3.4),
        "length_18_to_24s": (round(until, 1), 18 <= until <= 24),
        "caption_word_coverage_ge_0_9": (round(whisper_words, 2), whisper_words >= 0.9),
        "distinct_pictures_ge_7": (distinct_pics, distinct_pics >= 7),
        "labels_le_3_words": (labels, all(1 <= len(lb.split()) <= 3 for lb in labels)),
        "payoff_differs_from_hook": ([os.path.basename(p) for p in payoff_pics], bool(payoff_pics) and all(p != hook_pic for p in payoff_pics)),
        "every_subject_word_shown": (sorted(unshown), not unshown),
        "shot_variety": (sorted({str(sp["v"].get("shot", "")) for sp in vspans}),
                         {"close-up", "wide"} <= {str(sp["v"].get("shot", "")) for sp in vspans}),
    }
    for key, (ok, detail) in (export or {}).items():
        checks[key] = (detail, ok)
    return {"checks": {k: {"value": v, "pass": ok} for k, (v, ok) in checks.items()},
            "passed": all(ok for _, ok in checks.values()),
            "fails": [k for k, (_, ok) in checks.items() if not ok]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("--seconds", type=float, default=TARGET_SECONDS)
    ap.add_argument("--voice", default="echo")
    ap.add_argument("--speed", type=float, default=1.1)   # trimmed pauses already lift the pace; 1.2x ran 3.7 w/s
    ap.add_argument("--generate-images", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--music", default="tense", help="music_assets mood: tense|dramatic|energetic|upbeat|corporate|nostalgic")
    ap.add_argument("--music-lufs", type=float, default=-26.0,
                    help="bed loudness; the voice is -16, so -26 sits about 10 dB under it")
    ap.add_argument("--reuse-script", action="store_true",
                    help="keep the lines in short_package.json instead of writing new ones")
    args = ap.parse_args()
    job = os.path.abspath(args.job)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    import explainer_pipeline as ep
    import illustrated_story
    costs: list[float] = []
    title, hook, transcript, claims, states, setting, cautions = _load(job)
    have_images = any(s["path"] for s in states.values())
    print(f"{title} | {len(claims)} verified claims | {sum(1 for s in states.values() if s['path'])} film pictures on disk")

    prior = os.path.join(job, "short_package.json")
    openings: list[str] = []
    saved_lines = os.path.join(job, "short_lines.json")
    if args.reuse_script and (os.path.isfile(prior) or os.path.isfile(saved_lines)):
        # short_lines.json is written the moment a draft passes the validator; the package only
        # at the end. Prefer whichever is newer so a build that died after the writer reuses it.
        candidates = [f for f in (prior, saved_lines) if os.path.isfile(f)]
        source = max(candidates, key=os.path.getmtime)
        prev = json.load(open(source))
        lines, openings = prev["lines"], prev.get("openings") or []
        if any("visuals" not in l for l in lines if l.get("role") != "cta"):
            raise SystemExit("the saved script predates per-clause visuals; run without --reuse-script")
        print(f"reusing the {len(lines)} approved lines from {os.path.basename(source)}")
    else:
        lines, openings = write_script(title, hook, transcript, claims, states, costs, cautions)
        print("openings proposed:", " | ".join(openings))
        with open(os.path.join(job, "short_lines.json"), "w", encoding="utf-8") as handle:
            json.dump({"lines": lines, "openings": openings}, handle, indent=1)
    text = " ".join(str(l["text"]).strip() for l in lines)
    print("script:", text)
    for l in lines:
        for w in (l.get("emphasis") or []):
            _EMPHASIS_EXTRA.add(str(w).lower().strip(".,;:!?"))

    raw_audio = os.path.join(job, "short_audio_raw.mp3")
    audio = os.path.join(job, "short_audio.mp3")
    raw_len = _narrate(text, raw_audio, args.voice, args.speed)
    # The TTS pauses are true silence (-75 dB on decoded samples); the trim keys on -32 dB, where
    # a word's decay ends, and keeps 0.14 s, so a pause lands near 0.3 s. A 0.12 s lead-in, then
    # a 0.25 s fade ON the first word: compressed and gained, its breathy onset otherwise steps
    # from silence to full level in 20 ms and plays as a whoosh.
    _run([_ffmpeg_bin(), "-v", "error", "-y", "-i", raw_audio, "-af",
          "silenceremove=stop_periods=-1:stop_duration=0.2:stop_threshold=-32dB:stop_silence=0.14,"
          "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,"
          "adelay=120|120,afade=t=in:st=0.12:d=0.25",
          "-c:a", "libmp3lame", "-q:a", "2", audio])
    until = _duration(audio)
    print(f"narration {raw_len:.2f}s -> {until:.2f}s after trimming pauses")
    whisper = ep.transcribe_words(audio)
    words, matched_fraction = align_words(text, whisper) if whisper else ([], 0.0)
    spans = _line_spans(lines, words) if words else []
    if not spans:
        raise SystemExit("whisper returned no word timings; cannot sync captions")
    spans[-1] = (spans[-1][0], until)
    vspans = _visual_spans(lines, words, until)

    style = illustrated_story.visual_style_suffix(" Vertical portrait composition, subject in the middle third.")
    pictures, checks = [], []
    hook_path = ""
    for i, sp in enumerate(vspans):
        line = lines[sp["line"]]
        v = sp["v"]
        role = str(line.get("role"))
        narration = str(line["text"])
        # The hook, payoff and takeaway carry the Short; a film frame built for a 16:9
        # establishing shot puts the animal at the size of a speck. They are always drawn.
        force_new = role in ("hook", "payoff", "takeaway")
        path = _picture_for(v, narration, states, job, style, costs, setting, force_new=force_new)
        reference = hook_path if role == "payoff" else ""
        verdict = _check_picture(path, v, narration, costs, setting, reference=reference)
        for attempt in range(2):
            if verdict.get("ok") is not False:
                break
            reason = str(verdict.get("reason", ""))[:220]
            print(f"  redrawing visual {i + 1} [{v.get('label', '')}] ({attempt + 1}/2): {reason[:100]}")
            path = _picture_for(v, narration, states, job, style, costs, setting, feedback=reason, force_new=True)
            verdict = _check_picture(path, v, narration, costs, setting, reference=reference)
        if role == "hook" and not hook_path:
            hook_path = path
        pictures.append(path)
        checks.append(verdict)
    slots = _slots(vspans, pictures)

    out_path = args.out or os.path.join(job, "short.mp4")
    with tempfile.TemporaryDirectory(prefix="short_") as tmp:
        base = os.path.join(tmp, "base.mp4")
        _render_slots(slots, base, tmp)
        overlays = []
        probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
        # Beat labels: two words per visual, top of frame, first word yellow. They replace the
        # persistent headline, which told the viewer nothing about where they were in the chain.
        for i, sp in enumerate(vspans):
            label = str(sp["v"].get("label", "")).upper().split()
            if not label:
                continue
            png = os.path.join(tmp, f"label_{i:03d}.png")
            _text_png(png, [[(w, YELLOW if k == 0 else WHITE) for k, w in enumerate(label)]],
                      size=56, y=150, stroke=7, pill=True)
            overlays.append((png, sp["start"], sp["end"]))
        cap_y = H - SAFE_BOTTOM - 210
        chunks = _caption_chunks(words, until, lines)
        for i, (s, e, group) in enumerate(chunks):
            png = os.path.join(tmp, f"cap_{i:03d}.png")
            size = 84
            while size > 52 and probe.textlength(" ".join(w.upper() for w in group) + " ", font=_font(size)) > W - 150:
                size -= 6
            _text_png(png, [[(w.upper(), _emphasis(w)) for w in group]], size=size, y=cap_y, stroke=9, pill=True)
            overlays.append((png, s, e))
        # The invitation chip runs from the takeaway to the end; the spoken cta is four words.
        takeaway_at = spans[-2][0] if len(spans) >= 2 else spans[-1][0]
        end_png = os.path.join(tmp, "end.png")
        _text_png(end_png, [[("FULL", YELLOW), ("STORY", YELLOW), ("ON", WHITE), ("THE", WHITE), ("CHANNEL", WHITE)]],
                  size=46, y=cap_y - 125, stroke=6, pill=True)
        overlays.append((end_png, takeaway_at, until))

        music, music_credit = "", ""
        try:
            import music_assets
            music = music_assets.get_music_path(args.music) or ""
            music_credit = music_assets.MUSIC_CREDIT if music else ""
        except Exception:
            music = ""
        riser = os.path.join(tmp, "riser.wav")
        _run([_ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "anoisesrc=color=pink:d=1.3",
              "-f", "lavfi", "-i", "aevalsrc=0.5*sin(2*PI*t*(180+260*t)):d=1.3",
              "-filter_complex", "[0:a]highpass=f=220,volume=1.2[w];[1:a]volume=0.4[c];"
              "[w][c]amix=inputs=2:normalize=0,afade=t=in:st=0:d=1.2,volume=0.9,aresample=48000[o]",
              "-map", "[o]", riser])
        boom = os.path.join(tmp, "boom.wav")
        _run([_ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=58:d=0.7",
              "-f", "lavfi", "-i", "anoisesrc=color=brown:d=0.7",
              "-filter_complex", "[0:a]volume=1.6[s];[1:a]highpass=f=40,lowpass=f=200,volume=1.0[n];"
              "[s][n]amix=inputs=2:normalize=0,afade=t=out:st=0.12:d=0.55,volume=1.2,aresample=48000[o]",
              "-map", "[o]", boom])
        cta_at = takeaway_at
        voice_n, voice_mode = _loudnorm_linear(
            audio, os.path.join(tmp, "voice_n.wav"), -16.0, -1.5,
            pre_filter="acompressor=threshold=-24dB:ratio=3:attack=4:release=90:makeup=2:knee=6,"
                       "alimiter=limit=0.24:attack=3:release=40:level=false")
        music_mode = ""
        if music:
            music, music_mode = _loudnorm_linear(
                music, os.path.join(tmp, "music_n.wav"), args.music_lufs, -3.0,
                extra=f"atrim=0:{until:.3f},afade=t=in:st=0:d=0.4,"
                      f"afade=t=out:st={max(0, until - 0.8):.3f}:d=0.8")
        print(f"loudness normalisation: voice {voice_mode}" + (f", music {music_mode}" if music else ""))
        cmd = [_ffmpeg_bin(), "-v", "error", "-y", "-i", base, "-i", voice_n]
        if music:
            cmd += ["-i", music]
        cmd += ["-i", riser, "-i", boom]
        for png, _, _ in overlays:
            cmd += ["-i", png]
        first_png = (5 if music else 4)
        riser_idx, boom_idx = (3, 4) if music else (2, 3)
        chain, prev = [], "[0:v]"
        for k, (_, s, e) in enumerate(overlays):
            nxt = f"[v{k}]"
            chain.append(f"{prev}[{first_png + k}:v]overlay=0:0:enable='between(t,{s:.3f},{e:.3f})'{nxt}")
            prev = nxt
        fx = (f"[{riser_idx}:a]volume=0.22,adelay={int(max(0, cta_at - 1.3) * 1000)}|{int(max(0, cta_at - 1.3) * 1000)}[r];"
              f"[{boom_idx}:a]volume=0.35,adelay={int(cta_at * 1000)}|{int(cta_at * 1000)}[b]")
        inputs = "[1:a][2:a][r][b]" if music else "[1:a][r][b]"
        chain.append(fx + f";{inputs}amix=inputs={4 if music else 3}:duration=first:dropout_transition=0:normalize=0,"
                     f"alimiter=limit=0.92:level=false[a]")
        cmd += ["-filter_complex", ";".join(chain), "-map", prev, "-map", "[a]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                "-t", f"{until:.3f}", out_path]
        _run(cmd)

    words_total = len(text.split())
    export = audit_export(lines, chunks, until, claims)
    gate = readiness(lines, spans, vspans, slots, pictures, words_total, until, matched_fraction, export, audio)
    package = {
        "short": out_path, "seconds": round(until, 2), "title": (_headline_from(title).title() + " #Shorts")[:100],
        "lines": lines, "openings": openings, "music": music and os.path.basename(music),
        "music_credit": music_credit, "voice_norm": voice_mode, "music_norm": music_mode,
        "visuals": [{"line": sp["line"], "clause": sp["v"].get("clause"), "label": sp["v"].get("label"),
                     "shot": sp["v"].get("shot"), "state": sp["v"].get("state"), "start": round(sp["start"], 2),
                     "end": round(sp["end"], 2), "picture": os.path.basename(pictures[i]),
                     "check": checks[i]} for i, sp in enumerate(vspans)],
        "labels": [sp["v"].get("label") for sp in vspans],
        "slots": [{"start": round(a, 2), "end": round(b, 2), "picture": os.path.basename(p_), "framing": f_, "visual": vi}
                  for a, b, p_, f_, vi in slots],
        "captions": [{"start": round(s_, 2), "end": round(e_, 2), "text": " ".join(g)} for s_, e_, g in chunks],
        "words": words_total, "pictures": pictures, "picture_checks": checks,
        "readiness": gate, "cost_usd": round(sum(costs), 4), "voice": args.voice, "speed": args.speed,
        "source_title": title, "mode": "scripted_v5_per_clause",
    }
    with open(os.path.join(job, "short_package.json"), "w", encoding="utf-8") as handle:
        json.dump(package, handle, indent=1, ensure_ascii=False)
    print(json.dumps({"short": out_path, "seconds": package["seconds"], "words": words_total,
                      "visuals": len(vspans), "readiness_passed": gate["passed"], "fails": gate["fails"],
                      "cost_usd": package["cost_usd"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
