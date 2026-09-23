"""Audit trail helper - records who did what and when."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4


def _safe_dump(value: Any) -> Optional[dict]:
    if value is None:
        return None
    try:
        if hasattr(value, 'model_dump'):
            return value.model_dump(by_alias=True)
        if isinstance(value, dict):
            return dict(value)
        return {"value": str(value)[:2000]}
    except Exception:
        try:
            return {"value": str(value)[:2000]}
        except Exception:
            return None


def log_audit(
    actor_email: str,
    action: str,
    entity_type: str,
    entity_id: str,
    message: str = "",
    before: Any = None,
    after: Any = None,
) -> None:
    """Persist an audit event to data_store and DB. Never raises."""
    try:
        from app import data_store
        from app.models.schema import AuditEvent
        from app.database import save_audit
        # resolve role if known
        role = "admin"
        try:
            for u in data_store.USERS:
                if u.get("email","").lower() == (actor_email or "").lower():
                    role = u.get("role", "admin")
                    break
        except Exception:
            pass
        evt = AuditEvent(
            id=f"aud-{uuid4().hex[:10]}",
            actor_email=actor_email or "system",
            actor_role=role,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            message=message or f"{action} {entity_type} {entity_id}",
            before=_safe_dump(before),
            after=_safe_dump(after),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        data_store.AUDIT_LOGS.insert(0, evt)
        # keep bounded
        if len(data_store.AUDIT_LOGS) > 500:
            del data_store.AUDIT_LOGS[500:]
        save_audit(evt)
    except Exception:
        pass
