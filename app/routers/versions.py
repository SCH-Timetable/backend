"""
Schedule version endpoints.

GET    /api/versions              → list all versions
GET    /api/versions/{id}         → one version
POST   /api/versions              → create a new draft
POST   /api/versions/{id}/publish → publish a draft
POST   /api/versions/{id}/archive → archive a published version
DELETE /api/versions/{id}         → delete a draft
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from app.models.schema import ScheduleVersion
from app.data_store import VERSIONS
from app.database import delete_version, save_version
from app.routers.auth import require_admin, get_email_from_auth

router = APIRouter()


@router.get('', response_model=list[ScheduleVersion])
def list_versions():
    return VERSIONS


@router.get('/{version_id}', response_model=ScheduleVersion)
def get_version(version_id: str):
    v = next((v for v in VERSIONS if v.id == version_id), None)
    if v is None:
        raise HTTPException(status_code=404, detail=f"Version '{version_id}' not found")
    return v


class VersionCreate(BaseModel):
    label: str
    author: str = 'Scheduler'


@router.post('', response_model=ScheduleVersion, status_code=201)
def create_version(
    body: VersionCreate | None = None,
    label: str | None = None,
    author: str = 'Scheduler',
    authorization: str = Header(default=''),
):
    """Create a new draft version. Accepts JSON body or query params for backward compatibility."""
    require_admin(authorization)
    if body is not None:
        label = body.label
        author = body.author
    if not label:
        raise HTTPException(status_code=422, detail='label is required')
    new_id = f"v{len(VERSIONS) + 1}"
    latest_conflicts = next((v.conflicts for v in VERSIONS if v.status == 'draft'), 0)
    new_version = ScheduleVersion(
        id=new_id,
        label=label,
        status='draft',
        timestamp=datetime.now(timezone.utc).isoformat(),
        author=author,
        changes=0,
        conflicts=latest_conflicts,
    )
    VERSIONS.insert(0, new_version)
    save_version(new_version)
    try:
        from app.services.audit import log_audit
        actor = get_email_from_auth(authorization) or "admin@bua.edu.eg"
        log_audit(actor, "version_create", "version", new_version.id, message=f"Created draft '{new_version.label}'", after=new_version)
    except Exception:
        pass
    return new_version


@router.post('/{version_id}/publish', response_model=ScheduleVersion)
def publish_version(version_id: str, authorization: str = Header(default='')):
    require_admin(authorization)
    from app import data_store
    idx = next((i for i, v in enumerate(VERSIONS) if v.id == version_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Version '{version_id}' not found")
    v = VERSIONS[idx]
    if v.status == 'published':
        refreshed = v.model_copy(update={'timestamp': datetime.now(timezone.utc).isoformat()})
        VERSIONS[idx] = refreshed
        save_version(refreshed)
        try:
            from app.services.audit import log_audit
            actor = get_email_from_auth(authorization) or "admin@bua.edu.eg"
            log_audit(actor, "publish_refresh", "version", version_id, message=f"Refreshed publish timestamp for '{v.label}'", before=v, after=refreshed)
        except Exception:
            pass
        return refreshed
    if v.status != 'draft':
        raise HTTPException(status_code=409, detail=f"Version '{version_id}' is not a draft")
    # Archive existing published version
    for i, existing in enumerate(VERSIONS):
        if existing.status == 'published':
            VERSIONS[i] = existing.model_copy(update={'status': 'archived'})
            save_version(VERSIONS[i])
    from app.services.refresh import refresh_conflicts
    total = refresh_conflicts()
    VERSIONS[idx] = v.model_copy(
        update={'status': 'published',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'conflicts': total}
    )
    save_version(VERSIONS[idx])
    from app.services.notifications import notify_users
    notify_users(data_store.USERS, type='publish',
                 message=f"Schedule '{VERSIONS[idx].label}' was published with {total} open conflicts.",
                 related_id=VERSIONS[idx].id)
    try:
        from app.services.audit import log_audit
        actor = get_email_from_auth(authorization) or "admin@bua.edu.eg"
        log_audit(actor, "publish", "version", VERSIONS[idx].id, message=f"Published '{VERSIONS[idx].label}'", before=v, after=VERSIONS[idx])
    except Exception:
        pass
    return VERSIONS[idx]


@router.post('/{version_id}/archive', response_model=ScheduleVersion)
def archive_version(version_id: str, authorization: str = Header(default='')):
    require_admin(authorization)
    idx = next((i for i, v in enumerate(VERSIONS) if v.id == version_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Version '{version_id}' not found")
    before = VERSIONS[idx]
    VERSIONS[idx] = VERSIONS[idx].model_copy(update={'status': 'archived'})
    save_version(VERSIONS[idx])
    try:
        from app.services.audit import log_audit
        actor = get_email_from_auth(authorization) or "admin@bua.edu.eg"
        log_audit(actor, "archive", "version", version_id, message=f"Archived '{before.label}'", before=before, after=VERSIONS[idx])
    except Exception:
        pass
    return VERSIONS[idx]


@router.delete('/{version_id}')
def delete_version(version_id: str, authorization: str = Header(default='')):
    require_admin(authorization)
    original_len = len(VERSIONS)
    matching = next((v for v in VERSIONS if v.id == version_id), None)
    if matching is None:
        raise HTTPException(status_code=404, detail=f"Version '{version_id}' not found")
    if matching.status != 'draft':
        raise HTTPException(status_code=409, detail='Only draft versions can be deleted')
    VERSIONS[:] = [v for v in VERSIONS if v.id != version_id]
    delete_version(version_id)
    try:
        from app.services.audit import log_audit
        actor = get_email_from_auth(authorization) or "admin@bua.edu.eg"
        log_audit(actor, "delete", "version", version_id, message=f"Deleted draft '{matching.label}'", before=matching)
    except Exception:
        pass
    return {'ok': True, 'deleted': version_id}
