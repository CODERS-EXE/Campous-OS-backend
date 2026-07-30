from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Submission(Document):
    college_id: PydanticObjectId
    assignment_id: PydanticObjectId
    student_id: PydanticObjectId
    files: list[str] = Field(default_factory=list)
    created_by: PydanticObjectId | None = None
    submitted_at: datetime = Field(default_factory=utcnow)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    marks_awarded: float | None = None

    class Settings:
        name = "submissions"
        indexes = ["college_id", "assignment_id", "student_id"]
