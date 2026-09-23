"""
Timetable endpoints.

GET  /api/timetable                   → full grid (all view modes)
GET  /api/timetable/{view}            → grid for one view mode (rooms|labs|staff)
GET  /api/timetable/{view}/{row}      → one row (e.g. a single room or staff member)
PUT  /api/timetable/{view}/{row}/{day} → overwrite a day's slots for one row
GET  /api/timetable/constants         → DAYS, TIME_SLOTS, ROOMS, LABS, STAFF lists
"""
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from app.models.schema import Session, ViewMode
from app.data_store import TIMETABLE, DAYS, FULL_DAYS, TIME_SLOTS, ROOMS, LABS, STAFF
from app.routers.auth import is_admin_authorization, get_email_from_auth
from app.database import save_setting, save_timetable_cell, save_timetable_row

router = APIRouter()


@router.get('/constants')
def get_constants():
    return {
        'days': DAYS,
        'fullDays': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'],
        'timeSlots': TIME_SLOTS,
        'rooms': ROOMS,
        'labs': LABS,
        'staff': STAFF,
    }


@router.get('')
def get_full_grid():
    """Return the entire timetable (all view modes)."""
    return _serialize_grid(TIMETABLE)


@router.get('/{view}')
def get_view_grid(view: ViewMode):
    if view not in TIMETABLE:
        raise HTTPException(status_code=404, detail=f"View '{view}' not found")
    return _serialize_grid({view: TIMETABLE[view]})[view]


@router.post('/columns')
def create_column(payload: dict, authorization: str = Header(default='')):
    if not is_admin_authorization(authorization):
        raise HTTPException(status_code=403, detail='Only admins can create columns.')
    name = str(payload.get('name', '')).strip()
    if not name:
        raise HTTPException(status_code=422, detail='Column name is required.')
    if name in DAYS:
        raise HTTPException(status_code=400, detail=f"Column '{name}' already exists.")
    DAYS.append(name)
    new_day = len(DAYS) - 1
    for rows in TIMETABLE.values():
        for days in rows.values():
            days[new_day] = None
    save_setting('days', DAYS)
    for view, rows in TIMETABLE.items():
        for row_name, days in rows.items():
            save_timetable_cell(view, row_name, new_day, None)
    return {'ok': True, 'column': name, 'day': new_day}


@router.post('/{view}/rows')
def create_row(view: ViewMode, payload: dict, authorization: str = Header(default='')):
    if not is_admin_authorization(authorization):
        raise HTTPException(status_code=403, detail='Only admins can create rows.')
    name = str(payload.get('name', '')).strip()
    view_data = TIMETABLE.get(view)
    if view_data is None:
        raise HTTPException(status_code=404, detail=f"View '{view}' not found")
    if not name:
        raise HTTPException(status_code=422, detail='Row name is required.')
    if name in view_data:
        raise HTTPException(status_code=400, detail=f"Row '{name}' already exists.")
    view_data[name] = {day: None for day in range(len(DAYS))}
    if view == 'rooms' and name not in ROOMS:
        ROOMS.append(name)
    elif view == 'labs' and name not in LABS:
        LABS.append(name)
    elif view == 'staff' and name not in STAFF:
        STAFF.append(name)
    save_setting(view, {'rooms': ROOMS, 'labs': LABS, 'staff': STAFF}.get(view, STAFF))
    save_timetable_row(view, name, view_data[name])
    return {'ok': True, 'row': name}


@router.get('/{view}/{row}')
def get_row(view: ViewMode, row: str):
    view_data = TIMETABLE.get(view)
    if view_data is None:
        raise HTTPException(status_code=404, detail=f"View '{view}' not found")
    row_data = view_data.get(row)
    if row_data is None:
        raise HTTPException(status_code=404, detail=f"Row '{row}' not found in view '{view}'")
    return {str(day): _collapse_day(slots) for day, slots in row_data.items()}


