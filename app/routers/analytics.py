"""
Analytics endpoints.

GET /api/analytics/summary           → aggregate stats (matches AnalyticsScreen.tsx)
GET /api/analytics/utilization/rooms → per-room utilization
GET /api/analytics/utilization/days  → per-day utilization
GET /api/analytics/utilization/hours → per-hour utilization
GET /api/analytics/conflicts         → conflict type breakdown
"""

from fastapi import APIRouter
from app.data_store import TIMETABLE, CONFLICTS, ALL_ROOMS, DAYS, TIME_SLOTS
from app.models.schema import AnalyticsSummary, UtilizationPoint, ConflictStat

router = APIRouter()


def _iter_cells(view: str = 'rooms'):
    """Yield every (day, slot, session) cell of a view (day → slot → session)."""
    for days in TIMETABLE.get(view, {}).values():
        if not isinstance(days, dict):
            continue
        for day, slots in days.items():
            if isinstance(slots, dict):
                for slot, session in slots.items():
                    yield day, slot, session
            elif slots is not None:
                yield day, 0, slots


def _room_utilization() -> list[UtilizationPoint]:
    """Utilization as % of slots filled across all days."""
    rooms_view = TIMETABLE.get('rooms', {})
    result = []
    for room_name, days in rooms_view.items():
        total, filled = 0, 0
        if isinstance(days, dict):
            for slots in days.values():
                cells = slots.values() if isinstance(slots, dict) else [slots]
                for s in cells:
                    total += 1
                    if s is not None:
                        filled += 1
        pct = round(filled / total * 100) if total else 0
        result.append(UtilizationPoint(name=room_name, utilization=pct))
    return sorted(result, key=lambda x: x.utilization, reverse=True)


def _day_utilization() -> list[UtilizationPoint]:
    """How many sessions happen on each weekday (rooms view)."""
    day_counts: dict[int, int] = {d: 0 for d in range(len(DAYS))}
    total_rows = max(len(TIMETABLE.get('rooms', {})), 1)
    for day, _slot, sess in _iter_cells('rooms'):
        if sess is not None:
            day_counts[day] = day_counts.get(day, 0) + 1
    return [
        UtilizationPoint(name=DAYS[d] if d < len(DAYS) else str(d),
                         utilization=round(cnt / total_rows * 100))
        for d, cnt in day_counts.items()
    ]


def _hour_utilization() -> list[UtilizationPoint]:
    """How busy each time slot is across all rooms."""
    slot_counts: dict[int, int] = {s: 0 for s in range(len(TIME_SLOTS))}
    total_rooms = max(len(TIMETABLE.get('rooms', {})), 1)
    for _day, slot, sess in _iter_cells('rooms'):
        if sess is not None and slot in slot_counts:
            slot_counts[slot] = slot_counts.get(slot, 0) + 1
    return [
        UtilizationPoint(name=TIME_SLOTS[s], utilization=round(cnt / total_rooms * 100))
        for s, cnt in slot_counts.items()
    ]


def _conflict_breakdown() -> list[ConflictStat]:
    colours = {
        'double_booking': '#ef4444',
        'capacity':       '#f59e0b',
        'staff_overlap':  '#8b5cf6',
        'equipment':      '#06b6d4',
        'student_group':  '#10b981',
        'room_type':      '#f97316',
        'closure':        '#64748b',
    }
    counts: dict[str, int] = {}
    for c in CONFLICTS:
        counts[c.type] = counts.get(c.type, 0) + 1
    labels = {
        'double_booking': 'Double Booking',
        'capacity':       'Capacity',
        'staff_overlap':  'Staff Overlap',
        'equipment':      'Equipment',
        'student_group':  'Student Group',
        'room_type':      'Room Type',
        'closure':        'Closure',
    }
    return [
        ConflictStat(name=labels.get(t, t), value=v, color=colours.get(t, '#94a3b8'))
        for t, v in counts.items()
    ]


def _total_sessions() -> int:
    return sum(
        1
        for view in TIMETABLE
        for _day, _slot, s in _iter_cells(view)
        if s is not None
    )


def _rooms_at_capacity() -> int:
    count = 0
    for _day, _slot, s in _iter_cells('rooms'):
        if s:
            if isinstance(s, dict):
                enrolled = s.get('enrolled', 0)
                capacity = s.get('capacity', 0)
            else:
                enrolled = getattr(s, 'enrolled', 0)
                capacity = getattr(s, 'capacity', 0)
            if enrolled >= capacity:
                count += 1
    return count


@router.get('/summary', response_model=AnalyticsSummary)
def get_summary():
    room_util = _room_utilization()
    avg_util = round(sum(p.utilization for p in room_util) / len(room_util)) if room_util else 0
    return AnalyticsSummary(
        total_sessions=_total_sessions(),
        total_conflicts=len(CONFLICTS),
        avg_utilization=avg_util,
        rooms_at_capacity=_rooms_at_capacity(),
        utilization_by_room=room_util,
        utilization_by_day=_day_utilization(),
        utilization_by_hour=_hour_utilization(),
        conflict_breakdown=_conflict_breakdown(),
    )


@router.get('/utilization/rooms', response_model=list[UtilizationPoint])
def util_by_room():
    return _room_utilization()


@router.get('/utilization/days', response_model=list[UtilizationPoint])
def util_by_day():
    return _day_utilization()


@router.get('/utilization/hours', response_model=list[UtilizationPoint])
def util_by_hour():
    return _hour_utilization()


@router.get('/conflicts', response_model=list[ConflictStat])
def conflict_stats():
    return _conflict_breakdown()


@router.get('/occupancy')
async def get_occupancy():
    """Room occupancy statistics - used by chatbot."""
    occ = []
    for r in ALL_ROOMS:
        room_days = TIMETABLE.get('rooms', {}).get(r.name, {})
        used = sum(1 for s in room_days.values() if s is not None)
        total = len(DAYS)
        occ.append({
            'room_id': r.id,
            'room_number': r.name,
            'used': used,
            'total': total,
            'pct': round(used/total*100) if total else 0
        })
    return sorted(occ, key=lambda x: -x['pct'])
