from datetime import datetime, timezone

from beanie import Document, PydanticObjectId
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Result(Document):
    college_id: PydanticObjectId
    student_id: PydanticObjectId
    faculty_id: PydanticObjectId | None = None
    created_by: PydanticObjectId | None = None
    subject: str
    exam_name: str | None = None
    internal_marks: float | None = None
    practical_marks: float | None = None
    total_marks: float | None = None
    grade: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "results"
        indexes = ["college_id", "student_id", "subject"]
