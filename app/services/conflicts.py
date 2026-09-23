"""Automatic conflict detection over the live timetable grid.

Scans rooms+labs views (staff view mirrors sessions, so it is excluded to
avoid false positives) and reports:
- staff_overlap: same staff in 2+ sessions at the same day+slot
- student_group: same group in 2+ sessions at the same day+slot
- capacity: enrolled > room capacity
"""

from __future__ import annotations

from app.models.schema import Conflict, ConflictCell


def _iter_sessions(timetable: dict):
    """Yield (view, row, day, slot, session)."""
    for view in ('rooms', 'labs'):
        for row, days in (timetable.get(view) or {}).items():
            if not isinstance(days, dict):
                continue
            for day, slots in days.items():
                if not isinstance(slots, dict):
                    continue
                for slot, session in slots.items():
                    if session is None:
                        continue
                    yield view, row, int(day), int(slot), session


def _get(session, attr: str, default=None):
    if isinstance(session, dict):
        return session.get(attr, default)
    return getattr(session, attr, default)


def _safe_id(*parts: str) -> str:
    return 'auto-' + '-'.join(
        ''.join(ch if ch.isalnum() else '_' for ch in str(p)) for p in parts
    )


def detect_all_conflicts(timetable: dict, rooms: list) -> list[Conflict]:
    capacity_by_room = {}
    for r in rooms or []:
        name = r.get('name') if isinstance(r, dict) else getattr(r, 'name', None)
        cap = r.get('capacity') if isinstance(r, dict) else getattr(r, 'capacity', 0)
        if name:
            capacity_by_room[name] = cap or 0

    staff_slots: dict[tuple, list] = {}
    group_slots: dict[tuple, list] = {}
    conflicts: list[Conflict] = []

    for view, row, day, slot, session in _iter_sessions(timetable):
        staff = _get(session, 'staff')
        group = _get(session, 'group')
        enrolled = _get(session, 'enrolled', 0) or 0
        code = _get(session, 'code', '')
        if staff:
            staff_slots.setdefault((staff, day, slot), []).append((view, row, session))
        if group:
            group_slots.setdefault((group, day, slot), []).append((view, row, session))
        cap = capacity_by_room.get(row)
        if cap is not None and enrolled > cap:
            conflicts.append(Conflict(
                id=_safe_id('capacity', row, day, slot),
                type='capacity', severity='hard',
                description=f'{code}: {enrolled} enrolled exceeds {row} capacity {cap}.',
                cell=ConflictCell(row=row, day=day, slot=slot),
                alternatives=suggest_alternatives(
                    timetable, rooms, staff, group, enrolled, day, slot, exclude_row=row,
                ),
            ))

    for (staff, day, slot), places in staff_slots.items():
        if len(places) > 1:
            rows = ', '.join(f'{r}' for _, r, _ in places)
            view, row, _ = places[0]
            conflicts.append(Conflict(
                id=_safe_id('staff_overlap', staff, day, slot),
                type='staff_overlap', severity='hard',
                description=f'{staff} double-booked at day {day} slot {slot}: {rows}.',
                cell=ConflictCell(row=row, day=day, slot=slot),
                alternatives=[],
            ))

    for (group, day, slot), places in group_slots.items():
        if len(places) > 1:
            rows = ', '.join(f'{r}' for _, r, _ in places)
            view, row, _ = places[0]
            conflicts.append(Conflict(
                id=_safe_id('student_group', group, day, slot),
                type='student_group', severity='hard',
                description=f'Group {group} has {len(places)} sessions at day {day} slot {slot}: {rows}.',
                cell=ConflictCell(row=row, day=day, slot=slot),
                alternatives=[],
            ))

    return conflicts


def _slot_free(timetable: dict, view: str, row: str, day: int, slot: int) -> bool:
    try:
        cell = ((timetable.get(view) or {}).get(row) or {}).get(day)
        if isinstance(cell, dict):
            return cell.get(slot) is None
        return cell is None
    except Exception:
        return False


