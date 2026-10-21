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
    ("voice", "It sounds spoken; humour and personality come from the situation, not from jokes "
              "bolted on."),
)
RUBRIC_IDS = tuple(item for item, _ in RUBRIC)
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

    def call(self, *, role: str, stage: str, system: str, user: str, max_tokens: int = 8000):
        """(parsed JSON, cost_usd). One retry when the reply is not parseable JSON."""
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
                data = parse_json_reply(response.content[0].text)
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


# ── the contract ──────────────────────────────────────────────────────────────────────────────

CONTRACT_SYSTEM = """You are a documentary story editor. You plan a story around ONE question a \
viewer would want answered, and you choose the question and its answer together, from evidence \
you are given. You never invent facts: every element cites claim IDs from the list."""


def contract_prompt(question: str, dossier: dict, evidence: dict, duration_sec: int,
                    direction: str = "", errors: list | None = None) -> str:
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

Write the story contract.
- central_question: the one question the opening asks and the ending answers. It must be one the
  evidence can actually answer.
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
{{"topic": "...", "central_question": "...", "ending_answer": "...",
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


def validate_contract(contract: dict, known_claims) -> dict:
    """Deterministic checks on a story contract. {'passed', 'errors', 'warnings'}."""
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
from the situation. A number appears only when it serves the story."""


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

Write the COMPLETE narration as one continuous piece, about {target} words ({duration_sec} s).
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
Never make the contract's forbidden claims.

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


# The writer's view of its inputs leaking into the narration ("according to the supplied record",
# lionfish dry run 2026-10-21). A listener has no record, contract or title card in front of them.
_PROMPT_LEAK = re.compile(r"\b(supplied|the (claims?|dossier|contract|brief|evidence provided)|"
                          r"the title(?:'s)?|this (video|narration)'?s? (title|question))\b", re.I)


def validate_narration(sentences: list[dict], known_claims, duration_sec: int) -> dict:
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
            warnings.append({"code": "PROMPT_LEAK", "message": f"sentence {i} talks about the "
                             f"research or the brief ({leak.group(0)!r}), not the story"})
    words = sum(_words(s["text"]) for s in sentences)
    target = duration_sec * WORDS_PER_SECOND
    if target and not (0.75 * target <= words <= 1.25 * target):
        warnings.append({"code": "LENGTH", "message": f"{words} words for a ~{int(target)}-word target (length is a request)"})
    return {"passed": not errors, "errors": errors, "warnings": warnings, "words": words}


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
- ending_answer: the answer the ending gives to the central question ("none" if it does not answer).

Reply with JSON only:
{{"central_question": "...", "question_quote": "...", "question_position": 0.1,
  "main_idea": "...", "human": "...", "pivotal_discovery": "...", "ending_answer": "..."}}"""


def review_b_prompt(question: str, contract: dict, sentences: list[dict], dossier: dict,
                    reconstruction: dict) -> str:
    ids = set(c for s in sentences for c in s["claim_ids"])
    numbered = "\n".join(f"[{i}] ({s['kind']}; {', '.join(s['claim_ids']) or '-'}) {s['text']}"
                         for i, s in enumerate(sentences, 1))
    rubric = "\n".join(f"- {item}: {desc}" for item, desc in RUBRIC)
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
   Every score of 0 or 1 needs an editorial objective.
6. editorial_objectives: AT MOST THREE, the ones that matter most. Each with its location
   (sentence numbers), the problem, the repair objective, and the material to preserve.

Reply with JSON only:
{{"reconstruction_match": {{"central_question": {{"match": true, "note": "..."}},
                            "human": {{"match": true, "note": "..."}},
                            "pivotal_discovery": {{"match": true, "note": "..."}},
                            "ending_answer": {{"match": true, "note": "..."}}}},
  "opening_ending": {{"same_question": true, "opening_quote": "...", "ending_quote": "...", "note": "..."}},
  "removal": [{{"sentences": [1, 4], "loss": "...", "verdict": "keep|cut|merge"}}],
  "factual_blockers": [{{"sentences": [7], "problem": "...", "fix": "..."}}],
  "rubric": [{{"item": "human_entry", "score": 2, "quote": "...", "note": "..."}}],
  "editorial_objectives": [{{"sentences": [9, 12], "problem": "...", "objective": "...", "preserve": "..."}}],
  "overall": "one paragraph"}}"""


def normalize_review(raw: dict, sentences: list[dict], reconstruction: dict) -> dict:
    text_norm = _norm(narration_text(sentences))
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
                       "quote_verified": bool(quote) and _norm(quote) in text_norm})
    missing = [i for i in RUBRIC_IDS if i not in seen]
    objectives = [o for o in (raw or {}).get("editorial_objectives") or [] if isinstance(o, dict)
                  and _text(o.get("objective"))]
    # Every 0-1 score needs a repair objective. One the reviewer named but did not tie to an
    # objective is added from its own note; the list stays at MAX_EDITORIAL_OBJECTIVES, and
    # anything past it is kept as deferred rather than silently dropped.
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
        "rubric_max": 3 * len(RUBRIC_IDS),
        "editorial_objectives": objectives,
        "deferred_objectives": deferred,
        "overall": _text((raw or {}).get("overall")),
    }


def compare_prompt(question: str, narration_a: str, narration_b: str, duration_sec: int = 300) -> str:
    """Two narrations of one commission, judged side by side on the lane's rubric.

    The calibration the design asks for before the reviewer may gate anything (measuring plan,
    step 3): on lionfish v1 (compiled catalogue) against v2 (the Carlson / freezer story) it must
    prefer v2 and say why. Run in both orders (evals/promptfoo/story_reviewer.yaml); ties allowed.
    """
    rubric = "\n".join(f"- {item}: {desc}" for item, desc in RUBRIC)
    return f"""Two narrations were written for the same ~{duration_sec}-second illustrated documentary
commission: "{question}". You did not write either.

NARRATION A:
{narration_a}

NARRATION B:
{narration_b}

For each, reconstruct the central question it asks and the answer its ending gives. Then score
each on this rubric, 0-3 per item, quoting the narration as evidence:
{rubric}

Which would you publish? Prefer the one a viewer would keep watching because they want the
answer, not the one with more facts. A tie is allowed only if you genuinely cannot separate them.
Give your reasons, each with a short quotation from the preferred narration (and, where it helps,
one from the other).

Reply with JSON only:
{{"a": {{"central_question": "...", "ending_answer": "...", "rubric": {{"human_entry": 0, "...": 0}}}},
  "b": {{"central_question": "...", "ending_answer": "...", "rubric": {{"human_entry": 0, "...": 0}}}},
  "preferred": "A|B|tie",
  "reasons": [{{"reason": "...", "quote_preferred": "...", "quote_other": "..."}}]}}"""


def needs_repair(review: dict) -> bool:
    return bool((review or {}).get("factual_blockers") or (review or {}).get("editorial_objectives"))


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

Return the COMPLETE revised narration in the same sentence format. Sentences the notes do not touch
must come back word for word.

Reply with JSON only: {_narration_schema()}"""


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
    if review.get("factual_blockers"):
        lines += ["## ✗ Open factual blockers", ""] + [
            f"- sentences {b.get('sentences')}: {b.get('problem')} — fix: {b.get('fix')}"
            for b in review["factual_blockers"]] + [""]
    if review.get("editorial_objectives"):
        lines += ["## Open editorial objectives", ""] + [
            f"- sentences {o.get('sentences')}: {o.get('problem')} → {o.get('objective')}"
            + (f" (preserve: {o.get('preserve')})" if o.get("preserve") else "")
            for o in review["editorial_objectives"]] + [""]
    rec = review.get("reconstruction") or {}
    lines += ["## Blind reconstruction (reviewer saw only the narration)", "",
              f"- question: {rec.get('central_question')} (heard at ~{rec.get('question_position')}: “{rec.get('question_quote')}”)",
              f"- main idea: {rec.get('main_idea')}", f"- human: {rec.get('human')}",
              f"- pivot: {rec.get('pivotal_discovery')}", f"- ending answer: {rec.get('ending_answer')}",
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

    def __post_init__(self):
        os.makedirs(self.output_dir, exist_ok=True)
        self.state = LaneState(self.output_dir)
        self.budget = RepairBudget(self.output_dir)
        self.caller = self.caller or Caller()
        self.known = {c["claim_id"] for c in _claims(self.dossier)}

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
                               evidence_prompt(self.question, self.dossier, self.pack), 8000)
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
            check = validate_contract(approved, self.known)
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
        if cached is None:
            errors, total = None, 0.0
            for attempt in range(2):
                raw, cost = self._call("contract", "writer", CONTRACT_SYSTEM, contract_prompt(
                    self.question, dossier, evidence, self.duration_sec, self.direction, errors), 8000)
                total += cost
                check = validate_contract(raw, self.known)
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

    # 3-6. openings, narration, review, repairs
    def _review(self, sentences: list[dict], contract: dict, contract_sha: str, dossier: dict) -> dict:
        text = narration_text(sentences)
        reviewer = model_for("reviewer", getattr(self.caller, "provider", None) or None)
        key_a = canonical_hash({"n": policy.narration_sha256(text), "q": self.question, "m": reviewer, "v": LANE_VERSION})
        rec = self.state.get("review_a:" + key_a[:16], key_a)
        if rec is None:
            rec, cost = self._call("review_blind", "reviewer", REVIEW_A_SYSTEM,
                                   review_a_prompt(self.question, text, self.duration_sec), 3000)
            self.state.put("review_a:" + key_a[:16], key_a, rec, cost)
        key_b = canonical_hash({"a": key_a, "c": contract_sha, "s": sentences, "v": LANE_VERSION})
        out = self.state.get("review_b:" + key_b[:16], key_b)
        if out is None:
            raw, cost = self._call("review_contract", "reviewer", REVIEW_B_SYSTEM,
                                   review_b_prompt(self.question, contract, sentences, dossier, rec), 8000)
            out = normalize_review(raw, sentences, rec)
            self.state.put("review_b:" + key_b[:16], key_b, out, cost)
        return out

    def _candidate(self, sentences: list[dict], source: str, contract_sha: str) -> dict:
        text = narration_text(sentences)
        sha = policy.narration_sha256(text)
        for c in self.state.candidates(contract_sha):
            if c["sha256"] == sha:
                return c
        validation = validate_narration(sentences, self.known, self.duration_sec)
        return self.state.add_candidate({"source": source, "sentences": sentences, "sha256": sha,
                                         "contract_sha256": contract_sha, "validation": validation})

    def narration(self, contract: dict, contract_sha: str, evidence: dict) -> dict:
        dossier = apply_claim_kinds(self.dossier, evidence)
        key_o = canonical_hash({"c": contract_sha, "q": self.question, "d": self.duration_sec, "v": LANE_VERSION})
        openings = self.state.get("openings", key_o)
        if openings is None:
            raw, cost = self._call("openings", "writer", WRITER_SYSTEM,
                                   openings_prompt(self.question, contract, dossier, self.duration_sec), 6000)
            openings = validate_openings(raw)
            self.state.put("openings", key_o, openings, cost)
        key_n = canonical_hash({"o": canonical_hash(openings.get("selected")), "c": contract_sha,
                                "dir": self.direction, "v": LANE_VERSION})
        first = self.state.get("narration", key_n)
        if first is None:
            raw, cost = self._call("narration", "writer", WRITER_SYSTEM, narration_prompt(
                self.question, contract, openings, dossier, self.duration_sec, self.direction), 16000)
            first = normalize_sentences(raw)
            self.state.put("narration", key_n, first, cost)
        current = self._candidate(first, "writer", contract_sha)
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
            extra = [{"sentences": [], "problem": e["message"], "fix": "cite a listed claim or cut the assertion"}
                     for e in (current.get("validation") or {}).get("errors") or []]
            notes["factual_blockers"] = list(review.get("factual_blockers") or []) + extra
            raw, cost = self._call(f"repair_{n}", "writer", REPAIR_SYSTEM, repair_prompt(
                self.question, contract, current["sentences"], notes, dossier, self.duration_sec), 16000)
            self.state.data.setdefault("costs", []).append({"stage": f"repair_{n}", "cost_usd": round(cost, 6)})
            self.state.save()
            current = self._candidate(normalize_sentences(raw), f"repair_{n}", contract_sha)
        cands = self.state.candidates(contract_sha)
        chosen = select_candidate(cands)
        clean = not (chosen["review"].get("factual_blockers") or (chosen.get("validation") or {}).get("errors"))
        status = ("ready" if clean and not chosen["review"].get("editorial_objectives")
                  else ("ready_with_open_objectives" if clean else "evidence_gap"))
        record = {"lane": LANE, "lane_version": LANE_VERSION, "question": self.question,
                  "status": status, "version": chosen["version"], "sha256": chosen["sha256"],
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
