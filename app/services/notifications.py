"""Notification fan-out helper."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def notify(audience: str = 'all', email: str | None = None, type: str = 'info',
           message: str = '', related_id: str | None = None) -> dict:
    from app import data_store
    from app.models.schema import Notification
    from app.database import save_notification
    notif = Notification(
        id=f'n-{uuid4().hex[:8]}',
        audience=audience, email=email, type=type, message=message,
        related_id=related_id, read=False,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    data_store.NOTIFICATIONS.insert(0, notif)
    try:
        save_notification(notif)
    except Exception:
        pass
    return notif.model_dump()


def notify_users(users: list[dict], type: str, message: str, related_id: str | None = None,
                 roles: tuple[str, ...] = ('admin', 'lecturer', 'student')) -> int:
    n = 0
    for u in users:
        if u.get('role') in roles:
            notify(audience=u['role'], email=u['email'], type=type, message=message, related_id=related_id)
            n += 1
    return n


def get_affected_users(group: str | None = None, staff: str | None = None) -> list[dict]:
    """Derive affected users for a timetable cell: students in group + staff + admins."""
    from app import data_store
    affected: list[dict] = []
    seen: set[str] = set()
    # admins always
    for u in data_store.USERS:
        if u.get('role') == 'admin' and u['email'].lower() not in seen:
            affected.append(u); seen.add(u['email'].lower())
    # staff
    if staff:
        for u in data_store.USERS:
            if u.get('role') == 'lecturer' and u.get('name') == staff and u['email'].lower() not in seen:
                affected.append(u); seen.add(u['email'].lower())
        # also try email match fallback (e.g. dr.chen@...)
        if staff and not any(x.get('name') == staff for x in affected):
            # if staff not found as user, still keep admins already
            pass
    # students in group
    if group:
        for s in data_store.MANAGED_STUDENTS:
            if s.get('group') == group:
                # find matching user by email
                for u in data_store.USERS:
                    if u['email'].lower() == s['email'].lower() and u['email'].lower() not in seen:
                        affected.append(u); seen.add(u['email'].lower())
                        break
    return affected


def notify_affected(group: str | None, staff: str | None, type: str, message: str, related_id: str | None = None) -> int:
    users = get_affected_users(group, staff)
    # fallback to broadcast if no specific affected found (avoid silent)
    if not users:
        from app import data_store
        users = [u for u in data_store.USERS if u.get('role') == 'admin']
    n = 0
    for u in users:
        notify(audience=u['role'], email=u['email'], type=type, message=message, related_id=related_id)
        n += 1
    return n
