"""MySQL persistence for the BUA scheduling API."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import JSON
from dotenv import load_dotenv
from pwdlib import PasswordHash

load_dotenv()
PASSWORD_HASH = PasswordHash.recommended()


DATABASE_URL = os.getenv(
    'DATABASE_URL',
    # Keep local development runnable without requiring a MySQL service.
    # Deployments can set DATABASE_URL to the documented MySQL connection.
    'sqlite:///./bua_project.db',
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(255))


class PasswordResetRow(Base):
    __tablename__ = 'password_resets'
    token_hash: Mapped[str] = mapped_column(String(255), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TimetableCellRow(Base):
    __tablename__ = 'timetable_cells'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    view: Mapped[str] = mapped_column(String(32))
    row_name: Mapped[str] = mapped_column(String(255))
    day_index: Mapped[int] = mapped_column(Integer)
    slot_index: Mapped[int] = mapped_column(Integer, default=0)
    session_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (UniqueConstraint('view', 'row_name', 'day_index', 'slot_index', name='uq_timetable_cell'),)


class RoomRow(Base):
    __tablename__ = 'rooms'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class StudentRow(Base):
    __tablename__ = 'students'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class ScheduleVersionRow(Base):
    __tablename__ = 'schedule_versions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class CourseRow(Base):
    __tablename__ = 'courses'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class SectionRow(Base):
    __tablename__ = 'sections'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class RegistrationRow(Base):
    __tablename__ = 'registrations'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class NotificationRow(Base):
    __tablename__ = 'notifications'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class AuditRow(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class SettingRow(Base):
    __tablename__ = 'schedule_settings'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


def _dump_model(value: Any) -> dict[str, Any]:
    if hasattr(value, 'model_dump'):
        return value.model_dump(by_alias=True)
    return dict(value)


def _load_settings(db: Session, key: str, fallback: list[str]) -> list[str]:
    row = db.get(SettingRow, key)
    if row is None:
        return fallback
    return json.loads(row.value)


def _migrate_timetable_slots() -> None:
    """Add slot_index to existing MySQL tables created before day+slot allocations."""
    inspector = inspect(engine)
    if 'timetable_cells' not in inspector.get_table_names():
        return
    columns = {col['name'] for col in inspector.get_columns('timetable_cells')}
    if 'slot_index' in columns:
        return
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE timetable_cells ADD COLUMN slot_index INT NOT NULL DEFAULT 0'))
        conn.execute(text('ALTER TABLE timetable_cells DROP INDEX uq_timetable_cell'))
        conn.execute(text(
            'ALTER TABLE timetable_cells ADD UNIQUE KEY uq_timetable_cell '
            '(view, row_name, day_index, slot_index)'
        ))
        rows = conn.execute(text('SELECT id, session_json FROM timetable_cells')).mappings().all()
        for row in rows:
            payload = row['session_json']
            if isinstance(payload, str):
                payload = json.loads(payload)
            slot = 0
            if isinstance(payload, dict):
                slot = int(payload.get('slot') or 0)
            conn.execute(
                text('UPDATE timetable_cells SET slot_index = :slot WHERE id = :id'),
                {'slot': slot, 'id': row['id']},
            )


def initialize_database() -> None:
    """Create the schema, seed once, then load persisted state into compatibility objects."""
    Base.metadata.create_all(engine)
    _migrate_timetable_slots()
    from app import data_store

    with SessionLocal.begin() as db:
        if db.scalar(select(UserRow.id).limit(1)) is None:
            for user in data_store.USERS:
                db.add(UserRow(email=user['email'].lower(), password=PASSWORD_HASH.hash(user['password']), role=user['role'], display_name=user['name']))
        else:
            for user in db.scalars(select(UserRow)).all():
                if not user.password.startswith('$argon2'):
                    user.password = PASSWORD_HASH.hash(user.password)
        if db.scalar(select(RoomRow.id).limit(1)) is None:
            for room in data_store.ALL_ROOMS:
                db.add(RoomRow(id=room.id, payload=_dump_model(room)))
        if db.scalar(select(StudentRow.id).limit(1)) is None:
            for student in data_store.MANAGED_STUDENTS:
                db.add(StudentRow(id=student['id'], payload=dict(student)))
        if db.scalar(select(ScheduleVersionRow.id).limit(1)) is None:
            for version in data_store.VERSIONS:
                db.add(ScheduleVersionRow(id=version.id, payload=_dump_model(version)))
        if db.scalar(select(CourseRow.id).limit(1)) is None:
            for course in data_store.COURSES:
                db.add(CourseRow(id=course.id, payload=_dump_model(course)))
        if db.scalar(select(SectionRow.id).limit(1)) is None:
            for section in data_store.SECTIONS:
                db.add(SectionRow(id=section.id, payload=_dump_model(section)))
        if db.scalar(select(RegistrationRow.id).limit(1)) is None:
            for reg in data_store.REGISTRATIONS:
                db.add(RegistrationRow(id=reg.id, payload=_dump_model(reg)))
        if db.scalar(select(NotificationRow.id).limit(1)) is None:
            for notif in data_store.NOTIFICATIONS:
                db.add(NotificationRow(id=notif.id, payload=_dump_model(notif)))
        # Audit logs table will be created by create_all; seed empty if needed
        if db.scalar(select(AuditRow.id).limit(1)) is None:
            for evt in getattr(data_store, 'AUDIT_LOGS', []):
                db.add(AuditRow(id=evt.id, payload=_dump_model(evt)))
        if db.scalar(select(SettingRow).where(SettingRow.key == 'days')) is None:
            db.add(SettingRow(key='days', value=json.dumps(data_store.DAYS)))
        if db.scalar(select(SettingRow).where(SettingRow.key == 'time_slots')) is None:
            db.add(SettingRow(key='time_slots', value=json.dumps(data_store.TIME_SLOTS)))
        for key, values in (('rooms', data_store.ROOMS), ('labs', data_store.LABS), ('staff', data_store.STAFF)):
            if db.scalar(select(SettingRow).where(SettingRow.key == key)) is None:
                db.add(SettingRow(key=key, value=json.dumps(values)))
        if db.scalar(select(SettingRow).where(SettingRow.key == 'conflicts')) is None:
            db.add(SettingRow(key='conflicts', value=json.dumps([_dump_model(conflict) for conflict in data_store.CONFLICTS])))
        if db.scalar(select(TimetableCellRow.id).limit(1)) is None:
            for view, rows in data_store.TIMETABLE.items():
                for row_name, days in rows.items():
                    for day, slots in days.items():
                        if isinstance(slots, dict):
                            for slot, session in slots.items():
                                db.add(TimetableCellRow(
                                    view=view, row_name=row_name, day_index=int(day),
                                    slot_index=int(slot),
                                    session_json=_dump_model(session) if session else None,
                                ))
                        else:
                            session = slots
                            slot = getattr(session, 'slot', 0) if session else 0
                            db.add(TimetableCellRow(
                                view=view, row_name=row_name, day_index=int(day),
                                slot_index=int(slot),
                                session_json=_dump_model(session) if session else None,
                            ))

    load_persisted_state()


def load_persisted_state() -> None:
    from app import data_store
    from app.models.schema import Room, ScheduleVersion, Session
    with SessionLocal() as db:
        user_rows = db.scalars(select(UserRow)).all()
        if user_rows:
            data_store.USERS[:] = [
                {'email': row.email, 'password': row.password, 'role': row.role, 'name': row.display_name}
                for row in user_rows
            ]
        data_store.DAYS[:] = _load_settings(db, 'days', data_store.DAYS)
        data_store.TIME_SLOTS[:] = _load_settings(db, 'time_slots', data_store.TIME_SLOTS)
        data_store.ROOMS[:] = _load_settings(db, 'rooms', data_store.ROOMS)
        data_store.LABS[:] = _load_settings(db, 'labs', data_store.LABS)
        data_store.STAFF[:] = _load_settings(db, 'staff', data_store.STAFF)
        conflict_row = db.get(SettingRow, 'conflicts')
        if conflict_row is not None:
            from app.models.schema import Conflict
            data_store.CONFLICTS[:] = [Conflict.model_validate(item) for item in json.loads(conflict_row.value)]
        room_rows = db.scalars(select(RoomRow)).all()
        if room_rows:
            data_store.ALL_ROOMS[:] = [Room.model_validate(row.payload) for row in room_rows]
        student_rows = db.scalars(select(StudentRow)).all()
        if student_rows:
            data_store.MANAGED_STUDENTS[:] = [dict(row.payload) for row in student_rows]
        version_rows = db.scalars(select(ScheduleVersionRow)).all()
        if version_rows:
            data_store.VERSIONS[:] = [ScheduleVersion.model_validate(row.payload) for row in version_rows]
        from app.models.schema import Course, Section, CourseRegistration, Notification, AuditEvent
        course_rows = db.scalars(select(CourseRow)).all()
        if course_rows:
            data_store.COURSES[:] = [Course.model_validate(row.payload) for row in course_rows]
        section_rows = db.scalars(select(SectionRow)).all()
        if section_rows:
            data_store.SECTIONS[:] = [Section.model_validate(row.payload) for row in section_rows]
        reg_rows = db.scalars(select(RegistrationRow)).all()
        if reg_rows:
            data_store.REGISTRATIONS[:] = [CourseRegistration.model_validate(row.payload) for row in reg_rows]
        notif_rows = db.scalars(select(NotificationRow)).all()
        if notif_rows:
            data_store.NOTIFICATIONS[:] = [Notification.model_validate(row.payload) for row in notif_rows]
        audit_rows = db.scalars(select(AuditRow)).all()
        if audit_rows:
            data_store.AUDIT_LOGS[:] = [AuditEvent.model_validate(row.payload) for row in audit_rows]
        cell_rows = db.scalars(select(TimetableCellRow)).all()
        if cell_rows:
            data_store.TIMETABLE.clear()
            slot_count = max(len(data_store.TIME_SLOTS), 1)
            for cell in cell_rows:
                session = Session.model_validate(cell.session_json) if cell.session_json else None
                slot = int(getattr(cell, 'slot_index', 0) or (session.slot if session else 0))
                if session is not None:
                    session.slot = slot
                day_map = data_store.TIMETABLE.setdefault(cell.view, {}).setdefault(cell.row_name, {})
                slots = day_map.setdefault(cell.day_index, {i: None for i in range(slot_count)})
                if not isinstance(slots, dict):
                    slots = {i: None for i in range(slot_count)}
                    day_map[cell.day_index] = slots
                slots[slot] = session
            for view in ('rooms', 'labs', 'staff'):
                data_store.TIMETABLE.setdefault(view, {})
            for rows in data_store.TIMETABLE.values():
                for days in rows.values():
                    for day in range(len(data_store.DAYS)):
                        day_slots = days.setdefault(day, {i: None for i in range(slot_count)})
                        if not isinstance(day_slots, dict):
                            days[day] = {i: None for i in range(slot_count)}
                            continue
                        for slot in range(slot_count):
                            day_slots.setdefault(slot, None)


def save_timetable_cell(view: str, row_name: str, day: int, session: Any | None, slot: int | None = None) -> None:
    slot_index = int(slot if slot is not None else getattr(session, 'slot', 0) or 0)
    with SessionLocal.begin() as db:
        row = db.scalar(select(TimetableCellRow).where(
            TimetableCellRow.view == view,
            TimetableCellRow.row_name == row_name,
            TimetableCellRow.day_index == day,
            TimetableCellRow.slot_index == slot_index,
        ))
        payload = _dump_model(session) if session else None
        if row is None:
            db.add(TimetableCellRow(
                view=view, row_name=row_name, day_index=day,
                slot_index=slot_index, session_json=payload,
            ))
        else:
            row.session_json = payload


def save_timetable_row(view: str, row_name: str, days: dict[int, Any | None]) -> None:
    for day, slots in days.items():
        if isinstance(slots, dict):
            for slot, session in slots.items():
                save_timetable_cell(view, row_name, int(day), session, int(slot))
        else:
            save_timetable_cell(view, row_name, int(day), slots)


def save_setting(key: str, value: Any) -> None:
    with SessionLocal.begin() as db:
        row = db.get(SettingRow, key)
        if row is None:
            db.add(SettingRow(key=key, value=json.dumps(value)))
        else:
            row.value = json.dumps(value)


def save_staff_rows(staff: list[str]) -> None:
    save_setting('staff', staff)


def create_password_reset(email: str, expires_at: datetime) -> str:
    token = secrets.token_urlsafe(32)
    with SessionLocal.begin() as db:
        db.add(PasswordResetRow(token_hash=PASSWORD_HASH.hash(token), email=email.lower(), expires_at=expires_at))
    return token


def consume_password_reset(token: str, new_password_hash: str) -> bool:
    with SessionLocal.begin() as db:
        candidates = db.scalars(select(PasswordResetRow)).all()
        reset = next((item for item in candidates if PASSWORD_HASH.verify(token, item.token_hash)), None)
        if reset is None:
            return False
        expires_at = reset.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return False
        user = db.scalar(select(UserRow).where(UserRow.email == reset.email))
        if user is None:
            return False
        user.password = new_password_hash
        from app import data_store
        for cached_user in data_store.USERS:
            if cached_user['email'].lower() == reset.email:
                cached_user['password'] = new_password_hash
                break
        db.delete(reset)
        return True


def save_room(room: Any) -> None:
    with SessionLocal.begin() as db:
        row = db.get(RoomRow, room.id)
        payload = _dump_model(room)
        if row is None:
            db.add(RoomRow(id=room.id, payload=payload))
        else:
            row.payload = payload


def delete_room(room_id: str) -> None:
    with SessionLocal.begin() as db:
        row = db.get(RoomRow, room_id)
        if row is not None:
            db.delete(row)


def save_student(student: dict[str, Any]) -> None:
    with SessionLocal.begin() as db:
        row = db.get(StudentRow, student['id'])
        if row is None:
            db.add(StudentRow(id=student['id'], payload=student))
        else:
            row.payload = student


def delete_student(student_id: str) -> None:
    with SessionLocal.begin() as db:
        row = db.get(StudentRow, student_id)
        if row is not None:
            db.delete(row)


def save_version(version: Any) -> None:
    with SessionLocal.begin() as db:
        row = db.get(ScheduleVersionRow, version.id)
        payload = _dump_model(version)
        if row is None:
            db.add(ScheduleVersionRow(id=version.id, payload=payload))
        else:
            row.payload = payload


def delete_version(version_id: str) -> None:
    with SessionLocal.begin() as db:
        row = db.get(ScheduleVersionRow, version_id)
        if row is not None:
            db.delete(row)


def save_course(course: Any) -> None:
    with SessionLocal.begin() as db:
        row = db.get(CourseRow, course.id)
        payload = _dump_model(course)
        if row is None:
            db.add(CourseRow(id=course.id, payload=payload))
        else:
            row.payload = payload


def delete_course(course_id: str) -> None:
    with SessionLocal.begin() as db:
        row = db.get(CourseRow, course_id)
        if row is not None:
            db.delete(row)


def save_section(section: Any) -> None:
    with SessionLocal.begin() as db:
        row = db.get(SectionRow, section.id)
        payload = _dump_model(section)
        if row is None:
            db.add(SectionRow(id=section.id, payload=payload))
        else:
            row.payload = payload


def delete_section(section_id: str) -> None:
    with SessionLocal.begin() as db:
        row = db.get(SectionRow, section_id)
        if row is not None:
            db.delete(row)


def save_registration(reg: Any) -> None:
    with SessionLocal.begin() as db:
        payload = _dump_model(reg)
        row = db.get(RegistrationRow, reg.id)
        if row is None:
            db.add(RegistrationRow(id=reg.id, payload=payload))
        else:
            row.payload = payload


def delete_registration(reg_id: str) -> None:
    with SessionLocal.begin() as db:
        row = db.get(RegistrationRow, reg_id)
        if row is not None:
            db.delete(row)


def save_notification(notif: Any) -> None:
    with SessionLocal.begin() as db:
        payload = _dump_model(notif)
        row = db.get(NotificationRow, notif.id)
        if row is None:
            db.add(NotificationRow(id=notif.id, payload=payload))
        else:
            row.payload = payload


def save_audit(event: Any) -> None:
    with SessionLocal.begin() as db:
        payload = _dump_model(event)
        row = db.get(AuditRow, event.id)
        if row is None:
            db.add(AuditRow(id=event.id, payload=payload))
        else:
            row.payload = payload
