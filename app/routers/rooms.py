"""
Room endpoints.

GET  /api/rooms                      → list all rooms (supports ?type=&status=&building=)
GET  /api/rooms/{id}                 → one room
PUT  /api/rooms/{id}                 → update room (status, notes, bookingRate, …)
GET  /api/rooms/buildings            → list of building names
"""

from fastapi import APIRouter, Header, HTTPException, Query
from typing import Optional
from app.models.schema import Room, RoomStatus, RoomType
from app.data_store import ALL_ROOMS, TIMETABLE, DAYS
from app.database import delete_room, save_room
from app.routers.auth import require_admin

router = APIRouter()


@router.get('/buildings')
def get_buildings():
    return list({r.building for r in ALL_ROOMS})


@router.post('', response_model=Room, status_code=201)
def create_room(room_data: dict, authorization: str = Header(default='')):
    require_admin(authorization)
    # Provide default floor if not specified
    room_data.setdefault('floor', 1)
    room = Room(id=f"r{len(ALL_ROOMS) + 1}", **room_data)
    ALL_ROOMS.append(room)
    save_room(room)
    return room


@router.get('', response_model=list[Room])
def list_rooms(
    type_filter: Optional[str]   = Query(None, alias='type'),
    status:      Optional[RoomStatus] = None,
    building:    Optional[str]   = None,
    q:           Optional[str]   = None,   # search by name
):
    rooms = ALL_ROOMS
    if type_filter:
        rooms = [r for r in rooms if r.type == type_filter]
    if status:
        rooms = [r for r in rooms if r.status == status]
    if building:
        rooms = [r for r in rooms if building.lower() in r.building.lower()]
    if q:
        rooms = [r for r in rooms if q.lower() in r.name.lower()]
    return rooms


@router.get('/{room_id}', response_model=Room)
def get_room(room_id: str):
    room = next((r for r in ALL_ROOMS if r.id == room_id), None)
    if room is None:
        # also try by name
        room = next((r for r in ALL_ROOMS if r.name.lower() == room_id.lower()), None)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")
    return room


@router.put('/{room_id}', response_model=Room)
def update_room(room_id: str, updates: dict, authorization: str = Header(default='')):
    require_admin(authorization)
    idx = next((i for i, r in enumerate(ALL_ROOMS) if r.id == room_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")
    existing = ALL_ROOMS[idx]
    updated = existing.model_copy(update=updates)
    ALL_ROOMS[idx] = updated
    save_room(updated)
    return updated


@router.delete('/{room_id}')
def delete_room(room_id: str, authorization: str = Header(default='')):
    require_admin(authorization)
    idx = next((i for i, r in enumerate(ALL_ROOMS) if r.id == room_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")
    ALL_ROOMS.pop(idx)
    delete_room(room_id)
    return {'ok': True, 'deleted': room_id}


@router.get('/search/rooms')
async def search_rooms(minCapacity: Optional[int] = None, day: Optional[str] = None):
    """Search available rooms - used by chatbot."""
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
    day_idx = None
    if day is not None:
        try:
            day_idx = int(day)
        except ValueError:
            day_idx = day_map.get(day.lower(), None)
    
    results = []
    for r in ALL_ROOMS:
        if minCapacity and r.capacity < minCapacity:
            continue
        if r.status != 'Available':
            continue
        # Check if room is free on that day (any free slot counts)
        if day_idx is not None:
            slots = (TIMETABLE.get('rooms', {}).get(r.name, {}) or {}).get(day_idx)
            cells = slots.values() if isinstance(slots, dict) else ([slots] if slots is not None else [])
            if cells and all(s is not None for s in cells):
                continue
        results.append({
            'id': r.id,
            'name': r.name,
            'building': r.building,
            'floor': r.floor,
            'type': r.type,
            'capacity': r.capacity,
            'examCapacity': r.exam_capacity,
            'status': r.status,
            'pct': r.booking_rate
        })
    return results
