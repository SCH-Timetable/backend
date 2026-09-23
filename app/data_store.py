"""
In-memory data store that seeds from the same constants used in the frontend
(data.ts and roomsData.ts).  Replace with a real database layer as needed.
Mirrors frontend after all UI fixes: 10 rooms, 10 labs, 15 staff,
25 sessions, 6 hard conflicts, BUA branding.
"""

from copy import deepcopy
from app.models.schema import (
    Session, Conflict, ConflictCell, Alternative,
    Room, ClosureWindow, ScheduleVersion,
    StudentSession, Credit, StudentProfile,
    Course, Section, CourseRegistration, Notification,
)

# ── Constants (mirrors data.ts) ───────────────────────────────────────────────

DAYS       = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
FULL_DAYS  = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
TIME_SLOTS = ['08:00', '09:00', '10:00', '11:00', '12:00',
              '13:00', '14:00', '15:00', '16:00', '17:00']
ROOMS  = ['LT-101', 'LT-102', 'LT-201', 'LT-202', 'SEM-A', 'SEM-B', 'SEM-C', 'SEM-D', 'SEM-E', 'Studio-A']
LABS   = ['CS-Lab1', 'CS-Lab2', 'CS-Lab3', 'Phys-Lab', 'Phys-Lab2', 'Chem-Lab', 'Chem-Lab B', 'BioLab', 'BioLab2', 'Eng-Workshop']
STAFF  = ['Dr. Chen Wei', 'Prof. Amara Nwosu', 'Dr. Lena Kovač',
          'Dr. Raj Patel', 'Prof. Sara Johansson', 'Dr. Marcus Bell',
          'Dr. Ahmed Hassan', 'Dr. Fatma Ali', 'Prof. John Smith',
          'Dr. Mona Khalil', 'Eng. Omar Farouk', 'Dr. Heba Mostafa',
          'Prof. Karim Adel', 'Dr. Nadia Samir', 'TA. Youssef Nabil']

VALID_DOMAINS = ['bua.edu.eg', 'staff.bua.edu.eg',
                 'cs.bua.edu.eg', 'eng.bua.edu.eg', 'badr.edu.eg']


# ── Timetable data (mirrors TIMETABLE_DATA in data.ts) ───────────────────────

def _s(id_, code, name, staff, group, cap, enrolled, color, slot=2, duration=1, conflict_id=None, academic_year=None, major=None):
    return Session(
        id=id_, code=code, name=name, staff=staff, group=group,
        capacity=cap, enrolled=enrolled, color=color,
        slot=slot, duration=duration,
        academic_year=academic_year, major=major,
        **({'conflictId': conflict_id} if conflict_id else {}),
    )


def _infer_year_major(group: str) -> tuple[int | None, str | None]:
    """Infer academic_year/major from group like CS-3A, ENG-2B etc. Year 1-2 -> optional, 3-4 -> CS/IT/AI/DS."""
    try:
        # group format: PREFIX-YEAR? e.g. CS-3A -> year 3
        part = group.split('-')[-1] if '-' in group else ''
        year = int(part[0]) if part and part[0].isdigit() else None
    except Exception:
        year = None
    if year is None:
        return None, None
    if year <= 2:
        return year, None
    prefix = group.split('-')[0].upper() if '-' in group else group.upper()
    major_map = {'CS': 'CS', 'IT': 'IT', 'AI': 'AI', 'DS': 'DS',
                 'EE': 'IT', 'ENG': 'IT', 'MECH': 'IT', 'BIO': 'DS', 'CHEM': 'AI', 'PHYS': 'DS', 'MATH': 'CS'}
    major = major_map.get(prefix, 'CS')
    return year, major


def _empty_slots() -> dict[int, Session | None]:
    return {i: None for i in range(len(TIME_SLOTS))}


def _empty_week() -> dict[int, dict[int, Session | None]]:
    return {d: _empty_slots() for d in range(len(DAYS))}


def _blank_grid() -> dict[str, dict[str, dict[int, dict[int, Session | None]]]]:
    return {
        'rooms': {name: _empty_week() for name in ROOMS},
        'labs': {name: _empty_week() for name in LABS},
        'staff': {name: _empty_week() for name in STAFF},
    }


def _put(grid, view: str, row: str, day: int, session: Session) -> None:
    slot = session.slot
    grid[view][row][day][slot] = session
    staff_row = grid['staff'].get(session.staff)
    if staff_row is not None and staff_row[day][slot] is None:
        staff_row[day][slot] = session


