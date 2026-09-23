"""
Canonical schedule export endpoints.

GET /api/schedules/export/ics → timetable as ICS (supports ?staff=)
"""

from fastapi import APIRouter, Query
from typing import Optional

from app.data_store import TIMETABLE, DAYS, TIME_SLOTS
from app.services.export_ics import build_ics

router = APIRouter()


def _rows(staff: Optional[str] = None) -> list[dict]:
    rows = []
    for room_name, days in (TIMETABLE.get('rooms') or {}).items():
        for day, slots in (days or {}).items():
            if not isinstance(slots, dict):
                continue
            for slot, session in slots.items():
                if session is None:
                    continue
                s_staff = session.get('staff') if isinstance(session, dict) else getattr(session, 'staff', '')
                if staff and s_staff != staff:
                    continue
                rows.append({
                    'id': session.get('id') if isinstance(session, dict) else getattr(session, 'id', ''),
                    'code': session.get('code') if isinstance(session, dict) else getattr(session, 'code', ''),
                    'name': session.get('name') if isinstance(session, dict) else getattr(session, 'name', ''),
                    'room': room_name,
                    'day_name': DAYS[day] if day < len(DAYS) else f'Day {day}',
                    'time': TIME_SLOTS[slot] if slot < len(TIME_SLOTS) else '',
                    'staff': s_staff,
                    'group': session.get('group') if isinstance(session, dict) else getattr(session, 'group', ''),
                })
    return rows


@router.get('/export/ics')
async def export_ics(staff: Optional[str] = None):
    from fastapi.responses import Response
    content = build_ics(_rows(staff), DAYS)
    return Response(
        content=content,
        media_type='text/calendar',
        headers={'Content-Disposition': 'attachment; filename=timetable.ics'},
    )
