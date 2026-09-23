import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.database import initialize_database

from app.routers import auth, timetable, rooms, conflicts, analytics, students, versions, staff, chatbot, allocations, sections, notifications, schedules, audit

app = FastAPI(
    title="ScheduleAI API — Bua University",
    version="1.0.0",
    description="Backend for the Enterprise UI Dashboard timetable system.",
)

# CORS origins from env (comma-separated), fallback to dev defaults
cors_origins = os.getenv('CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174')
allow_origins = [o.strip() for o in cors_origins.split(',') if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Standardized error responses
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": exc.detail}},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": 422, "message": "Validation error", "details": exc.errors()}},
    )

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": {"code": 500, "message": "Internal server error"}},
    )

app.include_router(auth.router,       prefix="/api/auth",       tags=["Auth"])
app.include_router(timetable.router,  prefix="/api/timetable",  tags=["Timetable"])
app.include_router(rooms.router,      prefix="/api/rooms",      tags=["Rooms"])
app.include_router(conflicts.router,  prefix="/api/conflicts",  tags=["Conflicts"])
app.include_router(analytics.router,  prefix="/api/analytics",  tags=["Analytics"])
app.include_router(students.router,   prefix="/api/students",   tags=["Students"])
app.include_router(versions.router,   prefix="/api/versions",   tags=["Versions"])
app.include_router(staff.router,      prefix="/api/staff",      tags=["Staff"])
app.include_router(chatbot.router,    prefix="/api/chatbot",    tags=["Chatbot"])
app.include_router(allocations.router, prefix="/api/allocations", tags=["Allocations"])
app.include_router(sections.router,   prefix="/api/sections",   tags=["Sections"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
app.include_router(schedules.router,  prefix="/api/schedules",  tags=["Schedules"])
app.include_router(audit.router,      prefix="/api/audit",      tags=["Audit"])


@app.on_event('startup')
def startup_database():
    initialize_database()


@app.get("/api/health")
def health():
    from app.database import engine
    from sqlalchemy import text
    db_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    return {"status": "ok" if db_ok else "degraded", "database": "connected" if db_ok else "disconnected"}


@app.get("/health")
def health_alias():
    from app.database import engine
    from sqlalchemy import text
    db_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    return {"status": "ok" if db_ok else "degraded", "database": "connected" if db_ok else "disconnected"}


@app.get("/")
def root():
    return {"name": "ScheduleAI API — Bua University", "docs": "/docs", "health": "/api/health"}