def _build_timetable() -> dict[str, dict[str, dict[int, dict[int, Session | None]]]]:
    grid = _blank_grid()
    def mk(id_, code, name, staff, group, cap, enrolled, color, slot, duration=1, conflict_id=None):
        y, m = _infer_year_major(group)
        return _s(id_, code, name, staff, group, cap, enrolled, color, slot, duration, conflict_id, y, m)
    # Lectures / seminars: day + start slot (0 = 08:00). Labs sit in the afternoon.
    placements = [
        ('rooms', 'LT-101', 0, mk('s1',  'CS301',   'Algorithms',         'Dr. Chen Wei',         'CS-3A',    240, 108, '#2563eb', 0)),
        ('rooms', 'LT-101', 1, mk('s2',  'MATH201', 'Linear Algebra',     'Prof. Sara Johansson', 'ENG-2B',   240, 235, '#7c3aed', 1, 1, 'c1')),
        ('rooms', 'LT-101', 3, mk('s3',  'CS401',   'ML Foundations',     'Dr. Lena Kovač',       'CS-4A',    240,  94, '#2563eb', 3)),
        ('rooms', 'LT-101', 4, mk('s4',  'PHYS101', 'Mechanics',          'Dr. Raj Patel',        'ENG-1A',   240, 120, '#0891b2', 4, 1, 'c2')),
        ('rooms', 'LT-102', 1, mk('s5',  'ENG201',  'Circuit Analysis',   'Prof. Amara Nwosu',    'EE-2A',    120,  72, '#059669', 1)),
        ('rooms', 'LT-102', 2, mk('s6',  'CS201',   'Data Structures',    'Dr. Chen Wei',         'CS-2A',    120,  78, '#2563eb', 2)),
        ('rooms', 'LT-102', 4, mk('s7',  'MATH301', 'Calculus III',       'Prof. Sara Johansson', 'MATH-3A',  120,  68, '#7c3aed', 3)),
        ('rooms', 'LT-201', 0, mk('s8',  'BIO101',  'Cell Biology',       'Dr. Marcus Bell',      'BIO-1A',   300, 187, '#be185d', 0)),
        ('rooms', 'LT-201', 2, mk('s9',  'CHEM201', 'Organic Chem',       'Dr. Raj Patel',        'CHEM-2B',  300, 143, '#d97706', 1)),
        ('rooms', 'LT-201', 3, mk('s10', 'PHYS201', 'Electrodynamics',    'Dr. Raj Patel',        'PHYS-2A',  300,  98, '#0891b2', 4, 1, 'c2')),
        ('rooms', 'LT-202', 0, mk('s18', 'CS101',   'Intro to CS',        'Dr. Ahmed Hassan',     'CS-1A',    180, 172, '#2563eb', 0)),
        ('rooms', 'LT-202', 1, mk('s19', 'MATH101', 'Calculus I',         'Dr. Fatma Ali',        'ENG-1B',   180, 165, '#7c3aed', 1)),
        ('rooms', 'LT-202', 3, mk('s20', 'ENG101',  'Statics',            'Prof. John Smith',     'MECH-1A',  180, 150, '#059669', 3)),
        ('rooms', 'SEM-A',  1, mk('s11', 'CS501',   'Distributed Systems','Dr. Lena Kovač',       'CS-MSc',    30,  24, '#2563eb', 1)),
        ('rooms', 'SEM-A',  2, mk('s12', 'ENG401',  'Control Systems',    'Prof. Amara Nwosu',    'EE-4A',     30,  28, '#059669', 2)),
        ('rooms', 'SEM-A',  4, mk('s13', 'MATH501', 'Real Analysis',      'Prof. Sara Johansson', 'MATH-MSc',  30,  18, '#7c3aed', 3)),
        ('rooms', 'SEM-B',  0, mk('s14', 'CS601',   'Research Methods',   'Dr. Chen Wei',         'PhD-1',     20,  12, '#2563eb', 0)),
        ('rooms', 'SEM-B',  3, mk('s15', 'BIO301',  'Genetics',           'Dr. Marcus Bell',      'BIO-3A',    20,  19, '#be185d', 3)),
        ('rooms', 'SEM-C',  1, mk('s16', 'CHEM401', 'Spectroscopy',       'Dr. Raj Patel',        'CHEM-4A',   20,  16, '#d97706', 1, 1, 'c4')),
        ('rooms', 'SEM-C',  4, mk('s17', 'ENG301',  'Thermodynamics',     'Prof. Amara Nwosu',    'MECH-3A',   20,  20, '#059669', 4, 1, 'c3')),
        ('rooms', 'SEM-D',  0, mk('s21', 'CS302',   'Operating Systems',  'Dr. Mona Khalil',      'CS-3B',     25,  23, '#2563eb', 0)),
        ('rooms', 'SEM-D',  2, mk('s22', 'ENG202',  'Electronics I',      'Eng. Omar Farouk',     'EE-2B',     25,  22, '#059669', 2, 1, 'c5')),
        ('rooms', 'SEM-E',  2, mk('s23', 'BIO201',  'Microbiology',       'Dr. Heba Mostafa',     'BIO-2A',    25,  24, '#be185d', 2, 1, 'c6')),
        ('rooms', 'SEM-E',  3, mk('s24', 'CHEM102', 'General Chem II',    'Prof. Karim Adel',     'CHEM-1A',   25,  21, '#d97706', 3)),
        ('rooms', 'Studio-A', 1, mk('s25', 'CS402', 'HCI Studio',         'Dr. Nadia Samir',      'CS-4B',     22,  20, '#7c3aed', 1)),
        ('labs', 'CS-Lab1', 0, mk('lb1', 'CS201L', 'Data Structures Lab', 'Dr. Chen Wei',    'CS-2A', 60, 28, '#2563eb', 6)),
        ('labs', 'CS-Lab1', 2, mk('lb2', 'CS301L', 'Algorithms Lab',      'Dr. Chen Wei',    'CS-3A', 60, 24, '#2563eb', 6)),
        ('labs', 'CS-Lab1', 4, mk('lb3', 'CS401L', 'ML Lab',              'Dr. Lena Kovač',  'CS-4A', 60, 22, '#7c3aed', 6)),
        ('labs', 'CS-Lab2', 1, mk('lb4', 'CS501L', 'Distributed Sys Lab', 'Dr. Lena Kovač',  'CS-MSc', 40, 18, '#7c3aed', 6)),
        ('labs', 'CS-Lab2', 3, mk('lb5', 'CS601L', 'Research Lab',        'Dr. Chen Wei',    'PhD-1',  40, 12, '#2563eb', 6)),
        ('labs', 'CS-Lab3', 0, mk('lb12', 'CS302L', 'OS Lab',             'Dr. Mona Khalil',  'CS-3B', 50, 23, '#2563eb', 6)),
        ('labs', 'CS-Lab3', 3, mk('lb13', 'CS101L', 'Intro CS Lab',       'Dr. Ahmed Hassan', 'CS-1A', 50, 42, '#2563eb', 6)),
        ('labs', 'Phys-Lab', 0, mk('lb6', 'PHYS101L', 'Mechanics Lab',    'Dr. Raj Patel', 'ENG-1A', 48, 24, '#0891b2', 6)),
        ('labs', 'Phys-Lab', 3, mk('lb7', 'PHYS201L', 'Electrodynamics Lab', 'Dr. Raj Patel', 'PHYS-2A', 48, 20, '#0891b2', 6)),
        ('labs', 'Phys-Lab2', 1, mk('lb14', 'PHYS102L', 'Waves Lab',      'Dr. Fatma Ali',   'ENG-1B', 40, 22, '#0891b2', 6)),
        ('labs', 'Chem-Lab', 1, mk('lb8', 'CHEM201L', 'Organic Chem Lab', 'Dr. Raj Patel', 'CHEM-2B', 30, 16, '#d97706', 6)),
        ('labs', 'Chem-Lab', 4, mk('lb9', 'CHEM401L', 'Spectroscopy Lab', 'Dr. Raj Patel', 'CHEM-4A', 30, 14, '#d97706', 6)),
        ('labs', 'Chem-Lab B', 2, mk('lb15', 'CHEM102L', 'General Chem Lab', 'Prof. Karim Adel', 'CHEM-1A', 30, 21, '#d97706', 6)),
        ('labs', 'BioLab', 2, mk('lb10', 'BIO101L', 'Cell Biology Lab',  'Dr. Marcus Bell', 'BIO-1A', 28, 19, '#be185d', 6)),
        ('labs', 'BioLab', 3, mk('lb11', 'BIO301L', 'Genetics Lab',      'Dr. Marcus Bell', 'BIO-3A', 28, 18, '#be185d', 6)),
        ('labs', 'BioLab2', 1, mk('lb16', 'BIO201L', 'Microbiology Lab', 'Dr. Heba Mostafa', 'BIO-2A', 24, 22, '#be185d', 6)),
        ('labs', 'Eng-Workshop', 0, mk('lb17', 'ENG202L', 'Electronics Workshop', 'Eng. Omar Farouk', 'EE-2B', 30, 22, '#059669', 6)),
    ]
    for view, row, day, session in placements:
        _put(grid, view, row, day, session)
    return grid


