"""Recognize explicit account rejections without treating them as evidence failures.

Only a provider's HTTP rejection qualifies. Timeouts, server errors and malformed model
output have unknown or different outcomes and must not use this manual-resume path.
"""
import re


MESSAGES = {
    "insufficient_credit": "Anthropic credit balance is too low for this request. Add credit to the account used by ReelForge, then resume this video.",
    "authentication": "Anthropic rejected the configured credentials. Restore provider access, then resume this video.",
    "permission": "Anthropic denied this request. Restore access to the approved model, then resume this video.",
}
STATUSES = {"insufficient_credit": {400, 402}, "authentication": {401}, "permission": {403}}


def _block(status: int, message: str) -> dict:
    message = message.casefold()
    if status in {400, 402} and (
            "credit balance is too lo" in message or "insufficient credit" in message):
        code = "insufficient_credit"
    elif status == 401:
        code = "authentication"
    elif status == 403:
        code = "permission"
    else:
        return {}
    return {"provider": "anthropic", "code": code, "http_status": status,
            "message": MESSAGES[code]}


def from_exception(exc: Exception) -> dict:
    """Read status and body from an SDK HTTP error; never emit its raw body."""
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        return {}
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    message = error.get("message", "") if isinstance(error, dict) else ""
    return _block(status, str(message))


def from_recorded_error(error: str) -> dict:
    """Compatibility for saved SDK rejections from before structured blocks existed.

    The dispatch transaction also verifies the actual single failed Anthropic stage,
    its reservation and checkpoint; a public error string alone never grants a retry.
    """
    match = re.search(r"Error code: (400|401|402|403)\b", str(error or ""))
    return _block(int(match[1]), str(error)) if match else {}


def for_job(job: dict) -> dict:
    if job.get("status") not in {"error", "provider_blocked"}:
        return {}
    saved = (job.get("result") or {}).get("provider_block") or {}
    code, status = saved.get("code"), saved.get("http_status")
    if (job.get("status") == "provider_blocked" and saved.get("provider") == "anthropic"
            and code in STATUSES and isinstance(status, int) and status in STATUSES[code]):
        return {"provider": "anthropic", "code": code, "http_status": status,
                "message": MESSAGES[code]}
    return from_recorded_error(job.get("error"))


class ProviderBlocked(BaseException):
    """Control transfer to the worker, immune to optional content-repair fallbacks."""

    def __init__(self, block: dict):
        self.block = dict(block)
        self.stage_key = ""
        super().__init__(block["message"])
