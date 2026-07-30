from typing import Annotated, Any, Dict, List, Optional
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.constants import UserRole
from app.core.deps import get_current_user, get_tenant_college, require_roles
from app.models.college import College
from app.models.user import User
from app.services.bus import BusService

router = APIRouter(prefix="/transport", tags=["transport"])


# Pydantic Schemas
class BusCreateRequest(BaseModel):
    bus_number: str
    driver_name: str
    driver_phone: str
    capacity: int = 40
    route_id: Optional[str] = None
    status: str = "active"


class BusUpdateRequest(BaseModel):
    bus_number: Optional[str] = None
    driver_name: Optional[str] = None
    driver_phone: Optional[str] = None
    capacity: Optional[int] = None
    route_id: Optional[str] = None
    status: Optional[str] = None


class RouteStopSchema(BaseModel):
    name: str
    latitude: float
    longitude: float
    estimated_time: Optional[str] = None


class RouteCreateRequest(BaseModel):
    route_name: str
    stops: List[RouteStopSchema] = Field(default_factory=list)
    timings: Optional[str] = None


class RouteUpdateRequest(BaseModel):
    route_name: Optional[str] = None
    stops: Optional[List[RouteStopSchema]] = None
    timings: Optional[str] = None


class AssignmentCreateRequest(BaseModel):
    student_id: str
    bus_id: str
    route_id: str
    stop_name: Optional[str] = None


class LocationUpdateRequest(BaseModel):
    latitude: float
    longitude: float
    speed: float = 0.0
    status: str = "moving"