_RAW_TIMETABLE = _build_timetable()

# Mutable working copy (lets PUT/PATCH calls modify sessions)
TIMETABLE: dict[str, dict[str, dict[int, dict[int, Session | None]]]] = deepcopy(_RAW_TIMETABLE)

# ── Conflicts (mirrors CONFLICTS in data.ts) ─────────────────────────────────

_RAW_CONFLICTS: list[Conflict] = [
    Conflict(
        id='c1', type='capacity', severity='hard',
        description='MATH201: 235 enrolled in LT-101 (capacity 240) — safety margin under 5%. Move to larger hall.',
        cell=ConflictCell(row='LT-101', day=1, slot=1),
        alternatives=[
            Alternative(id='a1', score=97, day=1, slot=1, room='LT-201',
                        reasons=['Capacity 300 — 22% buffer', 'Same time slot retained', 'Prof. Johansson available']),
            Alternative(id='a2', score=82, day=3, slot=1, room='LT-101',
                        reasons=['Same room, Thu 09:00 free', 'Group has no conflicts Thu', 'Equipment match 100%']),
            Alternative(id='a3', score=71, day=1, slot=3, room='LT-201',
                        reasons=['LT-201 free at 11:00 Tue', 'Moderate group impact', 'Staff available']),
        ],
    ),
    Conflict(
        id='c2', type='staff_overlap', severity='hard',
        description='Dr. Raj Patel double-booked: PHYS101 (LT-101) and PHYS201 (LT-201) both at Fri 12:00',
        cell=ConflictCell(row='LT-101', day=4, slot=4),
        alternatives=[
            Alternative(id='a4', score=94, day=4, slot=7, room='LT-101',
                        reasons=['PHYS101 → Fri 15:00, room free', 'Dr. Patel free after 14:30', 'Group ENG-1A no afternoon conflict']),
            Alternative(id='a5', score=88, day=2, slot=4, room='LT-201',
                        reasons=['Move PHYS101 → Wed 12:00', 'Both staff and room available', 'Capacity sufficient']),
            Alternative(id='a6', score=63, day=0, slot=5, room='LT-102',
                        reasons=['Mon 13:00 open', 'Smaller room — 120 cap fits 120 enrolled', 'Travel time issue SEM block']),
        ],
    ),
    Conflict(
        id='c3', type='closure', severity='hard',
        description='SEM-C Fri 12:00 — ENG301 overlaps building close-down window (needs 60 min, only 30 left).',
        cell=ConflictCell(row='SEM-C', day=4, slot=4),
        alternatives=[
            Alternative(id='a7', score=91, day=4, slot=2, room='SEM-C',
                        reasons=['Fri 10:00 — 90 min clearance', 'Room unoccupied', 'Full session fits']),
            Alternative(id='a8', score=85, day=3, slot=3, room='SEM-A',
                        reasons=['Thu 11:00, SEM-A free', 'Prof. Nwosu available', 'Group MECH-3A no clashes']),
            Alternative(id='a8b', score=78, day=4, slot=1, room='SEM-D',
                        reasons=['Fri 09:00 free', 'Capacity 25 fits 20', 'No closure conflict']),
        ],
    ),
    Conflict(
        id='c4', type='equipment', severity='hard',
        description='CHEM401 in SEM-C: practical needs Fume Hoods + Spectrometers, room has only Smartboard.',
        cell=ConflictCell(row='SEM-C', day=1, slot=1),
        alternatives=[
            Alternative(id='a9', score=96, day=1, slot=2, room='Chem-Lab B',
                        reasons=['Fume Hoods + Spectrometers present', 'Capacity 30 fits 16', 'Staff available']),
            Alternative(id='a10', score=84, day=2, slot=1, room='Chem-Lab',
                        reasons=['Full equipment match', 'Tue 09:00 free', 'Group CHEM-4A free']),
            Alternative(id='a11', score=70, day=3, slot=1, room='Phys-Lab2',
                        reasons=['Spectrometers present, no fume hood', 'Partial match — needs supervision', 'Available Thu']),
        ],
    ),
    Conflict(
        id='c5', type='student_group', severity='hard',
        description='Group EE-2B clash: ENG202 (SEM-D) overlaps ENG201 lab for same group Tue 10:00.',
        cell=ConflictCell(row='SEM-D', day=2, slot=2),
        alternatives=[
            Alternative(id='a12', score=93, day=3, slot=2, room='SEM-D',
                        reasons=['Thu 10:00 group free', 'Same room retained', 'Staff Eng. Omar Farouk free']),
            Alternative(id='a13', score=86, day=2, slot=4, room='SEM-E',
                        reasons=['Wed 12:00 free', 'Capacity fits', 'No group overlap']),
            Alternative(id='a14', score=75, day=0, slot=2, room='LT-102',
                        reasons=['Mon 10:00 free', 'Larger room, more waste', 'Resolves group clash']),
        ],
    ),
    Conflict(
        id='c6', type='room_type', severity='hard',
        description='BIO201 practical placed in SEM-E (seminar). Practicals require Science Lab type.',
        cell=ConflictCell(row='SEM-E', day=2, slot=2),
        alternatives=[
            Alternative(id='a15', score=95, day=2, slot=2, room='BioLab2',
                        reasons=['Science Lab with Microscopes', 'Capacity 24 fits 24', 'Same slot retained']),
            Alternative(id='a16', score=88, day=4, slot=2, room='BioLab',
                        reasons=['Microscopes + Centrifuges', 'Fri 10:00 free', 'Staff available']),
            Alternative(id='a17', score=72, day=1, slot=3, room='Phys-Lab2',
                        reasons=['Lab type ok, equipment partial', 'Tue 11:00 free', 'Needs setup time']),
        ],
    ),
]

CONFLICTS: list[Conflict] = list(_RAW_CONFLICTS)


# ── Rooms (mirrors ALL_ROOMS in roomsData.ts — 22 rooms) ─────────────────────

