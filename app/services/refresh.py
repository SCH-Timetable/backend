"""Keep the curated conflict list in sync with auto-detected conflicts."""

from __future__ import annotations


def refresh_conflicts() -> int:
    """Replace stale auto-* conflicts with a fresh detection pass. Returns total count."""
    from app import data_store
    from app.services.conflicts import detect_all_conflicts
    from app.database import save_setting
    auto = detect_all_conflicts(data_store.TIMETABLE, data_store.ALL_ROOMS)
    manual = [c for c in data_store.CONFLICTS if not c.id.startswith('auto-')]
    manual_keys = {(c.type, c.cell.row, c.cell.day, c.cell.slot) for c in manual}
    fresh = [c for c in auto
             if (c.type, c.cell.row, c.cell.day, c.cell.slot) not in manual_keys]
    data_store.CONFLICTS[:] = manual + fresh
    try:
        save_setting('conflicts', [c.model_dump(by_alias=True) for c in data_store.CONFLICTS])
    except Exception:
        pass
    for v in data_store.VERSIONS:
        if v.status == 'draft':
            v.conflicts = len(data_store.CONFLICTS)
    return len(data_store.CONFLICTS)
