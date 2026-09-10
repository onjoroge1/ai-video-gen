"""A private, durable research-to-story record, shared by recovery and review.

The JSON is authoritative; the table is a read-only projection. A saved pass is reusable
only for the same evidence, draft and validation contracts. Failed and unavailable states
remain visible without being promoted to a supported script.
"""
from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path

import claim_entailment as entailment
import story_compiler as compiler
import story_fact_model as facts

# Bump for validation behavior changes not already reflected in the contract versions below.
VERSION = 1
FILENAME = "research_handoff.json"


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def identity(beats, engine, claims, cases, question, repair_enabled):
    return {"version": VERSION, "question": question, "engine": engine,
            "draft_sha256": _hash(beats), "evidence_sha256": _hash(claims),
            "cases_sha256": _hash(cases or {}), "repair_enabled": bool(repair_enabled),
            "compiler": compiler.COMPILER_VERSION, "fact_model": facts.SCHEMA_VERSION,
            "entailment": entailment.ENTAILMENT_CONTRACT_VERSION,
            "roles_sha256": _hash({role: facts.role_function(role, engine)
                                    for role in facts.required_spine_roles(engine)})}


def _location():
    from durable_execution import current
    runtime = current()
    return (Path(runtime.output_dir) / FILENAME, runtime) if runtime else (None, None)


def rows(beats, claims, compiled, engine):
    judgments = {row["beat_id"]: row for row in (compiled.get("cascade") or {}).get("judgments") or []}
    failures = {}
    issues = (((compiled.get("cascade") or {}).get("structural") or [])
              + (compiled.get("unrepairable") or []) + (compiled.get("duplicate_across_roles") or [])
              + [row for row in compiled.get("relationships") or [] if not row.get("passed")])
    for row in issues:
        failures.setdefault(row.get("beat_id"), []).append(
            row.get("message") or row.get("reason") or row.get("code") or "Unresolved validation")
    required = facts.required_spine_roles(engine)
    result = []
    for beat in beats:
        event = facts.event_of(beat)
        role = beat.get("causal_role") or beat.get("role") or ""
        judgment = judgments.get(beat.get("beat_id")) or {}
        problems = failures.get(beat.get("beat_id")) or []
        result.append({"beat_id": beat.get("beat_id"), "role": role,
                       "required": role in required, "requirement": facts.role_function(role, engine),
                       "event": event["text"], "claim_ids": event["claim_refs"],
                       "evidence": [deepcopy(claims[ref]) for ref in event["claim_refs"] if ref in claims],
                       "status": "blocked" if problems else judgment.get("verdict", "unchecked"),
                       "reason": "; ".join(problems) or judgment.get("reason", ""),
                       "missing_details": judgment.get("unsupported_details") or [],
                       "supported_core": judgment.get("supported_core") or ""})
    return result


def record(key, beats, claims, prepared=None, costs=None):
    compiled = (prepared or {}).get("compiled") or {}
    return {"version": VERSION, "identity": key, "question": key["question"],
            "engine": key["engine"],
            "status": ("ready" if compiled.get("passed") else "blocked") if prepared else "checking",
            "research_claims": deepcopy(claims), "draft_beats": deepcopy(beats),
            "rows": rows((prepared or {}).get("beats") or beats, claims, compiled, key["engine"]),
            "prepared": deepcopy(prepared), "costs": costs or {}}


def save(payload):
    path, runtime = _location()
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        runtime.checkpoint("research-handoff")


def load(key):
    path, _ = _location()
    if not path or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("identity") != key or not payload.get("prepared"):
        return None
    compiled = payload["prepared"].get("compiled") or {}
    # An outage is an unfinished judgment, never a reusable rejection.
    if (compiled.get("cascade") or {}).get("unavailable"):
        return None
    return payload