ALL_ROOMS: list[Room] = [
    Room(**{
        'id': 'r1', 'name': 'LT-101', 'building': 'Alan Turing Building', 'floor': 1,
        'type': 'Lecture Theatre', 'capacity': 240, 'examCapacity': 180,
        'accessibility': ['Wheelchair Access', 'Hearing Loop', 'Elevator Access', 'Level Access'],
        'equipment': ['Projector (4K)', 'PA System', 'Video Conferencing', 'Document Camera', 'Smartboard'],
        'closures': [
            {'label': 'Winter Recess', 'from': '2025-12-20', 'to': '2026-01-05', 'reason': 'University closure'},
            {'label': 'AV Upgrade',    'from': '2026-03-10', 'to': '2026-03-12', 'reason': 'Infrastructure works'},
        ],
        'status': 'Available', 'bookingRate': 87,
        'notes': 'Primary teaching theatre. Tiered seating. Requires 48h advance booking.',
    }),
    Room(**{
        'id': 'r2', 'name': 'LT-102', 'building': 'Alan Turing Building', 'floor': 1,
        'type': 'Lecture Theatre', 'capacity': 120, 'examCapacity': 90,
        'accessibility': ['Wheelchair Access', 'Hearing Loop', 'Level Access'],
        'equipment': ['Projector (4K)', 'Smartboard', 'PA System', 'Whiteboards'],
        'closures': [
            {'label': 'Winter Recess', 'from': '2025-12-20', 'to': '2026-01-05', 'reason': 'University closure'},
        ],
        'status': 'Available', 'bookingRate': 74,
        'notes': 'Flat-floor lecture room. Movable seating.',
    }),
    Room(**{
        'id': 'r3', 'name': 'LT-201', 'building': 'Alan Turing Building', 'floor': 2,
        'type': 'Lecture Theatre', 'capacity': 300, 'examCapacity': 240,
        'accessibility': ['Wheelchair Access', 'Hearing Loop', 'Elevator Access', 'Braille Signage', 'Accessible WC Nearby'],
        'equipment': ['Projector (4K)', 'PA System', 'Video Conferencing', 'Smartboard', 'Document Camera'],
        'closures': [
            {'label': 'Winter Recess', 'from': '2025-12-20', 'to': '2026-01-05', 'reason': 'University closure'},
            {'label': 'Graduation', 'from': '2026-07-14', 'to': '2026-07-16', 'reason': 'Ceremony venue'},
        ],
        'status': 'Available', 'bookingRate': 92,
        'notes': 'Largest teaching space on campus. Priority access for 200+ cohorts.',
    }),
    Room(**{
        'id': 'r4', 'name': 'SEM-A', 'building': 'Alan Turing Building', 'floor': 2,
        'type': 'Seminar Room', 'capacity': 30, 'examCapacity': 24,
        'accessibility': ['Wheelchair Access', 'Hearing Loop'],
        'equipment': ['Smartboard', 'Video Conferencing', 'Whiteboards'],
        'closures': [],
        'status': 'Available', 'bookingRate': 61,
        'notes': 'Small-group teaching. Circular seating arrangement.',
    }),
    Room(**{
        'id': 'r5', 'name': 'SEM-B', 'building': 'Alan Turing Building', 'floor': 2,
        'type': 'Seminar Room', 'capacity': 20, 'examCapacity': 16,
        'accessibility': ['Wheelchair Access'],
        'equipment': ['Smartboard', 'Whiteboards'],
        'closures': [
            {'label': 'Renovation', 'from': '2026-02-01', 'to': '2026-02-28', 'reason': 'Flooring replacement'},
        ],
        'status': 'Maintenance', 'bookingRate': 48,
        'notes': 'Undergoing flooring renovation Feb 2026.',
    }),
    Room(**{
        'id': 'r6', 'name': 'CS-Lab1', 'building': 'Lovelace Computing Hub', 'floor': 1,
        'type': 'Computer Lab', 'capacity': 60, 'examCapacity': 60,
        'accessibility': ['Wheelchair Access', 'Hearing Loop', 'Level Access', 'Accessible WC Nearby'],
        'equipment': ['PC Workstations', 'Smartboard', 'Projector (4K)', 'Video Conferencing'],
        'closures': [
            {'label': 'Winter Recess', 'from': '2025-12-20', 'to': '2026-01-05', 'reason': 'University closure'},
        ],
        'status': 'Available', 'bookingRate': 95,
        'notes': '60 x Dell Precision workstations. Dual-monitor setup. GPU cluster access.',
    }),
    Room(**{
        'id': 'r7', 'name': 'CS-Lab2', 'building': 'Lovelace Computing Hub', 'floor': 1,
        'type': 'Computer Lab', 'capacity': 40, 'examCapacity': 40,
        'accessibility': ['Wheelchair Access', 'Level Access'],
        'equipment': ['Mac Workstations', 'Smartboard', 'Projector (4K)'],
        'closures': [],
        'status': 'Available', 'bookingRate': 78,
        'notes': '40 x Apple Mac Studio. Adobe CC and Xcode licensed.',
    }),
    Room(**{
        'id': 'r8', 'name': 'Phys-Lab', 'building': 'Maxwell Physics Block', 'floor': 1,
        'type': 'Science Lab', 'capacity': 48, 'examCapacity': 32,
        'accessibility': ['Wheelchair Access', 'Level Access'],
        'equipment': ['Oscilloscopes', 'Spectrometers', 'Projector (4K)', 'Whiteboards'],
        'closures': [
            {'label': 'Safety Inspection', 'from': '2026-01-13', 'to': '2026-01-14', 'reason': 'Annual safety audit'},
        ],
        'status': 'Available', 'bookingRate': 69,
        'notes': 'Optics and electronics lab. Laser safety protocol required.',
    }),
    Room(**{
        'id': 'r9', 'name': 'Chem-Lab A', 'building': 'Curie Chemistry Centre', 'floor': 1,
        'type': 'Science Lab', 'capacity': 36, 'examCapacity': 24,
        'accessibility': ['Wheelchair Access', 'Accessible WC Nearby'],
        'equipment': ['Fume Hoods', 'Spectrometers', 'Centrifuges', 'Projector (4K)'],
        'closures': [
            {'label': 'COSHH Refit', 'from': '2026-04-01', 'to': '2026-04-30', 'reason': 'Fume hood replacement'},
            {'label': 'Winter Recess', 'from': '2025-12-20', 'to': '2026-01-05', 'reason': 'University closure'},
        ],
        'status': 'Available', 'bookingRate': 55,
        'notes': 'Wet chemistry. Full COSHH compliance. Supervisor must be present at all times.',
    }),
    Room(**{
        'id': 'r10', 'name': 'BioLab', 'building': 'Darwin Life Sciences', 'floor': 2,
        'type': 'Science Lab', 'capacity': 28, 'examCapacity': 20,
        'accessibility': ['Elevator Access', 'Wheelchair Access'],
        'equipment': ['Microscopes', 'Centrifuges', 'Projector (4K)', 'Fume Hoods'],
        'closures': [],
        'status': 'Available', 'bookingRate': 81,
        'notes': 'Microbiology suite. BSL-1 rated. Autoclave on-site.',
    }),
    Room(**{
        'id': 'r11', 'name': 'Fab-Studio', 'building': 'Faraday Engineering Wing', 'floor': 0,
        'type': 'Workshop', 'capacity': 24, 'examCapacity': 0,
        'accessibility': ['Level Access', 'Wheelchair Access'],
        'equipment': ['3D Printers', 'Laser Cutters', 'Whiteboards'],
        'closures': [
            {'label': 'H&S Audit', 'from': '2026-02-15', 'to': '2026-02-16', 'reason': 'Health and safety inspection'},
        ],
        'status': 'Available', 'bookingRate': 43,
        'notes': 'Fabrication studio. Induction mandatory before first use.',
    }),
    Room(**{
        'id': 'r12', 'name': 'SEM-C', 'building': 'Alan Turing Building', 'floor': 2,
        'type': 'Seminar Room', 'capacity': 20, 'examCapacity': 16,
        'accessibility': ['Wheelchair Access'],
        'equipment': ['Smartboard', 'Whiteboards', 'Video Conferencing'],
        'closures': [],
        'status': 'Closed', 'bookingRate': 0,
        'notes': 'Closed pending structural survey outcome.',
    }),
    Room(**{
        'id': 'r13', 'name': 'LT-202', 'building': 'Alan Turing Building', 'floor': 2,
        'type': 'Lecture Theatre', 'capacity': 180, 'examCapacity': 140,
        'accessibility': ['Wheelchair Access', 'Hearing Loop', 'Elevator Access'],
        'equipment': ['Projector (4K)', 'PA System', 'Smartboard', 'Video Conferencing'],
        'closures': [],
        'status': 'Available', 'bookingRate': 76,
        'notes': 'Second large theatre. Backup for 150+ cohorts.',
    }),
    Room(**{
        'id': 'r14', 'name': 'SEM-D', 'building': 'Alan Turing Building', 'floor': 3,
        'type': 'Seminar Room', 'capacity': 25, 'examCapacity': 20,
        'accessibility': ['Wheelchair Access', 'Level Access'],
        'equipment': ['Smartboard', 'Whiteboards', 'Video Conferencing'],
        'closures': [],
        'status': 'Available', 'bookingRate': 58,
        'notes': 'Small-group teaching, north wing.',
    }),
    Room(**{
        'id': 'r15', 'name': 'SEM-E', 'building': 'Alan Turing Building', 'floor': 3,
        'type': 'Seminar Room', 'capacity': 25, 'examCapacity': 20,
        'accessibility': ['Wheelchair Access'],
        'equipment': ['Smartboard', 'Whiteboards'],
        'closures': [],
        'status': 'Available', 'bookingRate': 52,
        'notes': 'Tutorial rooms, movable tables.',
    }),
    Room(**{
        'id': 'r16', 'name': 'Studio-A', 'building': 'Faraday Engineering Wing', 'floor': 1,
        'type': 'Studio', 'capacity': 22, 'examCapacity': 0,
        'accessibility': ['Level Access', 'Wheelchair Access'],
        'equipment': ['Smartboard', 'Video Conferencing', 'Recording Studio Gear', 'Whiteboards'],
        'closures': [],
        'status': 'Available', 'bookingRate': 47,
        'notes': 'HCI/design studio. Crit wall + recording gear.',
    }),
    Room(**{
        'id': 'r17', 'name': 'CS-Lab3', 'building': 'Lovelace Computing Hub', 'floor': 2,
        'type': 'Computer Lab', 'capacity': 50, 'examCapacity': 50,
        'accessibility': ['Wheelchair Access', 'Level Access'],
        'equipment': ['PC Workstations', 'Smartboard', 'Projector (4K)'],
        'closures': [],
        'status': 'Available', 'bookingRate': 71,
        'notes': '50 workstations. Linux + GPU access.',
    }),
    Room(**{
        'id': 'r18', 'name': 'Phys-Lab2', 'building': 'Maxwell Physics Block', 'floor': 2,
        'type': 'Science Lab', 'capacity': 40, 'examCapacity': 28,
        'accessibility': ['Wheelchair Access', 'Level Access'],
        'equipment': ['Oscilloscopes', 'Spectrometers', 'Whiteboards'],
        'closures': [],
        'status': 'Available', 'bookingRate': 63,
        'notes': 'Electronics overflow lab.',
    }),
    Room(**{
        'id': 'r19', 'name': 'Chem-Lab', 'building': 'Curie Chemistry Centre', 'floor': 1,
        'type': 'Science Lab', 'capacity': 30, 'examCapacity': 20,
        'accessibility': ['Wheelchair Access'],
        'equipment': ['Fume Hoods', 'Spectrometers', 'Centrifuges'],
        'closures': [],
        'status': 'Available', 'bookingRate': 60,
        'notes': 'General chemistry teaching lab.',
    }),
    Room(**{
        'id': 'r20', 'name': 'Chem-Lab B', 'building': 'Curie Chemistry Centre', 'floor': 2,
        'type': 'Science Lab', 'capacity': 30, 'examCapacity': 20,
        'accessibility': ['Wheelchair Access', 'Accessible WC Nearby'],
        'equipment': ['Fume Hoods', 'Spectrometers', 'Projector (4K)'],
        'closures': [{'label': 'COSHH Refit', 'from': '2026-05-01', 'to': '2026-05-07', 'reason': 'Filter replacement'}],
        'status': 'Available', 'bookingRate': 57,
        'notes': 'Spectroscopy focus lab.',
    }),
    Room(**{
        'id': 'r21', 'name': 'BioLab2', 'building': 'Darwin Life Sciences', 'floor': 2,
        'type': 'Science Lab', 'capacity': 24, 'examCapacity': 18,
        'accessibility': ['Elevator Access', 'Wheelchair Access'],
        'equipment': ['Microscopes', 'Centrifuges', 'Projector (4K)'],
        'closures': [],
        'status': 'Available', 'bookingRate': 66,
        'notes': 'Microbiology overflow.',
    }),
    Room(**{
        'id': 'r22', 'name': 'Eng-Workshop', 'building': 'Faraday Engineering Wing', 'floor': 0,
        'type': 'Workshop', 'capacity': 30, 'examCapacity': 0,
        'accessibility': ['Level Access', 'Wheelchair Access'],
        'equipment': ['3D Printers', 'Laser Cutters', 'Oscilloscopes', 'Whiteboards'],
        'closures': [],
        'status': 'Available', 'bookingRate': 49,
        'notes': 'Electronics + fabrication. Induction required.',
    }),
]


