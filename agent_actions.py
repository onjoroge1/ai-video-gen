"""Persistent, single-use action approvals for narrow headless ReelForge operations.

An action is not a service account and carries no general studio authority.  An unauthenticated
client may propose one immutable directed-video pilot, but only an authenticated studio session
may approve it.  Approval rotates the one-time execution capability to the action's random UUID,
so the approval UI can immediately enqueue the exact approved payload without a second user step.
Full-film generation is intentionally not an operation in this module.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import db


OPERATION = "directed_pilot"
class AgentActionError(RuntimeError):
    pass


class AgentActionStorageError(AgentActionError):
    pass


class AgentActionConflict(AgentActionError):
    pass


class AgentActionForbidden(AgentActionError):
    pass


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_claim_token(action: dict, supplied: str) -> bool:
    expected = str(action.get("claim_token_sha256") or "")
    actual = token_digest(str(supplied or ""))
    return bool(expected and supplied and hmac.compare_digest(expected, actual))


def public_action(action: dict, *, include_private: bool = False) -> dict:
    """Return the auditable summary; never return the normalized spec or token digest."""
    out = {
        "action_id": action.get("action_id"),
        "operation": action.get("operation"),
        "status": effective_status(action),
        "title": action.get("title"),
        "spec_sha256": action.get("spec_sha256"),
        "estimated_cost_usd": float(action.get("estimated_cost_usd") or 0),
        "cost_ceiling_usd": float(action.get("cost_ceiling_usd") or 0),
        "scope": "first-45-pilot",
        "created_at": _iso(action.get("created_at")),
        "expires_at": _iso(action.get("expires_at")),
        "approved_at": _iso(action.get("approved_at")),
    }
    if include_private:
        out["job_id"] = action.get("job_id") or ""
        out["job"] = action.get("job") or {}
        out["finished_video"] = action.get("finished_video") or {}
        out["error"] = action.get("error") or ""
    return out


def effective_status(action: dict, now: datetime | None = None) -> str:
    status = str(action.get("status") or "")
    expires = action.get("expires_at")
    current = now or datetime.now(timezone.utc)
    if status in {"pending", "approved"} and expires:
        if getattr(expires, "tzinfo", None) is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= current:
            return "expired"
    return status


def _iso(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


class PostgresAgentActionRepository:
    def _connection(self):
        conn = db._conn()
        if conn is None:
            raise AgentActionStorageError("Agent actions require durable Postgres storage")
        return conn

    @staticmethod
    def _ensure(cur) -> None:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_actions (
                action_id text PRIMARY KEY,
                operation text NOT NULL,
                status text NOT NULL,
                title text NOT NULL,
                spec_sha256 text NOT NULL,
                payload jsonb NOT NULL,
                claim_token_sha256 text NOT NULL,
                estimated_cost_usd numeric(10,4) NOT NULL,
                cost_ceiling_usd numeric(10,4) NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                expires_at timestamptz NOT NULL,
                approved_at timestamptz,
                approved_by text,
                consumed_at timestamptz,
                job_id text,
                error text
            )""")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS agent_actions_pending_idx
            ON agent_actions (status, expires_at DESC)""")

    @staticmethod
    def _row(cur, row) -> dict | None:
        if not row:
            return None
        columns = [item.name if hasattr(item, "name") else item[0] for item in cur.description]
        return dict(zip(columns, row))

    def create(self, *, title: str, spec_sha256: str, payload: dict,
               claim_token_sha256: str, estimated_cost_usd: float,
               cost_ceiling_usd: float, ttl_seconds: int) -> dict:
        conn = None
        try:
            conn = self._connection()
            cur = conn.cursor()
            self._ensure(cur)
            hourly_limit = max(1, int(os.environ.get("AGENT_ACTION_RATE_LIMIT_PER_HOUR", "10")))
            cur.execute("SELECT count(*) FROM agent_actions WHERE created_at > now()-interval '1 hour'")
            if int(cur.fetchone()[0]) >= hourly_limit:
                raise AgentActionConflict("Agent action creation rate limit reached")
            action_id = "act_" + uuid.uuid4().hex
            cur.execute("""
                INSERT INTO agent_actions
                    (action_id,operation,status,title,spec_sha256,payload,claim_token_sha256,
                     estimated_cost_usd,cost_ceiling_usd,expires_at)
                VALUES (%s,%s,'pending',%s,%s,%s::jsonb,%s,%s,%s,
                        now()+(%s * interval '1 second'))
                RETURNING *
                """, (action_id, OPERATION, title, spec_sha256,
                        json.dumps(payload, separators=(",", ":")), claim_token_sha256,
                        Decimal(str(estimated_cost_usd)), Decimal(str(cost_ceiling_usd)),
                        int(ttl_seconds)))
            action = self._row(cur, cur.fetchone())
            conn.commit()
            return action or {}
        except AgentActionError:
            if conn:
                conn.rollback()
            raise
        except Exception as exc:
            if conn:
                conn.rollback()
            raise AgentActionStorageError(str(exc)) from exc
        finally:
            if conn:
                conn.close()

    def get(self, action_id: str, *, for_update: bool = False, conn=None) -> dict | None:
        owned = conn is None
        try:
            conn = conn or self._connection()
            cur = conn.cursor()
            self._ensure(cur)
            cur.execute("SELECT * FROM agent_actions WHERE action_id=%s" +
                        (" FOR UPDATE" if for_update else ""), (action_id,))
            return self._row(cur, cur.fetchone())
        except AgentActionError:
            raise
        except Exception as exc:
            raise AgentActionStorageError(str(exc)) from exc
        finally:
            if owned and conn:
                conn.close()

    def pending(self, limit: int = 50) -> list[dict]:
        conn = None
        try:
            conn = self._connection()
            cur = conn.cursor()
            self._ensure(cur)
            cur.execute("""
                SELECT * FROM agent_actions
                WHERE status IN ('pending','approved') AND expires_at > now()
                ORDER BY created_at DESC LIMIT %s""", (max(1, min(limit, 100)),))
            return [self._row(cur, row) or {} for row in cur.fetchall()]
        except Exception as exc:
            if isinstance(exc, AgentActionError):
                raise
            raise AgentActionStorageError(str(exc)) from exc
        finally:
            if conn:
                conn.close()

    def approve(self, action_id: str, *, spec_sha256: str, cost_ceiling_usd: float,
                approver: str) -> dict:
        conn = None
        try:
            conn = self._connection()
            action = self.get(action_id, for_update=True, conn=conn)
            if not action:
                raise AgentActionConflict("Agent action not found")
            if effective_status(action) == "expired":
                raise AgentActionConflict("Agent action expired")
            if action["status"] != "pending":
                raise AgentActionConflict(f"Agent action is already {action['status']}")
            if not hmac.compare_digest(action["spec_sha256"], spec_sha256):
                raise AgentActionConflict("Specification hash changed")
            if Decimal(str(action["cost_ceiling_usd"])) != Decimal(str(cost_ceiling_usd)):
                raise AgentActionConflict("Cost ceiling changed")
            cur = conn.cursor()
            # Once the authenticated operator approves the immutable spec+ceiling, rotate the
            # one-time execution capability to this action's 128-bit random UUID.  The approval
            # page can then enqueue immediately without depending on another tab's sessionStorage.
            # claim() still consumes it exactly once and all spec/cost validation remains intact.
            cur.execute("""
                UPDATE agent_actions
                SET status='approved',approved_at=now(),approved_by=%s,claim_token_sha256=%s
                WHERE action_id=%s RETURNING *""",
                (approver, token_digest(action_id), action_id))
            approved = self._row(cur, cur.fetchone()) or {}
            conn.commit()
            return approved
        except AgentActionError:
            if conn:
                conn.rollback()
            raise
        except Exception as exc:
            if conn:
                conn.rollback()
            raise AgentActionStorageError(str(exc)) from exc
        finally:
            if conn:
                conn.close()

    def reject(self, action_id: str, *, approver: str) -> dict:
        return self._transition_pending(action_id, "rejected", approver=approver)

    def claim(self, action_id: str, *, claim_token: str) -> dict:
        conn = None
        try:
            conn = self._connection()
            action = self.get(action_id, for_update=True, conn=conn)
            if not action or not verify_claim_token(action, claim_token):
                raise AgentActionForbidden("Invalid agent action claim token")
            if effective_status(action) == "expired":
                raise AgentActionConflict("Agent action expired")
            if action["status"] != "approved":
                raise AgentActionConflict("Agent action has not been approved")
            cur = conn.cursor()
            cur.execute("""
                UPDATE agent_actions SET status='executing',consumed_at=now()
                WHERE action_id=%s RETURNING *""", (action_id,))
            claimed = self._row(cur, cur.fetchone()) or {}
            conn.commit()
            return claimed
        except AgentActionError:
            if conn:
                conn.rollback()
            raise
        except Exception as exc:
            if conn:
                conn.rollback()
            raise AgentActionStorageError(str(exc)) from exc
        finally:
            if conn:
                conn.close()

    def mark_queued(self, action_id: str, job_id: str) -> dict:
        return self._transition(action_id, "queued", job_id=job_id)

    def mark_failed(self, action_id: str, error: str) -> dict:
        return self._transition(action_id, "failed", error=str(error)[:500])

    def _transition_pending(self, action_id: str, status: str, *, approver: str) -> dict:
        conn = None
        try:
            conn = self._connection()
            action = self.get(action_id, for_update=True, conn=conn)
            if not action or action["status"] != "pending":
                raise AgentActionConflict("Only a pending action can be rejected")
            cur = conn.cursor()
            cur.execute("""
                UPDATE agent_actions SET status=%s,approved_at=now(),approved_by=%s
                WHERE action_id=%s RETURNING *""", (status, approver, action_id))
            result = self._row(cur, cur.fetchone()) or {}
            conn.commit()
            return result
        except AgentActionError:
            if conn:
                conn.rollback()
            raise
        except Exception as exc:
            if conn:
                conn.rollback()
            raise AgentActionStorageError(str(exc)) from exc
        finally:
            if conn:
                conn.close()

    def _transition(self, action_id: str, status: str, **fields) -> dict:
        conn = None
        try:
            conn = self._connection()
            cur = conn.cursor()
            self._ensure(cur)
            assignments = ["status=%s"]
            values: list[Any] = [status]
            for field in ("job_id", "error"):
                if field in fields:
                    assignments.append(f"{field}=%s")
                    values.append(fields[field])
            values.append(action_id)
            cur.execute(f"UPDATE agent_actions SET {','.join(assignments)} "
                        "WHERE action_id=%s RETURNING *", tuple(values))
            result = self._row(cur, cur.fetchone())
            if not result:
                raise AgentActionConflict("Agent action not found")
            conn.commit()
            return result
        except AgentActionError:
            if conn:
                conn.rollback()
            raise
        except Exception as exc:
            if conn:
                conn.rollback()
            raise AgentActionStorageError(str(exc)) from exc
        finally:
            if conn:
                conn.close()


_repository = PostgresAgentActionRepository()


def repository():
    return _repository


def new_claim_token() -> str:
    return secrets.token_urlsafe(32)
