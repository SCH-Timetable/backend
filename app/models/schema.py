"""
Pydantic models that mirror the TypeScript types in the frontend.

Frontend file → Python model(s):
  data.ts        → Session, Conflict, Alternative, ConflictType, ViewMode
  roomsData.ts   → Room, ClosureWindow, RoomType, AccessTag, EquipmentItem
  LoginScreen.tsx → LoginRequest, LoginResponse
  App.tsx         → ScheduleVersion
  StudentPortal.tsx → StudentSession, Credit
"""

from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ── Shared enumerations ────────────────────────────────────────────────────────

ViewMode      = Literal["rooms", "labs", "staff"]
ConflictType  = Literal["double_booking", "capacity", "staff_overlap", "equipment", "student_group", "room_type", "closure"]
Severity      = Literal["hard", "soft"]
RoomStatus    = Literal["Available", "Maintenance", "Closed"]
VersionStatus = Literal["draft", "published", "archived"]

RoomType = Literal[
    "Lecture Theatre", "Seminar Room", "Computer Lab",
    "Science Lab", "Studio", "Workshop"
]

AccessTag = Literal[
    "Wheelchair Access", "Hearing Loop", "Braille Signage",
    "Elevator Access", "Accessible WC Nearby", "Level Access"
]

EquipmentItem = Literal[
    "Projector (4K)", "Smartboard", "Document Camera", "PA System",
    "Video Conferencing", "Whiteboards", "PC Workstations", "Mac Workstations",
    "Oscilloscopes", "Fume Hoods", "3D Printers", "Laser Cutters",
    "Recording Studio Gear", "Microscopes", "Centrifuges", "Spectrometers"
]

UserRole = Literal["admin", "lecturer", "student"]

Major = Literal["CS", "IT", "AI", "DS"]
AcademicYear = Literal[1, 2, 3, 4]


# ── Auth ───────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    role: UserRole
    token: str          # JWT or opaque session token
    display_name: str


# ── Timetable / Session ────────────────────────────────────────────────────────

class ConflictCell(BaseModel):
    row: str            # room / lab / staff name
    day: int            # 0-4 (Mon-Fri)
    slot: int           # 0-9 (08:00-17:00)

class Alternative(BaseModel):
    id: str
    score: int          # 0-100 fitness score
    day: int
    slot: int
    room: str
    reasons: list[str]

class Conflict(BaseModel):
    id: str
    type: ConflictType
    severity: Severity
    description: str
    cell: ConflictCell
    alternatives: list[Alternative]

class Session(BaseModel):
    id: str
    code: str           # e.g. "CS301"
    name: str           # e.g. "Algorithms"
    staff: str
    group: str          # student group, e.g. "CS-3A"
    capacity: int
    enrolled: int
    color: str          # hex colour for the cell
    slot: int = 0       # start time-slot index (0 = 08:00)
    duration: int = 1   # number of consecutive slots
    academic_year: Optional[int] = Field(None, description="1-4")
    major: Optional[Major] = None  # CS/IT/AI/DS, optional for 1-2, required for 3-4
    conflict_id: Optional[str] = Field(None, alias="conflictId")

    class Config:
        populate_by_name = True

# Grid: { view → { row → { day_index → { slot_index → Session | null } } } }
TimetableGrid = dict[str, dict[str, dict[int, dict[int, Optional[Session]]]]]


# ── Rooms ──────────────────────────────────────────────────────────────────────

class ClosureWindow(BaseModel):
    label: str
    from_date: str = Field(..., alias="from")   # ISO date string
    to_date: str   = Field(..., alias="to")
    reason: str

    class Config:
        populate_by_name = True

class Room(BaseModel):
    id: str
    name: str
    building: str
    floor: int
    type: RoomType
    capacity: int
    exam_capacity: int   = Field(..., alias="examCapacity")
    accessibility: list[AccessTag]
    equipment: list[EquipmentItem]
    closures: list[ClosureWindow]
    status: RoomStatus
    booking_rate: int    = Field(..., alias="bookingRate")   # % utilisation
    notes: str

    class Config:
        populate_by_name = True