# ── Schedule versions (mirrors VERSIONS in App.tsx) ───────────────────────────

VERSIONS: list[ScheduleVersion] = [
    ScheduleVersion(
        id='draft-3', label='Draft v3 (current)',
        status='draft', timestamp='2026-09-14T11:20:00Z',
        author='Scheduler Admin', changes=12, conflicts=6,
    ),
    ScheduleVersion(
        id='draft-2', label='Draft v2',
        status='draft', timestamp='2026-09-10T09:00:00Z',
        author='Scheduler Admin', changes=5, conflicts=3,
    ),
    ScheduleVersion(
        id='pub-1', label='Published v1',
        status='published', timestamp='2026-09-07T15:45:00Z',
        author='Scheduler Admin', changes=0, conflicts=0,
    ),
]


# ── Student data (mirrors StudentManagerModal defaults + catalog) ─────────────
# academic_year 1-4, major CS/IT/AI/DS required for 3-4
# At least 5 per year, and for Year 3 & 4 : 5 per major (CS,IT,AI,DS) => 50 total
MANAGED_STUDENTS: list[dict] = [
    # ── Year 1 — General (no major) — 5 students ──
    {'id': 'st1', 'name': 'Amara Osei',       'email': 'amara@bua.edu.eg',            'group': 'CS-3A',   'year': 'Year 3', 'academic_year': 3, 'major': 'CS'}, # keep legacy admin-visible student
    {'id': 'st7', 'name': 'Salma Tarek',      'email': 'salma@bua.edu.eg',            'group': 'CS-1A',   'year': 'Year 1', 'academic_year': 1, 'major': None},
    {'id': 'st_y1_1', 'name': 'Y1 Student One',   'email': 'student.y1.gen1@bua.edu.eg', 'group': 'CS-1A',   'year': 'Year 1', 'academic_year': 1, 'major': None},
    {'id': 'st_y1_2', 'name': 'Y1 Student Two',   'email': 'student.y1.gen2@bua.edu.eg', 'group': 'CS-1B',   'year': 'Year 1', 'academic_year': 1, 'major': None},
    {'id': 'st_y1_3', 'name': 'Y1 Student Three', 'email': 'student.y1.gen3@bua.edu.eg', 'group': 'ENG-1A',  'year': 'Year 1', 'academic_year': 1, 'major': None},
    {'id': 'st_y1_4', 'name': 'Y1 Student Four',  'email': 'student.y1.gen4@bua.edu.eg', 'group': 'BIO-1A',  'year': 'Year 1', 'academic_year': 1, 'major': None},
    {'id': 'st_y1_5', 'name': 'Y1 Student Five',  'email': 'student.y1.gen5@bua.edu.eg', 'group': 'ENG-1B',  'year': 'Year 1', 'academic_year': 1, 'major': None},
    # ── Year 2 — General (no major, except IT example) — 5 students ──
    {'id': 'st2', 'name': 'Youssef Adel',     'email': 'youssef@bua.edu.eg',          'group': 'CS-2A',   'year': 'Year 2', 'academic_year': 2, 'major': None},
    {'id': 'st3', 'name': 'Mariam Hany',      'email': 'mariam@bua.edu.eg',           'group': 'ENG-2B',  'year': 'Year 2', 'academic_year': 2, 'major': None},
    {'id': 'st5', 'name': 'Nour Elhouda',     'email': 'nour@bua.edu.eg',             'group': 'BIO-2A',  'year': 'Year 2', 'academic_year': 2, 'major': None},
    {'id': 'st6', 'name': 'Karim Samy',       'email': 'karim@bua.edu.eg',            'group': 'EE-2A',   'year': 'Year 2', 'academic_year': 2, 'major': 'IT'},
    {'id': 'st_y2_5', 'name': 'Y2 Student Five',  'email': 'student.y2.gen5@bua.edu.eg', 'group': 'CHEM-2B', 'year': 'Year 2', 'academic_year': 2, 'major': None},
    # ── Year 3 — 5 per major (20 students) ──
    # CS major
    {'id': 'st_y3_cs1', 'name': 'Y3 CS One',   'email': 'student.y3.cs1@bua.edu.eg',  'group': 'CS-3A', 'year': 'Year 3', 'academic_year': 3, 'major': 'CS'},
    {'id': 'st_y3_cs2', 'name': 'Y3 CS Two',   'email': 'student.y3.cs2@bua.edu.eg',  'group': 'CS-3B', 'year': 'Year 3', 'academic_year': 3, 'major': 'CS'},
    {'id': 'st_y3_cs3', 'name': 'Y3 CS Three', 'email': 'student.y3.cs3@bua.edu.eg',  'group': 'CS-3C', 'year': 'Year 3', 'academic_year': 3, 'major': 'CS'},
    {'id': 'st_y3_cs4', 'name': 'Y3 CS Four',  'email': 'student.y3.cs4@bua.edu.eg',  'group': 'CS-3D', 'year': 'Year 3', 'academic_year': 3, 'major': 'CS'},
    {'id': 'st_y3_cs5', 'name': 'Y3 CS Five',  'email': 'student.y3.cs5@bua.edu.eg',  'group': 'CS-3E', 'year': 'Year 3', 'academic_year': 3, 'major': 'CS'},
    {'id': 'st4', 'name': 'Omar Khaled',      'email': 'omar@bua.edu.eg',             'group': 'CS-3B', 'year': 'Year 3', 'academic_year': 3, 'major': 'CS'}, # legacy keep
    # IT major
    {'id': 'st_y3_it1', 'name': 'Y3 IT One',   'email': 'student.y3.it1@bua.edu.eg',  'group': 'IT-3A', 'year': 'Year 3', 'academic_year': 3, 'major': 'IT'},
    {'id': 'st_y3_it2', 'name': 'Y3 IT Two',   'email': 'student.y3.it2@bua.edu.eg',  'group': 'IT-3B', 'year': 'Year 3', 'academic_year': 3, 'major': 'IT'},
    {'id': 'st_y3_it3', 'name': 'Y3 IT Three', 'email': 'student.y3.it3@bua.edu.eg',  'group': 'IT-3C', 'year': 'Year 3', 'academic_year': 3, 'major': 'IT'},
    {'id': 'st_y3_it4', 'name': 'Y3 IT Four',  'email': 'student.y3.it4@bua.edu.eg',  'group': 'IT-3D', 'year': 'Year 3', 'academic_year': 3, 'major': 'IT'},
    {'id': 'st_y3_it5', 'name': 'Y3 IT Five',  'email': 'student.y3.it5@bua.edu.eg',  'group': 'IT-3E', 'year': 'Year 3', 'academic_year': 3, 'major': 'IT'},
    {'id': 'st8', 'name': 'Mostafa Fathy',    'email': 'mostafa@bua.edu.eg',          'group': 'MECH-3A','year': 'Year 3', 'academic_year': 3, 'major': 'IT'}, # legacy IT example
    # AI major
    {'id': 'st_y3_ai1', 'name': 'Y3 AI One',   'email': 'student.y3.ai1@bua.edu.eg',  'group': 'AI-3A', 'year': 'Year 3', 'academic_year': 3, 'major': 'AI'},
    {'id': 'st_y3_ai2', 'name': 'Y3 AI Two',   'email': 'student.y3.ai2@bua.edu.eg',  'group': 'AI-3B', 'year': 'Year 3', 'academic_year': 3, 'major': 'AI'},
    {'id': 'st_y3_ai3', 'name': 'Y3 AI Three', 'email': 'student.y3.ai3@bua.edu.eg',  'group': 'AI-3C', 'year': 'Year 3', 'academic_year': 3, 'major': 'AI'},
    {'id': 'st_y3_ai4', 'name': 'Y3 AI Four',  'email': 'student.y3.ai4@bua.edu.eg',  'group': 'AI-3D', 'year': 'Year 3', 'academic_year': 3, 'major': 'AI'},
    {'id': 'st_y3_ai5', 'name': 'Y3 AI Five',  'email': 'student.y3.ai5@bua.edu.eg',  'group': 'AI-3E', 'year': 'Year 3', 'academic_year': 3, 'major': 'AI'},
    # DS major
    {'id': 'st_y3_ds1', 'name': 'Y3 DS One',   'email': 'student.y3.ds1@bua.edu.eg',  'group': 'DS-3A', 'year': 'Year 3', 'academic_year': 3, 'major': 'DS'},
    {'id': 'st_y3_ds2', 'name': 'Y3 DS Two',   'email': 'student.y3.ds2@bua.edu.eg',  'group': 'DS-3B', 'year': 'Year 3', 'academic_year': 3, 'major': 'DS'},
    {'id': 'st_y3_ds3', 'name': 'Y3 DS Three', 'email': 'student.y3.ds3@bua.edu.eg',  'group': 'DS-3C', 'year': 'Year 3', 'academic_year': 3, 'major': 'DS'},
    {'id': 'st_y3_ds4', 'name': 'Y3 DS Four',  'email': 'student.y3.ds4@bua.edu.eg',  'group': 'DS-3D', 'year': 'Year 3', 'academic_year': 3, 'major': 'DS'},
    {'id': 'st_y3_ds5', 'name': 'Y3 DS Five',  'email': 'student.y3.ds5@bua.edu.eg',  'group': 'DS-3E', 'year': 'Year 3', 'academic_year': 3, 'major': 'DS'},
    # ── Year 4 — 5 per major (20 students) ──
    {'id': 'st_y4_cs1', 'name': 'Y4 CS One',   'email': 'student.y4.cs1@bua.edu.eg',  'group': 'CS-4A', 'year': 'Year 4', 'academic_year': 4, 'major': 'CS'},
    {'id': 'st_y4_cs2', 'name': 'Y4 CS Two',   'email': 'student.y4.cs2@bua.edu.eg',  'group': 'CS-4B', 'year': 'Year 4', 'academic_year': 4, 'major': 'CS'},
    {'id': 'st_y4_cs3', 'name': 'Y4 CS Three', 'email': 'student.y4.cs3@bua.edu.eg',  'group': 'CS-4C', 'year': 'Year 4', 'academic_year': 4, 'major': 'CS'},
    {'id': 'st_y4_cs4', 'name': 'Y4 CS Four',  'email': 'student.y4.cs4@bua.edu.eg',  'group': 'CS-4D', 'year': 'Year 4', 'academic_year': 4, 'major': 'CS'},
    {'id': 'st_y4_cs5', 'name': 'Y4 CS Five',  'email': 'student.y4.cs5@bua.edu.eg',  'group': 'CS-4E', 'year': 'Year 4', 'academic_year': 4, 'major': 'CS'},
    {'id': 'st_y4_it1', 'name': 'Y4 IT One',   'email': 'student.y4.it1@bua.edu.eg',  'group': 'IT-4A', 'year': 'Year 4', 'academic_year': 4, 'major': 'IT'},
    {'id': 'st_y4_it2', 'name': 'Y4 IT Two',   'email': 'student.y4.it2@bua.edu.eg',  'group': 'IT-4B', 'year': 'Year 4', 'academic_year': 4, 'major': 'IT'},
    {'id': 'st_y4_it3', 'name': 'Y4 IT Three', 'email': 'student.y4.it3@bua.edu.eg',  'group': 'IT-4C', 'year': 'Year 4', 'academic_year': 4, 'major': 'IT'},
    {'id': 'st_y4_it4', 'name': 'Y4 IT Four',  'email': 'student.y4.it4@bua.edu.eg',  'group': 'IT-4D', 'year': 'Year 4', 'academic_year': 4, 'major': 'IT'},
    {'id': 'st_y4_it5', 'name': 'Y4 IT Five',  'email': 'student.y4.it5@bua.edu.eg',  'group': 'IT-4E', 'year': 'Year 4', 'academic_year': 4, 'major': 'IT'},
    {'id': 'st_y4_ai1', 'name': 'Y4 AI One',   'email': 'student.y4.ai1@bua.edu.eg',  'group': 'AI-4A', 'year': 'Year 4', 'academic_year': 4, 'major': 'AI'},
    {'id': 'st_y4_ai2', 'name': 'Y4 AI Two',   'email': 'student.y4.ai2@bua.edu.eg',  'group': 'AI-4B', 'year': 'Year 4', 'academic_year': 4, 'major': 'AI'},
    {'id': 'st_y4_ai3', 'name': 'Y4 AI Three', 'email': 'student.y4.ai3@bua.edu.eg',  'group': 'AI-4C', 'year': 'Year 4', 'academic_year': 4, 'major': 'AI'},
    {'id': 'st_y4_ai4', 'name': 'Y4 AI Four',  'email': 'student.y4.ai4@bua.edu.eg',  'group': 'AI-4D', 'year': 'Year 4', 'academic_year': 4, 'major': 'AI'},
    {'id': 'st_y4_ai5', 'name': 'Y4 AI Five',  'email': 'student.y4.ai5@bua.edu.eg',  'group': 'AI-4E', 'year': 'Year 4', 'academic_year': 4, 'major': 'AI'},
    {'id': 'st_y4_ds1', 'name': 'Y4 DS One',   'email': 'student.y4.ds1@bua.edu.eg',  'group': 'DS-4A', 'year': 'Year 4', 'academic_year': 4, 'major': 'DS'},
    {'id': 'st_y4_ds2', 'name': 'Y4 DS Two',   'email': 'student.y4.ds2@bua.edu.eg',  'group': 'DS-4B', 'year': 'Year 4', 'academic_year': 4, 'major': 'DS'},
    {'id': 'st_y4_ds3', 'name': 'Y4 DS Three', 'email': 'student.y4.ds3@bua.edu.eg',  'group': 'DS-4C', 'year': 'Year 4', 'academic_year': 4, 'major': 'DS'},
    {'id': 'st_y4_ds4', 'name': 'Y4 DS Four',  'email': 'student.y4.ds4@bua.edu.eg',  'group': 'DS-4D', 'year': 'Year 4', 'academic_year': 4, 'major': 'DS'},
    {'id': 'st_y4_ds5', 'name': 'Y4 DS Five',  'email': 'student.y4.ds5@bua.edu.eg',  'group': 'DS-4E', 'year': 'Year 4', 'academic_year': 4, 'major': 'DS'},
]

