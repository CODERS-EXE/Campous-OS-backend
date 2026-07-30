from datetime import datetime, timezone
from typing import List, Optional

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HostelBuilding(Document):
    college_id: PydanticObjectId
    name: str
    total_floors: int = 1
    total_rooms: int = 0
    gender: Optional[str] = "unisex"  # male, female, unisex
    status: str = "active"  # active, under_maintenance, inactive
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "hostel_buildings"
        indexes = ["college_id", "name"]


class Room(Document):
    college_id: PydanticObjectId
    building_id: Optional[PydanticObjectId] = None
    hostel_name: str
    block: Optional[str] = None
    floor: Optional[int] = 1
    room_number: str
    capacity: int = 2
    occupied: int = 0
    room_type: str = "double"  # single, double, triple, dormitory
    status: str = "available"  # available, occupied, maintenance
    student_ids: List[str] = Field(default_factory=list)  # List of student user_ids
    current_student_ids: List[str] = Field(default_factory=list)  # Alias / synonym for student_ids
    amenities: List[str] = Field(default_factory=list)
    is_available: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "rooms"
        indexes = ["college_id", "building_id", "hostel_name", "room_number"]


class RoomAllocation(Document):
    college_id: PydanticObjectId
    student_id: str  # user_id or student ObjectId string
    room_id: PydanticObjectId
    allocated_by: str  # user_id of warden/admin
    allocated_date: datetime = Field(default_factory=utcnow)
    vacated_date: Optional[datetime] = None
    status: str = "active"  # active, vacated, changed
    remarks: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "room_allocations"
        indexes = ["college_id", "student_id", "room_id", "status"]


class HostelRequest(Document):
    college_id: PydanticObjectId
    student_id: str  # user_id
    preferred_hostel: str
    request_reason: str
    status: str = "pending"  # pending, approved, rejected, allocated
    approved_by: Optional[str] = None  # user_id of approver
    allocated_room_id: Optional[PydanticObjectId] = None
    remarks: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "hostel_requests"
        indexes = ["college_id", "student_id", "status"]


class Outpass(Document):
    college_id: PydanticObjectId
    student_id: str  # user_id
    reason: str
    from_date: datetime
    to_date: datetime
    destination: Optional[str] = None
    contact_number: Optional[str] = None
    status: str = "pending"  # pending, approved, rejected
    approved_by: Optional[str] = None  # warden user_id
    remarks: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "outpasses"
        indexes = ["college_id", "student_id", "status"]
