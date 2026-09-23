"""
Student endpoints.

GET /api/students/me          → current student profile + sessions + credits
GET /api/students/me/sessions → timetable sessions for the current student (filtered by academic_year + major)
GET /api/students/me/credits  → credit summary
GET /api/students/me/timetable → filtered timetable for current student (by academic_year + major)
GET /api/students             → managed student roster (mirrors StudentManagerModal)
POST /api/students            → add a student {name, email, group, year, academic_year?, major?}
PATCH /api/students/{id}      → update group (or name/email/year/academic_year/major)
DELETE /api/students/{id}     → remove a student
POST /api/students/register-courses → register sections {student_id, section_ids, year, term}
GET /api/students/{id}/registrations → list a student's registrations
POST /api/students/me/register → student self-registration with seat check
GET /api/students/me/registrations → list current student's registrations
GET /api/students/me/timetable → filtered timetable for current student (by academic_year + major)
"""

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel
from typing import Optional, Literal
from uuid import uuid4
from app.models.schema import StudentProfile, StudentSession, Credit, CourseRegistration, Major
from app.data_store import STUDENT_PROFILE, MANAGED_STUDENTS, TIMETABLE, SECTIONS, REGISTRATIONS
from app.database import delete_student, save_student, save_registration, delete_registration, save_section
from app.routers.auth import require_admin, get_email_from_auth

router = APIRouter()


class StudentCreate(BaseModel):
    name: str
    email: str
    group: str
    year: str = 'Year 2'
    academic_year: Optional[int] = None  # 1-4
    major: Optional[Major] = None  # CS, IT, AI, DS (required for year 3-4)


class StudentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    group: Optional[str] = None
    year: Optional[str] = None
    academic_year: Optional[int] = None
    major: Optional[Major] = None


@router.get('/me', response_model=StudentProfile)
def get_my_profile():
    return STUDENT_PROFILE


def _get_student_profile_data(authorization: str = ''):
    """Resolve authenticated student's profile; falls back to demo STUDENT_PROFILE."""
    email = None
    try:
        from app.routers.auth import get_email_from_auth
        email = get_email_from_auth(authorization)
    except Exception:
        email = None
    if email:
        # Find managed student by email (real per-user filtering)
        for s in MANAGED_STUDENTS:
            if s.get('email','').lower() == email.lower():
                # Return dict-like with same attrs as StudentProfile for filtering
                return s  # dict with group, academic_year, major, email, year
        # Also fallback to USERS lookup? Keep demo profile for amara@ etc.
        if email.lower() == 'amara@bua.edu.eg':
            return STUDENT_PROFILE
    return STUDENT_PROFILE


def _resolve_profile(authorization: str = ''):
    """Return tuple (group, academic_year, major, email) for current student."""
    p = _get_student_profile_data(authorization)
    if isinstance(p, dict):
        return p.get('group'), p.get('academic_year'), p.get('major'), p.get('email')
    return getattr(p, 'group', None), getattr(p, 'academic_year', None), getattr(p, 'major', None), getattr(p, 'id', '')


@router.get('/me/sessions', response_model=list[StudentSession])
def get_my_sessions(response: Response, authorization: str = Header(default='')):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    profile_group, profile_academic_year, profile_major, _ = _resolve_profile(authorization)
    
    # Build filtered list from rooms + labs (lectures + practicals)
    # Publish sync: always read live TIMETABLE (the published or draft active grid)
    # so admin's Save/Publish appears instantly without student reload.
    sessions: list[StudentSession] = []
    for view in ('rooms', 'labs'):
        for row_name, days in TIMETABLE.get(view, {}).items():
            for day, slots in days.items():
                cells = slots.values() if isinstance(slots, dict) else [slots]
                for session in cells:
                    if session is None:
                        continue
                    session_group = session.get('group') if isinstance(session, dict) else getattr(session, 'group', None)
                    session_academic_year = session.get('academic_year') if isinstance(session, dict) else getattr(session, 'academic_year', None)
                    session_major = session.get('major') if isinstance(session, dict) else getattr(session, 'major', None)
                    session_slot = session.get('slot') if isinstance(session, dict) else getattr(session, 'slot', 0)
                    is_general = session_academic_year is None and session_major is None
                    # General (no year/major) => visible to all, skip group/year/major checks
                    if not is_general:
                        # General group GEN also visible to all
                        if session_group != "GEN" and session_group != profile_group:
                            continue
                        if session_academic_year is not None and session_academic_year != profile_academic_year:
                            continue
                        if session_major is not None and session_major != profile_major:
                            continue
                    code = session.get('code') if isinstance(session, dict) else getattr(session, 'code', '')
                    sessions.append(StudentSession(
                        id=session.get('id') if isinstance(session, dict) else getattr(session, 'id', ''),
                        code=code,
                        name=session.get('name') if isinstance(session, dict) else getattr(session, 'name', ''),
                        staff=session.get('staff') if isinstance(session, dict) else getattr(session, 'staff', ''),
                        room=row_name,
                        day=day,
                        slot=session_slot if isinstance(session_slot, int) else 0,
                        color=session.get('color') if isinstance(session, dict) else getattr(session, 'color', '#2563eb'),
                        academic_year=session_academic_year,
                        major=session_major,
                    ))
    # Deduplicate by code+day (avoid double counting if same session in staff view)
    seen = set()
    uniq = []
    for s in sessions:
        key = (s.code, s.day, s.room)
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return uniq


