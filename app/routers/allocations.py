"""
Allocations endpoints for what-if checks.

POST /api/allocations/check → Validate move (dry-run)
"""

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from app.data_store import TIMETABLE, DAYS, TIME_SLOTS, ALL_ROOMS, STAFF
from app.routers.auth import require_admin

router = APIRouter()


class CheckMoveRequest(BaseModel):
    staff: Optional[str] = None
    room: Optional[str] = None
    day: Optional[str] = None  # name or 0-4
    group: Optional[str] = None
    enrolled: Optional[int] = None
    section_id: Optional[str] = None  # for mock fallback


class CheckMoveResponse(BaseModel):
    ok: bool
    conflicts: List[dict] = []
    recommendations: List[dict] = []


def resolve_day(day_input: Optional[str]) -> Optional[int]:
    """Resolve day name or index to 0-4 index."""
    if day_input is None:
        return None
    if isinstance(day_input, int):
        return day_input
    try:
        return int(day_input)
    except ValueError:
        pass
    day_map = {
        'sunday': 0, 'mon': 0, 'monday': 0,
        'tue': 1, 'tuesday': 1,
        'wed': 2, 'wednesday': 2,
        'thu': 3, 'thursday': 3,
        'fri': 4, 'friday': 4,
        'الأحد': 0, 'الاحد': 0,
        'الاثنين': 1,
        'الثلاثاء': 2,
        'الاربعاء': 3, 'الأربعاء': 3,
        'الخميس': 4,
    }
    return day_map.get(day_input.lower(), None)


def find_staff_by_name(name: str) -> Optional[int]:
    """Find staff index by name."""
    for i, s in enumerate(STAFF):
        if name.lower() in s.lower():
            return i
    return None


def find_room_by_name(name: str) -> Optional[str]:
    """Find room name by partial match."""
    for r in ALL_ROOMS:
        if name.lower() in r.name.lower():
            return r.name
    return None


@router.post('/check', response_model=CheckMoveResponse)
async def check_move(body: CheckMoveRequest):
    """Validate a move (dry-run, read-only). Returns conflicts and alternatives."""
    from app.services.conflicts import check_candidate
    day_idx = resolve_day(body.day)
    if body.day is not None and day_idx is None:
        return CheckMoveResponse(
            ok=False,
            conflicts=[{'conflict_type': 'INVALID_DAY', 'description': f'Invalid day: {body.day}'}],
            recommendations=[],
        )
    ok, conflicts, recs = check_candidate(
        TIMETABLE, ALL_ROOMS, staff=body.staff, room=body.room,
        day=day_idx, slot=0, group=body.group, enrolled=body.enrolled or 0,
    )
    recs_out = [r.model_dump() if hasattr(r, 'model_dump') else dict(r) for r in recs]
    return CheckMoveResponse(ok=ok, conflicts=conflicts, recommendations=recs_out)