# ── Schedule versions ──────────────────────────────────────────────────────────

class ScheduleVersion(BaseModel):
    id: str
    label: str              # e.g. "v2.3 — Spring 2026"
    status: VersionStatus
    timestamp: str          # ISO datetime string
    author: str
    changes: int            # number of changes vs previous version
    conflicts: int          # unresolved conflict count


# ── Analytics ─────────────────────────────────────────────────────────────────

class UtilizationPoint(BaseModel):
    name: str       # e.g. room name, day abbreviation, or hour string
    utilization: int

class ConflictStat(BaseModel):
    name: str
    value: int
    color: str

class AnalyticsSummary(BaseModel):
    total_sessions: int
    total_conflicts: int
    avg_utilization: float
    rooms_at_capacity: int
    utilization_by_room: list[UtilizationPoint]
    utilization_by_day: list[UtilizationPoint]
    utilization_by_hour: list[UtilizationPoint]
    conflict_breakdown: list[ConflictStat]


# ── Student portal ─────────────────────────────────────────────────────────────

class StudentSession(BaseModel):
    id: str
    code: str
    name: str
    staff: str
    room: str
    day: int            # 0-4
    slot: int           # 0-9
    color: str
    academic_year: Optional[int] = None
    major: Optional[Major] = None

class Credit(BaseModel):
    code: str
    name: str
    credits: int
    grade: Optional[str]
    status: Literal["completed", "in_progress", "planned"]

class StudentProfile(BaseModel):
    id: str
    name: str
    group: str
    programme: str
    year: int
    academic_year: Optional[int] = None
    major: Optional[Major] = None
    sessions: list[StudentSession]
    credits: list[Credit]
    total_credits_required: int
    total_credits_earned: int


# ── Apply-alternative request ─────────────────────────────────────────────────

class ApplyAlternativeRequest(BaseModel):
    conflict_id: str
    alternative_id: str


# ── Courses / Sections / Registrations ───────────────────────────────────────

class Course(BaseModel):
    id: str
    code: str           # e.g. "CS301"
    name: str
    credits: int = 3
    year: str = 'Year 2'    # Year 1..4
    term: str = 'Fall'      # Fall | Spring | Summer

class Section(BaseModel):
    id: str             # e.g. "sec-s1"
    course_id: str
    code: str           # course code snapshot, e.g. "CS301"
    name: str
    staff: str
    group: str
    capacity: int
    enrolled: int = 0
    year: str = 'Year 2'
    term: str = 'Fall'
    academic_year: Optional[int] = None  # 1-4 (target academic year)
    major: Optional[Major] = None  # CS, IT, AI, DS (required for year 3-4)

class CourseRegistration(BaseModel):
    id: str
    student_id: str
    section_id: str
    year: str
    term: str
    status: Literal["registered", "dropped"] = "registered"


# ── Notifications ────────────────────────────────────────────────────────────

class Notification(BaseModel):
    id: str
    audience: Literal["all", "admin", "lecturer", "student"] = "all"
    email: Optional[str] = None   # targeted user, if any
    type: str = "info"            # info | publish | timetable_change | conflict
    message: str
    related_id: Optional[str] = None
    read: bool = False
    created_at: str = ""


# ── Audit Trail ──────────────────────────────────────────────────────────────

class AuditEvent(BaseModel):
    id: str
    actor_email: str
    actor_role: str = "admin"
    action: str  # e.g. timetable_update, publish, archive, conflict_apply, room_update
    entity_type: str  # timetable | version | conflict | room | student | section
    entity_id: str
    message: str = ""
    before: Optional[dict] = None
    after: Optional[dict] = None
    created_at: str = ""
