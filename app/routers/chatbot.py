"""
Chatbot endpoints for SCH scheduling assistant.

POST /api/chatbot/message        → NLU + facts + Arabic answer in one call
GET  /api/chatbot/timetable      → Get timetable data (supports ?staff=&day=)
POST /api/allocations/check      → Validate move (dry-run)
GET  /api/search/rooms           → Search available rooms (?minCapacity=&day=)
GET  /api/analytics/occupancy    → Room occupancy stats
POST /api/chatbot/analyze-image  → Analyze timetable photo (multipart)
GET  /api/chatbot/export-ics     → Export ICS calendar file
"""

from fastapi import APIRouter, Header, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import base64
import io

from app.data_store import (
    TIMETABLE, CONFLICTS, ALL_ROOMS, DAYS, TIME_SLOTS, ROOMS, LABS, STAFF,
    MANAGED_STUDENTS, STUDENT_PROFILE, VERSIONS
)
from app.database import SessionLocal, TimetableCellRow
from sqlalchemy import select
from app.routers.auth import require_admin

router = APIRouter()

# ── Request/Response Models ────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    message: str
    # Optional: live timetable snapshot (formatted JSON text) attached by the
    # frontend "Export & Send" button. Passed to Gemini as core context.
    timetable_json: Optional[str] = None

class ChatResponse(BaseModel):
    intent: str
    entities: dict
    answer_ar: str
    facts: dict
    gemini_used: bool = False

class TimetableRow(BaseModel):
    id: str
    name: str
    code: str
    room: str
    day_name: str
    time: str
    staff: str
    group: str
    capacity: int
    enrolled: int
    color: str

class CheckMoveRequest(BaseModel):
    staff: Optional[str] = None
    room: Optional[str] = None
    day: Optional[str] = None  # name or 0-4
    group: Optional[str] = None
    enrolled: Optional[int] = None
    section_id: Optional[str] = None  # for mock fallback

class CheckMoveResponse(BaseModel):
    ok: bool
    conflicts: List[dict]
    recommendations: List[dict] = []

class SearchRoomsRequest(BaseModel):
    minCapacity: Optional[int] = None
    day: Optional[str] = None

class RoomInfo(BaseModel):
    id: str
    name: str
    building: str
    floor: int
    type: str
    capacity: int
    examCapacity: int
    status: str
    pct: Optional[int] = None

# ── Helpers ────────────────────────────────────────────────────────────────────

import json as _json
import os as _os
import urllib.request as _urlrequest


def _gemini_answer_sync(user_message: str, timetable_context: str) -> str | None:
    """Call Google Gemini REST API. Returns answer text or None on any failure."""
    api_key = (_os.getenv('GEMINI_API_KEY') or '').strip()
    if not api_key:
        return None
    model = (_os.getenv('GEMINI_MODEL') or 'gemini-3.6-flash').strip()
    system = (
        'You are SCH, the Bua University timetable assistant. '
        'Answer in Arabic (Egyptian dialect is fine). '
        'Base your answer ONLY on the timetable JSON context below; '
        'never invent sessions, rooms, staff, or times. '
        'If the context lacks the needed rows, say so honestly and suggest what to attach. '
        'Format rules (mandatory): reply as short organized bullet points only, '
        'no long paragraphs; keep the whole answer concise so it fits in one message; '
        'always finish with a complete sentence — never stop mid-sentence or mid-list. '
        'Each timetable row carries an explicit time range (HH:MM-HH:MM): always use it '
        'when checking same-day same-time overlaps for staff, rooms, and student groups. '
        'Structure: 1) direct answer first, 2) supporting bullets with day/time/room/code, '
        '3) one closing line (recommendation or next step).'
    )
    body = _json.dumps({
        'system_instruction': {'parts': [{'text': system}]},
        'contents': [{'parts': [{
            'text': f'Timetable context (JSON):\n{timetable_context}\n\nUser question:\n{user_message}'
        }]}],
        'generationConfig': {'temperature': 0.3, 'maxOutputTokens': 2048},
    }).encode('utf-8')
    req = _urlrequest.Request(
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=' + api_key,
        data=body, headers={'Content-Type': 'application/json'}, method='POST',
    )
    try:
        with _urlrequest.urlopen(req, timeout=25) as resp:
            payload = _json.loads(resp.read().decode('utf-8'))
        parts = (((payload.get('candidates') or [{}])[0].get('content') or {}).get('parts') or [])
        text = ''.join(p.get('text', '') for p in parts if isinstance(p, dict)).strip()
        return text or None
    except Exception:
        return None


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