def _staff_busy(timetable: dict, staff: str | None, day: int, slot: int) -> bool:
    if not staff:
        return False
    for view, row, d, s, session in _iter_sessions(timetable):
        if d == day and s == slot and _get(session, 'staff') == staff:
            return True
    return False


def _group_busy(timetable: dict, group: str | None, day: int, slot: int) -> bool:
    if not group:
        return False
    for view, row, d, s, session in _iter_sessions(timetable):
        if d == day and s == slot and _get(session, 'group') == group:
            return True
    return False


def suggest_alternatives(
    timetable: dict, rooms: list, staff: str | None, group: str | None,
    enrolled: int, day: int, slot: int, exclude_row: str | None = None,
    limit: int = 3,
) -> list:
    """Find up to `limit` free rooms with enough capacity and no staff/group clash."""
    from app.models.schema import Alternative
    out = []
    for r in rooms or []:
        name = r.get('name') if isinstance(r, dict) else getattr(r, 'name', None)
        cap = r.get('capacity') if isinstance(r, dict) else getattr(r, 'capacity', 0)
        status = r.get('status') if isinstance(r, dict) else getattr(r, 'status', 'Available')
        if not name or name == exclude_row or status != 'Available':
            continue
        if (cap or 0) < (enrolled or 0):
            continue
        if not _slot_free(timetable, 'rooms', name, day, slot):
            continue
        if _staff_busy(timetable, staff, day, slot):
            continue
        if _group_busy(timetable, group, day, slot):
            continue
        out.append(Alternative(
            id=f'alt-{len(out) + 1}-{name}-{day}-{slot}'.replace(' ', '_'),
            score=max(0, 100 - max(0, (cap or 0) - (enrolled or 0))),
            day=day, slot=slot, room=name,
            reasons=[f'Capacity {cap} fits {enrolled}', 'Room free at this slot', 'No staff/group clash'],
        ))
        if len(out) >= limit:
            break
    return out


def check_candidate(
    timetable: dict, rooms: list, staff: str | None = None, room: str | None = None,
    day: int | None = None, slot: int = 0, group: str | None = None,
    enrolled: int = 0,
) -> tuple[bool, list[dict], list]:
    """Evaluate a hypothetical placement; returns (ok, conflicts, recommendations)."""
    conflicts: list[dict] = []
    if day is None:
        return False, [{'conflict_type': 'INVALID_DAY', 'description': 'Day is required.'}], []
    if room:
        cap = next(
            ((r.get('capacity') if isinstance(r, dict) else getattr(r, 'capacity', 0))
             for r in (rooms or [])
             if (r.get('name') if isinstance(r, dict) else getattr(r, 'name', None)) == room),
            None,
        )
        if cap is None:
            conflicts.append({'conflict_type': 'INVALID_ROOM', 'description': f'Room not found: {room}.'})
        else:
            if enrolled > (cap or 0):
                conflicts.append({'conflict_type': 'CAPACITY', 'description': f'Room capacity {cap} < enrolled {enrolled}.'})
            if not _slot_free(timetable, 'rooms', room, day, slot):
                conflicts.append({'conflict_type': 'ROOM_BUSY', 'description': f'Room {room} is occupied at day {day} slot {slot}.'})
    if staff and _staff_busy(timetable, staff, day, slot):
        conflicts.append({'conflict_type': 'STAFF_BUSY', 'description': f'{staff} already teaches at day {day} slot {slot}.'})
    if group and _group_busy(timetable, group, day, slot):
        conflicts.append({'conflict_type': 'GROUP_CLASH', 'description': f'Group {group} already has a session at day {day} slot {slot}.'})
    recs = []
    if conflicts:
        recs = suggest_alternatives(timetable, rooms, staff, group, enrolled, day, slot, exclude_row=room)
    return (len(conflicts) == 0), conflicts, recs
