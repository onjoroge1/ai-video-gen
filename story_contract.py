"""The story-contract scripting lane (docs/STORY_CONTRACT_LANE.md, operator decision 2026-10-21).

A second lane BESIDE `unfolding_consequence`, not a retrofit of it. The compiled lane plans from
the evidence (claims -> factual functions -> roles -> narration) and its only repeatable role is
escalation, so the middle of every film became a list. This lane plans from the question:

    research dossier (existing) + human-material ask + claim kinds      [1 call]   evidence
    -> story contract                                                    [1-2 calls] contract
       ** operator approves the contract (contract.approved.json) **
    -> 3 openings x 2 endings, one pair selected                         [1 call]   openings
    -> one continuous narration + a sentence -> claim map                [1 call]   narration
    -> fresh review: blind reconstruction, then contract + evidence      [2 calls]  review
    -> at most 2 focused repairs for the WHOLE run (resume never resets)  [<=2 x 3]  repair
       ** operator approves the exact narration, bound by sha256 **
    -> segmenter: narration -> scenes, words unchanged                   [0-1 call] segment
    -> the existing claim ledger, storyboard, TTS, images, render

Every stage is checkpointed in <job>/story_contract_state.json, keyed on its inputs, so a resumed
run never re-buys a stage whose inputs have not changed. The repair budget is an append-only file
(story_contract_repairs.jsonl): a pass is written down BEFORE its call is made, so a crash, a
resume, a new reviewer or a re-approved contract cannot hand out a third.

Gate policy for scripts this lane produces lives in story_contract_policy (imported by the
pipeline). Nothing here changes the compiled lane.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field

import story_contract_policy as policy

LANE = policy.LANE
LANE_VERSION = "story_contract_v1"
MAX_REPAIRS = 2
WORDS_PER_SECOND = 2.588          # opening_turn's slowest measured rate; a planning figure only

# Claim kinds this lane adds (beside the ledger's own claim_kind, which roles still read).
CLAIM_KINDS = ("event", "model", "interpretation")
# A narration sentence may also be an illustration (an imagined situation framed aloud, e.g. "put
# yourself on a commercial boat") or framing (no factual content: "One fish.").
SENTENCE_KINDS = CLAIM_KINDS + ("illustration", "framing")
HUMAN_MATERIAL_TYPES = ("routine", "choice", "cost", "reward", "object", "quotation")

CONTRACT_PARTS = ("opening", "attempt", "complication", "development", "ending")

# The reviewer's rubric, 0-3 per item with a quotation from the narration as evidence. The scores
# describe defects; they never trigger a loop -- only factual blockers and editorial objectives do.
RUBRIC = (
    ("human_entry", "A documented person's want, action or reward gives the viewer a way in, and "
                    "the person returns where it matters (not a cameo)."),
    ("question_early", "The central question is clear early, in plain words a listener hears."),
    ("causal_development", "Each passage changes the situation and makes the next one matter; "
                           "the middle is cause and effect, not a list of facts."),
    ("complication_mechanism", "The complication is shown and the mechanism that produces it is "
                               "explained."),
    ("payoff", "The ending answers the question the opening asked, with the contract's answer."),
    ("evidence_discipline", "Causal links and qualifications hold; models are framed as models; "
                            "imagined situations are framed aloud and never leak into a fact about "
                            "a named person."),
    ("specificity", "Concrete, surprising details; every number serves the story."),
    ("voice", "It sounds spoken: short sentences, few numbers, sources named only where it matters, "
              "no rewind to history before the question; humour and personality come from the "
              "situation (credited when present, never required)."),
)
CONSEQUENCE_RUBRIC = ("consequence_chain", "A listener can name the past deliberate decision, its "
                      "documented consequence, and the dated sign it is still unfolding today; the "
                      "ending answers the question from today.")


def rubric_items(consequence_rule: bool = False) -> tuple:
    return RUBRIC + ((CONSEQUENCE_RUBRIC,) if consequence_rule else ())


RUBRIC_IDS = tuple(item for item, _ in RUBRIC) + (CONSEQUENCE_RUBRIC[0],)
# The scale. v2 scored 3 on every item under a bare 0-3 (2026-10-21), so the top no longer
# separated a good narration from a very good one: a 3 now has to name what is distinctive.
RUBRIC_SCALE = """0 = absent or wrong. 1 = present but generic or muddled. 2 = solid: does the job
clearly. 3 = distinctive: does something few narrations on this topic would -- the quote must show
it and the note must say what it is. Most competent narrations earn mostly 2s; give a 3 only with
that evidence, and a 1 or 0 wherever a listener would drift."""
MAX_EDITORIAL_OBJECTIVES = 3

STATE_FILE = "story_contract_state.json"
REPAIRS_FILE = "story_contract_repairs.jsonl"
CONTRACT_FILE = "contract.json"
CONTRACT_MD = "contract_for_approval.md"
CONTRACT_APPROVED = "contract.approved.json"
NARRATION_FILE = "narration.json"
NARRATION_MD = "narration_for_approval.md"
NARRATION_APPROVED = "narration.approved.json"
CANDIDATE_DIR = "story_contract_candidates"


# ── errors ────────────────────────────────────────────────────────────────────────────────────

class LaneStop(RuntimeError):
    """A deliberate stop for the operator. `status` goes into run_result.json."""
    status = "stopped"

    def __init__(self, message: str, *, path: str = "", details: dict | None = None):
        super().__init__(message)
        self.path = path
        self.details = details or {}


class ContractApprovalRequired(LaneStop):
    status = "awaiting_contract_approval"


class NarrationApprovalRequired(LaneStop):
    status = "awaiting_narration_approval"


class ContractInvalid(LaneStop):
    status = "contract_invalid"


class RepairBudgetExhausted(RuntimeError):
    pass


# ── small helpers ─────────────────────────────────────────────────────────────────────────────

def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ("" if value is None else str(value).strip())


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", _text(value).lower())).strip()


def _words(value) -> int:
    return len(_text(value).split())


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _write_json(path: str, value) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def _read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def parse_json_reply(text: str):
    """The first JSON object in a model reply (fences and prose around it tolerated)."""
    raw = _text(text)
    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if fenced:
        raw = fenced.group(1).strip()
    start = raw.find("{")
    if start < 0:
        raise ValueError("model reply has no JSON object")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[start:i + 1])
    raise ValueError("model reply has an unterminated JSON object (cut off at max_tokens?)")


def reply_text(response) -> str:
    """The text of a model reply. Newer Claude models put a thinking block before the text, so
    content[0] is not always the answer."""
    blocks = getattr(response, "content", None) or []
    parts = [getattr(b, "text", "") for b in blocks
             if getattr(b, "type", "text") == "text" and isinstance(getattr(b, "text", None), str)]
    return "".join(parts)


# ── the repair budget ─────────────────────────────────────────────────────────────────────────

class RepairBudget:
    """At most MAX_REPAIRS repair passes per job directory, counted from an append-only file.

    `consume` writes the pass down before the caller makes its model call, so a pass is counted
    even when the call or the process dies. Nothing reads the count from the stage cache: a resume,
    a changed reviewer model or a re-approved contract all see the same file.
    """

    def __init__(self, output_dir: str, maximum: int = MAX_REPAIRS):
        self.path = os.path.join(output_dir, REPAIRS_FILE)
        self.maximum = int(maximum)

    def entries(self) -> list[dict]:
        rows = []
        try:
            with open(self.path, encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except ValueError:
                            rows.append({"unreadable": True})   # still a spent pass
        except OSError:
            pass
        return rows

    def used(self) -> int:
        return len(self.entries())

    def remaining(self) -> int:
        return max(0, self.maximum - self.used())

    def consume(self, reason: str, *, from_version: int = 0, contract_sha256: str = "") -> int:
        used = self.used()
        if used >= self.maximum:
            raise RepairBudgetExhausted(
                f"repair budget spent: {used} of {self.maximum} passes already used in this job")
        row = {"pass": used + 1, "t": round(time.time(), 3), "reason": _text(reason)[:300],
               "from_version": int(from_version), "contract_sha256": contract_sha256}
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return used + 1


# ── checkpoint ────────────────────────────────────────────────────────────────────────────────

class LaneState:
    """<job>/story_contract_state.json: stage outputs keyed by an input hash, plus candidates."""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.path = os.path.join(output_dir, STATE_FILE)
        self.data = _read_json(self.path, None) or {
            "version": 1, "lane": LANE, "lane_version": LANE_VERSION, "stages": {},
            "candidates": [], "costs": []}

    def save(self) -> None:
        _write_json(self.path, self.data)

    def get(self, stage: str, key: str):
        row = (self.data.get("stages") or {}).get(stage)
        if isinstance(row, dict) and row.get("key") == key:
            return row.get("output")
        return None

    def put(self, stage: str, key: str, output, cost_usd: float = 0.0) -> None:
        self.data.setdefault("stages", {})[stage] = {
            "key": key, "output": output, "cost_usd": round(float(cost_usd or 0.0), 6),
            "t": round(time.time(), 3)}
        self.data.setdefault("costs", []).append({"stage": stage, "cost_usd": round(float(cost_usd or 0.0), 6)})
        self.save()

    def candidates(self, contract_sha: str) -> list[dict]:
        return [c for c in self.data.get("candidates") or [] if c.get("contract_sha256") == contract_sha]

    def add_candidate(self, candidate: dict) -> dict:
        allc = self.data.setdefault("candidates", [])
        candidate = dict(candidate, version=len(allc) + 1)
        allc.append(candidate)
        self.save()
        os.makedirs(os.path.join(self.output_dir, CANDIDATE_DIR), exist_ok=True)
        _write_json(os.path.join(self.output_dir, CANDIDATE_DIR, f"narration_v{candidate['version']}.json"),
                    candidate)
        return candidate

    def update_candidate(self, version: int, **fields) -> None:
        for cand in self.data.get("candidates") or []:
            if cand.get("version") == version:
                cand.update(fields)
                _write_json(os.path.join(self.output_dir, CANDIDATE_DIR, f"narration_v{version}.json"), cand)
        self.save()


# ── model calls ───────────────────────────────────────────────────────────────────────────────

def _provider() -> str:
    choice = _text(os.environ.get("STORY_CONTRACT_PROVIDER")).lower()
    if choice in ("anthropic", "openai"):
        return choice
    import script_provider
    return "openai" if script_provider.active_provider() == script_provider.OPENAI else "anthropic"


DEFAULT_MODELS = {
    # Writer and reviewer are different models and never share context (design, open question 3).
    "anthropic": {"writer": "claude-opus-5-5", "reviewer": "claude-sonnet-5-5"},
    "openai": {"writer": "gpt-5.5", "reviewer": "gpt-5.6-luna"},
}


def model_for(role: str, provider: str | None = None) -> str:
    provider = provider or _provider()
    env = _text(os.environ.get(f"STORY_CONTRACT_{role.upper()}_MODEL"))
    return env or DEFAULT_MODELS[provider]["reviewer" if role == "reviewer" else "writer"]


@dataclass
class Caller:
    """One JSON-returning model call per stage. Tests pass a fake with the same `call` signature."""
    provider: str = ""
    costs: list = field(default_factory=list)
    _clients: dict = field(default_factory=dict)

    def __post_init__(self):
        self.provider = self.provider or _provider()

    def _client(self):
        if self.provider in self._clients:
            return self._clients[self.provider]
        import usage_ledger
        if self.provider == "openai":
            from openai import OpenAI
            import script_provider
            client = script_provider.OpenAIScriptClient(OpenAI(api_key=os.environ["OPENAI_API_KEY"]))
        else:
            import anthropic
            workspace = _text(os.environ.get("ANTHROPIC_WORKSPACE_ID"))
            client = usage_ledger.meter(anthropic.Anthropic(
                api_key=os.environ["ANTHROPIC_API_KEY"], timeout=300.0,
                default_headers={"anthropic-workspace-id": workspace} if workspace else {},
                max_retries=int(os.environ.get("CLAUDE_MAX_RETRIES", "6"))))
        self._clients[self.provider] = client
        return client

    def _cost(self, model: str, usage) -> float:
        import usage_ledger
        if self.provider == "anthropic":
            return usage_ledger.anthropic_cost(model, usage)
        rate_in = float(os.environ.get("OPENAI_SCRIPT_RATE_IN", "5.0"))
        rate_out = float(os.environ.get("OPENAI_SCRIPT_RATE_OUT", "20.0"))
        return (getattr(usage, "input_tokens", 0) * rate_in
                + getattr(usage, "output_tokens", 0) * rate_out) / 1_000_000

    def text(self, *, role: str, stage: str, system: str, user: str, max_tokens: int = 4000):
        """(raw text, cost_usd): for judges that parse their own reply (topic_fit.screen)."""
        import usage_ledger
        model = model_for(role, self.provider)
        response = self._client().messages.create(model=model, max_tokens=max_tokens, system=system,
                                                  messages=[{"role": "user", "content": user}])
        cost = self._cost(model, response.usage)
        if self.provider == "openai":
            usage_ledger.record("openai", "message", cost, model=model, caller=f"story_contract.{stage}",
                                usage=response.usage)
        self.costs.append({"stage": stage, "model": model, "cost_usd": round(cost, 6)})
        return reply_text(response), cost

    def call(self, *, role: str, stage: str, system: str, user: str, max_tokens: int = 8000):
        """(parsed JSON, cost_usd). One retry when the reply is not parseable JSON.

        max_tokens is generous on purpose: on newer Claude models it also pays for the thinking
        block, and a reply cut off at the cap is unparseable (review B on sonnet, 2026-10-21)."""
        import usage_ledger
        model = model_for(role, self.provider)
        last_error = None
        total = 0.0
        for attempt in range(2):
            prompt = user if attempt == 0 else (
                user + "\n\nYour previous reply was not one valid JSON object ("
                + str(last_error)[:200] + "). Reply with the JSON object only.")
            response = self._client().messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": prompt}])
            cost = self._cost(model, response.usage)
            total += cost
            if self.provider == "openai":   # the Anthropic client is metered already
                usage_ledger.record("openai", "message", cost, model=model,
                                    caller=f"story_contract.{stage}", usage=response.usage)
            try:
                data = parse_json_reply(reply_text(response))
                self.costs.append({"stage": stage, "model": model, "cost_usd": round(total, 6)})
                return data, total
            except ValueError as exc:
                last_error = exc
        self.costs.append({"stage": stage, "model": model, "cost_usd": round(total, 6)})
        raise ValueError(f"{stage}: {model} returned no parseable JSON twice ({last_error})")


# ── evidence: claim kinds and the human-material ask ──────────────────────────────────────────

_FALLBACK_KIND = {"event": "event", "context": "event", "outcome": "event",
                  "mechanism": "interpretation", "general_principle": "interpretation"}


def _claims(dossier: dict) -> list[dict]:
    return [c for c in (dossier or {}).get("claims") or [] if isinstance(c, dict) and c.get("claim_id")]


def claim_table(dossier: dict, *, quotes: bool = True, ids: set | None = None, limit: int = 320) -> str:
    rows = []
    for c in _claims(dossier):
        if ids is not None and c["claim_id"] not in ids:
            continue
        host = re.sub(r"^https?://(www\.)?", "", _text(c.get("source_url"))).split("/")[0]
        kind = c.get("story_kind") or c.get("claim_kind") or ""
        row = f"{c['claim_id']} [{kind}; {host}] {_text(c.get('claim'))}"
        if quotes:
            row += f'\n    quote: "{_text(c.get("support_quote"))[:limit]}"'
        rows.append(row)
    return "\n".join(rows)


EVIDENCE_SYSTEM = """You prepare research for a documentary narrator. You never invent facts: \
every item you return cites claim IDs from the list you are given, exactly as written."""


def evidence_prompt(question: str, dossier: dict, pack: dict | None = None) -> str:
    hints = ""
    if pack:
        bits = [f"{k}: {_text(pack.get(k))}" for k in ("angle", "human", "decision", "current_type")
                if _text(pack.get(k))]
        if bits:
            hints = "Operator source-pack notes (leads, not evidence):\n" + "\n".join(bits) + "\n\n"
    return f"""Video question: {question}