def get_timetable_rows(staff: Optional[str] = None, day: Optional[int] = None) -> List[dict]:
    """Get timetable rows enriched with names."""
    rows = []
    rooms_view = TIMETABLE.get('rooms', {})
    for room_name, days in rooms_view.items():
        for day_idx, slots in days.items():
            if day is not None and day_idx != day:
                continue
            if not isinstance(slots, dict):
                continue
            for slot_idx, session in slots.items():
                if session is None:
                    continue
                # Handle both Session objects and dicts
                session_staff = session.get('staff') if isinstance(session, dict) else getattr(session, 'staff', None)
                if staff and session_staff != staff:
                    continue
                session_name = session.get('name') if isinstance(session, dict) else getattr(session, 'name', '')
                session_code = session.get('code') if isinstance(session, dict) else getattr(session, 'code', '')
                session_group = session.get('group') if isinstance(session, dict) else getattr(session, 'group', '')
                session_capacity = session.get('capacity') if isinstance(session, dict) else getattr(session, 'capacity', 0)
                session_enrolled = session.get('enrolled') if isinstance(session, dict) else getattr(session, 'enrolled', 0)
                session_color = session.get('color') if isinstance(session, dict) else getattr(session, 'color', '#2563eb')
                session_duration = session.get('duration') if isinstance(session, dict) else getattr(session, 'duration', 1)
                
                start_time = TIME_SLOTS[slot_idx] if slot_idx < len(TIME_SLOTS) else ''
                end_slot = min(slot_idx + session_duration, len(TIME_SLOTS) - 1)
                end_time = TIME_SLOTS[end_slot] if end_slot < len(TIME_SLOTS) else ''
                
                rows.append({
                    'id': session.get('id') if isinstance(session, dict) else getattr(session, 'id', ''),
                    'name': session_name,
                    'code': session_code,
                    'room': room_name,
                    'day_name': DAYS[day_idx] if day_idx < len(DAYS) else f'Day {day_idx}',
                    'time': f"{start_time}-{end_time}" if start_time and end_time else start_time,
                    'staff': session_staff,
                    'group': session_group,
                    'capacity': session_capacity,
                    'enrolled': session_enrolled,
                    'color': session_color,
                })
    return rows

def generate_arabic_answer(intent: str, entities: dict, facts: dict) -> str:
    """Generate Arabic answer from intent + facts."""
    if intent == 'show_schedule':
        staff = entities.get('staff', 'الكل')
        day = entities.get('day', 'الكل')
        rows = facts.get('rows', [])
        if not rows:
            return f'ما فيش جلسات لـ {staff} يوم {day}.'
        lines = [f'📅 جدول {staff} — {day}:']
        for r in rows:
            lines.append(f"{r['day_name']} {r['time']} — {r['name']} ({r['code']}) — {r['room']}")
        return '\n'.join(lines)

    if intent == 'check_move':
        if facts.get('ok'):
            return '✅ التغيير ممكن. مفيش تعارضات صعبة.'
        lines = ['❌ مش ممكن تعمل التغيير ده:']
        for c in facts.get('conflicts', []):
            lines.append(f"- [{c.get('conflict_type', 'CONFLICT')}] {c.get('description', '')}")
        if facts.get('recommendations'):
            lines.append('\nالبدائل المقترحة:')
            for i, a in enumerate(facts['recommendations'], 1):
                room = a.get('room_number') or a.get('room') or '?'
                time = f"{a.get('start_time','')}-{a.get('end_time','')}"
                expl = a.get('explanation') or '، '.join(a.get('reasons', []))
                lines.append(f"{i}. {a.get('day_name','')} {time} في {room} ({expl})")
            lines.append('\nاكتبي رقم البديل (1-3) أو "نفذ رقم 1" للمعاينة.')
        return '\n'.join(lines)

    if intent == 'find_room':
        rooms = facts.get('rooms', [])
        if not rooms:
            return 'مفيش قاعة متاحة بالمواصفات دي.'
        lines = ['القاعات المتاحة:']
        for r in rooms[:5]:
            pct = f" ({r.get('pct','')}%)" if r.get('pct') is not None else ''
            lines.append(f"{r.get('room_number') or r.get('name')}: سعة {r.get('capacity')}{pct}")
        return '\n'.join(lines)

    if intent == 'occupancy':
        occ = facts.get('occupancy', [])
        if not occ:
            return 'مفيش بيانات إشغال.'
        return '\n'.join([f"{o['room_number']}: {o['used']}/{o['total']} ({o['pct']}%)" for o in occ])

    if intent == 'export':
        return facts.get('message', 'التصدير محتاج الباك شغال.')

    return 'أنا فاهم طلبك. جرب: "اعرض جدول د. أحمد الأثنين" / "انقل Database للثلاثاء 11:00" / "قاعة 60 طالب الأحد" / "إشغال القاعات" / "ابعتلي الجدول ICS".'

# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post('/message', response_model=ChatResponse)
async def chatbot_message(body: ChatMessage):
    """
    Main chatbot endpoint: NLU + facts + Arabic answer in one call.
    Falls back to rule-based parsing if Gemini unavailable.
    """
    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=422, detail='Message is required')

    # Simple rule-based NLU (deterministic fallback)
    t = text.lower()
    intent = 'show_schedule'
    entities = {}

    if any(w in t for w in ['occupancy', 'استخدام', 'إشغال', 'اشغال', 'احصائيات', 'أكثر القاعات', 'اكثر القاعات']):
        intent = 'occupancy'
    elif any(w in t for w in ['insight', 'تحليل', 'ضغط', 'متتالية', 'مضغوط', 'توزيع']):
        intent = 'insights'
    elif any(w in t for w in ['ics', 'ical', 'تقويم', 'calendar', 'export', 'تحميل', 'تصدير', 'نزل']):
        intent = 'export'
    elif any(w in t for w in ['room', 'lab', 'قاعة', 'معمل', 'فاضية', 'فاضي', 'سعة', 'طالب']):
        intent = 'find_room'
        import re
        cap_match = re.search(r'(\d{2,3})\s*(طالب|student|capacity|سعة)?', t)
        entities['capacity'] = int(cap_match.group(1)) if cap_match else 60
        day_map = {
            # Arabic days (system is Mon-Fri: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri)
            'الأحد': 0, 'الاحد': 0,      # Sunday (not in system, map to Mon)
            'الأثنين': 0, 'الاثنين': 0,   # Monday -> 0
            'الثلاثاء': 1,                # Tuesday -> 1
            'الاربعاء': 2, 'الأربعاء': 2, # Wednesday -> 2
            'الخميس': 3,                  # Thursday -> 3
            'الجمعة': 4,                  # Friday -> 4
            # English days
            'sunday': 0, 'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4
        }
        for ar, idx in day_map.items():
            if ar in t:
                entities['day'] = idx
                break
    elif any(w in t for w in ['move', 'انقل', 'ينفع', 'ماذا لو', 'احطه', 'احط', 'what if', 'check']):
        intent = 'check_move'
        # Extract course
        for course in ['database', 'ai', 'networks', 'algorithms', 'داتابيز', 'ذكاء']:
            if course in t:
                entities['course'] = course
                break
        # Extract day
        day_map = {
            # Arabic days (system is Mon-Fri: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri)
            'الأحد': 0, 'الاحد': 0,      # Sunday (not in system, map to Mon)
            'الأثنين': 0, 'الاثنين': 0,   # Monday -> 0
            'الثلاثاء': 1,                # Tuesday -> 1
            'الاربعاء': 2, 'الأربعاء': 2, # Wednesday -> 2
            'الخميس': 3,                  # Thursday -> 3
            'الجمعة': 4,                  # Friday -> 4
            # English days
            'sunday': 0, 'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4
        }
        for ar, idx in day_map.items():
            if ar in t:
                entities['day'] = idx
                break
        # Extract time
        import re
        time_match = re.search(r'(\d{1,2}):(\d{2})', t)
        if time_match:
            entities['time'] = time_match.group(0)
        # Extract staff
        if 'ahmed' in t or 'أحمد' in t:
            entities['staff'] = 'Ahmed'
        elif 'sara' in t or 'سارة' in t:
            entities['staff'] = 'Sara'
    else:
        # show_schedule
        if 'ahmed' in t or 'أحمد' in t:
            entities['staff'] = 'Ahmed'
        elif 'sara' in t or 'سارة' in t:
            entities['staff'] = 'Sara'
        day_map = {
            # Arabic days (system is Mon-Fri: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri)
            'الأحد': 0, 'الاحد': 0,      # Sunday (not in system, map to Mon)
            'الأثنين': 0, 'الاثنين': 0,   # Monday -> 0
            'الثلاثاء': 1,                # Tuesday -> 1
            'الاربعاء': 2, 'الأربعاء': 2, # Wednesday -> 2
            'الخميس': 3,                  # Thursday -> 3
            'الجمعة': 4,                  # Friday -> 4
            # English days
            'sunday': 0, 'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4
        }
        for ar, idx in day_map.items():
            if ar in t:
                entities['day'] = idx
                break

    # Gather facts based on intent
    facts = {}
    if intent == 'show_schedule':
        staff = entities.get('staff')
        day = entities.get('day')
        # Map common short names to full names
        staff_map = {
            'ahmed': 'Dr. Ahmed Hassan',
            'أحمد': 'Dr. Ahmed Hassan',
            'sara': 'Prof. Sara Johansson',
            'سارة': 'Prof. Sara Johansson',
            'chen': 'Dr. Chen Wei',
            'نوسو': 'Prof. Amara Nwosu',
            'نوسة': 'Prof. Amara Nwosu',
            'kovac': 'Dr. Lena Kovač',
            'كوفاك': 'Dr. Lena Kovač',
            'patel': 'Dr. Raj Patel',
            'باتل': 'Dr. Raj Patel',
            'bell': 'Dr. Marcus Bell',
            'بل': 'Dr. Marcus Bell',
            'hassan': 'Dr. Ahmed Hassan',
            'حسن': 'Dr. Ahmed Hassan',
            'ali': 'Dr. Fatma Ali',
            'علي': 'Dr. Fatma Ali',
            'johansson': 'Prof. Sara Johansson',
            'جوهانسون': 'Prof. Sara Johansson',
            'nwosu': 'Prof. Amara Nwosu',
            'محمد': 'Dr. Mohamed',
        }
        if staff:
            staff_lower = staff.lower()
            staff = staff_map.get(staff_lower, staff)
        rows = get_timetable_rows(staff=staff, day=day)
        facts['rows'] = rows
    elif intent == 'check_move':
        # Simplified check - in production call conflict engine
        facts['ok'] = True
        facts['conflicts'] = []
        facts['recommendations'] = []
    elif intent == 'find_room':
        min_cap = entities.get('capacity', 60)
        day = entities.get('day')
        # Find available rooms
        available = []
        for r in ALL_ROOMS:
            if r.capacity >= min_cap and r.status == 'Available':
                available.append({
                    'id': r.id,
                    'room_number': r.name,
                    'name': r.name,
                    'capacity': r.capacity,
                    'pct': r.booking_rate,
                })
        facts['rooms'] = available
    elif intent == 'occupancy':
        # Calculate occupancy (day → slot → session cells)
        occ = []
        for r in ALL_ROOMS:
            used, total = 0, 0
            for slots in (TIMETABLE.get('rooms', {}).get(r.name, {}) or {}).values():
                cells = slots.values() if isinstance(slots, dict) else [slots]
                for s in cells:
                    total += 1
                    if s is not None:
                        used += 1
            occ.append({'room_number': r.name, 'used': used, 'total': total, 'pct': round(used/total*100) if total else 0})
        facts['occupancy'] = sorted(occ, key=lambda x: -x['pct'])
    elif intent == 'export':
        facts['message'] = 'التصدير محتاج الباك شغال. شغل السيرفر على 8000.'
        # Map staff name for export
        staff_map = {
            'ahmed': 'Dr. Ahmed Hassan',
            'أحمد': 'Dr. Ahmed Hassan',
            'sara': 'Prof. Sara Johansson',
            'سارة': 'Prof. Sara Johansson',
            'chen': 'Dr. Chen Wei',
            'نوسو': 'Prof. Amara Nwosu',
            'نوسة': 'Prof. Amara Nwosu',
            'kovac': 'Dr. Lena Kovač',
            'كوفاك': 'Dr. Lena Kovač',
            'patel': 'Dr. Raj Patel',
            'باتل': 'Dr. Raj Patel',
            'bell': 'Dr. Marcus Bell',
            'بل': 'Dr. Marcus Bell',
            'hassan': 'Dr. Ahmed Hassan',
            'حسن': 'Dr. Ahmed Hassan',
            'ali': 'Dr. Fatma Ali',
            'علي': 'Dr. Fatma Ali',
            'johansson': 'Prof. Sara Johansson',
            'جوهانسون': 'Prof. Sara Johansson',
            'nwosu': 'Prof. Amara Nwosu',
        }
        staff = entities.get('staff')
        if staff:
            staff_lower = staff.lower()
            entities['staff'] = staff_map.get(staff_lower, staff)

    answer_ar = generate_arabic_answer(intent, entities, facts)

    # Real Gemini pass (if GEMINI_API_KEY is set): attached timetable JSON is
    # the core context; otherwise fall back to the facts gathered above.
    attached = (body.timetable_json or '').strip()
    if attached or intent in ('show_schedule', 'check_move', 'find_room', 'occupancy', 'insights'):
        try:
            context = attached if attached else _json.dumps(facts, ensure_ascii=False, default=str)[:12000]
        except Exception:
            context = attached
        if context:
            from starlette.concurrency import run_in_threadpool
            try:
                gemini_text = await run_in_threadpool(_gemini_answer_sync, text, context)
            except Exception:
                gemini_text = None
            if gemini_text:
                return ChatResponse(
                    intent=intent,
                    entities=entities,
                    answer_ar=gemini_text,
                    facts=facts,
                    gemini_used=True
                )

    return ChatResponse(
        intent=intent,
        entities=entities,
        answer_ar=answer_ar,
        facts=facts,
        gemini_used=False
    )

