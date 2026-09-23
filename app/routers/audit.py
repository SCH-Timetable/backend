"""Audit log read-only endpoints.

GET /api/audit            → list audit events (supports ?actor=&action=&entity_type=&limit=)
GET /api/audit/{id}       → one event
"""

from fastapi import APIRouter, Header, HTTPException, Query
from typing import Optional

from app.data_store import AUDIT_LOGS
from app.routers.auth import require_admin

router = APIRouter()


@router.get('', response_model=list)
def list_audit(
    actor: Optional[str] = None,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    authorization: str = Header(default=''),
):
    require_admin(authorization)
    items = AUDIT_LOGS
    if actor:
        al = actor.lower()
        items = [e for e in items if al in e.actor_email.lower()]
    if action:
        al = action.lower()
        items = [e for e in items if al in e.action.lower()]
    if entity_type:
        items = [e for e in items if e.entity_type == entity_type]
    return items[:limit]


@router.get('/{event_id}')
def get_audit(event_id: str, authorization: str = Header(default='')):
    require_admin(authorization)
    evt = next((e for e in AUDIT_LOGS if e.id == event_id), None)
    if evt is None:
        raise HTTPException(status_code=404, detail=f"Audit event '{event_id}' not found")
    return evt