STUDENT_PROFILE = StudentProfile(
    id='u1001',
    name='Amara Osei',
    group='CS-3A',
    programme='BSc Computer Science',
    year=3, academic_year=3, major='CS',
    sessions=[
        StudentSession(id='s1', code='CS301', name='Algorithms & Complexity', staff='Dr. Chen Wei',
                       room='LT-101', day=0, slot=0, color='#2563eb'),
        StudentSession(id='s6', code='CS201', name='Data Structures',   staff='Dr. Chen Wei',
                       room='LT-102', day=2, slot=2, color='#2563eb'),
        StudentSession(id='s3', code='CS401', name='ML Foundations',    staff='Dr. Lena Kovač',
                       room='LT-101', day=3, slot=3, color='#2563eb'),
        StudentSession(id='s2', code='MATH201', name='Linear Algebra',  staff='Prof. Sara Johansson',
                       room='LT-101', day=1, slot=1, color='#7c3aed'),
        StudentSession(id='s4', code='PHYS101', name='Classical Mechanics', staff='Dr. Raj Patel',
                       room='LT-101', day=4, slot=4, color='#0891b2'),
    ],
    credits=[
        Credit(code='CS101', name='Intro to Programming',   credits=6,  grade='A',  status='completed'),
        Credit(code='CS201', name='Data Structures',         credits=6,  grade='B+', status='completed'),
        Credit(code='MATH101', name='Discrete Mathematics',  credits=4,  grade='A-', status='completed'),
        Credit(code='CS301', name='Algorithms',              credits=6,  grade=None, status='in_progress'),
        Credit(code='CS401', name='ML Foundations',          credits=6,  grade=None, status='in_progress'),
        Credit(code='MATH201', name='Linear Algebra',        credits=4,  grade=None, status='in_progress'),
        Credit(code='CS501', name='Distributed Systems',     credits=6,  grade=None, status='planned'),
    ],
    total_credits_required=180,
    total_credits_earned=72,
)


