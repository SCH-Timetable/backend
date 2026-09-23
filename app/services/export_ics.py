"""Shared ICS calendar builder (used by chatbot + canonical schedules export)."""

from __future__ import annotations


def build_ics(rows: list[dict], days: list[str]) -> str:
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Bua University//EN', 'CALSCALE:GREGORIAN']
    base_dates = ['20260119', '20260120', '20260121', '20260122', '20260123']
    for r in rows:
        try:
            day_idx = days.index(r['day_name']) if r.get('day_name') in days else 0
        except Exception:
            day_idx = 0
        slot_str = (r.get('time') or '').split('-')[0] if '-' in (r.get('time') or '') else (r.get('time') or '')
        try:
            slot_hour = int(slot_str.split(':')[0]) if ':' in slot_str else 8
        except Exception:
            slot_hour = 8
        lines.extend([
            'BEGIN:VEVENT',
            f"UID:{r.get('id')}@bua.edu.eg",
            'DTSTAMP:20260115T080000Z',
            f"DTSTART:2026{base_dates[day_idx][4:]}T{slot_hour:02d}0000",
            f"DTEND:2026{base_dates[day_idx][4:]}T{slot_hour + 1:02d}0000",
            f"SUMMARY:{r.get('code')} — {r.get('name')}",
            f"LOCATION:{r.get('room')}",
            f"DESCRIPTION:{r.get('staff')} - {r.get('group')}",
            'END:VEVENT',
        ])
    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines)