@router.get('/timetable', response_model=List[TimetableRow])
async def get_timetable(staff: Optional[str] = None, day: Optional[str] = None):
    """Get timetable rows for staff/day."""
    # Map common short names to full names
    staff_map = {
        'ahmed': 'Dr. Ahmed Hassan',
        'أحمد': 'Dr. Ahmed Hassan',
        'sara': 'Prof. Sara Johansson',
        'سارة': 'Prof. Sara Johansson',
        'chen': 'Dr. Chen Wei',
        'نوسو': 'Prof. Amara Nwosu',
        'نوسة': 'Prof. Amara Nwosu',
        'kovac': 'Dr. Lena Kovač',
        'كوفاك': 'Dr. Lena Kovač',
        'patel': 'Dr. Raj Patel',
        'باتل': 'Dr. Raj Patel',
        'bell': 'Dr. Marcus Bell',
        'بل': 'Dr. Marcus Bell',
        'hassan': 'Dr. Ahmed Hassan',
        'حسن': 'Dr. Ahmed Hassan',
        'ali': 'Dr. Fatma Ali',
        'علي': 'Dr. Fatma Ali',
        'johansson': 'Prof. Sara Johansson',
        'جوهانسون': 'Prof. Sara Johansson',
        'nwosu': 'Prof. Amara Nwosu',
    }
    if staff:
        staff_lower = staff.lower()
        staff = staff_map.get(staff_lower, staff)
    day_idx = resolve_day(day)
    rows = get_timetable_rows(staff=staff, day=day_idx)
    return rows

