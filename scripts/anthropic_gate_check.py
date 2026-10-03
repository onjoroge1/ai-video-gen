"""Is the Anthropic billing gate open for the key in .env? Three requests, no spend beyond one token.

The API has no endpoint that returns the credit balance; the console is the only place that
shows it. What a key CAN observe is the gate itself, and the three calls below separate its
possible states:

  1. GET  /v1/models                 credit-free -> proves the key is valid and names its org
  2. POST /v1/messages/count_tokens  free but metered -> sits behind the billing gate
  3. POST /v1/messages (1 token)     paid -> the call the pipeline actually makes

Key valid + (2) and (3) refused with "credit balance is too low" = the gate is closed at
Anthropic's side regardless of what the console balance says.

    python3 scripts/anthropic_gate_check.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        sys.exit("ANTHROPIC_API_KEY is not set in .env")
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    # A user-scoped key (the newer "linked" kind) must name the workspace on every request;
    # a workspace-scoped key must not. ANTHROPIC_WORKSPACE_ID in .env covers the first kind.
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    if workspace:
        headers["anthropic-workspace-id"] = workspace
    model = "claude-haiku-4-5-20251001"
    workspace = headers.get("anthropic-workspace-id", "")
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  key ...{key[-6:]}  base {base}"
          + (f"  workspace {workspace}" if workspace else ""))

    checks = [
        ("models (credit-free)", "GET", "/v1/models?limit=1", None),
        ("count_tokens (free, metered)", "POST", "/v1/messages/count_tokens",
         {"model": model, "messages": [{"role": "user", "content": "hi"}]}),
        ("messages (paid, 1 token)", "POST", "/v1/messages",
         {"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}),
    ]
    gate_open = None
    for label, method, path, body in checks:
        try:
            r = requests.request(method, base + path, headers=headers, json=body, timeout=30)
        except requests.RequestException as exc:
            print(f"  {label:30} network error: {exc}")
            continue
        org = r.headers.get("anthropic-organization-id", "")
        req = r.headers.get("request-id", "")
        if r.ok:
            note = "OK"
            if path == "/v1/messages":
                gate_open = True
                usage = r.json().get("usage", {})
                note = f"OK  usage={usage}"
        else:
            try:
                err = r.json().get("error", {})
                note = f"{err.get('type')}: {err.get('message')}"
            except ValueError:
                note = r.text[:160]
            if path == "/v1/messages":
                gate_open = False
        print(f"  {label:30} HTTP {r.status_code}  {note}")
        if org:
            print(f"  {'':30} org {org}  request {req}")
    print()
    if gate_open:
        print("GATE OPEN: paid requests succeed. The pipeline can run.")
    elif gate_open is False:
        print("GATE CLOSED: the key is accepted but metered requests are refused. Nothing on this "
              "machine changes that; the console balance and invoices decide it, and if those "
              "look healthy the state is stuck on Anthropic's side (quote the org and request ids).")
    else:
        print("UNDETERMINED: the paid request did not complete.")
    return 0 if gate_open else 1


if __name__ == "__main__":
    sys.exit(main())