# ── Users (for auth — in production use hashed passwords + DB) ───────────────

USERS: list[dict] = [
    {'email': 'admin@bua.edu.eg',          'password': 'Admin1234',  'role': 'admin',    'name': 'Schedule Admin'},
    {'email': 'scheduler@bua.edu.eg',      'password': 'Admin1234',  'role': 'admin',    'name': 'Timetable Office'},
    {'email': 'dr.chen@staff.bua.edu.eg',  'password': 'Staff1234',  'role': 'lecturer', 'name': 'Dr. Chen Wei'},
    {'email': 'prof.nwosu@staff.bua.edu.eg','password':'Staff1234',  'role': 'lecturer', 'name': 'Prof. Amara Nwosu'},
    {'email': 'amara@bua.edu.eg',          'password': 'Student1234','role': 'student',  'name': 'Amara Osei'},
]

# Auto-add remaining managed students as users (student.y1.* etc.)
_existing_emails = {u['email'].lower() for u in USERS}
for _s in MANAGED_STUDENTS:
    if _s['email'].lower() not in _existing_emails:
        USERS.append({'email': _s['email'], 'password': 'Student1234', 'role': 'student', 'name': _s['name']})
        _existing_emails.add(_s['email'].lower())


# ── Courses / Sections (derived from timetable sessions) ─────────────────────