@router.post('/allocations/check', response_model=CheckMoveResponse)
async def check_move(body: CheckMoveRequest):
    """Validate a move (dry-run). Returns conflicts and alternatives."""
    # In production, use the conflict engine
    # For now, return basic validation
    conflicts = []
    recommendations = []

    # Mock check logic
    if body.day is not None:
        day_idx = resolve_day(body.day)
        if day_idx is None:
            conflicts.append({'conflict_type': 'INVALID_DAY', 'description': 'Invalid day'})

    ok = len(conflicts) == 0
    return CheckMoveResponse(ok=ok, conflicts=conflicts, recommendations=recommendations)

@router.get('/search/rooms', response_model=List[RoomInfo])
async def search_rooms(minCapacity: Optional[int] = None, day: Optional[str] = None):
    """Search available rooms."""
    day_idx = resolve_day(day)
    results = []
    for r in ALL_ROOMS:
        if minCapacity and r.capacity < minCapacity:
            continue
        if r.status != 'Available':
            continue
        # Check if room is free on that day
        if day_idx is not None:
            room_days = TIMETABLE.get('rooms', {}).get(r.name, {})
            occupied = sum(1 for s in room_days.values() if s is not None)
            if occupied >= len(DAYS):
                continue
        results.append(RoomInfo(
            id=r.id,
            name=r.name,
            building=r.building,
            floor=r.floor,
            type=r.type,
            capacity=r.capacity,
            examCapacity=r.exam_capacity,
            status=r.status,
            pct=r.booking_rate
        ))
    return results

