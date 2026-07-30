from datetime import datetime, timezone
from typing import List, Optional

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BusStop(BaseModel):
    name: str
    latitude: float
    longitude: float
    estimated_time: Optional[str] = None


class BusRoute(Document):
    college_id: PydanticObjectId
    route_name: str
    stops: List[BusStop] = Field(default_factory=list)
    timings: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "bus_routes"
        indexes = ["college_id", "route_name"]


class Bus(Document):
    college_id: PydanticObjectId
    bus_number: str
    driver_name: str
    driver_phone: str
    route_id: Optional[PydanticObjectId] = None
    route_name: Optional[str] = None
    capacity: int = 40
    status: str = "active"  # active, in_transit, maintenance, inactive
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "buses"
        indexes = ["college_id", "bus_number", "route_id"]


class BusLocation(Document):
    bus_id: PydanticObjectId
    college_id: PydanticObjectId
    latitude: float
    longitude: float
    speed: float = 0.0
    status: str = "moving"  # moving, stopped, idle, delayed
    timestamp: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "bus_locations"
        indexes = ["bus_id", "college_id", "timestamp"]


class StudentBusAssignment(Document):
    college_id: PydanticObjectId
    student_id: PydanticObjectId
    bus_id: PydanticObjectId
    route_id: PydanticObjectId
    stop_name: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "student_bus_assignments"
        indexes = ["college_id", "student_id", "bus_id"]
