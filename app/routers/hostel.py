from typing import Annotated, List, Optional
from beanie import PydanticObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.constants import UserRole
from app.core.deps import get_current_user, get_tenant_college, require_roles
from app.models.college import College
from app.models.hostel import HostelBuilding, HostelRequest, Outpass, Room, RoomAllocation
from app.models.student import Student
from app.models.user import User
from app.services.hostel import HostelService
from app.services.notification_service import (
    notify_outpass_approved,
    notify_outpass_rejected,
    notify_room_changed,
)

router = APIRouter(prefix="/hostel", tags=["hostel"])


# --- SCHEMAS ---
class BuildingCreateRequest(BaseModel):
    name: str
    total_floors: int = 1
    total_rooms: int = 0
    gender: Optional[str] = "unisex"
    status: str = "active"
    description: Optional[str] = None


class BuildingUpdateRequest(BaseModel):
    name: Optional[str] = None
    total_floors: Optional[int] = None
    total_rooms: Optional[int] = None
    gender: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None


class RoomCreateRequest(BaseModel):
    room_number: str
    hostel_name: Optional[str] = "Main Hostel"
    building_id: Optional[str] = None
    block: Optional[str] = None
    floor: int = 1
    capacity: int = 2
    room_type: str = "double"
    status: str = "available"
    amenities: List[str] = Field(default_factory=lambda: ["Bed", "Study Table", "Wardrobe"])


class RoomUpdateRequest(BaseModel):
    room_number: Optional[str] = None
    hostel_name: Optional[str] = None
    building_id: Optional[str] = None
    block: Optional[str] = None
    floor: Optional[int] = None
    capacity: Optional[int] = None
    room_type: Optional[str] = None
    status: Optional[str] = None
    amenities: Optional[List[str]] = None


class AllocationCreateRequest(BaseModel):
    student_id: str
    room_id: str
    remarks: Optional[str] = None


class AllocationChangeRequest(BaseModel):
    student_id: str
    new_room_id: str
    remarks: Optional[str] = None


class RequestCreateRequest(BaseModel):
    preferred_hostel: str
    request_reason: str


class RequestApproveRequest(BaseModel):
    allocated_room_id: Optional[str] = None
    remarks: Optional[str] = None


class RequestRejectRequest(BaseModel):
    remarks: Optional[str] = None


class OutpassCreateRequest(BaseModel):
    reason: str
    from_date: str
    to_date: str
    destination: Optional[str] = None
    contact_number: Optional[str] = None


class OutpassUpdateRequest(BaseModel):
    status: str
    remarks: Optional[str] = None