def from_saved_failure(dossier, failure):
    """Read old jobs without rewriting them or inventing a reusable validation result."""
    claims = {c["claim_id"]: c for c in (failure.get("research_dossier") or dossier).get("claims") or []}
    report = failure.get("report") or {}
    engine = report.get("engine_id") or report.get("engine") or ""
    beats = (failure.get("script") or {}).get("beats") or []
    return {"version": VERSION, "status": "legacy_failure" if failure else "research_saved",
            "question": dossier.get("topic", ""),
            "engine": engine, "research_claims": claims, "draft_beats": beats,
            "rows": rows(beats, claims, report, engine), "prepared": None,
            "note": "Read-only view of saved evidence. This legacy snapshot is not a reusable pass."}


def render_table(payload):
    """Escape every model/source field; the view performs no provider or job mutation."""
    esc = lambda value: html.escape(str(value or ""))
    body = []
    for row in payload.get("rows") or []:
        evidence = "".join(
            f"<li><b>{esc(c.get('claim_id'))}</b>: {esc(c.get('claim'))}"
            f"<blockquote>{esc(c.get('support_quote'))}</blockquote>"
            f"<small>{esc(c.get('source_url'))}</small></li>" for c in row.get("evidence") or [])
        missing = "; ".join(row.get("missing_details") or [])
        body.append(f"<tr><th>{esc(row.get('role'))}<br><small>{esc(row.get('beat_id'))}</small></th>"
                    f"<td>{esc(row.get('event'))}</td><td><ul>{evidence}</ul></td>"
                    f"<td>{esc(row.get('status'))}<p>{esc(row.get('reason'))}</p>{esc(missing)}</td></tr>")
    def claim_rows(claims):
        return "".join(
            f"<tr><th>{esc(c.get('claim_id'))}</th><td>{esc(c.get('claim'))}</td>"
            f"<td><blockquote>{esc(c.get('support_quote'))}</blockquote><small>{esc(c.get('source_url'))}</small></td>"
            f"<td>Quote verified: {esc(str(c.get('quote_verified', 'unknown')))}<br>"
            f"Source reachable: {esc(str(c.get('source_reachable', 'unknown')))}</td></tr>"
            for c in claims)
    supplement_rows = claim_rows((payload.get("research_supplement") or {}).get("claims") or [])
    supplement_section = (
        "<h2>Focused research</h2><div class='table'><table><thead><tr><th>Claim</th>"
        "<th>Statement</th><th>Quotation and source</th><th>Retrieval</th></tr></thead>"
        f"<tbody>{supplement_rows}</tbody></table></div>" if supplement_rows else "")
    raw = esc(json.dumps(payload, indent=2, ensure_ascii=False))
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Research and story handoff · ReelForge</title><style>"
            "body{font:16px/1.5 system-ui;background:#090b10;color:#f5f7fa;margin:24px}"
            "main{max-width:1400px;margin:auto}a{color:#91bfff}.table{overflow:auto}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #465066;"
            "padding:12px;text-align:left;vertical-align:top;min-width:140px}"
            "td{max-width:520px}small,pre{overflow-wrap:anywhere}pre{white-space:pre-wrap}"
            "blockquote{margin:8px 0;border-left:3px solid #465066;padding-left:12px}"
            "ul{padding-left:18px}</style></head><body><main><a href='/agent/actions'>Agent approvals</a>"
            f"<h1>Research and story handoff</h1><p>{esc(payload.get('question'))}</p>"
            f"<p>Status: <b>{esc(payload.get('status'))}</b></p>"
            "<p>This is the factual story outline. A ready outline can proceed to script writing.</p>"
            f"<p>{esc(payload.get('failure'))}</p>"
            f"<p>{esc(payload.get('note'))}</p><h2>Story evidence</h2><div class='table'><table>"
            "<thead><tr><th>Story beat</th><th>Event</th><th>Saved evidence</th><th>Validation / missing facts</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div><h2>Saved research claims</h2><div class='table'><table>"
            "<thead><tr><th>Claim</th><th>Statement</th><th>Quotation and source</th><th>Retrieval</th></tr></thead>"
            f"<tbody>{claim_rows((payload.get('research_claims') or {}).values())}</tbody></table></div>"
            f"{supplement_section}<details><summary>Saved JSON</summary><pre>{raw}</pre>"
            "</details></main></body></html>")
