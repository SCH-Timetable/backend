"""
Notification endpoints.

GET   /api/notifications            → list (supports ?email=&role=&unread=true)
PATCH /api/notifications/{id}/read  → mark as read
"""

from fastapi import APIRouter, Header, HTTPException, Query
from typing import Optional

from app.data_store import NOTIFICATIONS
from app.database import save_notification

router = APIRouter()


def _visible(email: Optional[str], role: Optional[str]):
    items = NOTIFICATIONS
    if email:
        items = [n for n in items
                 if n.audience == 'all' or (n.email or '').lower() == email.lower()]
    elif role:
        items = [n for n in items if n.audience in ('all', role)]
    return items


@router.get('', response_model=list)
def list_notifications(
    email: Optional[str] = None,
    role: Optional[str] = None,
    unread: Optional[bool] = None,
):
    items = _visible(email, role)
    if unread:
        items = [n for n in items if not n.read]
    return items


@router.patch('/{notif_id}/read')
def mark_read(notif_id: str):
    n = next((x for x in NOTIFICATIONS if x.id == notif_id), None)
    if n is None:
        raise HTTPException(status_code=404, detail=f"Notification '{notif_id}' not found")
    n.read = True
    save_notification(n)
    return n