{hints}Claims (id [ledger kind; source] claim, then the verbatim source quote):
{claim_table(dossier)}

Two jobs.

1. KIND for every claim, from what the quote supports:
   - "event": something documented as having happened or being the case.
   - "model": what a study, model or projection predicts under its assumptions.
   - "interpretation": an expert's or agency's reading, explanation or judgement.

2. HUMAN MATERIAL. Find documented details about real people that a story could be built on: a
   routine, a choice, a cost, a reward, a revealing object, or a quotation with personality. Rank
   them. A detail ranks highest when it does two jobs at once -- it helps the viewer understand the
   PERSON and the larger PROBLEM (example of the kind of thing: a record-setting hunter's full
   freezer is both his reward and the plan working). Expert commentary alone ("X called them
   voracious") ranks low: it explains the problem but gives the viewer no one to follow. Cite only
   claim IDs that support the detail. If a promising lead has no supporting claim, include it with
   "claim_ids": [] so it is reported as an evidence gap.

Reply with JSON only:
{{"claim_kinds": {{"c01": "event", ...}},
  "human_material": [
    {{"type": "routine|choice|cost|reward|object|quotation", "person": "...", "detail": "...",
      "claim_ids": ["c.."], "serves_person": "what it shows about them",
      "serves_problem": "what it shows about the larger problem", "does_both": true}}
  ]}}"""


def normalize_evidence(raw: dict, dossier: dict) -> dict:
    known = {c["claim_id"]: c for c in _claims(dossier)}
    kinds_in = (raw or {}).get("claim_kinds") or {}
    kinds, errors = {}, []
    for cid, claim in known.items():
        kind = _text(kinds_in.get(cid)).lower()
        if kind not in CLAIM_KINDS:
            if kind:
                errors.append(f"{cid}: kind {kind!r} is not one of {CLAIM_KINDS}")
            kind = _FALLBACK_KIND.get(_text(claim.get("claim_kind")).lower(), "event")
            kinds[cid] = {"kind": kind, "source": "fallback"}
        else:
            kinds[cid] = {"kind": kind, "source": "model"}
    material, gaps = [], []
    for item in (raw or {}).get("human_material") or []:
        if not isinstance(item, dict):
            continue
        cited = [c for c in item.get("claim_ids") or [] if c in known]
        unknown = [c for c in item.get("claim_ids") or [] if c not in known]
        entry = {
            "type": _text(item.get("type")).lower() if _text(item.get("type")).lower() in HUMAN_MATERIAL_TYPES else "quotation",
            "person": _text(item.get("person")), "detail": _text(item.get("detail")),
            "claim_ids": cited, "serves_person": _text(item.get("serves_person")),
            "serves_problem": _text(item.get("serves_problem")),
            "does_both": bool(item.get("does_both")) and bool(_text(item.get("serves_person")))
                         and bool(_text(item.get("serves_problem"))),
        }
        if unknown:
            entry["unknown_claim_ids"] = unknown
        (material if cited else gaps).append(entry)
    material.sort(key=lambda m: (not m["does_both"], -len(m["claim_ids"])))
    return {"claim_kinds": kinds, "human_material": material, "evidence_gaps": gaps, "errors": errors}


def apply_claim_kinds(dossier: dict, evidence: dict) -> dict:
    """The dossier with `story_kind` on every claim (the ledger's claim_kind is left alone)."""
    out = json.loads(json.dumps(dossier))
    kinds = (evidence or {}).get("claim_kinds") or {}
    for c in _claims(out):
        row = kinds.get(c["claim_id"]) or {}
        c["story_kind"] = row.get("kind") or _FALLBACK_KIND.get(_text(c.get("claim_kind")).lower(), "event")
    return out


# ── the World consequence model (operator 2026-10-15; lane rule 2026-10-21) ───────────────────
#
# A World film tells a past DELIBERATE decision or fix -- an animal introduced, removed or
# targeted; an invention or product adopted; a rule enforced -- whose documented consequence is
# STILL unfolding today, told from today. Accidents with no deliberate fix behind them are out, and
# so is a story that ends in the past. Lionfish v2 failed it ("not a consequence video"): its
# central consequence was a bioeconomic MODEL result and its question a forward hypothetical.
WORLD_CHANNELS = ("", "world")
DECISION_KINDS = ("animal_introduced", "animal_removed", "animal_targeted", "invention_adopted",
                  "product_adopted", "rule_enforced")
CONSEQUENCE_LEDGER_KINDS = ("event", "outcome")      # the ledger's claim_kind
PRESENT_YEARS = 5                                    # "today" = a claim dated within five years
_HYPOTHETICAL_RE = re.compile(r"^\s*(what (happens|would happen|will happen|could happen|if)|"
                              r"what'?s next|imagine|suppose|could|would|will)\b|\bwhat if\b|"
                              r"\bwhat happens (when|if)\b", re.I)
_YEAR4 = re.compile(r"\b(1[5-9]\d\d|20\d\d)s?\b")   # "1985", "1980s"


def consequence_rule_applies(topic_channel: str = "") -> bool:
    return _text(topic_channel).lower() in WORLD_CHANNELS


def documented_consequence_claim(claim: dict) -> bool:
    """A claim that can BE a consequence: documented (story_kind event), and in the ledger an event
    or an outcome. A model or an interpretation may explain the mechanism, never be the
    consequence."""
    if not isinstance(claim, dict):
        return False
    story = _text(claim.get("story_kind")).lower()
    if story and story != "event":
        return False
    return _text(claim.get("claim_kind")).lower() in CONSEQUENCE_LEDGER_KINDS


def _years(*texts) -> list[int]:
    return [int(y) for t in texts for y in _YEAR4.findall(_text(t))]


def is_hypothetical_question(question: str) -> bool:
    return bool(_HYPOTHETICAL_RE.search(_text(question)))


def validate_consequence_model(contract: dict, claims: dict, this_year: int | None = None) -> list[dict]:
    """decision -> documented consequence -> still unfolding today, each bound to claims."""
    this_year = this_year or int(time.strftime("%Y"))
    errors = []

    def err(code, message):
        errors.append({"code": code, "message": message})

    decision = contract.get("decision") if isinstance(contract.get("decision"), dict) else {}
    d_ids = [c for c in decision.get("claim_ids") or [] if c in claims]
    if not _text(decision.get("what")) or not d_ids:
        err("DECISION_MISSING", "name the past deliberate decision or fix, with the claims that document it")
    kind = _text(decision.get("kind")).lower()
    if kind not in DECISION_KINDS:
        err("DECISION_NOT_DELIBERATE", f"decision.kind {kind or '(none)'!r} is not a deliberate fix "
            f"({', '.join(DECISION_KINDS)}); an accident with no fix behind it is not a World film")
    if not _years(decision.get("when"), decision.get("what")):
        err("DECISION_UNDATED", "the decision needs a date (decision.when, a year)")

    cons = contract.get("consequence") if isinstance(contract.get("consequence"), dict) else {}
    c_ids = [c for c in cons.get("claim_ids") or [] if c in claims]
    if not _text(cons.get("what")) or not c_ids:
        err("CONSEQUENCE_MISSING", "name the documented consequence of the decision, with its claims")
    elif not any(documented_consequence_claim(claims[c]) for c in c_ids):
        kinds = ", ".join(f"{c} ({_text(claims[c].get('story_kind')) or _text(claims[c].get('claim_kind'))})" for c in c_ids)
        err("CONSEQUENCE_NOT_DOCUMENTED", f"the consequence rests only on {kinds}: a model result or an "
            "interpretation may explain the mechanism but may not BE the consequence; cite a documented "
            "event or outcome")

    now = contract.get("still_unfolding") if isinstance(contract.get("still_unfolding"), dict) else {}
    n_ids = [c for c in now.get("claim_ids") or [] if c in claims]
    recent = [c for c in n_ids if documented_consequence_claim(claims[c]) and any(
        y >= this_year - PRESENT_YEARS for y in _years(claims[c].get("claim"), claims[c].get("support_quote")))]
    if not _text(now.get("what")) or not n_ids:
        err("STILL_UNFOLDING_MISSING", "name the documented, dated sign that the consequence is still unfolding today")
    elif not recent:
        err("STILL_UNFOLDING_NOT_PRESENT", f"no cited claim is a documented event dated within {PRESENT_YEARS} "
            f"years ({this_year - PRESENT_YEARS} or later): the film must be told from today")

    question = _text(contract.get("central_question"))
    if is_hypothetical_question(question):
        err("QUESTION_HYPOTHETICAL", f"{question!r} is a forward hypothetical; ask about the decision's consequence")
    cands = [c for c in contract.get("question_candidates") or [] if isinstance(c, dict)]
    try:
        chosen = cands[int(contract.get("chosen"))]
    except (TypeError, ValueError, IndexError):
        chosen = {}
    if chosen and (chosen.get("names_decision") is False or chosen.get("asks_consequence") is False):
        err("QUESTION_NOT_CONSEQUENCE", "the chosen question must name (or clearly imply) the decision and ask about its consequence")
    screen = chosen.get("topic_fit") if isinstance(chosen.get("topic_fit"), dict) else {}
    if screen.get("screened") and (screen.get("verdict") == "no_story" or
                                   (screen.get("channel") and screen.get("channel") != "world")):
        err("QUESTION_NOT_WORLD", f"topic_fit screens the chosen question as {screen.get('verdict')} "
            f"({screen.get('channel') or 'no channel'}): {screen.get('reason')}")
    return errors


# ── the contract ──────────────────────────────────────────────────────────────────────────────

CONTRACT_SYSTEM = """You are a documentary story editor. You plan a story around ONE question a \
viewer would want answered, and you choose the question and its answer together, from evidence \
you are given. You never invent facts: every element cites claim IDs from the list."""


def _content_words(text: str) -> set:
    stop = {"the", "a", "an", "of", "to", "in", "is", "are", "and", "or", "it", "its", "them", "they",
            "why", "what", "how", "when", "does", "do", "can", "at", "on", "for", "people", "this", "that"}
    return {w for w in _norm(text).split() if w not in stop and len(w) > 2}


def question_overlap(a: str, b: str) -> float:
    wa, wb = _content_words(a), _content_words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


_NO_FIX_PENALTY = re.compile(r"(ends? on (a |an )?(failure|constraint|limit|dispute)|(no|little|without|lacks?) "
                             r"(real |clear )?resolution|unresolved|no (happy|clear) ending|bleak|"
                             r"depressing|without a fix|rather than an answer)", re.I)


def question_choice_penalties(contract: dict) -> list[dict]:
    """A candidate marked down for ending on an honest partial answer (operator 2026-10-21): an
    error, so the contract goes back once with the rule restated."""
    out = []
    for i, c in enumerate(contract.get("question_candidates") or []):
        if not isinstance(c, dict):
            continue
        scores = c.get("scores") or {}
        if _NO_FIX_PENALTY.search(_text(c.get("reason"))) and int(scores.get("deliverable") or 0) < 3:
            out.append({"code": "QUESTION_PENALISED_FOR_NO_FIX",
                        "message": f"candidate {i + 1} ({_text(c.get('question'))!r}) is marked down because "
                                   "its ending is a constraint or a partial answer; that is a valid ending. "
                                   "Re-score it on curiosity, support and deliverable alone"})
    return out


def validate_question_choice(contract: dict, commission: str, known) -> list[dict]:
    """Three scored candidates, the chosen one is the central question, and it is not the
    commission title restated."""
    errors = []
    cands = [c for c in contract.get("question_candidates") or [] if isinstance(c, dict) and _text(c.get("question"))]
    if len(cands) != 3:
        return [{"code": "QUESTION_CANDIDATES", "message": f"propose exactly three candidate questions (got {len(cands)})"}]
    try:
        chosen = int(contract.get("chosen"))
    except (TypeError, ValueError):
        chosen = -1
    if not 0 <= chosen < 3:
        errors.append({"code": "QUESTION_NOT_CHOSEN", "message": "chosen must be the index (0-2) of a candidate"})
    elif _norm(cands[chosen]["question"]) != _norm(contract.get("central_question")):
        errors.append({"code": "QUESTION_NOT_CHOSEN", "message": "central_question is not the chosen candidate's question"})
    for i, c in enumerate(cands):
        if not [x for x in c.get("claim_ids") or [] if x in set(known or [])]:
            errors.append({"code": "QUESTION_UNSUPPORTED", "message": f"candidate {i} cites no known claim"})
    if commission and question_overlap(contract.get("central_question"), commission) >= 0.6:
        errors.append({"code": "QUESTION_IS_TITLE", "message": "the central question restates the commission "
                       "title; choose the question the evidence makes interesting"})
    return errors


WORLD_MODEL_PROMPT = """THIS IS A WORLD FILM. It tells ONE past DELIBERATE decision or fix -- an animal
introduced, removed or targeted; an invention or product adopted; or a rule enforced -- and its
documented consequence, which is STILL unfolding today, told from today. Accidents with no deliberate
fix behind them are out, and so is a story that ends in the past.
- decision: what was decided, by whom, when (a year), its kind, and the claims documenting it.
- consequence: what it documentably caused. Cite at least one claim of kind event that the ledger
  marks event or outcome. A model's projection or an expert's interpretation may explain the
  mechanism but may NOT be the consequence.
- still_unfolding: the dated, documented present-day sign that it continues (a claim dated within
  the last five years).
- Every question candidate must name, or clearly imply, the decision and ask about its consequence.
  Never a forward hypothetical ("what happens when/if ...", "what would happen ...").
- The ending answers the consequence question from today."""


def contract_prompt(question: str, dossier: dict, evidence: dict, duration_sec: int,
                    direction: str = "", errors: list | None = None, consequence_rule: bool = False) -> str:
    material = json.dumps((evidence or {}).get("human_material") or [], ensure_ascii=False, indent=1)
    gaps = json.dumps((evidence or {}).get("evidence_gaps") or [], ensure_ascii=False)
    fix = ""
    if errors:
        fix = ("\n\nYour previous contract failed these checks; fix every one:\n- "
               + "\n- ".join(f"{e['code']}: {e['message']}" for e in errors))
    return f"""Commission: {question}
Runtime: about {duration_sec} seconds of narration (~{int(duration_sec * WORDS_PER_SECOND)} words).
{('Operator direction: ' + direction.strip()) if _text(direction) else ''}

Claims (id [kind; source] claim, then the verbatim quote):
{claim_table(dossier)}

Human material, ranked (prefer a detail that serves both the person and the problem):
{material}

Leads without a supporting claim (you may NOT state these as fact): {gaps}

{(WORLD_MODEL_PROMPT + chr(10) + chr(10)) if consequence_rule else ''}Write the story contract.
- question_candidates: FIRST propose three genuinely different central questions. Do not take the
  commission's wording as the question: it names the topic, and its own question is often one the
  viewer can already answer from the title. Look in the evidence for the surprise -- a paradox, a
  consequence nobody intended, a cost hidden inside a success -- and ask about that. For each
  candidate give: the question; what the title already gives away and what it does not
  (curiosity_gap); the claim IDs that support it; the answer the ending could deliver from the
  evidence; and scores 0-3 for curiosity (a gap the title does not already close), support (the
  evidence establishes the pieces) and deliverable (an ending the evidence can actually give).
  An honest partial answer, a named constraint, or a cost the evidence shows is a valid ending: do
  not mark a question down because its answer is not a fix or a happy resolution.
  Then choose one (chosen: its index, 0-2) and say why.
- central_question: the chosen candidate's question, word for word. It must be one the evidence
  can actually answer.
- ending_answer: the answer the ending delivers, in one or two sentences.
- human_perspective: a documented person the viewer follows, their want, action and reward, each
  with the claim IDs that support it (leave an element empty rather than unsupported).
- reasonable_attempt: what people tried, and why it made sense at the time.
- complication: what went wrong or turned out stranger, and the mechanism that produces it.
- developments: as many as the story needs, in order. For EACH: what happens, what it CHANGES
  (in the situation, the stakes or what the viewer understands), and why the next development
  matters because of it. If a development cannot name what it changes, it is a list item: cut it
  or merge it.
- recurring_image: an optional object or image planted early and called back later; name the part
  where it is planted and where it returns ("opening", "attempt", "complication", "development_N",
  "ending"). null if none.
- forbidden_claims: claims this film must NOT make even though they would be tempting (unsupported
  expansions, e.g. a named person's income, or a cause the sources do not establish).
- tangents_left_out: true and striking material deliberately left out, and why.
- evidence_gaps: anything the story wants that the claims do not support.{fix}

Reply with JSON only:
{{"topic": "...",
  "question_candidates": [{{"question": "...", "curiosity_gap": "...", "claim_ids": [],
                            "ending_answer": "...", "scores": {{"curiosity": 0, "support": 0, "deliverable": 0}},
                            "names_decision": true, "asks_consequence": true,
                            "reason": "..."}}, ...3],
  "chosen": 0, "chosen_reason": "...",
  "central_question": "...", "ending_answer": "...",
  "decision": {{"what": "...", "who": "...", "when": "year", "kind": "{'|'.join(DECISION_KINDS)}", "claim_ids": []}},
  "consequence": {{"what": "...", "claim_ids": []}},
  "still_unfolding": {{"what": "...", "as_of": "year", "claim_ids": []}},
  "human_perspective": {{"person": "...", "want": "...", "action": "...", "reward": "...",
                         "claim_ids": {{"want": [], "action": [], "reward": []}}}},
  "reasonable_attempt": {{"what": "...", "why_it_made_sense": "...", "claim_ids": []}},
  "complication": {{"what": "...", "mechanism": "...", "claim_ids": []}},
  "developments": [{{"what_happens": "...", "what_it_changes": "...", "why_next_matters": "...",
                     "claim_ids": []}}],
  "recurring_image": {{"image": "...", "planted_in": "opening", "callback_in": "ending"}},
  "forbidden_claims": ["..."],
  "tangents_left_out": [{{"tangent": "...", "why": "..."}}],
  "evidence_gaps": ["..."]}}"""


def _part_order(contract: dict) -> list[str]:
    n = len(contract.get("developments") or [])
    return ["opening", "attempt", "complication"] + [f"development_{i}" for i in range(1, n + 1)] + ["ending"]


def contract_claim_ids(contract: dict) -> list[str]:
    ids = []
    hp = (contract.get("human_perspective") or {}).get("claim_ids") or {}
    for part in ("want", "action", "reward"):
        ids += list(hp.get(part) or []) if isinstance(hp, dict) else []
    ids += list((contract.get("reasonable_attempt") or {}).get("claim_ids") or [])
    ids += list((contract.get("complication") or {}).get("claim_ids") or [])
    for dev in contract.get("developments") or []:
        ids += list((dev or {}).get("claim_ids") or [])
    return list(dict.fromkeys(_text(i) for i in ids if _text(i)))


def validate_contract(contract: dict, known_claims, commission: str = "",
                      consequence_rule: bool = False) -> dict:
    """Deterministic checks on a story contract. {'passed', 'errors', 'warnings'}.

    known_claims: claim IDs, or {id: claim} (needed for the World consequence rule's kinds)."""
    claims = known_claims if isinstance(known_claims, dict) else {}
    known = set(known_claims or [])
    errors, warnings = [], []

    def err(code, message):
        errors.append({"code": code, "message": message})

    def warn(code, message):
        warnings.append({"code": code, "message": message})

    if not isinstance(contract, dict):
        return {"passed": False, "errors": [{"code": "NOT_A_CONTRACT", "message": "contract is not an object"}],
                "warnings": []}
    if not _text(contract.get("central_question")):
        err("MISSING_QUESTION", "the contract names no central question")
    if not _text(contract.get("ending_answer")):
        err("MISSING_ANSWER", "the contract names no answer for the ending to deliver")
    elif _norm(contract.get("ending_answer")) == _norm(contract.get("central_question")):
        err("ANSWER_RESTATES_QUESTION", "the ending answer only restates the question")

    hp = contract.get("human_perspective") or {}
    hp_ids = hp.get("claim_ids") if isinstance(hp.get("claim_ids"), dict) else {}
    if not _text(hp.get("person")):
        err("HUMAN_PERSPECTIVE_MISSING", "no documented person for the viewer to follow")
    stated = [p for p in ("want", "action", "reward") if _text(hp.get(p))]
    if _text(hp.get("person")) and not stated:
        err("HUMAN_PERSPECTIVE_MISSING", "the person has no want, action or reward")
    for part in stated:
        if not [c for c in hp_ids.get(part) or [] if _text(c)]:
            err("HUMAN_CLAIM_MISSING", f"human_perspective.{part} cites no claim")

    attempt = contract.get("reasonable_attempt") or {}
    if not _text(attempt.get("what")) or not _text(attempt.get("why_it_made_sense")):
        err("ATTEMPT_MISSING", "the reasonable attempt or why it made sense is missing")
    comp = contract.get("complication") or {}
    if not _text(comp.get("what")) or not _text(comp.get("mechanism")):
        err("COMPLICATION_MISSING", "the complication or the mechanism that produces it is missing")
    elif not [c for c in comp.get("claim_ids") or [] if _text(c)]:
        err("COMPLICATION_UNSUPPORTED", "the complication cites no claim")

    devs = contract.get("developments")
    if not isinstance(devs, list) or not devs:
        err("NO_DEVELOPMENTS", "the contract has no developments")
        devs = []
    seen_changes: dict[str, int] = {}
    for i, dev in enumerate(devs, 1):
        dev = dev if isinstance(dev, dict) else {}
        happens, changes = _text(dev.get("what_happens")), _text(dev.get("what_it_changes"))
        if not happens:
            err("DEVELOPMENT_EMPTY", f"development {i} says nothing happens")
        if not changes or _words(changes) < 3:
            err("DEVELOPMENT_NO_CHANGE", f"development {i} does not name what it changes; a "
                                         "development without a change is a list item: cut or merge it")
        elif _norm(changes) == _norm(happens):
            err("DEVELOPMENT_NO_CHANGE", f"development {i} restates what happens as its change")
        elif _norm(changes) in seen_changes:
            err("DEVELOPMENT_REPEATS_CHANGE", f"development {i} changes the same thing as development "
                                              f"{seen_changes[_norm(changes)]}: merge them")
        else:
            seen_changes[_norm(changes)] = i
        if i < len(devs) and not _text(dev.get("why_next_matters")):
            err("DEVELOPMENT_NO_LINK", f"development {i} does not say why the next one matters")
        if not [c for c in dev.get("claim_ids") or [] if _text(c)]:
            err("DEVELOPMENT_UNSUPPORTED", f"development {i} cites no claim")

    image = contract.get("recurring_image")
    if isinstance(image, dict) and _text(image.get("image")):
        order = _part_order(contract)
        planted, back = _text(image.get("planted_in")), _text(image.get("callback_in"))
        if planted not in order or back not in order:
            err("RECURRING_IMAGE_PARTS", f"recurring image parts must be among {order}")
        elif order.index(back) <= order.index(planted):
            err("CALLBACK_BEFORE_PLANT", f"the recurring image returns in {back} but is planted in {planted}")

    if not [x for x in contract.get("forbidden_claims") or [] if _text(x)]:
        err("FORBIDDEN_CLAIMS_MISSING", "list the claims this film must not make")
    if not [x for x in contract.get("tangents_left_out") or [] if x]:
        warn("NO_TANGENTS_LEFT_OUT", "no tangent was deliberately left out")

    errors.extend(validate_question_choice(contract, commission, known))
    errors.extend(question_choice_penalties(contract))
    if consequence_rule:
        errors.extend(validate_consequence_model(contract, claims))
        for i, c in enumerate(contract.get("question_candidates") or []):
            if isinstance(c, dict) and is_hypothetical_question(c.get("question")) and str(i) != str(contract.get("chosen")):
                warnings.append({"code": "CANDIDATE_HYPOTHETICAL",
                                 "message": f"candidate {i + 1} is a forward hypothetical and may not be chosen"})
    unknown = sorted({c for c in contract_claim_ids(contract) if c not in known})
    if unknown:
        err("UNKNOWN_CLAIM", "the contract cites claims the dossier does not have: " + ", ".join(unknown))
    return {"passed": not errors, "errors": errors, "warnings": warnings}


def contract_markdown(contract: dict, validation: dict, evidence: dict, dossier: dict,
                      question: str, contract_sha: str) -> str:
    claims = {c["claim_id"]: c for c in _claims(dossier)}

    def cites(ids):
        ids = [i for i in ids or [] if i]
        return (" — " + ", ".join(f"{i} ({_text((claims.get(i) or {}).get('story_kind'))})" for i in ids)) if ids else " — (no claim)"

    hp = contract.get("human_perspective") or {}
    hp_ids = hp.get("claim_ids") if isinstance(hp.get("claim_ids"), dict) else {}
    lines = [f"# Story contract: {question}", "",
             f"Lane: `{LANE}` ({LANE_VERSION}). Contract sha256: `{contract_sha}`", "",
             "Approve by copying `contract.json` to `contract.approved.json` (edit it first if you "
             "want; the edited file is what the narration is written from) and rerun the same "
             "command. No media is bought before the exact narration is approved too.", ""]
    if not validation.get("passed"):
        lines += ["## ✗ Contract checks failed", ""] + [f"- **{e['code']}**: {e['message']}" for e in validation["errors"]] + [""]
    for w in validation.get("warnings") or []:
        lines.append(f"- ⚠ {w['code']}: {w['message']}")
    cands = [c for c in contract.get("question_candidates") or [] if isinstance(c, dict)]
    if cands:
        lines += ["", "## Question choice (three candidates)", ""]
        for i, c in enumerate(cands):
            sc_ = c.get("scores") or {}
            total = sum(int(sc_.get(k) or 0) for k in ("curiosity", "support", "deliverable"))
            mark = " **← chosen**" if str(contract.get("chosen")) == str(i) else ""
            lines += [f"{i + 1}. **{_text(c.get('question'))}**{mark}",
                      f"   - scores: curiosity {sc_.get('curiosity')}, support {sc_.get('support')}, "
                      f"deliverable {sc_.get('deliverable')} (total {total}/9)",
                      f"   - curiosity gap: {_text(c.get('curiosity_gap'))}",
                      f"   - consequence question: names decision {c.get('names_decision')}, asks consequence "
                      f"{c.get('asks_consequence')}" + (", **forward hypothetical**" if is_hypothetical_question(c.get("question")) else "")
                      + (f"; topic_fit: {(c.get('topic_fit') or {}).get('verdict')} "
                         f"({(c.get('topic_fit') or {}).get('channel') or '—'}) — {(c.get('topic_fit') or {}).get('reason')}"
                         if isinstance(c.get("topic_fit"), dict) else ""),
                      f"   - ending it could deliver: {_text(c.get('ending_answer'))}{cites(c.get('claim_ids'))}",
                      f"   - {_text(c.get('reason'))}"]
        lines += ["", f"Why this one: {_text(contract.get('chosen_reason'))}",
                  f"(overlap with the commission title: {question_overlap(contract.get('central_question'), question):.2f})"]
    if any(isinstance(contract.get(k), dict) for k in ("decision", "consequence", "still_unfolding")):
        dec, con, now = (contract.get(k) or {} for k in ("decision", "consequence", "still_unfolding"))
        lines += ["", "## World consequence model", "",
                  f"- **Decision** ({_text(dec.get('kind'))}, {_text(dec.get('when'))}): {_text(dec.get('what'))}{cites(dec.get('claim_ids'))}",
                  f"- **Consequence:** {_text(con.get('what'))}{cites(con.get('claim_ids'))}",
                  f"- **Still unfolding** (as of {_text(now.get('as_of'))}): {_text(now.get('what'))}{cites(now.get('claim_ids'))}"]
    lines += ["", f"**Topic.** {_text(contract.get('topic'))}", "",
              f"**Central question.** {_text(contract.get('central_question'))}", "",
              f"**The answer the ending delivers.** {_text(contract.get('ending_answer'))}", "",
              "## Human perspective", "", f"**{_text(hp.get('person'))}**", ""]
    for part in ("want", "action", "reward"):
        lines.append(f"- {part}: {_text(hp.get(part)) or '—'}{cites(hp_ids.get(part))}")
    att = contract.get("reasonable_attempt") or {}
    comp = contract.get("complication") or {}
    lines += ["", "## The reasonable attempt", "", f"{_text(att.get('what'))}", "",
              f"Why it made sense: {_text(att.get('why_it_made_sense'))}{cites(att.get('claim_ids'))}", "",
              "## The complication", "", f"{_text(comp.get('what'))}", "",
              f"Mechanism: {_text(comp.get('mechanism'))}{cites(comp.get('claim_ids'))}", "",
              "## Developments", ""]
    for i, dev in enumerate(contract.get("developments") or [], 1):
        lines += [f"{i}. **{_text(dev.get('what_happens'))}**{cites(dev.get('claim_ids'))}",
                  f"   - changes: {_text(dev.get('what_it_changes')) or '✗ (nothing named)'}",
                  f"   - why the next matters: {_text(dev.get('why_next_matters')) or '—'}"]
    image = contract.get("recurring_image")
    lines += ["", "## Recurring image", "",
              (f"{_text(image.get('image'))} (planted in {_text(image.get('planted_in'))}, returns in "
               f"{_text(image.get('callback_in'))})") if isinstance(image, dict) and _text(image.get("image")) else "none",
              "", "## Claims we cannot make", ""]
    lines += [f"- {_text(x)}" for x in contract.get("forbidden_claims") or []]
    lines += ["", "## Tangents left out on purpose", ""]
    lines += [f"- {_text((t or {}).get('tangent') if isinstance(t, dict) else t)}"
              + (f" — {_text(t.get('why'))}" if isinstance(t, dict) and _text(t.get("why")) else "")
              for t in contract.get("tangents_left_out") or []]
    gaps = list(contract.get("evidence_gaps") or []) + [
        f"{g.get('person')}: {g.get('detail')}" for g in (evidence or {}).get("evidence_gaps") or []]
    lines += ["", "## Evidence gaps", ""] + ([f"- {_text(g)}" for g in gaps] or ["none"])
    lines += ["", "## Human material found (ranked)", ""]
    for m in (evidence or {}).get("human_material") or []:
        lines.append(f"- [{m['type']}] {m['person']}: {m['detail']} — {', '.join(m['claim_ids'])}"
                     + (" — **serves person and problem**" if m.get("does_both") else ""))
    return "\n".join(lines) + "\n"


# ── openings, narration ───────────────────────────────────────────────────────────────────────

WRITER_SYSTEM = """You write narration for a documentary video, read aloud by one narrator. You \
tell a true story: a real person, one question, development through cause and effect, an ending \
that answers the opening question. Every factual sentence rests on the claims you are given and \
never goes beyond them. You do not follow formulas: there is no fixed number of sections, no \
required second-person opening, no banned phrasing and no joke quota. Humour, when it comes, comes \
from the situation. A number appears only when it serves the story.

It is heard once, at speaking pace, by someone who cannot reread. Keep sentences short -- about
twelve words on average, one idea each; a long sentence is two. Name a source only where the
listener needs to know who says so, about once or twice a spoken minute, never in every sentence.
Do not rewind to origins or history before the viewer has the question and the person's want; tell
backstory later, briefly, only where the story needs it. Never mention the research, the claims,
the brief, the title or the contract: the listener has none of them. Use few numbers -- about one or
two a spoken minute -- and only ones the story turns on. Never count obstacles ("a third limit"):
each development changes the answer, it is not the next item on a list."""


def _contract_block(contract: dict) -> str:
    return json.dumps(contract, ensure_ascii=False, indent=1)


def openings_prompt(question: str, contract: dict, dossier: dict, duration_sec: int) -> str:
    ids = set(contract_claim_ids(contract))
    return f"""Commission: {question} (about {duration_sec} s of narration)

Approved story contract:
{_contract_block(contract)}

Claims the contract relies on:
{claim_table(dossier, ids=ids or None)}

Write THREE different openings (40-110 words each) and TWO different endings (40-100 words each).
- Each opening gives the viewer the human way in and makes the central question clear early, in
  words a listener hears. Try genuinely different approaches (scene, quotation, object, situation).
- Each ending answers the central question with the contract's answer, and returns to the human
  perspective or the recurring image if the contract has one.
- Then pick the opening-ending pair that best asks and answers the same question.
List the claim IDs each text relies on. Do not state anything the claims do not support, and none
of the contract's forbidden claims.

Reply with JSON only:
{{"openings": [{{"id": "O1", "approach": "...", "text": "...", "claim_ids": []}}, ...3],
  "endings": [{{"id": "E1", "text": "...", "claim_ids": []}}, ...2],
  "selected": {{"opening": "O1", "ending": "E1", "reason": "..."}}}}"""


def validate_openings(raw: dict) -> dict:
    openings = [o for o in (raw or {}).get("openings") or [] if isinstance(o, dict) and _text(o.get("text"))]
    endings = [e for e in (raw or {}).get("endings") or [] if isinstance(e, dict) and _text(e.get("text"))]
    sel = (raw or {}).get("selected") or {}
    errors = []
    if len(openings) != 3:
        errors.append(f"expected 3 openings, got {len(openings)}")
    if len(endings) != 2:
        errors.append(f"expected 2 endings, got {len(endings)}")
    oid = {_text(o.get("id")): o for o in openings}
    eid = {_text(e.get("id")): e for e in endings}
    if _text(sel.get("opening")) not in oid or _text(sel.get("ending")) not in eid:
        errors.append("the selected pair does not name one of the openings and one of the endings")
    return {"passed": not errors, "errors": errors, "openings": openings, "endings": endings,
            "selected": {"opening": oid.get(_text(sel.get("opening"))) or (openings[0] if openings else {}),
                         "ending": eid.get(_text(sel.get("ending"))) or (endings[0] if endings else {}),
                         "reason": _text(sel.get("reason"))}}


def _narration_schema() -> str:
    return ('{"sentences": [{"text": "...", "claim_ids": ["c.."], '
            '"kind": "event|model|interpretation|illustration|framing", '
            '"part": "opening|attempt|complication|development_N|ending"}]}')


def narration_prompt(question: str, contract: dict, openings: dict, dossier: dict,
                     duration_sec: int, direction: str = "") -> str:
    sel = (openings or {}).get("selected") or {}
    target = int(duration_sec * WORDS_PER_SECOND)
    return f"""Commission: {question}
{('Operator direction: ' + direction.strip()) if _text(direction) else ''}

Approved story contract:
{_contract_block(contract)}

Selected opening:
{_text((sel.get('opening') or {}).get('text'))}

Selected ending:
{_text((sel.get('ending') or {}).get('text'))}

Claims (id [kind; source] claim, then the verbatim quote). Use only these:
{claim_table(dossier)}

Write the COMPLETE narration as one continuous piece, about {target} words ({duration_sec} s),
and never more than {int(target * LENGTH_MAX_RATIO)}: if the contract holds more than fits, leave
out the weakest development rather than squeezing every one in.
Begin from the selected opening and finish on the selected ending; you may adjust a few words so
they join the body. Follow the contract's developments in order: each passage must change the
situation and make the next one matter. Keep the human perspective alive through the middle, not
only at the edges.

Return it as a list of sentences, in order, each with:
- claim_ids: every claim the sentence relies on (empty only for sentences with no factual content);
- kind: "event", "model" (a study's prediction, said as one) or "interpretation" when it states a
  fact; "illustration" for an imagined situation, which must be framed aloud as imagined ("put
  yourself...", "suppose...") and never attributed to a named person; "framing" for sentences that
  assert nothing ("One fish.");
- part: which contract part it serves.
Never make the contract's forbidden claims.{chr(10) + "This is a World film: the listener must hear the past deliberate decision, its documented consequence, and the dated sign it is still unfolding; the ending answers the question from today, citing the contract's still_unfolding claims." if (contract or {}).get("still_unfolding") else ""}

Reply with JSON only: {_narration_schema()}"""


def normalize_sentences(raw) -> list[dict]:
    items = raw.get("sentences") if isinstance(raw, dict) else raw
    out = []
    for item in items or []:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict) or not _text(item.get("text")):
            continue
        kind = _text(item.get("kind")).lower()
        out.append({"text": policy.normalize_narration(item.get("text")),
                    "claim_ids": [_text(c) for c in item.get("claim_ids") or item.get("claims") or [] if _text(c)],
                    "kind": kind if kind in SENTENCE_KINDS else ("framing" if not item.get("claim_ids") else "event"),
                    "part": _text(item.get("part")) or "development"})
    return out


def narration_text(sentences: list[dict]) -> str:
    return policy.normalize_narration(" ".join(s["text"] for s in sentences))


_FRAMING_CUES = re.compile(r"\b(imagine|picture|suppose|say you|put yourself|pretend|let'?s say|"
                           r"if you were|you'?re a|think of)\b", re.I)


# ── spoken voice (operator 2026-10-21, after the first dry run) ───────────────────────────────
# Measured on the lionfish scripts: v2 (the story) 838 words, mean sentence 8.8, 2 over 25 words,
# 1.3 attributions a spoken minute; v1 (catalogue) 832 / 14.1 / 6 / 1.7; the lane's first narration
# 1,321 / 21.0 / 17 / 2.9. These limits sit between the reference and the failure.
LENGTH_MAX_RATIO = 1.10
MEAN_SENTENCE_MAX = 15.0
SENTENCE_FLAG_WORDS = 30          # a flag, not a blocker: v2 itself has one 31-word sentence
ATTRIBUTIONS_PER_MINUTE_MAX = 2.0
# Numbers a spoken minute. v2 1.9, v1 3.9, lane draft 2 5.1 (same definitions, 2026-10-21).
NUMBERS_PER_MINUTE_MAX = 2.0
# Humour that comes from the situation, the calibration the reviewer is given (lionfish v2).
HUMOR_EXAMPLES = ("A fish dressed like it's expecting photographers.",
                  "One fish. A very busy mouth.",
                  "Government advice you could serve with lemon.")
# Parallel-obstacle framing: "a third limit", "the second wall" -- the compiled lane's list middle.
_LIST_FRAMING_RE = re.compile(
    r"\b(second|third|fourth|fifth|final|last|another|one more|next)\s+(?:big\s+|real\s+)?"
    r"(limit|limits|problem|obstacle|wall|catch|barrier|hurdle|snag|complication|setback)\b", re.I)

_SENTENCE_RE = re.compile(r'[^.!?]+[.!?]+["”’)]*')
_NUMBER_WORDS = (r"(?:zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
                 r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
                 r"sixty|seventy|eighty|ninety|hundred|thousand|million|billion|dozen)")
_NUMBER_RE = re.compile(r"\b\d[\d,.]*\b|\b" + _NUMBER_WORDS + r"(?:[- ]" + _NUMBER_WORDS + r")*\b", re.I)
_ATTRIBUTION_RE = re.compile(
    r"\b(according to|said|says|told|reported|reports|researchers?|scientists?|experts?|"
    r"stud(?:y|ies)|a model|modell?ed|projected|estimated|surveys?|NOAA|USGS|FWC|the agency|"
    r"officials?)\b", re.I)
# Origin and backstory: a rewind cue, or a year more than a decade back. A recent year is the
# present-day story ("In the summer of 2025, he made seventy-three dive trips", v2), not a rewind.
BACKSTORY_YEARS_BACK = 10
_REWIND_RE = re.compile(r"\b(go(?:es)? back|going back|first (?:reported|recorded|seen|spotted|arrived|"
                        r"appeared)|originally|it all began|began in|back in|decades ago|how (?:it|they) got)\b", re.I)
_YEAR_RE = re.compile(r"\b(1[6-9]\d\d|20\d\d)s?\b")


def is_backstory(sentence: str, this_year: int | None = None) -> bool:
    this_year = this_year or int(time.strftime("%Y"))
    if _REWIND_RE.search(sentence):
        return True
    return any(int(y) < this_year - BACKSTORY_YEARS_BACK for y in _YEAR_RE.findall(sentence))


def minutes_floor(words: int) -> float:
    """Spoken minutes, never less than one: a rate is not measured on a 25-second passage."""
    return max(1.0, words / WORDS_PER_SECOND / 60.0)


def spoken_sentences(text: str) -> list[str]:
    return [m.strip() for m in _SENTENCE_RE.findall(_text(text)) if m.strip()]


def voice_metrics(text: str) -> dict:
    """Listener-side measures of a narration. Same definitions for every script compared."""
    sents = spoken_sentences(text)
    lengths = [len(x.split()) for x in sents]
    words = sum(lengths)
    minutes = words / WORDS_PER_SECOND / 60.0 if words else 0.0
    numbers = sum(len(_NUMBER_RE.findall(x)) for x in sents)
    attributions = sum(len(_ATTRIBUTION_RE.findall(x)) for x in sents)
    return {"words": words, "sentences": len(sents),
            "mean_sentence_words": round(words / len(sents), 1) if sents else 0.0,
            "sentences_over_25": sum(n > 25 for n in lengths),
            "sentences_over_30": sum(n > SENTENCE_FLAG_WORDS for n in lengths),
            "longest_sentence_words": max(lengths) if lengths else 0,
            "numbers_per_100w": round(100.0 * numbers / words, 1) if words else 0.0,
            "numbers_per_minute": round(numbers / minutes, 2) if minutes else 0.0,
            "numbers": numbers,
            "attributions_per_100w": round(100.0 * attributions / words, 1) if words else 0.0,
            "attributions_per_minute": round(attributions / minutes, 2) if minutes else 0.0,
            "est_runtime_sec": round(words / WORDS_PER_SECOND, 1)}


def _question_gate(sentences: list[dict], contract: dict | None) -> int:
    """Index of the sentence by which the central question AND the human's want are both heard."""
    human = set()
    hp = (contract or {}).get("human_perspective") or {}
    ids = hp.get("claim_ids") if isinstance(hp.get("claim_ids"), dict) else {}
    for part in ("want", "action", "reward"):
        human |= {c for c in ids.get(part) or [] if c}
    person = _text(hp.get("person")).split()
    surname = person[-1].lower() if person else ""
    q = next((i for i, s in enumerate(sentences) if s["text"].rstrip('"”’) ').endswith("?")), None)
    h = next((i for i, s in enumerate(sentences) if (set(s["claim_ids"]) & human)
              or (surname and surname in s["text"].lower())), None)
    if q is None or h is None:
        return len(sentences)
    return max(q, h)


# The writer's view of its inputs leaking into the narration ("according to the supplied record",
# lionfish dry run 2026-10-21). A listener has no record, contract or title card in front of them.
_PROMPT_LEAK = re.compile(r"\b(supplied|the (claims?|dossier|contract|brief|evidence provided|"
                          r"sources provided|record shows)|the title(?:'s)?|this (video|narration)'?s? "
                          r"(title|question)|according to the (record|evidence|sources))\b", re.I)


def validate_narration(sentences: list[dict], known_claims, duration_sec: int,
                       contract: dict | None = None, consequence_rule: bool = False) -> dict:
    known = set(known_claims or [])
    errors, warnings = [], []
    if not sentences:
        errors.append({"code": "NO_NARRATION", "message": "the narration is empty"})
    for i, s in enumerate(sentences, 1):
        unknown = [c for c in s["claim_ids"] if c not in known]
        if unknown:
            errors.append({"code": "UNKNOWN_CLAIM", "message": f"sentence {i} cites {', '.join(unknown)}"})
        if s["kind"] in CLAIM_KINDS and not s["claim_ids"]:
            errors.append({"code": "UNSOURCED_FACT", "message": f"sentence {i} is a {s['kind']} with no claim: {s['text'][:80]}"})
        if s["kind"] == "illustration":
            if s["claim_ids"]:
                warnings.append({"code": "ILLUSTRATION_CITES_CLAIM",
                                 "message": f"sentence {i} is an illustration but cites claims (leak risk)"})
            prev = sentences[i - 2]["text"] if i > 1 else ""
            if not (_FRAMING_CUES.search(s["text"]) or _FRAMING_CUES.search(prev)):
                warnings.append({"code": "ILLUSTRATION_NOT_FRAMED",
                                 "message": f"sentence {i} is an illustration with no framing cue nearby"})
        leak = _PROMPT_LEAK.search(s["text"])
        if leak:
            errors.append({"code": "PROMPT_LEAK", "message": f"sentence {i} talks about the "
                           f"research or the brief ({leak.group(0)!r}), not the story: rewrite it "
                           "as something a listener can follow"})
        if _words(s["text"]) > SENTENCE_FLAG_WORDS:
            warnings.append({"code": "SENTENCE_OVER_30",
                             "message": f"sentence {i} runs {_words(s['text'])} words"})
    gate = _question_gate(sentences, contract)
    if gate >= len(sentences) and sentences:
        warnings.append({"code": "QUESTION_OR_HUMAN_NOT_HEARD",
                         "message": "no sentence asks the question, or the person never appears"})
    for i, s in enumerate(sentences[:gate] if gate < len(sentences) else [], 1):
        if is_backstory(s["text"]):
            errors.append({"code": "BACKSTORY_BEFORE_QUESTION",
                           "message": f"sentence {i} rewinds to origin or backstory before the central "
                                      f"question and the person's want are both heard (by sentence {gate + 1})"})
    if consequence_rule and contract and sentences:
        present = set((contract.get("still_unfolding") or {}).get("claim_ids") or [])
        ending = [x for x in sentences if _text(x.get("part")).startswith("ending")] or sentences[-4:]
        if present and not any(set(x["claim_ids"]) & present for x in ending):
            errors.append({"code": "ENDING_NOT_FROM_TODAY",
                           "message": "the ending cites none of the still-unfolding claims ("
                                      + ", ".join(sorted(present)) + "): answer the question from today"})
    voice = voice_metrics(narration_text(sentences))
    words = voice["words"]
    target = int(duration_sec * WORDS_PER_SECOND)
    if target and words > LENGTH_MAX_RATIO * target:
        errors.append({"code": "LENGTH_OVER",
                       "message": f"{words} words is {words - target} over the ~{target}-word target "
                                  f"(limit {int(LENGTH_MAX_RATIO * target)}): cut to about {target} words. "
                                  "Cut whole passages the story does not need; do not compress sentences"})
    elif target and words < 0.75 * target:
        warnings.append({"code": "LENGTH_SHORT", "message": f"{words} words for a ~{target}-word target"})
    if voice["numbers"] > NUMBERS_PER_MINUTE_MAX * minutes_floor(voice["words"]):
        errors.append({"code": "NUMBER_DENSE",
                       "message": f"{voice['numbers_per_minute']} numbers a spoken minute (limit "
                                  f"{NUMBERS_PER_MINUTE_MAX:g}): keep only the numbers the story turns on; "
                                  "say the rest in words or cut them"})
    for i, s in enumerate(sentences, 1):
        framing = _LIST_FRAMING_RE.search(s["text"])
        if framing:
            errors.append({"code": "LIST_FRAMING",
                           "message": f"sentence {i} counts obstacles ({framing.group(0)!r}): a "
                                      "parallel list, not a development; show what this one changes "
                                      "or cut it"})
    if voice["mean_sentence_words"] > MEAN_SENTENCE_MAX:
        errors.append({"code": "SENTENCE_MEAN_LONG",
                       "message": f"mean sentence is {voice['mean_sentence_words']} words (limit "
                                  f"{MEAN_SENTENCE_MAX:g}, aim ~12): split long sentences, one idea each"})
    # Counted against at least one minute, so one "NOAA" in a 25-second test passage is not a rate.
    if voice["attributions_per_minute"] * (voice["words"] / WORDS_PER_SECOND / 60.0) > ATTRIBUTIONS_PER_MINUTE_MAX * minutes_floor(voice["words"]):
        errors.append({"code": "ATTRIBUTION_DENSE",
                       "message": f"{voice['attributions_per_minute']} source attributions a spoken minute "
                                  f"(limit {ATTRIBUTIONS_PER_MINUTE_MAX:g}): keep attribution where the "
                                  "listener needs to know who says so, drop the rest"})
    return {"passed": not errors, "errors": errors, "warnings": warnings, "words": words,
            "target_words": target, "voice": voice}


# ── the fresh reviewer ────────────────────────────────────────────────────────────────────────

REVIEW_A_SYSTEM = """You are a careful first-time listener. You have only the narration of a \
documentary video and its one-line brief. You know nothing else about how it was made."""

REVIEW_B_SYSTEM = """You are a demanding documentary story editor and fact checker, reviewing a \
narration you did not write. You quote the narration as evidence for every judgement. You are \
specific and brief, and you only ask for changes that matter."""


def review_a_prompt(question: str, narration: str, duration_sec: int) -> str:
    return f"""Brief: a ~{duration_sec}-second illustrated documentary answering "{question}".

Narration:
{narration}

From the narration alone, reconstruct:
- central_question: the question it asks early (quote where you first hear it, and say roughly how
  far in it is, as a fraction of the narration);
- main_idea: what the film is really about, in one sentence;
- human: the person the viewer follows and their want or reward ("none" if no one);
- pivotal_discovery: the turn or discovery the story hinges on;
- ending_answer: the answer the ending gives to the central question ("none" if it does not answer);
- decision: the past deliberate decision or fix the story is about, with its date ("none" if you cannot tell);
- consequence: what that decision documentably caused ("none" if you cannot tell);
- still_unfolding: how the narration says it continues today, with the date ("none" if it does not).

Reply with JSON only:
{{"central_question": "...", "question_quote": "...", "question_position": 0.1,
  "main_idea": "...", "human": "...", "pivotal_discovery": "...", "ending_answer": "...",
  "decision": "...", "consequence": "...", "still_unfolding": "..."}}"""


def review_b_prompt(question: str, contract: dict, sentences: list[dict], dossier: dict,
                    reconstruction: dict, consequence_rule: bool = False) -> str:
    ids = set(c for s in sentences for c in s["claim_ids"])
    numbered = "\n".join(f"[{i}] ({s['kind']}; {', '.join(s['claim_ids']) or '-'}) {s['text']}"
                         for i, s in enumerate(sentences, 1))
    rubric = "\n".join(f"- {item}: {desc}" for item, desc in rubric_items(consequence_rule))
    chain = ("\n9. consequence_chain: did the blind reader recover the contract's decision, consequence "
             "and still-unfolding sign? Does the ending answer the question from today (ending_from_today)?"
             if consequence_rule else "")
    return f"""Commission: {question}

The story contract the narration was meant to execute:
{_contract_block(contract)}

A blind reader, given only the narration, reconstructed:
{json.dumps(reconstruction, ensure_ascii=False, indent=1)}

The narration, one sentence per line: [n] (kind; claim ids) text
{numbered}

The cited claims with their verbatim source quotes:
{claim_table(dossier, ids=ids)}

Review it.
1. reconstruction_match: compare the blind reconstruction with the contract (central question,
   human, pivotal discovery, ending answer). A mismatch means the narration did not execute the
   plan where the reader could hear it.
2. opening_ending: do the opening and the ending ask and answer the same question? Quote both.
3. removal: for each passage (a run of sentences), what would be lost without it? Verdict keep,
   cut or merge.
4. evidence: does each causal link and qualification hold against the quotes? Does any model get
   stated as an event, or any illustration leak into a fact about a named person? Does the
   narration make any of the contract's forbidden claims? Each problem that states something the
   sources do not support is a factual blocker.
5. rubric: score each item 0-3 with a short quotation from the narration as evidence:
{rubric}
   Scale: {RUBRIC_SCALE}
   Measured voice (count, not opinion): {json.dumps(voice_metrics(narration_text(sentences)))}
   Judge voice as a listener: long sentences, stacked attributions ("according to", "researchers
   found") and early rewinds to history lose people. Credit humour that comes from the situation
   (calibration, from another film: {' / '.join(HUMOR_EXAMPLES)}); never ask for jokes, and its
   absence is not a defect.
7. development_removal: for EACH contract development, find its passage and ask whether removing
   it would change the ANSWER to the central question. A development that does not change the
   answer is a side story (true and interesting is not enough): mark changes_answer false. Flag
   any "first / second / third limit"-style counting as a parallel-obstacle list.
8. numbers_without_purpose: every number in the narration that the story does not turn on, quoted
   with its sentence number.{chain}
   Every score of 0 or 1 needs an editorial objective.
6. editorial_objectives: AT MOST THREE, the ones that matter most. Each with its location
   (sentence numbers), the problem, the repair objective, and the material to preserve.

Reply with JSON only:
{{"ending_from_today": true,
  "reconstruction_match": {{"central_question": {{"match": true, "note": "..."}},
                            "decision": {{"match": true, "note": "..."}},
                            "consequence": {{"match": true, "note": "..."}},
                            "still_unfolding": {{"match": true, "note": "..."}},
                            "human": {{"match": true, "note": "..."}},
                            "pivotal_discovery": {{"match": true, "note": "..."}},
                            "ending_answer": {{"match": true, "note": "..."}}}},
  "opening_ending": {{"same_question": true, "opening_quote": "...", "ending_quote": "...", "note": "..."}},
  "removal": [{{"sentences": [1, 4], "loss": "...", "verdict": "keep|cut|merge"}}],
  "factual_blockers": [{{"sentences": [7], "problem": "...", "fix": "..."}}],
  "rubric": [{{"item": "human_entry", "score": 2, "quote": "...", "note": "..."}}],
  "editorial_objectives": [{{"sentences": [9, 12], "problem": "...", "objective": "...", "preserve": "..."}}],
  "development_removal": [{{"development": 1, "sentences": [11, 19], "changes_answer": true, "note": "..."}}],
  "parallel_obstacle_lists": [{{"sentences": [54], "quote": "..."}}],
  "numbers_without_purpose": [{{"sentence": 23, "number": "...", "note": "..."}}],
  "overall": "one paragraph"}}"""


def quote_in(quote: str, text: str) -> bool:
    """Is the quotation in the text? An ellipsis joins fragments; each must be there, in order."""
    hay = _norm(text)
    # Reviewers number sentences ("[34] ..."); the markers are theirs, not the narration's.
    parts = [_norm(re.sub(r"\[\d+\]", " ", p)) for p in re.split(r"\.\.\.|…", _text(quote))]
    parts = [p for p in parts if p]
    pos = 0
    for part in parts:
        found = hay.find(part, pos)
        if found < 0:
            return False
        pos = found + len(part)
    return bool(parts)


_NONE = {"", "none", "n/a", "unclear", "unknown", "cannot tell"}


def consequence_blockers(raw: dict, reconstruction: dict) -> list[dict]:
    """The blind reader must recover decision -> consequence -> still unfolding; a miss blocks."""
    out = []
    match = (raw or {}).get("reconstruction_match") or {}
    for key, label in (("decision", "the deliberate decision"), ("consequence", "its documented consequence"),
                       ("still_unfolding", "that it is still unfolding today")):
        heard = _norm((reconstruction or {}).get(key))
        missed = heard in _NONE or (isinstance(match.get(key), dict) and match[key].get("match") is False)
        if missed:
            out.append({"code": "CONSEQUENCE_CHAIN_MISSED", "problem": f"a listener given only the narration "
                        f"could not recover {label} (blind reader: {(reconstruction or {}).get(key) or 'none'})",
                        "fix": f"say {label} plainly, where the listener needs it"})
    if (raw or {}).get("ending_from_today") is False:
        out.append({"code": "ENDING_NOT_FROM_TODAY", "problem": "the ending does not answer the question from today",
                    "fix": "end on the dated present-day consequence, answering the question"})
    return out


def normalize_review(raw: dict, sentences: list[dict], reconstruction: dict,
                     consequence_rule: bool = False) -> dict:
    text_norm = narration_text(sentences)
    rubric, seen = [], set()
    for row in (raw or {}).get("rubric") or []:
        if not isinstance(row, dict):
            continue
        item = _text(row.get("item"))
        if item not in RUBRIC_IDS or item in seen:
            continue
        seen.add(item)
        try:
            score = max(0, min(3, int(row.get("score"))))
        except (TypeError, ValueError):
            score = 0
        quote = _text(row.get("quote"))
        rubric.append({"item": item, "score": score, "quote": quote, "note": _text(row.get("note")),
                       "quote_verified": quote_in(quote, text_norm)})
    missing = [i for i, _ in rubric_items(consequence_rule) if i not in seen]
    objectives = [o for o in (raw or {}).get("editorial_objectives") or [] if isinstance(o, dict)
                  and _text(o.get("objective"))]
    # Every 0-1 score needs a repair objective. One the reviewer named but did not tie to an
    # objective is added from its own note; the list stays at MAX_EDITORIAL_OBJECTIVES, and
    # anything past it is kept as deferred rather than silently dropped.
    # A development the narration already left out has nothing to cut: it is reported, not repaired.
    side = [d for d in (raw or {}).get("development_removal") or []
            if isinstance(d, dict) and d.get("changes_answer") is False and d.get("sentences")]
    lists = [x for x in (raw or {}).get("parallel_obstacle_lists") or [] if isinstance(x, dict)]
    numbers = [x for x in (raw or {}).get("numbers_without_purpose") or [] if isinstance(x, dict)]
    structural = []
    for d in side:
        structural.append({"sentences": d.get("sentences") or [], "problem": f"development {d.get('development')} "
                           f"does not change the answer to the central question: {_text(d.get('note'))}",
                           "objective": "cut this side story or merge what it changes into a development that matters",
                           "preserve": "", "from_removal_test": True})
    if lists:
        structural.append({"sentences": [n for x in lists for n in x.get("sentences") or []],
                           "problem": "parallel-obstacle list: " + "; ".join(_text(x.get("quote")) for x in lists),
                           "objective": "drop the counting; keep each passage only for what it changes",
                           "preserve": "", "from_removal_test": True})
    if numbers:
        structural.append({"sentences": [x.get("sentence") for x in numbers],
                           "problem": "numbers with no story purpose: " + "; ".join(_text(x.get("number")) for x in numbers),
                           "objective": "cut these numbers or say them in words", "preserve": ""})
    objectives = structural + [o for o in objectives]
    covered = " ".join(_norm(json.dumps(o)) for o in objectives)
    for row in rubric:
        if row["score"] <= 1 and row["item"].replace("_", " ") not in covered and row["item"] not in covered:
            objectives.append({"sentences": [], "problem": f"{row['item']} scored {row['score']}: {row['note']}",
                               "objective": f"raise {row['item']}", "preserve": "", "from_rubric": row["item"]})
    deferred = objectives[MAX_EDITORIAL_OBJECTIVES:]
    objectives = objectives[:MAX_EDITORIAL_OBJECTIVES]
    blockers = [b for b in (raw or {}).get("factual_blockers") or [] if isinstance(b, dict) and _text(b.get("problem"))]
    match = (raw or {}).get("reconstruction_match") or {}
    oe = (raw or {}).get("opening_ending") or {}
    return {
        "reconstruction": reconstruction,
        "reconstruction_match": match,
        "reconstruction_mismatches": [k for k, v in match.items() if isinstance(v, dict) and v.get("match") is False],
        "opening_ending": oe,
        "removal": [r for r in (raw or {}).get("removal") or [] if isinstance(r, dict)],
        "factual_blockers": blockers,
        "rubric": rubric,
        "rubric_missing": missing,
        "rubric_total": sum(r["score"] for r in rubric),
        "rubric_max": 3 * len(rubric_items(consequence_rule)),
        "consequence_blockers": consequence_blockers(raw, reconstruction) if consequence_rule else [],
        "editorial_objectives": objectives,
        "development_removal": [d for d in (raw or {}).get("development_removal") or [] if isinstance(d, dict)],
        "side_stories": side,
        "parallel_obstacle_lists": lists,
        "numbers_without_purpose": numbers,
        "deferred_objectives": deferred,
        "overall": _text((raw or {}).get("overall")),
    }


def rank_prompt(question: str, narrations: list[str], duration_sec: int = 300) -> str:
    """Several narrations of one commission, ranked on the lane's rubric.

    The calibration the design asks for before the reviewer may gate anything (measuring plan,
    step 3): on lionfish it must rank v2 (the Carlson story) above the lane's first narration
    above v1 (the compiled catalogue), whatever order they are shown in
    (evals/promptfoo/story_reviewer.yaml).
    """
    labels = [chr(ord("A") + i) for i in range(len(narrations))]
    rubric = "\n".join(f"- {item}: {desc}" for item, desc in RUBRIC)
    blocks = "\n\n".join(f"NARRATION {lab}:\n{text}" for lab, text in zip(labels, narrations))
    voice = {lab: voice_metrics(text) for lab, text in zip(labels, narrations)}
    return f"""{len(narrations)} narrations were written for the same ~{duration_sec}-second illustrated
documentary commission: "{question}". You wrote none of them.

{blocks}

Measured voice (counts, not opinions): {json.dumps(voice)}

For each, reconstruct the central question it asks and the answer its ending gives. Then score
each on this rubric, 0-3 per item, quoting it as evidence:
{rubric}
Scale: {RUBRIC_SCALE}

Rank them, best first: which would a viewer keep watching because they want the answer? More facts
is not better. Ties are allowed only if you genuinely cannot separate two. For each adjacent pair in
your ranking give reasons, each with a short quotation from the higher-ranked narration (and,
where it helps, one from the lower).

Reply with JSON only:
{{"scripts": {{"A": {{"central_question": "...", "ending_answer": "...", "rubric": {{"human_entry": 0, "...": 0}}}}, ...}},
  "ranking": ["A", "B", ...],
  "reasons": [{{"higher": "A", "lower": "B", "reason": "...", "quote_higher": "...", "quote_lower": "..."}}]}}"""


def compare_prompt(question: str, narration_a: str, narration_b: str, duration_sec: int = 300) -> str:
    return rank_prompt(question, [narration_a, narration_b], duration_sec)


def needs_repair(review: dict) -> bool:
    return bool((review or {}).get("factual_blockers") or (review or {}).get("editorial_objectives")
                or (review or {}).get("consequence_blockers"))


REPAIR_SYSTEM = WRITER_SYSTEM + """ You are revising your narration against an editor's notes. \
Change only what the notes require; keep every other sentence exactly as it is."""


def repair_prompt(question: str, contract: dict, sentences: list[dict], review: dict,
                  dossier: dict, duration_sec: int) -> str:
    numbered = "\n".join(f"[{i}] ({s['kind']}; {', '.join(s['claim_ids']) or '-'}; {s['part']}) {s['text']}"
                         for i, s in enumerate(sentences, 1))
    notes = {"factual_blockers": review.get("factual_blockers") or [],
             "editorial_objectives": review.get("editorial_objectives") or []}
    return f"""Commission: {question} (about {duration_sec} s)

Approved story contract:
{_contract_block(contract)}

Current narration: [n] (kind; claim ids; part) text
{numbered}

Editor's notes. Fix EVERY factual blocker. Meet each editorial objective while preserving what it
says to preserve:
{json.dumps(notes, ensure_ascii=False, indent=1)}

Claims (use only these):
{claim_table(dossier)}

Length: now {sum(_words(s['text']) for s in sentences)} words; the target is about
{int(duration_sec * WORDS_PER_SECOND)} and the limit {int(duration_sec * WORDS_PER_SECOND * LENGTH_MAX_RATIO)}.
If it is over, cut whole passages the question does not need; do not compress sentences.

Return the COMPLETE revised narration in the same sentence format. Sentences the notes do not touch
must come back word for word.

Reply with JSON only: {_narration_schema()}"""


_FIX = {
    "LENGTH_OVER": "cut whole passages the central question does not need until it is within the limit",
    "PROMPT_LEAK": "say it as story, never mention the research, claims, brief, title or contract",
    "SENTENCE_MEAN_LONG": "split long sentences: one idea each, about twelve words on average",
    "ATTRIBUTION_DENSE": "drop attributions the listener does not need; keep them only where who-says-so matters",
    "BACKSTORY_BEFORE_QUESTION": "move the origin story after the question and the person's want, and shorten it",
    "NUMBER_DENSE": "keep only the numbers the story turns on; say the rest in words or cut them",
    "ENDING_NOT_FROM_TODAY": "end on the dated present-day consequence, answering the question from today",
    "LIST_FRAMING": "drop the counting ('a third limit'); keep the passage only if it changes the answer, else cut it",
}
_DELIVERY_CODES = {"LENGTH_OVER", "PROMPT_LEAK", "SENTENCE_MEAN_LONG", "ATTRIBUTION_DENSE",
                   "BACKSTORY_BEFORE_QUESTION", "NUMBER_DENSE", "LIST_FRAMING", "ENDING_NOT_FROM_TODAY"}


def narration_status(candidate: dict) -> tuple[str, list[str]]:
    """ready | ready_with_open_objectives | not_ready (voice/length) | evidence_gap (facts)."""
    review = candidate.get("review") or {}
    errors = (candidate.get("validation") or {}).get("errors") or []
    factual = list(review.get("factual_blockers") or []) + [e for e in errors if e["code"] not in _DELIVERY_CODES]
    delivery = [e for e in errors if e["code"] in _DELIVERY_CODES] + [
        {"message": b["problem"]} for b in review.get("consequence_blockers") or []]
    if factual:
        return "evidence_gap", [b.get("problem") or b.get("message") for b in factual]
    if delivery:
        return "not_ready", [e["message"] for e in delivery]
    return ("ready" if not review.get("editorial_objectives") else "ready_with_open_objectives"), []


def select_candidate(candidates: list[dict]) -> dict:
    """The strongest factually acceptable candidate; else the one with the fewest blockers."""
    if not candidates:
        return {}
    reviewed = [c for c in candidates if isinstance(c.get("review"), dict)]
    if not reviewed:
        return candidates[-1]

    def blockers(c):
        return len(c["review"].get("factual_blockers") or []) + len((c.get("validation") or {}).get("errors") or [])

    clean = [c for c in reviewed if blockers(c) == 0]
    pool = clean or reviewed
    return max(pool, key=lambda c: (-blockers(c), c["review"].get("rubric_total", 0),
                                    -len(c["review"].get("editorial_objectives") or []),
                                    c.get("version", 0)))


def narration_markdown(question: str, chosen: dict, candidates: list[dict], budget: RepairBudget,
                       contract_sha: str, status: str) -> str:
    sha = chosen["sha256"]
    review = chosen.get("review") or {}
    lines = [f"# Narration for approval: {question}", "",
             f"Lane `{LANE}`. Candidate v{chosen['version']} of {len(candidates)} "
             f"(repair passes used: {budget.used()} of {budget.maximum}). Status: **{status}**.", "",
             f"Narration sha256: `{sha}`", f"Contract sha256: `{contract_sha}`", "",
             "Approve exactly this text with `--approve-narration " + sha + "` (or write "
             f"`{{\"sha256\": \"{sha}\"}}` to `{NARRATION_APPROVED}`) and rerun. Any later change of "
             "a word produces a new version for review; media spend starts only on an approved hash.", ""]
    voice = (chosen.get("validation") or {}).get("voice") or voice_metrics(narration_text(chosen["sentences"]))
    target = (chosen.get("validation") or {}).get("target_words") or 0
    lines += ["## Spoken voice (measured)", "",
              "| measure | value | limit |", "|---|---|---|",
              f"| words | {voice['words']} | target ~{target}, limit {int(target * LENGTH_MAX_RATIO)} |",
              f"| est. runtime | {voice['est_runtime_sec']} s | |",
              f"| sentences | {voice['sentences']} | |",
              f"| mean sentence | {voice['mean_sentence_words']} words | ≤ {MEAN_SENTENCE_MAX:g} (aim ~12) |",
              f"| sentences > 25 words | {voice['sentences_over_25']} | |",
              f"| sentences > 30 words | {voice['sentences_over_30']} (longest {voice['longest_sentence_words']}) | flagged |",
              f"| numbers / 100 words | {voice['numbers_per_100w']} | |",
              f"| numbers / spoken minute | {voice.get('numbers_per_minute')} | ≤ {NUMBERS_PER_MINUTE_MAX:g} |",
              f"| attributions / 100 words | {voice['attributions_per_100w']} | |",
              f"| attributions / spoken minute | {voice['attributions_per_minute']} | ≤ {ATTRIBUTIONS_PER_MINUTE_MAX:g} |", ""]
    errs = (chosen.get("validation") or {}).get("errors") or []
    if errs:
        lines += ["## ✗ Not ready: deterministic blockers still open", ""] + [
            f"- **{e['code']}**: {e['message']}" for e in errs] + [""]
    if review.get("consequence_blockers"):
        lines += ["## ✗ Consequence chain (World): blockers", ""] + [
            f"- **{b['code']}**: {b['problem']}" for b in review["consequence_blockers"]] + [""]
    if review.get("factual_blockers"):
        lines += ["## ✗ Open factual blockers", ""] + [
            f"- sentences {b.get('sentences')}: {b.get('problem')} — fix: {b.get('fix')}"
            for b in review["factual_blockers"]] + [""]
    if review.get("editorial_objectives"):
        lines += ["## Open editorial objectives", ""] + [
            f"- sentences {o.get('sentences')}: {o.get('problem')} → {o.get('objective')}"
            + (f" (preserve: {o.get('preserve')})" if o.get("preserve") else "")
            for o in review["editorial_objectives"]] + [""]
    if review.get("development_removal"):
        lines += ["## Removal test per development", ""] + [
            f"- development {d.get('development')} (sentences {d.get('sentences')}): "
            + ("changes the answer" if d.get("changes_answer") else "**side story: does not change the answer**")
            + f" — {_text(d.get('note'))}" for d in review["development_removal"]] + [""]
    if review.get("numbers_without_purpose"):
        lines += ["## Numbers without a story purpose (reviewer)", ""] + [
            f"- sentence {x.get('sentence')}: {x.get('number')} — {_text(x.get('note'))}"
            for x in review["numbers_without_purpose"]] + [""]
    rec = review.get("reconstruction") or {}
    lines += ["## Blind reconstruction (reviewer saw only the narration)", "",
              f"- question: {rec.get('central_question')} (heard at ~{rec.get('question_position')}: “{rec.get('question_quote')}”)",
              f"- main idea: {rec.get('main_idea')}", f"- human: {rec.get('human')}",
              f"- pivot: {rec.get('pivotal_discovery')}", f"- ending answer: {rec.get('ending_answer')}",
              f"- decision → consequence → still unfolding: {rec.get('decision')} → {rec.get('consequence')} → {rec.get('still_unfolding')}",
              f"- mismatches with the contract: {', '.join(review.get('reconstruction_mismatches') or []) or 'none'}", "",
              f"## Rubric ({review.get('rubric_total')}/{review.get('rubric_max')}) — describes, never loops", ""]
    for r in review.get("rubric") or []:
        lines.append(f"- {r['item']}: {r['score']}/3 — “{r['quote']}”{'' if r['quote_verified'] else ' (quote not found in narration)'} {r['note']}")
    for w in (chosen.get("validation") or {}).get("warnings") or []:
        lines.append(f"- ⚠ {w['code']}: {w['message']}")
    lines += ["", "## Narration", ""]
    for i, s in enumerate(chosen["sentences"], 1):
        lines.append(f"{i}. {s['text']}  <sub>{s['kind']} · {', '.join(s['claim_ids']) or '—'} · {s['part']}</sub>")
    lines += ["", f"Words: {sum(_words(s['text']) for s in chosen['sentences'])}", "",
              "## All candidates", ""]
    for c in candidates:
        r = c.get("review") or {}
        lines.append(f"- v{c['version']} ({c.get('source')}): sha `{c['sha256'][:12]}`, rubric "
                     f"{r.get('rubric_total')}/{r.get('rubric_max')}, blockers {len(r.get('factual_blockers') or [])}, "
                     f"objectives {len(r.get('editorial_objectives') or [])}")
    return "\n".join(lines) + "\n"


# ── the lane ──────────────────────────────────────────────────────────────────────────────────

@dataclass
class LaneRun:
    question: str
    output_dir: str
    duration_sec: int = 300
    direction: str = ""
    dossier: dict = field(default_factory=dict)
    pack: dict | None = None
    caller: object = None
    log: object = print
    topic_channel: str = ""

    def __post_init__(self):
        os.makedirs(self.output_dir, exist_ok=True)
        self.state = LaneState(self.output_dir)
        self.budget = RepairBudget(self.output_dir)
        self.caller = self.caller or Caller()
        self.known = {c["claim_id"] for c in _claims(self.dossier)}
        self.consequence_rule = consequence_rule_applies(self.topic_channel)

    def _path(self, name: str) -> str:
        return os.path.join(self.output_dir, name)

    def _call(self, stage: str, role: str, system: str, user: str, max_tokens: int = 8000):
        self.log(f"story_contract: {stage} ({role}, {model_for(role, getattr(self.caller, 'provider', None) or None)})")
        return self.caller.call(role=role, stage=stage, system=system, user=user, max_tokens=max_tokens)

    # 1. evidence
    def evidence(self) -> dict:
        key = canonical_hash({"q": self.question, "claims": sorted(self.known),
                              "dossier": canonical_hash(_claims(self.dossier)), "v": LANE_VERSION})
        cached = self.state.get("evidence", key)
        if cached is not None:
            return cached
        raw, cost = self._call("evidence", "writer", EVIDENCE_SYSTEM,
                               evidence_prompt(self.question, self.dossier, self.pack), 16000)
        out = normalize_evidence(raw, self.dossier)
        self.state.put("evidence", key, out, cost)
        return out

    # 2. contract
    def contract(self, evidence: dict) -> tuple[dict, str]:
        """The approved contract and its hash, or raise ContractApprovalRequired."""
        dossier = apply_claim_kinds(self.dossier, evidence)
        approved_path = self._path(CONTRACT_APPROVED)
        if os.path.isfile(approved_path):
            approved = _read_json(approved_path, None)
            check = validate_contract(approved, self._claim_map(evidence), self.question, self.consequence_rule)
            sha = canonical_hash(approved)
            if not check["passed"]:
                with open(self._path(CONTRACT_MD), "w", encoding="utf-8") as h:
                    h.write(contract_markdown(approved, check, evidence, dossier, self.question, sha))
                raise ContractInvalid("STORY_CONTRACT_INVALID: the approved contract fails its checks: "
                                      + "; ".join(e["message"] for e in check["errors"]),
                                      path=self._path(CONTRACT_MD), details=check)
            return approved, sha
        key = canonical_hash({"q": self.question, "evidence": evidence, "d": self.duration_sec,
                              "dir": self.direction, "v": LANE_VERSION})
        cached = self.state.get("contract", key)
        errors = None
        if cached is not None:
            # A contract bought under older checks is re-checked under the current ones.
            recheck = validate_contract(cached["contract"], self._claim_map(evidence), self.question,
                                        self.consequence_rule)
            if not recheck["passed"]:
                errors, cached = recheck["errors"], None
        if cached is None:
            total = 0.0
            for attempt in range(2):
                raw, cost = self._call("contract", "writer", CONTRACT_SYSTEM, contract_prompt(
                    self.question, dossier, evidence, self.duration_sec, self.direction, errors,
                    self.consequence_rule), 16000)
                total += cost
                if self.consequence_rule:
                    total += self._screen_candidates(raw)
                check = validate_contract(raw, self._claim_map(evidence), self.question, self.consequence_rule)
                if check["passed"]:
                    break
                errors = check["errors"]
            cached = {"contract": raw, "validation": check, "attempts": attempt + 1}
            self.state.put("contract", key, cached, total)
        contract, check = cached["contract"], cached["validation"]
        sha = canonical_hash(contract)
        _write_json(self._path(CONTRACT_FILE), contract)
        with open(self._path(CONTRACT_MD), "w", encoding="utf-8") as h:
            h.write(contract_markdown(contract, check, evidence, dossier, self.question, sha))
        if not check["passed"]:
            raise ContractInvalid("STORY_CONTRACT_INVALID after a corrected attempt: "
                                  + "; ".join(e["message"] for e in check["errors"])
                                  + ". Edit contract.json into contract.approved.json by hand, or rerun.",
                                  path=self._path(CONTRACT_MD), details=check)
        raise ContractApprovalRequired(
            f"Story contract written for approval: {self._path(CONTRACT_MD)}. Copy {CONTRACT_FILE} to "
            f"{CONTRACT_APPROVED} (edited or not) and rerun.", path=self._path(CONTRACT_MD),
            details={"contract_sha256": sha})

    def _claim_map(self, evidence: dict) -> dict:
        return {c["claim_id"]: c for c in _claims(apply_claim_kinds(self.dossier, evidence))}

    def _screen_candidates(self, contract: dict) -> float:
        """topic_fit's World screen on each candidate question (one small reviewer call each)."""
        import topic_fit
        total = [0.0]

        def judge(prompt: str, system: str = "") -> str:
            text, cost = self.caller.text(role="reviewer", stage="topic_fit", system=system, user=prompt,
                                          max_tokens=4000)
            total[0] += cost
            return text

        for c in contract.get("question_candidates") or []:
            if isinstance(c, dict) and _text(c.get("question")):
                try:
                    c["topic_fit"] = topic_fit.screen(c["question"], channel="world", judge=judge)
                except Exception as exc:  # noqa: BLE001 - a screen outage is not a verdict
                    c["topic_fit"] = {"verdict": "unknown", "screened": False, "reason": str(exc)[:120]}
        return total[0]

    # 3-6. openings, narration, review, repairs
    def _review(self, sentences: list[dict], contract: dict, contract_sha: str, dossier: dict) -> dict:
        text = narration_text(sentences)
        reviewer = model_for("reviewer", getattr(self.caller, "provider", None) or None)
        key_a = canonical_hash({"n": policy.narration_sha256(text), "q": self.question, "m": reviewer, "v": LANE_VERSION})
        rec = self.state.get("review_a:" + key_a[:16], key_a)
        if rec is None:
            rec, cost = self._call("review_blind", "reviewer", REVIEW_A_SYSTEM,
                                   review_a_prompt(self.question, text, self.duration_sec), 8000)
            self.state.put("review_a:" + key_a[:16], key_a, rec, cost)
        key_b = canonical_hash({"a": key_a, "c": contract_sha, "s": sentences, "v": LANE_VERSION})
        out = self.state.get("review_b:" + key_b[:16], key_b)
        if out is None:
            raw, cost = self._call("review_contract", "reviewer", REVIEW_B_SYSTEM,
                                   review_b_prompt(self.question, contract, sentences, dossier, rec,
                                                   self.consequence_rule), 24000)
            out = normalize_review(raw, sentences, rec, self.consequence_rule)
            self.state.put("review_b:" + key_b[:16], key_b, out, cost)
        return out

    def _candidate(self, sentences: list[dict], source: str, contract_sha: str,
                   contract: dict | None = None) -> dict:
        text = narration_text(sentences)
        sha = policy.narration_sha256(text)
        for c in self.state.candidates(contract_sha):
            if c["sha256"] == sha:
                return c
        validation = validate_narration(sentences, self.known, self.duration_sec, contract, self.consequence_rule)
        return self.state.add_candidate({"source": source, "sentences": sentences, "sha256": sha,
                                         "contract_sha256": contract_sha, "validation": validation})

    def narration(self, contract: dict, contract_sha: str, evidence: dict) -> dict:
        dossier = apply_claim_kinds(self.dossier, evidence)
        key_o = canonical_hash({"c": contract_sha, "q": self.question, "d": self.duration_sec, "v": LANE_VERSION})
        openings = self.state.get("openings", key_o)
        if openings is None:
            raw, cost = self._call("openings", "writer", WRITER_SYSTEM,
                                   openings_prompt(self.question, contract, dossier, self.duration_sec), 12000)
            openings = validate_openings(raw)
            self.state.put("openings", key_o, openings, cost)
        key_n = canonical_hash({"o": canonical_hash(openings.get("selected")), "c": contract_sha,
                                "dir": self.direction, "v": LANE_VERSION})
        first = self.state.get("narration", key_n)
        if first is None:
            raw, cost = self._call("narration", "writer", WRITER_SYSTEM, narration_prompt(
                self.question, contract, openings, dossier, self.duration_sec, self.direction), 24000)
            first = normalize_sentences(raw)
            self.state.put("narration", key_n, first, cost)
        current = self._candidate(first, "writer", contract_sha, contract)
        # Resume from the latest candidate already reviewed under this contract.
        cands = self.state.candidates(contract_sha)
        if cands:
            current = cands[-1]
        while True:
            if not isinstance(current.get("review"), dict):
                review = self._review(current["sentences"], contract, contract_sha, dossier)
                self.state.update_candidate(current["version"], review=review)
                current = dict(current, review=review)
            review = current["review"]
            if not needs_repair(review) and not (current.get("validation") or {}).get("errors"):
                break
            if self.budget.remaining() <= 0:
                self.log(f"story_contract: repair budget spent ({self.budget.used()}/{self.budget.maximum}); "
                         "returning the strongest candidate with its open issues")
                break
            n = self.budget.consume(
                f"{len(review.get('factual_blockers') or [])} blockers, "
                f"{len(review.get('editorial_objectives') or [])} objectives",
                from_version=current["version"], contract_sha256=contract_sha)
            notes = dict(review)
            extra = [{"sentences": [], "code": e["code"], "problem": e["message"],
                      "fix": _FIX.get(e["code"], "cite a listed claim or cut the assertion")}
                     for e in (current.get("validation") or {}).get("errors") or []]
            notes["factual_blockers"] = (list(review.get("factual_blockers") or []) + extra
                                         + list(review.get("consequence_blockers") or []))
            raw, cost = self._call(f"repair_{n}", "writer", REPAIR_SYSTEM, repair_prompt(
                self.question, contract, current["sentences"], notes, dossier, self.duration_sec), 24000)
            self.state.data.setdefault("costs", []).append({"stage": f"repair_{n}", "cost_usd": round(cost, 6)})
            self.state.save()
            current = self._candidate(normalize_sentences(raw), f"repair_{n}", contract_sha, contract)
        cands = self.state.candidates(contract_sha)
        chosen = select_candidate(cands)
        status, not_ready = narration_status(chosen)
        record = {"lane": LANE, "lane_version": LANE_VERSION, "question": self.question,
                  "status": status, "not_ready_reasons": not_ready,
                  "version": chosen["version"], "sha256": chosen["sha256"],
                  "contract_sha256": contract_sha, "text": narration_text(chosen["sentences"]),
                  "sentences": chosen["sentences"], "review": chosen["review"],
                  "validation": chosen.get("validation"), "openings": openings,
                  "repair_passes_used": self.budget.used(), "repair_passes_max": self.budget.maximum}
        _write_json(self._path(NARRATION_FILE), record)
        with open(self._path(NARRATION_MD), "w", encoding="utf-8") as h:
            h.write(narration_markdown(self.question, chosen, cands, self.budget, contract_sha, status))
        return record

    def approved_sha(self) -> str:
        approved = _read_json(self._path(NARRATION_APPROVED), {}) or {}
        return _text(approved.get("sha256"))

    def run(self, *, stop_after: str = "", approve_narration: str = "") -> dict:
        """Through the narration approval. Returns the approved narration record, or raises a
        LaneStop. stop_after: 'contract' (or 'plan') or 'script'."""
        evidence = self.evidence()
        contract, contract_sha = self.contract(evidence)
        if stop_after in ("contract", "plan"):
            raise ContractApprovalRequired("stop_after contract: the approved contract is in place; "
                                           "rerun without --stop-after to write the narration",
                                           path=self._path(CONTRACT_APPROVED),
                                           details={"contract_sha256": contract_sha})
        record = self.narration(contract, contract_sha, evidence)
        if approve_narration:
            if approve_narration != record["sha256"]:
                raise NarrationApprovalRequired(
                    f"--approve-narration {approve_narration[:12]} does not match the narration on "
                    f"disk ({record['sha256'][:12]}); nothing approved", path=self._path(NARRATION_MD),
                    details={"sha256": record["sha256"]})
            _write_json(self._path(NARRATION_APPROVED), {"sha256": record["sha256"], "t": round(time.time(), 3),
                                                          "contract_sha256": contract_sha})
        approved = self.approved_sha()
        if stop_after == "script" or approved != record["sha256"]:
            raise NarrationApprovalRequired(
                f"Narration written for approval ({record['status']}): {self._path(NARRATION_MD)} "
                f"sha256 {record['sha256']}" + (" (an approval exists for a different hash)" if approved else ""),
                path=self._path(NARRATION_MD),
                details={"sha256": record["sha256"], "status": record["status"]})
        record["evidence"] = evidence
        record["contract"] = contract
        record["dossier"] = apply_claim_kinds(self.dossier, evidence)
        return record

    def segment(self, record: dict, *, title: str = "") -> dict:
        """The resumable `_state.json` for an APPROVED narration record (words unchanged)."""
        import story_contract_segment as seg
        if record.get("sha256") != self.approved_sha():
            raise NarrationApprovalRequired("segmenting needs the approved narration",
                                            path=self._path(NARRATION_MD))
        scenes = seg.build_scenes(record["sentences"], record["dossier"])
        plan = None
        if _text(os.environ.get("STORY_CONTRACT_VISUAL_PLAN", "1")) != "0":
            key = canonical_hash({"n": record["sha256"], "scenes": [s["narration"] for s in scenes],
                                  "v": LANE_VERSION})
            plan = self.state.get("visual_plan", key)
            if plan is None:
                plan, cost = self._call("visual_plan", "writer", "You are an illustration director.",
                                        seg.plan_visuals_prompt(self.question, scenes, record.get("contract") or {}),
                                        12000)
                self.state.put("visual_plan", key, plan, cost)
        state = seg.strip_private(seg.build_state(record, title=title or self.question,
                                                  visual_plan=plan, duration_sec=self.duration_sec))
        with open(self._path("segment_report.md"), "w", encoding="utf-8") as h:
            h.write(seg.segment_report(state))
        return state

    def cost_summary(self) -> dict:
        try:
            import usage_ledger
            return usage_ledger.summarize(os.path.join(self.output_dir, usage_ledger.LEDGER_FILENAME))
        except Exception:  # noqa: BLE001
            return {}
