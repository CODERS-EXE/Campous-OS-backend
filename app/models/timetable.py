from datetime import time, datetime, timezone
from typing import Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimetableEntry(Document):
    college_id: PydanticObjectId
    faculty_id: PydanticObjectId
    subject: str
    classroom: Optional[str] = None
    day_of_week: int  # 0=Monday .. 6=Sunday
    start_time: time
    end_time: time
    created_by: PydanticObjectId | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "timetable"
        indexes = ["college_id", "faculty_id", "day_of_week"]