@router.put('/{view}/{row}/{day}')
def update_slot(view: ViewMode, row: str, day: int, session: Session | None = None, authorization: str = Header(default='')):
    """Set (or clear) a single slot. Auto-creates the row for new staff."""
    if not is_admin_authorization(authorization):
        raise HTTPException(status_code=403, detail='Only admins can edit the timetable.')
    if day < 0 or day >= len(DAYS):
        raise HTTPException(status_code=422, detail=f'day must be 0-{len(DAYS) - 1}')
    if session is not None and session.academic_year is not None and session.academic_year >= 3 and not session.major:
        raise HTTPException(status_code=422, detail='Major is required for academic years 3 and 4 (CS, IT, AI, DS)')
    if session is not None and session.major and session.major not in ('CS', 'IT', 'AI', 'DS'):
        raise HTTPException(status_code=422, detail='Invalid major')
    view_data = TIMETABLE.get(view)
    if view_data is None:
        raise HTTPException(status_code=404, detail=f"View '{view}' not found")
    if row not in view_data:
        # allow admin to add new staff rows on the fly (mirrors Manage staff)
        if view == 'staff':
            view_data[row] = {d: None for d in range(5)}
            if row not in STAFF:
                STAFF.append(row)
        else:
            raise HTTPException(status_code=404, detail=f"Row '{row}' not found")
    # Grid stores day → slot → session; write into the session's slot (default 0).
    # Smart move: if session id already exists elsewhere in this view, clear old cell first
    # so day/slot change truly moves (fixes stale slot at 08:00 after reschedule).
    def _clear_previous_occurrences(view_name: str, sess_id: str, exclude_row: str, exclude_day: int, exclude_slot: int):
        vd = TIMETABLE.get(view_name, {})
        for r_name, days in vd.items():
            for d, slots in days.items():
                if not isinstance(slots, dict):
                    continue
                for s_idx, sess in list(slots.items()):
                    if sess is None:
                        continue
                    sid = sess.get('id') if isinstance(sess, dict) else getattr(sess, 'id', None)
                    if sid == sess_id and not (r_name == exclude_row and d == exclude_day and s_idx == exclude_slot):
                        slots[s_idx] = None
                        try:
                            save_timetable_cell(view_name, r_name, d, None, s_idx)
                        except Exception:
                            pass
                        # also clear mirrored staff view if applicable
                        try:
                            staff_name = sess.get('staff') if isinstance(sess, dict) else getattr(sess, 'staff', None)
                            if staff_name and staff_name in TIMETABLE.get('staff', {}):
                                s_days = TIMETABLE['staff'][staff_name]
                                for sd, s_slots in s_days.items():
                                    if isinstance(s_slots, dict):
                                        for ss_idx, ss in list(s_slots.items()):
                                            ssid = ss.get('id') if isinstance(ss, dict) else getattr(ss, 'id', None)
                                            if ssid == sess_id:
                                                s_slots[ss_idx] = None
                                                try:
                                                    save_timetable_cell('staff', staff_name, sd, None, ss_idx)
                                                except Exception:
                                                    pass
                        except Exception:
                            pass

    day_slots = view_data[row].get(day)
    if not isinstance(day_slots, dict):
        day_slots = {s: None for s in range(len(TIME_SLOTS))}
        view_data[row][day] = day_slots
    # capture before for audit
    if session is None:
        # clear specific slot if possible: find first booked, but prefer exact slot if provided via query? keep first
        slot_idx = next((s for s in sorted(day_slots.keys()) if day_slots[s] is not None), 0)
        before = day_slots.get(slot_idx)
        # also clear any other occurrence of same session id if before has id (handles slot-move via null)
        if before is not None:
            sid = before.get('id') if isinstance(before, dict) else getattr(before, 'id', None)
            if sid:
                _clear_previous_occurrences(view, sid, row, day, slot_idx)
        day_slots[slot_idx] = None
        after = None
        save_timetable_cell(view, row, day, None, slot_idx)
    else:
        slot_idx = int(session.slot or 0)
        # clear previous location of this session id before overwriting (smart reschedule)
        try:
            _clear_previous_occurrences(view, session.id, row, day, slot_idx)
        except Exception:
            pass
        before = day_slots.get(slot_idx)
        # if same id exists at old slot within same day, clear old slot
        if before is None:
            # search same day other slots for same id
            for s_idx, sess in list(day_slots.items()):
                if sess is None:
                    continue
                sid = sess.get('id') if isinstance(sess, dict) else getattr(sess, 'id', None)
                if sid == session.id and s_idx != slot_idx:
                    day_slots[s_idx] = None
                    try:
                        save_timetable_cell(view, row, day, None, s_idx)
                    except Exception:
                        pass
                    before = sess
                    break
        day_slots[slot_idx] = session
        after = session
        save_timetable_cell(view, row, day, session, slot_idx)
        # mirror to staff view
        try:
            if session.staff and session.staff in TIMETABLE.get('staff', {}):
                staff_days = TIMETABLE['staff'][session.staff]
                # clear previous staff occurrence
                for sd, s_slots in staff_days.items():
                    if isinstance(s_slots, dict):
                        for ss_idx, ss in list(s_slots.items()):
                            if ss is None:
                                continue
                            ssid = ss.get('id') if isinstance(ss, dict) else getattr(ss, 'id', None)
                            if ssid == session.id and not (sd == day and ss_idx == slot_idx):
                                s_slots[ss_idx] = None
                                try:
                                    save_timetable_cell('staff', session.staff, sd, None, ss_idx)
                                except Exception:
                                    pass
                # set new staff slot
                s_day = staff_days.get(day)
                if isinstance(s_day, dict):
                    s_day[slot_idx] = session
                    try:
                        save_timetable_cell('staff', session.staff, day, session, slot_idx)
                    except Exception:
                        pass
        except Exception:
            pass
    # Re-run automatic conflict detection after every write.
    from app import data_store
    from app.services.refresh import refresh_conflicts
    total = refresh_conflicts()
    # Audit trail
    try:
        from app.services.audit import log_audit
        actor = get_email_from_auth(authorization) or "admin@bua.edu.eg"
        log_audit(actor, "timetable_update", "timetable", f"{view}/{row}/{day}/{slot_idx}",
                  message=f"Timetable {view}/{row} day {day} slot {slot_idx} updated",
                  before=before, after=after)
    except Exception:
        pass
    # Notify affected users if a version is already published.
    published = next((v for v in data_store.VERSIONS if v.status == 'published'), None)
    if published is not None:
        from app.services.notifications import notify_affected
        src = after if after is not None else before
        grp = src.get('group') if isinstance(src, dict) else getattr(src, 'group', None) if src else None
        stf = src.get('staff') if isinstance(src, dict) else getattr(src, 'staff', None) if src else None
        code = src.get('code') if isinstance(src, dict) else getattr(src, 'code', 'session') if src else 'session'
        name = src.get('name') if isinstance(src, dict) else getattr(src, 'name', '') if src else ''
        day_name = FULL_DAYS[day] if 0 <= day < len(FULL_DAYS) else f'day {day}'
        slot_time = TIME_SLOTS[slot_idx] if 0 <= slot_idx < len(TIME_SLOTS) else f'slot {slot_idx}'
        # richer message: mentions new hall/day/time
        notify_affected(grp, stf, type='timetable_change',
                     message=f'تم نقل/تحديث محاضرة {code} {name} إلى {row} يوم {day_name} الساعة {slot_time}' + f' (was published as {published.label})',
                     related_id=published.id)
    return {'ok': True, 'slot': session.model_dump(by_alias=True) if session else None,
            'conflicts': total}


# ── helpers ───────────────────────────────────────────────────────────────────

def _session_to_dict(sess: Any) -> dict | None:
    """Convert Session object or dict to dict."""
    if sess is None:
        return None
    if hasattr(sess, 'model_dump'):
        return sess.model_dump(by_alias=True)
    return dict(sess)


def _collapse_day(slots: Any) -> dict | None:
    """Frontend grid is day-granular: return the first booked session of the day."""
    if slots is None:
        return None
    if not isinstance(slots, dict):
        return _session_to_dict(slots)
    for slot in sorted(slots.keys()):
        sess = slots[slot]
        if sess is not None:
            return _session_to_dict(sess)
    return None


def _serialize_grid(grid: dict) -> dict:
    """Convert Session objects to dicts; keep None as null (flat day → session)."""
    result = {}
    for view, rows in grid.items():
        result[view] = {}
        for row, days in rows.items():
            result[view][row] = {
                str(day): _collapse_day(slots)
                for day, slots in days.items()
            }
    return result