# ADMIN ENDPOINTS
@router.post("/buses", status_code=201)
async def create_bus(
    body: BusCreateRequest,
    _: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    route_oid = PydanticObjectId(body.route_id) if body.route_id else None
    bus = await BusService.create_bus(
        college_id=college.id,
        bus_number=body.bus_number,
        driver_name=body.driver_name,
        driver_phone=body.driver_phone,
        capacity=body.capacity,
        route_id=route_oid,
        status=body.status
    )
    return {
        "id": str(bus.id),
        "bus_number": bus.bus_number,
        "driver_name": bus.driver_name,
        "driver_phone": bus.driver_phone,
        "route_id": str(bus.route_id) if bus.route_id else None,
        "route_name": bus.route_name,
        "capacity": bus.capacity,
        "status": bus.status,
    }


@router.get("/buses")
async def list_buses(
    _: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    buses = await BusService.get_buses(college.id)
    return [
        {
            "id": str(b.id),
            "bus_number": b.bus_number,
            "driver_name": b.driver_name,
            "driver_phone": b.driver_phone,
            "route_id": str(b.route_id) if b.route_id else None,
            "route_name": b.route_name,
            "capacity": b.capacity,
            "status": b.status,
        }
        for b in buses
    ]


@router.get("/buses/{bus_id}")
async def get_bus(
    bus_id: str,
    _: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    bus = await BusService.get_bus_by_id(PydanticObjectId(bus_id), college.id)
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    location = await BusService.get_latest_bus_location(bus.id, college.id)
    return {
        "id": str(bus.id),
        "bus_number": bus.bus_number,
        "driver_name": bus.driver_name,
        "driver_phone": bus.driver_phone,
        "route_id": str(bus.route_id) if bus.route_id else None,
        "route_name": bus.route_name,
        "capacity": bus.capacity,
        "status": bus.status,
        "location": {
            "latitude": location.latitude if location else 12.9716,
            "longitude": location.longitude if location else 77.5946,
            "speed": location.speed if location else 0.0,
            "status": location.status if location else "stopped",
            "timestamp": location.timestamp.isoformat() if location else bus.updated_at.isoformat()
        } if location else None
    }


@router.patch("/buses/{bus_id}")
async def update_bus(
    bus_id: str,
    body: BusUpdateRequest,
    _: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    route_oid = PydanticObjectId(body.route_id) if body.route_id else None
    bus = await BusService.update_bus(
        bus_id=PydanticObjectId(bus_id),
        college_id=college.id,
        bus_number=body.bus_number,
        driver_name=body.driver_name,
        driver_phone=body.driver_phone,
        capacity=body.capacity,
        route_id=route_oid,
        status=body.status
    )
    if not bus:
        raise HTTPException(status_code=404, detail="Bus not found")
    return {
        "id": str(bus.id),
        "bus_number": bus.bus_number,
        "driver_name": bus.driver_name,
        "driver_phone": bus.driver_phone,
        "route_id": str(bus.route_id) if bus.route_id else None,
        "route_name": bus.route_name,
        "capacity": bus.capacity,
        "status": bus.status,
    }


@router.delete("/buses/{bus_id}")
async def delete_bus(
    bus_id: str,
    _: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    ok = await BusService.delete_bus(PydanticObjectId(bus_id), college.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Bus not found")
    return {"ok": True}


# ROUTES ENDPOINTS
@router.post("/routes", status_code=201)
async def create_route(
    body: RouteCreateRequest,
    _: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    route = await BusService.create_route(
        college_id=college.id,
        route_name=body.route_name,
        stops=[s.model_dump() for s in body.stops],
        timings=body.timings
    )
    return {
        "id": str(route.id),
        "route_name": route.route_name,
        "stops": [s.model_dump() for s in route.stops],
        "timings": route.timings,
    }


@router.get("/routes")
async def list_routes(
    _: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    routes = await BusService.get_routes(college.id)
    return [
        {
            "id": str(r.id),
            "route_name": r.route_name,
            "stops": [s.model_dump() for s in r.stops],
            "timings": r.timings,
        }
        for r in routes
    ]


@router.patch("/routes/{route_id}")
async def update_route(
    route_id: str,
    body: RouteUpdateRequest,
    _: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    stops_data = [s.model_dump() for s in body.stops] if body.stops is not None else None
    route = await BusService.update_route(
        route_id=PydanticObjectId(route_id),
        college_id=college.id,
        route_name=body.route_name,
        stops=stops_data,
        timings=body.timings
    )
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return {
        "id": str(route.id),
        "route_name": route.route_name,
        "stops": [s.model_dump() for s in route.stops],
        "timings": route.timings,
    }


@router.delete("/routes/{route_id}")
async def delete_route(
    route_id: str,
    _: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    ok = await BusService.delete_route(PydanticObjectId(route_id), college.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Route not found")
    return {"ok": True}


# ASSIGNMENT ENDPOINTS
@router.post("/assignments", status_code=201)
async def assign_student(
    body: AssignmentCreateRequest,
    _: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    assignment = await BusService.assign_student(
        college_id=college.id,
        student_id=PydanticObjectId(body.student_id),
        bus_id=PydanticObjectId(body.bus_id),
        route_id=PydanticObjectId(body.route_id),
        stop_name=body.stop_name
    )
    return {
        "id": str(assignment.id),
        "student_id": str(assignment.student_id),
        "bus_id": str(assignment.bus_id),
        "route_id": str(assignment.route_id),
        "stop_name": assignment.stop_name,
    }


@router.get("/assignments")
async def list_assignments(
    _: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    return await BusService.get_assignments(college.id)


@router.delete("/assignments/{assignment_id}")
async def remove_assignment(
    assignment_id: str,
    _: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    ok = await BusService.remove_assignment(PydanticObjectId(assignment_id), college.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return {"ok": True}


# LOCATION UPDATE ENDPOINT (ADMIN/DRIVER)
@router.post("/buses/{bus_id}/location")
async def update_bus_location(
    bus_id: str,
    body: LocationUpdateRequest,
    _: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN, UserRole.FACULTY))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    loc = await BusService.update_bus_location(
        bus_id=PydanticObjectId(bus_id),
        college_id=college.id,
        latitude=body.latitude,
        longitude=body.longitude,
        speed=body.speed,
        status=body.status
    )
    return {
        "id": str(loc.id),
        "bus_id": str(loc.bus_id),
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "speed": loc.speed,
        "status": loc.status,
        "timestamp": loc.timestamp.isoformat()
    }


# STUDENT / PARENT ASSIGNED BUS LOCATION & ETA
@router.get("/my-bus")
async def get_my_bus(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    student_user_id: Optional[str] = None
):
    target_id = user.id
    if user.role == UserRole.PARENT.value and student_user_id:
        target_id = PydanticObjectId(student_user_id)

    bus_bundle = await BusService.get_student_assigned_bus(
        student_user_id=target_id,
        college_id=college.id
    )
    if not bus_bundle:
        raise HTTPException(status_code=404, detail="No bus assignment found for this student")
    return bus_bundle
