"""
Staff endpoints (mirrors Manage staff modal in the frontend).

GET /api/staff              → list staff names
POST /api/staff             → add staff {name}
DELETE /api/staff/{name}    → remove staff (sessions become Unassigned)
"""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from app.data_store import DAYS, TIME_SLOTS, STAFF, TIMETABLE
from app.database import save_setting, save_timetable_row
from app.routers.auth import require_admin

router = APIRouter()


class StaffCreate(BaseModel):
    name: str


@router.get('')
def list_staff():
    return STAFF


@router.post('', status_code=201)
def add_staff(body: StaffCreate, authorization: str = Header(default='')):
    require_admin(authorization)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail='name is required')
    if name not in STAFF:
        STAFF.append(name)
        TIMETABLE.setdefault('staff', {})[name] = {
            d: {s: None for s in range(len(TIME_SLOTS))} for d in range(len(DAYS))
        }
        save_setting('staff', STAFF)
        save_timetable_row('staff', name, TIMETABLE['staff'][name])
    return {'ok': True, 'name': name, 'staff': STAFF}


@router.delete('/{name}')
def remove_staff(name: str, authorization: str = Header(default='')):
    require_admin(authorization)
    if name not in STAFF:
        raise HTTPException(status_code=404, detail=f"Staff '{name}' not found")
    STAFF[:] = [s for s in STAFF if s != name]
    staff_view = TIMETABLE.get('staff', {})
    staff_view.pop(name, None)
    save_setting('staff', STAFF)
    for view_data in TIMETABLE.values():
        for row_days in view_data.values():
            if not isinstance(row_days, dict):
                continue
            for day, slots in list(row_days.items()):
                cells = slots.items() if isinstance(slots, dict) else [(0, slots)]
                for slot, sess in list(cells):
                    if sess is None:
                        continue
                    s_staff = sess.get('staff') if isinstance(sess, dict) else getattr(sess, 'staff', None)
                    if s_staff != name:
                        continue
                    updated = dict(sess, staff='Unassigned') if isinstance(sess, dict) \
                        else sess.model_copy(update={'staff': 'Unassigned'})
                    if isinstance(slots, dict):
                        slots[slot] = updated
                    else:
                        row_days[day] = updated
    return {'ok': True, 'deleted': name, 'staff': STAFF}