# --- STATS ---
@router.get("/stats")
async def get_hostel_stats(
    _: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    return await HostelService.get_hostel_stats(college.id)


# --- BUILDINGS ENDPOINTS ---
@router.post("/buildings", status_code=201)
async def create_building(
    body: BuildingCreateRequest,
    _: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    bld = await HostelService.create_building(
        college_id=college.id,
        name=body.name,
        total_floors=body.total_floors,
        total_rooms=body.total_rooms,
        gender=body.gender,
        status=body.status,
        description=body.description
    )
    return {
        "id": str(bld.id),
        "name": bld.name,
        "total_floors": bld.total_floors,
        "total_rooms": bld.total_rooms,
        "gender": bld.gender,
        "status": bld.status,
        "description": bld.description,
        "created_at": bld.created_at.isoformat()
    }


@router.get("/buildings")
async def list_buildings(
    _: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    buildings = await HostelService.get_buildings(college.id)
    result = []
    for b in buildings:
        rooms_count = await Room.find(Room.building_id == b.id).count()
        occupied_count = sum(r.occupied for r in await Room.find(Room.building_id == b.id).to_list())
        capacity_sum = sum(r.capacity for r in await Room.find(Room.building_id == b.id).to_list())
        result.append({
            "id": str(b.id),
            "name": b.name,
            "total_floors": b.total_floors,
            "total_rooms": max(b.total_rooms, rooms_count),
            "gender": b.gender,
            "status": b.status,
            "description": b.description,
            "capacity": capacity_sum,
            "occupied": occupied_count,
            "created_at": b.created_at.isoformat()
        })
    return result


@router.patch("/buildings/{building_id}")
async def update_building(
    building_id: str,
    body: BuildingUpdateRequest,
    _: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    bld = await HostelService.update_building(
        building_id=PydanticObjectId(building_id),
        college_id=college.id,
        name=body.name,
        total_floors=body.total_floors,
        total_rooms=body.total_rooms,
        gender=body.gender,
        status=body.status,
        description=body.description
    )
    if not bld:
        raise HTTPException(status_code=404, detail="Building not found")
    return {
        "id": str(bld.id),
        "name": bld.name,
        "total_floors": bld.total_floors,
        "total_rooms": bld.total_rooms,
        "gender": bld.gender,
        "status": bld.status,
        "description": bld.description
    }


@router.delete("/buildings/{building_id}")
async def delete_building(
    building_id: str,
    _: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    ok = await HostelService.delete_building(PydanticObjectId(building_id), college.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Building not found")
    return {"ok": True}


# --- ROOMS ENDPOINTS ---
@router.post("/rooms", status_code=201)
async def create_room(
    body: RoomCreateRequest,
    _: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    b_oid = PydanticObjectId(body.building_id) if body.building_id else None
    room = await HostelService.create_room(
        college_id=college.id,
        room_number=body.room_number,
        hostel_name=body.hostel_name or "Main Hostel",
        building_id=b_oid,
        block=body.block,
        floor=body.floor,
        capacity=body.capacity,
        room_type=body.room_type,
        status=body.status,
        amenities=body.amenities
    )
    return {
        "id": str(room.id),
        "building_id": str(room.building_id) if room.building_id else None,
        "hostel_name": room.hostel_name,
        "block": room.block,
        "floor": room.floor,
        "room_number": room.room_number,
        "capacity": room.capacity,
        "occupied": room.occupied,
        "room_type": room.room_type,
        "status": room.status,
        "student_ids": room.student_ids,
        "amenities": room.amenities,
        "is_available": room.is_available,
        "created_at": room.created_at.isoformat()
    }


@router.get("/rooms")
async def list_rooms(
    _: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    hostel: Optional[str] = None,
    building_id: Optional[str] = None,
    floor: Optional[int] = None,
    status_filter: Optional[str] = None
):
    query = {"college_id": college.id}
    if hostel:
        query["hostel_name"] = hostel
    if building_id:
        query["building_id"] = PydanticObjectId(building_id)
    if floor:
        query["floor"] = floor
    if status_filter:
        query["status"] = status_filter

    rooms = await Room.find(query).to_list()
    result = []
    for r in rooms:
        # Populate occupants details
        occupants = []
        for sid in r.student_ids:
            u = await User.get(PydanticObjectId(sid) if len(sid) == 24 else sid)
            st = await Student.find_one(Student.user_id == PydanticObjectId(sid)) if len(sid) == 24 else None
            if u:
                occupants.append({
                    "user_id": str(u.id),
                    "name": u.name,
                    "email": u.email,
                    "roll_no": st.roll_no if st else "N/A",
                    "department": st.department if st else "N/A"
                })

        result.append({
            "id": str(r.id),
            "building_id": str(r.building_id) if r.building_id else None,
            "hostel_name": r.hostel_name,
            "block": r.block,
            "floor": r.floor,
            "room_number": r.room_number,
            "capacity": r.capacity,
            "occupied": r.occupied,
            "room_type": r.room_type,
            "status": r.status,
            "student_ids": r.student_ids,
            "occupants": occupants,
            "amenities": r.amenities,
            "is_available": r.is_available,
            "created_at": r.created_at.isoformat()
        })
    return result


@router.patch("/rooms/{room_id}")
async def update_room(
    room_id: str,
    body: RoomUpdateRequest,
    _: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    b_oid = PydanticObjectId(body.building_id) if body.building_id else None
    room = await HostelService.update_room(
        room_id=PydanticObjectId(room_id),
        college_id=college.id,
        room_number=body.room_number,
        hostel_name=body.hostel_name,
        building_id=b_oid,
        block=body.block,
        floor=body.floor,
        capacity=body.capacity,
        room_type=body.room_type,
        status=body.status,
        amenities=body.amenities
    )
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return {
        "id": str(room.id),
        "room_number": room.room_number,
        "hostel_name": room.hostel_name,
        "capacity": room.capacity,
        "occupied": room.occupied,
        "status": room.status
    }


@router.delete("/rooms/{room_id}")
async def delete_room(
    room_id: str,
    _: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    ok = await HostelService.delete_room(PydanticObjectId(room_id), college.id)
    if not ok:
        raise HTTPException(status_code=400, detail="Cannot delete room that has active occupants or does not exist.")
    return {"ok": True}


# --- ALLOCATION ENDPOINTS ---
@router.post("/allocations", status_code=201)
async def allocate_room(
    body: AllocationCreateRequest,
    user: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    try:
        alloc = await HostelService.allocate_room(
            college_id=college.id,
            student_id=body.student_id,
            room_id=PydanticObjectId(body.room_id),
            allocated_by=str(user.id),
            remarks=body.remarks
        )
        return {
            "id": str(alloc.id),
            "student_id": alloc.student_id,
            "room_id": str(alloc.room_id),
            "allocated_by": alloc.allocated_by,
            "allocated_date": alloc.allocated_date.isoformat(),
            "status": alloc.status,
            "remarks": alloc.remarks
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/allocations/change")
async def change_room(
    body: AllocationChangeRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    try:
        alloc = await HostelService.change_room(
            college_id=college.id,
            student_id=body.student_id,
            new_room_id=PydanticObjectId(body.new_room_id),
            allocated_by=str(user.id),
            remarks=body.remarks
        )

        # Auto-notify student about room change
        new_room = await Room.get(PydanticObjectId(body.new_room_id))
        if new_room:
            background_tasks.add_task(
                notify_room_changed,
                college_id=college.id,
                student_user_id=body.student_id,
                new_room=new_room.room_number,
                created_by=user.id,
            )

        return {
            "id": str(alloc.id),
            "student_id": alloc.student_id,
            "room_id": str(alloc.room_id),
            "allocated_by": alloc.allocated_by,
            "allocated_date": alloc.allocated_date.isoformat(),
            "status": alloc.status,
            "remarks": alloc.remarks
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/allocations/{allocation_id}/vacate")
async def vacate_room(
    allocation_id: str,
    _: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
    remarks: Optional[str] = None
):
    ok = await HostelService.vacate_room(PydanticObjectId(allocation_id), college.id, remarks=remarks)
    if not ok:
        raise HTTPException(status_code=404, detail="Allocation not found or already vacated")
    return {"ok": True}


@router.get("/allocations")
async def list_allocations(
    _: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
    status_filter: Optional[str] = None
):
    query = {"college_id": college.id}
    if status_filter:
        query["status"] = status_filter

    allocs = await RoomAllocation.find(query).sort("-created_at").to_list()
    result = []
    for a in allocs:
        student_user = await User.get(PydanticObjectId(a.student_id) if len(a.student_id) == 24 else a.student_id)
        st = await Student.find_one(Student.user_id == PydanticObjectId(a.student_id)) if len(a.student_id) == 24 else None
        room = await Room.get(a.room_id)
        allocator = await User.get(PydanticObjectId(a.allocated_by) if len(a.allocated_by) == 24 else a.allocated_by)

        result.append({
            "id": str(a.id),
            "student_id": a.student_id,
            "student_name": student_user.name if student_user else "Student",
            "roll_no": st.roll_no if st else "N/A",
            "department": st.department if st else "N/A",
            "room_id": str(a.room_id),
            "room_number": room.room_number if room else "N/A",
            "hostel_name": room.hostel_name if room else "N/A",
            "allocated_by_name": allocator.name if allocator else "Admin",
            "allocated_date": a.allocated_date.isoformat(),
            "vacated_date": a.vacated_date.isoformat() if a.vacated_date else None,
            "status": a.status,
            "remarks": a.remarks
        })
    return result


# --- HOSTEL REQUESTS ENDPOINTS ---
@router.post("/requests", status_code=201)
async def create_hostel_request(
    body: RequestCreateRequest,
    user: Annotated[User, Depends(require_roles(UserRole.STUDENT))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    req = await HostelService.create_request(
        college_id=college.id,
        student_id=str(user.id),
        preferred_hostel=body.preferred_hostel,
        request_reason=body.request_reason
    )
    return {
        "id": str(req.id),
        "student_id": req.student_id,
        "preferred_hostel": req.preferred_hostel,
        "request_reason": req.request_reason,
        "status": req.status,
        "created_at": req.created_at.isoformat()
    }


@router.get("/requests")
async def list_hostel_requests(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    status_filter: Optional[str] = None
):
    query = {"college_id": college.id}
    if user.role == UserRole.STUDENT.value:
        query["student_id"] = str(user.id)
    if status_filter:
        query["status"] = status_filter

    requests = await HostelRequest.find(query).sort("-created_at").to_list()
    result = []
    for r in requests:
        student_user = await User.get(PydanticObjectId(r.student_id) if len(r.student_id) == 24 else r.student_id)
        st = await Student.find_one(Student.user_id == PydanticObjectId(r.student_id)) if len(r.student_id) == 24 else None
        approver = await User.get(PydanticObjectId(r.approved_by) if r.approved_by and len(r.approved_by) == 24 else r.approved_by) if r.approved_by else None

        result.append({
            "id": str(r.id),
            "student_id": r.student_id,
            "student_name": student_user.name if student_user else "Student",
            "roll_no": st.roll_no if st else "N/A",
            "department": st.department if st else "N/A",
            "preferred_hostel": r.preferred_hostel,
            "request_reason": r.request_reason,
            "status": r.status,
            "approved_by_name": approver.name if approver else None,
            "remarks": r.remarks,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat()
        })
    return result


@router.patch("/requests/{request_id}/approve")
async def approve_hostel_request(
    request_id: str,
    body: RequestApproveRequest,
    user: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    try:
        alloc_room_oid = PydanticObjectId(body.allocated_room_id) if body.allocated_room_id else None
        req = await HostelService.approve_request(
            request_id=PydanticObjectId(request_id),
            college_id=college.id,
            approved_by=str(user.id),
            allocated_room_id=alloc_room_oid,
            remarks=body.remarks
        )
        return {
            "id": str(req.id),
            "status": req.status,
            "remarks": req.remarks
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/requests/{request_id}/reject")
async def reject_hostel_request(
    request_id: str,
    body: RequestRejectRequest,
    user: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    try:
        req = await HostelService.reject_request(
            request_id=PydanticObjectId(request_id),
            college_id=college.id,
            approved_by=str(user.id),
            remarks=body.remarks
        )
        return {
            "id": str(req.id),
            "status": req.status,
            "remarks": req.remarks
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- STUDENT MY-ROOM & STATUS ENDPOINT ---
@router.get("/my-room")
async def get_my_room(
    user: Annotated[User, Depends(require_roles(UserRole.STUDENT))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    alloc = await RoomAllocation.find_one(
        RoomAllocation.college_id == college.id,
        RoomAllocation.student_id == str(user.id),
        RoomAllocation.status == "active"
    )
    if not alloc:
        # Check active requests if any
        recent_req = await HostelRequest.find_one(
            HostelRequest.college_id == college.id,
            HostelRequest.student_id == str(user.id)
        )
        return {
            "allocated": False,
            "room": None,
            "building": None,
            "roommates": [],
            "latest_request": {
                "id": str(recent_req.id),
                "preferred_hostel": recent_req.preferred_hostel,
                "status": recent_req.status,
                "created_at": recent_req.created_at.isoformat()
            } if recent_req else None
        }

    room = await Room.get(alloc.room_id)
    building = await HostelBuilding.get(room.building_id) if room and room.building_id else None

    # Roommates
    roommates = []
    if room:
        for sid in room.student_ids:
            if sid != str(user.id):
                u = await User.get(PydanticObjectId(sid) if len(sid) == 24 else sid)
                st = await Student.find_one(Student.user_id == PydanticObjectId(sid)) if len(sid) == 24 else None
                if u:
                    roommates.append({
                        "name": u.name,
                        "email": u.email,
                        "roll_no": st.roll_no if st else "N/A",
                        "department": st.department if st else "N/A",
                        "phone": u.profile.get("phone", "N/A")
                    })

    return {
        "allocated": True,
        "allocation": {
            "id": str(alloc.id),
            "allocated_date": alloc.allocated_date.isoformat(),
            "remarks": alloc.remarks
        },
        "room": {
            "id": str(room.id) if room else None,
            "room_number": room.room_number if room else "N/A",
            "hostel_name": room.hostel_name if room else "N/A",
            "floor": room.floor if room else 1,
            "capacity": room.capacity if room else 2,
            "occupied": room.occupied if room else 1,
            "room_type": room.room_type if room else "double",
            "amenities": room.amenities if room else []
        },
        "building": {
            "id": str(building.id) if building else None,
            "name": building.name if building else (room.hostel_name if room else "Main Hostel"),
            "description": building.description if building else None
        } if (building or room) else None,
        "roommates": roommates
    }


# --- OUTPASS ENDPOINTS (PRESERVED) ---
@router.get("/outpasses")
async def list_outpasses(
    user: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.STUDENT, UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
    status_filter: Optional[str] = None,
):
    query = {"college_id": college.id}
    if user.role == UserRole.STUDENT.value:
        query["student_id"] = str(user.id)
    if status_filter:
        query["status"] = status_filter

    outpasses = await Outpass.find(query).sort("-created_at").to_list()
    result = []
    for outpass in outpasses:
        student_user = await User.get(PydanticObjectId(outpass.student_id) if len(outpass.student_id) == 24 else outpass.student_id)
        student = await Student.find_one(Student.user_id == PydanticObjectId(outpass.student_id)) if len(outpass.student_id) == 24 else None

        approved_by_name = None
        if outpass.approved_by:
            approver = await User.get(PydanticObjectId(outpass.approved_by) if len(outpass.approved_by) == 24 else outpass.approved_by)
            if approver:
                approved_by_name = approver.name

        result.append({
            "id": str(outpass.id),
            "student_id": outpass.student_id,
            "student_name": student_user.name if student_user else "Unknown",
            "student_roll_no": student.roll_no if student else None,
            "reason": outpass.reason,
            "from_date": outpass.from_date.isoformat(),
            "to_date": outpass.to_date.isoformat(),
            "destination": outpass.destination,
            "contact_number": outpass.contact_number,
            "status": outpass.status,
            "approved_by": outpass.approved_by,
            "approved_by_name": approved_by_name,
            "remarks": outpass.remarks,
            "created_at": outpass.created_at.isoformat(),
            "updated_at": outpass.updated_at.isoformat(),
        })

    return result


@router.post("/outpasses")
async def create_outpass(
    body: OutpassCreateRequest,
    user: Annotated[User, Depends(require_roles(UserRole.STUDENT))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    outpass = Outpass(
        college_id=college.id,
        student_id=str(user.id),
        reason=body.reason,
        from_date=datetime.fromisoformat(body.from_date.replace("Z", "+00:00")),
        to_date=datetime.fromisoformat(body.to_date.replace("Z", "+00:00")),
        destination=body.destination,
        contact_number=body.contact_number,
        status="pending",
    )
    await outpass.insert()

    student = await Student.find_one(Student.user_id == user.id)

    return {
        "id": str(outpass.id),
        "student_id": outpass.student_id,
        "student_name": user.name,
        "student_roll_no": student.roll_no if student else None,
        "reason": outpass.reason,
        "from_date": outpass.from_date.isoformat(),
        "to_date": outpass.to_date.isoformat(),
        "destination": outpass.destination,
        "contact_number": outpass.contact_number,
        "status": outpass.status,
        "approved_by": None,
        "approved_by_name": None,
        "remarks": outpass.remarks,
        "created_at": outpass.created_at.isoformat(),
        "updated_at": outpass.updated_at.isoformat(),
    }


@router.patch("/outpasses/{outpass_id}")
async def update_outpass(
    outpass_id: str,
    body: OutpassUpdateRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    outpass = await Outpass.get(PydanticObjectId(outpass_id))
    if not outpass or outpass.college_id != college.id:
        raise HTTPException(status_code=404, detail="Outpass not found")

    outpass.status = body.status
    outpass.approved_by = str(user.id)
    outpass.remarks = body.remarks
    outpass.updated_at = utcnow()
    await outpass.save()

    # Auto-notify student about outpass decision
    if body.status == "approved":
        background_tasks.add_task(
            notify_outpass_approved,
            college_id=college.id,
            student_user_id=outpass.student_id,
            from_date=outpass.from_date.strftime("%Y-%m-%d"),
            to_date=outpass.to_date.strftime("%Y-%m-%d"),
            outpass_id=str(outpass.id),
            created_by=user.id,
        )
    elif body.status == "rejected":
        background_tasks.add_task(
            notify_outpass_rejected,
            college_id=college.id,
            student_user_id=outpass.student_id,
            reason=body.remarks or "No reason provided",
            outpass_id=str(outpass.id),
            created_by=user.id,
        )

    student_user = await User.get(PydanticObjectId(outpass.student_id) if len(outpass.student_id) == 24 else outpass.student_id)
    student = await Student.find_one(Student.user_id == PydanticObjectId(outpass.student_id)) if len(outpass.student_id) == 24 else None

    return {
        "id": str(outpass.id),
        "student_id": outpass.student_id,
        "student_name": student_user.name if student_user else "Unknown",
        "student_roll_no": student.roll_no if student else None,
        "reason": outpass.reason,
        "from_date": outpass.from_date.isoformat(),
        "to_date": outpass.to_date.isoformat(),
        "destination": outpass.destination,
        "contact_number": outpass.contact_number,
        "status": outpass.status,
        "approved_by": outpass.approved_by,
        "approved_by_name": user.name,
        "remarks": outpass.remarks,
        "created_at": outpass.created_at.isoformat(),
        "updated_at": outpass.updated_at.isoformat(),
    }


@router.get("/students", response_model=List[dict])
async def list_hostel_students(
    _: Annotated[User, Depends(require_roles(UserRole.WARDEN, UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
    hostel: Optional[str] = None,
):
    students = await Student.find(Student.college_id == college.id).to_list()
    result = []
    for student in students:
        u = await User.get(student.user_id)
        if not u:
            continue
        if hostel and u.profile.get("hostel") != hostel:
            continue
        result.append({
            "id": str(student.id),
            "user_id": str(u.id),
            "name": u.name,
            "email": u.email,
            "roll_no": student.roll_no,
            "department": student.department,
            "year": student.year,
            "semester": student.semester,
            "hostel": u.profile.get("hostel"),
            "phone": u.profile.get("phone"),
            "emergency_contact": student.emergency_contact,
            "blood_group": student.blood_group,
        })
    return result