@router.get('/analytics/occupancy')
async def get_occupancy():
    """Room occupancy statistics."""
    occ = []
    for r in ALL_ROOMS:
        used, total = 0, 0
        for slots in (TIMETABLE.get('rooms', {}).get(r.name, {}) or {}).values():
            cells = slots.values() if isinstance(slots, dict) else [slots]
            for s in cells:
                total += 1
                if s is not None:
                    used += 1
        occ.append({
            'room_id': r.id,
            'room_number': r.name,
            'used': used,
            'total': total,
            'pct': round(used/total*100) if total else 0
        })
    return sorted(occ, key=lambda x: -x['pct'])

@router.post('/analyze-image')
async def analyze_image(file: UploadFile = File(...)):
    """Analyze timetable photo (placeholder - needs OCR integration)."""
    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail='File must be an image')
    # Placeholder - in production integrate with OCR/Vision API
    return {
        'answer_ar': 'تحليل الصورة مش مطوّر بعد. ابعت النص بدل ما تبعت صورة دلوقتي.',
        'extracted': []
    }

@router.get('/export-ics')
async def export_ics(staff: Optional[str] = None):
    """Export timetable as ICS file."""
    from fastapi.responses import Response
    # Map common short names to full names
    staff_map = {
        'ahmed': 'Dr. Ahmed Hassan',
        'أحمد': 'Dr. Ahmed Hassan',
        'sara': 'Prof. Sara Johansson',
        'سارة': 'Prof. Sara Johansson',
        'chen': 'Dr. Chen Wei',
        'نوسو': 'Prof. Amara Nwosu',
        'نوسة': 'Prof. Amara Nwosu',
        'kovac': 'Dr. Lena Kovač',
        'كوفاك': 'Dr. Lena Kovač',
        'patel': 'Dr. Raj Patel',
        'باتل': 'Dr. Raj Patel',
        'bell': 'Dr. Marcus Bell',
        'بل': 'Dr. Marcus Bell',
        'hassan': 'Dr. Ahmed Hassan',
        'حسن': 'Dr. Ahmed Hassan',
        'ali': 'Dr. Fatma Ali',
        'علي': 'Dr. Fatma Ali',
        'johansson': 'Prof. Sara Johansson',
        'جوهانسون': 'Prof. Sara Johansson',
        'nwosu': 'Prof. Amara Nwosu',
    }
    if staff:
        staff_lower = staff.lower()
        staff = staff_map.get(staff_lower, staff)
    rows = get_timetable_rows(staff=staff)
    from app.services.export_ics import build_ics
    ics_content = build_ics(rows, DAYS)
    return Response(
        content=ics_content,
        media_type='text/calendar',
        headers={'Content-Disposition': 'attachment; filename=timetable.ics'}
    )