def _build_sections() -> tuple[list[Course], list[Section]]:
    seen: dict[str, Section] = {}
    courses: dict[str, Course] = {}
    for view in ('rooms', 'labs'):
        for days in TIMETABLE.get(view, {}).values():
            for slots in days.values():
                if not isinstance(slots, dict):
                    continue
                for session in slots.values():
                    if session is None or session.code in seen:
                        continue
                    if session.code not in courses:
                        courses[session.code] = Course(
                            id=f"crs-{session.code}", code=session.code,
                            name=session.name, credits=3, year='Year 2', term='Fall',
                        )
                    seen[session.code] = Section(
                        id=f"sec-{session.id}", course_id=f"crs-{session.code}",
                        code=session.code, name=session.name, staff=session.staff,
                        group=session.group, capacity=session.capacity,
                        enrolled=session.enrolled, year='Year 2', term='Fall',
                        academic_year=session.academic_year, major=session.major,
                    )
    return list(courses.values()), list(seen.values())


COURSES, SECTIONS = _build_sections()

# student_id -> registrations (link table replacement)
REGISTRATIONS: list[CourseRegistration] = []

# ── Notifications ────────────────────────────────────────────────────────────

NOTIFICATIONS: list[Notification] = []

# ── Audit Trail ──────────────────────────────────────────────────────────────

AUDIT_LOGS: list["AuditEvent"] = []  # populated via services/audit.py
