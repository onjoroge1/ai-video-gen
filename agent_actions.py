"""Persistent, single-use action approvals for narrow headless ReelForge operations.

An action is not a service account and carries no general studio authority.  An unauthenticated
client may propose one immutable directed-video spend boundary, but only an authenticated studio
session may approve it. Approval rotates the one-time execution capability to the action's random
UUID, so the approval UI can immediately enqueue the exact approved payload without a second user
step. A remaining-film action is separately hash-bound to its accepted pilot and never inherits the
pilot's spend authority.
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


DIRECTED_PILOT_OPERATION = "directed_pilot"
DIRECTED_FULL_FILM_OPERATION = "directed_full_film"
OPERATIONS = {DIRECTED_PILOT_OPERATION, DIRECTED_FULL_FILM_OPERATION}
# Compatibility name used by older tests and callers.
OPERATION = DIRECTED_PILOT_OPERATION
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
    operation = str(action.get("operation") or DIRECTED_PILOT_OPERATION)
    payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
    promotion = payload.get("promotion") if isinstance(payload.get("promotion"), dict) else {}
    out = {
        "action_id": action.get("action_id"),
        "operation": action.get("operation"),
        "status": effective_status(action),
        "title": action.get("title"),
        "spec_sha256": action.get("spec_sha256"),
        "estimated_cost_usd": float(action.get("estimated_cost_usd") or 0),
        "cost_ceiling_usd": float(action.get("cost_ceiling_usd") or 0),
        "scope": (promotion.get("scope") or "remaining-45-to-300"
                  if operation == DIRECTED_FULL_FILM_OPERATION else "first-45-pilot"),
        "created_at": _iso(action.get("created_at")),
        "expires_at": _iso(action.get("expires_at")),
        "approved_at": _iso(action.get("approved_at")),
    }
    if operation == DIRECTED_FULL_FILM_OPERATION:
        out["parent_job_id"] = promotion.get("parent_job_id") or ""
        out["parent_action_id"] = promotion.get("parent_action_id") or ""
        out["parent_video_sha256"] = promotion.get("parent_video_sha256") or ""
        out["content_spec_sha256"] = promotion.get("content_spec_sha256") or ""
        out["start_sec"] = float(promotion.get("start_sec") or 45.0)
        out["end_sec"] = float(promotion.get("end_sec") or 300.0)
        out["pilot_reused"] = True
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
               cost_ceiling_usd: float, ttl_seconds: int,
               operation: str = DIRECTED_PILOT_OPERATION) -> dict:
        if operation not in OPERATIONS:
            raise AgentActionConflict(f"Unsupported agent action operation: {operation}")
        conn = None
        try:
            conn = self._connection()
            cur = conn.cursor()
            self._ensure(cur)
            # Serialize proposals for the same immutable spend boundary.  The API performs a
            # fast lookup first, but this transaction lock also closes the concurrent-request
            # race between that lookup and INSERT.
            boundary = f"{operation}:{spec_sha256}:{Decimal(str(cost_ceiling_usd))}"
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (boundary,))
            existing = self._reusable_query(
                cur, operation=operation, spec_sha256=spec_sha256,
                cost_ceiling_usd=cost_ceiling_usd)
            if existing:
                existing["_reused"] = True
                conn.commit()
                return existing
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
                """, (action_id, operation, title, spec_sha256,
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

    def _reusable_query(self, cur, *, operation: str, spec_sha256: str,
                        cost_ceiling_usd: float) -> dict | None:
        cur.execute("""
            SELECT * FROM agent_actions
            WHERE operation=%s AND spec_sha256=%s AND cost_ceiling_usd=%s AND (
                status IN ('executing','queued','failed')
                OR (status IN ('pending','approved') AND expires_at > now())
            )
            ORDER BY CASE status
                WHEN 'executing' THEN 0
                WHEN 'queued' THEN 1
                WHEN 'failed' THEN 2
                WHEN 'approved' THEN 3
                ELSE 4
            END, created_at DESC
            LIMIT 1
        """, (operation, spec_sha256, Decimal(str(cost_ceiling_usd))))
        return self._row(cur, cur.fetchone())

    def reusable_for_spec(self, spec_sha256: str, cost_ceiling_usd: float,
                          operation: str = DIRECTED_PILOT_OPERATION) -> dict | None:
        """Return the authoritative lifecycle for a spec instead of duplicating it.

        A queued/executing action outranks a later pending duplicate.  That ordering lets a
        convenience URL reconnect to the render that already consumed the one human approval,
        including its finished artifact, rather than presenting another spend button.
        """
        conn = None
        try:
            conn = self._connection()
            cur = conn.cursor()
            self._ensure(cur)
            return self._reusable_query(
                cur, operation=operation, spec_sha256=spec_sha256,
                cost_ceiling_usd=cost_ceiling_usd)
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
            # Approval is the sole human spending authorization. Rotate the execution capability
            # to this action's 128-bit random UUID so the same approval page can enqueue the exact
            # immutable payload immediately; claim() still consumes it exactly once.
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
            # Compatibility for actions approved immediately before the single-approval rollout:
            # their stored digest is the old browser-only token, but the operator already approved
            # the exact spec+ceiling. The random action UUID is therefore accepted as the bounded,
            # single-use execution capability for approved actions only.
            uuid_capability = bool(
                action and action.get("status") == "approved" and claim_token
                and hmac.compare_digest(str(claim_token), str(action_id)))
            if not action or not (verify_claim_token(action, claim_token) or uuid_capability):
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
