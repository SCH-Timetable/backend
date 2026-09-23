"""
Conflict endpoints.

GET  /api/conflicts                  → list all unresolved conflicts
GET  /api/conflicts/{id}             → one conflict with alternatives
POST /api/conflicts/{id}/apply       → apply an alternative (resolves the conflict)
DELETE /api/conflicts/{id}           → dismiss / ignore a conflict
"""

from fastapi import APIRouter, Header, HTTPException
from app.models.schema import Conflict, ApplyAlternativeRequest
from app.data_store import CONFLICTS, TIMETABLE
from app.database import save_setting, save_timetable_cell
from app.routers.auth import require_admin, get_email_from_auth

router = APIRouter()


@router.get('', response_model=list[Conflict])
def list_conflicts():
    return CONFLICTS


@router.get('/{conflict_id}', response_model=Conflict)
def get_conflict(conflict_id: str):
    c = next((c for c in CONFLICTS if c.id == conflict_id), None)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Conflict '{conflict_id}' not found")
    return c


@router.post('/{conflict_id}/apply')
def apply_alternative(conflict_id: str, body: ApplyAlternativeRequest, authorization: str = Header(default='')):
    """
    Apply an alternative resolution for a conflict.
    Moves the affected session to the new slot and removes the conflict.
    """
    require_admin(authorization)
    c = next((c for c in CONFLICTS if c.id == conflict_id), None)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Conflict '{conflict_id}' not found")

    alt = next((a for a in c.alternatives if a.id == body.alternative_id), None)
    if alt is None:
        raise HTTPException(status_code=404, detail=f"Alternative '{body.alternative_id}' not found")

    # Find the session in the timetable and move it (slot-aware).
    old_row = c.cell.row
    old_day = c.cell.day
    old_slot = c.cell.slot

    for view_name, view_data in TIMETABLE.items():
        if old_row not in view_data:
            continue
        day_slots = view_data[old_row].get(old_day)
        if not isinstance(day_slots, dict):
            continue
        session = day_slots.get(old_slot)
        if session is None:
            continue
        # Clear old slot
        day_slots[old_slot] = None
        save_timetable_cell(view_name, old_row, old_day, None, old_slot)
        # Set new slot (in the target room when it belongs to this view)
        new_row = alt.room if alt.room in view_data else old_row
        new_slots = view_data[new_row].get(alt.day)
        if not isinstance(new_slots, dict):
            continue
        moved = session.model_copy(update={'conflict_id': None, 'slot': alt.slot}) \
            if hasattr(session, 'model_copy') else dict(session, conflict_id=None, slot=alt.slot)
        new_slots[alt.slot] = moved
        save_timetable_cell(view_name, new_row, alt.day, moved, alt.slot)
        break

    # Remove conflict from list
    CONFLICTS[:] = [x for x in CONFLICTS if x.id != conflict_id]
    save_setting('conflicts', [c.model_dump(by_alias=True) for c in CONFLICTS])
    from app import data_store
    from app.services.refresh import refresh_conflicts
    total = refresh_conflicts()
    # targeted notification: use moved session's group/staff if available
    try:
        grp = session.get('group') if isinstance(session, dict) else getattr(session, 'group', None) if 'session' in locals() and session else None
        stf = session.get('staff') if isinstance(session, dict) else getattr(session, 'staff', None) if 'session' in locals() and session else None
        from app.services.notifications import notify_affected
        notify_affected(grp, stf, type='conflict',
                     message=f"Conflict '{conflict_id}' resolved via alternative '{alt.id}'. {total} conflicts remain.",
                     related_id=conflict_id)
    except Exception:
        from app.services.notifications import notify_users
        notify_users(data_store.USERS, type='conflict',
                     message=f"Conflict '{conflict_id}' resolved via alternative '{alt.id}'. {total} conflicts remain.",
                     related_id=conflict_id)
    # audit
    try:
        from app.services.audit import log_audit
        actor = get_email_from_auth(authorization) or "admin@bua.edu.eg"
        log_audit(actor, "conflict_apply", "conflict", conflict_id, message=f"Applied alternative {alt.id} for conflict {conflict_id}", before=c, after={"alternative": alt.model_dump() if hasattr(alt, 'model_dump') else dict(alt)})
    except Exception:
        pass

    return {'ok': True, 'applied_alternative': alt.id, 'conflict_removed': conflict_id,
            'conflicts': total}


@router.delete('/{conflict_id}')
def dismiss_conflict(conflict_id: str, authorization: str = Header(default='')):
    require_admin(authorization)
    target = next((c for c in CONFLICTS if c.id == conflict_id), None)
    original_len = len(CONFLICTS)
    CONFLICTS[:] = [c for c in CONFLICTS if c.id != conflict_id]
    if len(CONFLICTS) == original_len:
        raise HTTPException(status_code=404, detail=f"Conflict '{conflict_id}' not found")
    save_setting('conflicts', [c.model_dump(by_alias=True) for c in CONFLICTS])
    try:
        from app.services.audit import log_audit
        actor = get_email_from_auth(authorization) or "admin@bua.edu.eg"
        log_audit(actor, "conflict_dismiss", "conflict", conflict_id, message=f"Dismissed conflict {conflict_id}", before=target)
    except Exception:
        pass
    return {'ok': True, 'dismissed': conflict_id}
