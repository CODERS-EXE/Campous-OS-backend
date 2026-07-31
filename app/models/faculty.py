from datetime import datetime, timezone
from typing import List, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Faculty(Document):
    college_id: PydanticObjectId
    user_id: PydanticObjectId
    department: str
    course: Optional[str] = None
    designation: Optional[str] = None
    status: str = "active"
    subjects: List[str] = Field(default_factory=list)
    # Assigned students for this faculty (minimal mapping)
    student_ids: List[PydanticObjectId] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "faculty"
        indexes = ["college_id", "user_id"]
