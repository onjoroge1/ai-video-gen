"""Fact validation gate (GENERIC). No facts gate → no render. Extracts every factual/numeric claim in
the narration, assesses each (supported / needs_qualification / unsupported / false), recomputes
derived numbers, checks unit consistency, and REJECTS unsupported absolutes unless they are tied to a
declared scenario. Sources are labelled honestly — claims verified from model knowledge are labelled as
such; this module never fabricates a citation (see the no-synthetic-data rule). An optional
`web_search(query)->[{title,url,snippet}]` callback can be supplied to attach real external sources.

Returns a report; `apply_rewrites` folds the required qualifications back into the narration before the
script is approved for render."""
from __future__ import annotations
import os, json

_SYS = ("You are a rigorous fact-checker for a science explainer. You will be given the narration lines "
        "of a short video and its scenario/subject. Identify EVERY factual or numeric claim. For each, "
        "judge it against well-established science. Be strict about ABSOLUTES ('always', 'never', "
        "'almost no', 'instantly', exact numbers) — an absolute or specific number is only acceptable if "
        "it is either universally true or explicitly tied to stated conditions (e.g. a specific speed, "
        "size, material, environment). If a claim depends on conditions that the narration omits, mark it "
        "needs_qualification and supply a corrected line that adds the qualifying condition. Recompute any "
        "derived number and flag mismatches. Check units are consistent. "
        "Return ONLY JSON: {\"claims\":[{\"line_idx\":int,\"text\":str,"
        "\"type\":\"numeric|absolute|causal|definition\",\"assessment\":\"supported|needs_qualification|"
        "unsupported|false\",\"correct_value_or_range\":str,\"unit\":str,\"qualification\":str,"
        "\"confidence\":0.0-1.0,\"suggested_line\":str}],\"unit_issues\":[str],"
        "\"derived_recompute\":[{\"claim\":str,\"stated\":str,\"expected\":str,\"ok\":bool}],"
        "\"notes\":str}. suggested_line is REQUIRED whenever assessment is not 'supported'.")


def validate_claims(narration_lines, subject, cost=None, log=print, web_search=None, model="claude-opus-4-8"):
    import explainer_pipeline as ep
    lines = "\n".join(f"[{i}] {t}" for i, t in enumerate(narration_lines))
    try:
        r = ep._claude().messages.create(model=model, max_tokens=1500, system=_SYS,
            messages=[{"role": "user", "content": f"SUBJECT/SCENARIO: {subject}\n\nNARRATION LINES:\n{lines}"}])
        if cost is not None:
            cost.append(ep._msg_cost(r.usage))
        obj, _ = ep._parse_script_json(r.content[0].text)
        rep = obj if isinstance(obj, dict) else {"claims": [], "notes": "parse_failed"}
    except Exception as e:
        return {"ok": False, "error": str(e), "claims": [], "gate": "ERROR (fact check unavailable → no render)"}

    claims = rep.get("claims", [])
    for c in claims:
        c.setdefault("source_label", "model_knowledge:" + model)
    # optional real external verification for numeric/absolute claims (attaches genuine sources only)
    if web_search:
        for c in claims:
            if c.get("type") in ("numeric", "absolute") and c.get("confidence", 1) < 0.85:
                try:
                    hits = web_search(f"{subject} {c['text']}")[:2]
                    if hits:
                        c["sources"] = hits
                        c["source_label"] = "web:" + ";".join(h.get("url", "") for h in hits)
                except Exception:
                    pass

    unsupported = [c for c in claims if c.get("assessment") in ("unsupported", "false")]
    needs_qual = [c for c in claims if c.get("assessment") == "needs_qualification"]
    unit_issues = rep.get("unit_issues", [])
    bad_derived = [d for d in rep.get("derived_recompute", []) if not d.get("ok", True)]
    # required rewrites: qualify or correct every non-supported claim that offers a better line
    rewrites = {}
    for c in claims:
        if c.get("assessment") != "supported" and c.get("suggested_line") and c.get("line_idx") is not None:
            rewrites[int(c["line_idx"])] = c["suggested_line"]

    # GATE: pass only if no unsupported/false remain unrewritten, no unit issues, derived numbers ok
    unresolved = [c for c in unsupported if int(c.get("line_idx", -1)) not in rewrites]
    ok = not unresolved and not unit_issues and not bad_derived
    report = {"ok": ok, "subject": subject, "n_claims": len(claims), "claims": claims,
              "unsupported_or_false": [c.get("text") for c in unsupported],
              "needs_qualification": [c.get("text") for c in needs_qual],
              "unit_issues": unit_issues, "bad_derived": bad_derived,
              "required_rewrites": rewrites,
              "gate": "PASS" if ok else "FAIL (unresolved claims → no render)",
              "notes": rep.get("notes", "")}
    log(f"[facts] {len(claims)} claims · unsupported {len(unsupported)} · needs_qual {len(needs_qual)} "
        f"· unit {len(unit_issues)} · derived-bad {len(bad_derived)} → {report['gate']}")
    return report


def apply_rewrites(narration_lines, report):
    """Return narration with the fact-gate's required qualifications folded in."""
    out = list(narration_lines)
    for idx, line in (report.get("required_rewrites") or {}).items():
        if 0 <= int(idx) < len(out):
            out[int(idx)] = line
    return out


def validate_and_resolve(narration_lines, subject, cost=None, log=print, web_search=None, passes=2):
    """Validate → apply the required qualifications → RE-validate (bounded), so the gate reflects the
    narration that will actually be spoken. Returns (final_report, resolved_narration)."""
    narr = list(narration_lines)
    rep = validate_claims(narr, subject, cost, log, web_search)
    for _ in range(passes - 1):
        if rep.get("ok"):
            break
        rw = rep.get("required_rewrites") or {}
        if not rw:
            break                      # nothing left to auto-fix → a genuine gate failure
        narr = apply_rewrites(narr, rep)
        rep = validate_claims(narr, subject, cost, log, web_search)
    return rep, narr


def write_reports(report, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    json.dump({"claims": report.get("claims", [])}, open(os.path.join(out_dir, "sources.json"), "w"), indent=2, default=str)
    md = [f"# Fact validation — {report.get('subject','')}", "",
          f"**Gate: {report.get('gate')}** · {report.get('n_claims',0)} claims", ""]
    for c in report.get("claims", []):
        md.append(f"- [{c.get('assessment')}] ({c.get('confidence')}) \"{c.get('text')}\" — "
                  f"{c.get('correct_value_or_range','')} {c.get('unit','')} "
                  f"{'· QUALIFY: '+c['qualification'] if c.get('qualification') else ''} "
                  f"[{c.get('source_label','')}]")
    if report.get("unit_issues"):
        md += ["", "## Unit issues", *[f"- {u}" for u in report["unit_issues"]]]
    if report.get("required_rewrites"):
        md += ["", "## Required narration rewrites",
               *[f"- line {i}: {t}" for i, t in report["required_rewrites"].items()]]
    open(os.path.join(out_dir, "facts.md"), "w").write("\n".join(md))
    return out_dir