@router.get('/me/timetable', response_model=list[StudentSession])
def get_my_timetable(response: Response, authorization: str = Header(default='')):
    """Filtered timetable for current student (by academic_year + major). Mirrors /me/sessions for My Schedule tab."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    profile_group, profile_academic_year, profile_major, _ = _resolve_profile(authorization)
    sessions: list[StudentSession] = []
    for view in ('rooms', 'labs'):
        for row_name, days in TIMETABLE.get(view, {}).items():
            for day, slots in days.items():
                cells = slots.values() if isinstance(slots, dict) else [slots]
                for session in cells:
                    if session is None:
                        continue
                    session_group = session.get('group') if isinstance(session, dict) else getattr(session, 'group', None)
                    session_academic_year = session.get('academic_year') if isinstance(session, dict) else getattr(session, 'academic_year', None)
                    session_major = session.get('major') if isinstance(session, dict) else getattr(session, 'major', None)
                    session_slot = session.get('slot') if isinstance(session, dict) else getattr(session, 'slot', 0)
                    is_general = session_academic_year is None and session_major is None
                    if not is_general:
                        if session_group != "GEN" and session_group != profile_group:
                            continue
                        if session_academic_year is not None and session_academic_year != profile_academic_year:
                            continue
                        if session_major is not None and session_major != profile_major:
                            continue
                    code = session.get('code') if isinstance(session, dict) else getattr(session, 'code', '')
                    sessions.append(StudentSession(
                        id=session.get('id') if isinstance(session, dict) else getattr(session, 'id', ''),
                        code=code,
                        name=session.get('name') if isinstance(session, dict) else getattr(session, 'name', ''),
                        staff=session.get('staff') if isinstance(session, dict) else getattr(session, 'staff', ''),
                        room=row_name,
                        day=day,
                        slot=session_slot if isinstance(session_slot, int) else 0,
                        color=session.get('color') if isinstance(session, dict) else getattr(session, 'color', '#2563eb'),
                        academic_year=session_academic_year,
                        major=session_major,
                    ))
    seen = set()
    uniq = []
    for s in sessions:
        key = (s.code, s.day, s.room)
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return uniq



@router.get('')
def list_students(q: Optional[str] = None):
    if not q:
        return MANAGED_STUDENTS
    ql = q.lower()
    return [s for s in MANAGED_STUDENTS
            if ql in s['name'].lower() or ql in s['group'].lower() or ql in s['email'].lower()]


@router.post('', status_code=201)
def add_student(body: StudentCreate, authorization: str = Header(default='')):
    require_admin(authorization)
    if not body.name.strip() or not body.email.strip():
        raise HTTPException(status_code=422, detail='name and email are required')
    if any(s['email'].lower() == body.email.lower() for s in MANAGED_STUDENTS):
        raise HTTPException(status_code=409, detail='email already exists')
    _validate_student_year_major(body.year, body.academic_year, body.major)
    new = {'id': f"st-{len(MANAGED_STUDENTS) + 100}", 'name': body.name.strip(),
           'email': body.email.strip(), 'group': body.group.strip() or 'GEN', 'year': body.year,
           'academic_year': body.academic_year, 'major': body.major}
    MANAGED_STUDENTS.append(new)
    save_student(new)
    return new


def _validate_student_year_major(year: str, academic_year: Optional[int], major: Optional[Major]):
    """Validate that major is required for academic years 3-4."""
    year_num = None
    if year.startswith('Year '):
        try:
            year_num = int(year.split(' ')[1])
        except ValueError:
            pass
    if academic_year:
        year_num = academic_year
    
    if year_num and year_num >= 3:
        if not major:
            raise HTTPException(status_code=422, detail='Major is required for academic years 3 and 4 (CS, IT, AI, DS)')
        if major not in ('CS', 'IT', 'AI', 'DS'):
            raise HTTPException(status_code=422, detail='Invalid major. Must be one of: CS, IT, AI, DS')


@router.patch('/{student_id}')
def update_student(student_id: str, body: StudentUpdate, authorization: str = Header(default='')):
    require_admin(authorization)
    s = next((x for x in MANAGED_STUDENTS if x['id'] == student_id), None)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' not found")
    for k in ('name', 'email', 'group', 'year', 'academic_year', 'major'):
        v = getattr(body, k)
        if v is not None and str(v).strip():
            s[k] = str(v).strip() if k != 'academic_year' and k != 'major' else v
    _validate_student_year_major(s.get('year', ''), s.get('academic_year'), s.get('major'))
    save_student(s)
    return s


@router.delete('/{student_id}')
def remove_student(student_id: str, authorization: str = Header(default='')):
    require_admin(authorization)
    before = len(MANAGED_STUDENTS)
    MANAGED_STUDENTS[:] = [x for x in MANAGED_STUDENTS if x['id'] != student_id]
    if len(MANAGED_STUDENTS) == before:
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' not found")
    delete_student(student_id)
    return {'ok': True, 'deleted': student_id}
