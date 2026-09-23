"""
Section endpoints (master data for courses/sections).

GET    /api/sections              → list all sections (?q=&year=&term=)
GET    /api/sections/{id}         → one section
POST   /api/sections              → create a section (admin)
PUT    /api/sections/{id}         → update a section (admin)
DELETE /api/sections/{id}         → delete a section (admin)
"""

from fastapi import APIRouter, Header, HTTPException, Query
from typing import Optional
from uuid import uuid4

from app.models.schema import Section
from app.data_store import SECTIONS, COURSES
from app.database import save_section, delete_section, save_course
from app.routers.auth import require_admin

router = APIRouter()


@router.get('', response_model=list[Section])
def list_sections(
    q: Optional[str] = None,
    year: Optional[str] = None,
    term: Optional[str] = None,
):
    sections = SECTIONS
    if year:
        sections = [s for s in sections if s.year == year]
    if term:
        sections = [s for s in sections if s.term == term]
    if q:
        ql = q.lower()
        sections = [s for s in sections
                    if ql in s.code.lower() or ql in s.name.lower()
                    or ql in s.staff.lower() or ql in s.group.lower()]
    return sections


@router.get('/{section_id}', response_model=Section)
def get_section(section_id: str):
    s = next((x for x in SECTIONS if x.id == section_id), None)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Section '{section_id}' not found")
    return s


@router.post('', response_model=Section, status_code=201)
def create_section(body: dict, authorization: str = Header(default='')):
    require_admin(authorization)
    for field in ('code', 'name', 'staff', 'group'):
        if not str(body.get(field, '')).strip():
            raise HTTPException(status_code=422, detail=f'{field} is required')
    code = body['code'].strip()
    course = next((c for c in COURSES if c.code == code), None)
    if course is None:
        from app.models.schema import Course
        course = Course(id=f'crs-{code}', code=code, name=body['name'].strip(),
                        credits=int(body.get('credits', 3)), year=body.get('year', 'Year 2'),
                        term=body.get('term', 'Fall'))
        COURSES.append(course)
        save_course(course)
    academic_year = body.get('academic_year')
    if academic_year is not None:
        try:
            academic_year = int(academic_year)
        except Exception:
            raise HTTPException(status_code=422, detail='academic_year must be 1-4')
        if academic_year not in (1,2,3,4):
            raise HTTPException(status_code=422, detail='academic_year must be 1-4')
    major = body.get('major')
    if academic_year is not None and academic_year >= 3 and not major:
        raise HTTPException(status_code=422, detail='Major is required for academic years 3 and 4 (CS, IT, AI, DS)')
    if major and major not in ('CS','IT','AI','DS'):
        raise HTTPException(status_code=422, detail='Invalid major')
    section = Section(
        id=f"sec-{uuid4().hex[:8]}", course_id=course.id, code=code,
        name=body['name'].strip(), staff=body['staff'].strip(), group=body['group'].strip(),
        capacity=int(body.get('capacity', 30)), enrolled=int(body.get('enrolled', 0)),
        year=body.get('year', course.year), term=body.get('term', course.term),
        academic_year=academic_year, major=major,
    )
    SECTIONS.append(section)
    save_section(section)
    return section


@router.put('/{section_id}', response_model=Section)
def update_section(section_id: str, updates: dict, authorization: str = Header(default='')):
    require_admin(authorization)
    idx = next((i for i, x in enumerate(SECTIONS) if x.id == section_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Section '{section_id}' not found")
    allowed = {'name', 'staff', 'group', 'capacity', 'enrolled', 'year', 'term', 'academic_year', 'major'}
    clean = {k: v for k, v in updates.items() if k in allowed}
    # validate major requirement if academic_year being set
    ay = clean.get('academic_year', SECTIONS[idx].academic_year)
    mj = clean.get('major', SECTIONS[idx].major)
    # also allow explicit null to clear? keep as is
    if ay is not None and ay >= 3 and not mj:
        raise HTTPException(status_code=422, detail='Major is required for academic years 3 and 4 (CS, IT, AI, DS)')
    if mj and mj not in ('CS','IT','AI','DS'):
        raise HTTPException(status_code=422, detail='Invalid major')
    SECTIONS[idx] = SECTIONS[idx].model_copy(update=clean)
    save_section(SECTIONS[idx])
    return SECTIONS[idx]


@router.delete('/{section_id}')
def remove_section(section_id: str, authorization: str = Header(default='')):
    require_admin(authorization)
    before = len(SECTIONS)
    SECTIONS[:] = [x for x in SECTIONS if x.id != section_id]
    if len(SECTIONS) == before:
        raise HTTPException(status_code=404, detail=f"Section '{section_id}' not found")
    delete_section(section_id)
    return {'ok': True, 'deleted': section_id}
