from datetime import datetime, timezone
from typing import List

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudentAttendance(BaseModel):
    student_id: PydanticObjectId
    status: str  # present/absent/late
    marked_by: PydanticObjectId | None = None


class Attendance(Document):
    college_id: PydanticObjectId
    faculty_id: PydanticObjectId
    subject: str
    date: datetime
    session_name: str | None = None
    records: List[StudentAttendance] = Field(default_factory=list)
    created_by: PydanticObjectId | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "attendance"
        indexes = ["college_id", "faculty_id", "date"]
