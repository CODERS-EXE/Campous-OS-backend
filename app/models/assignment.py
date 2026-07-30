from datetime import datetime, timezone
from typing import List, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Assignment(Document):
    college_id: PydanticObjectId
    created_by: PydanticObjectId  # faculty user id
    title: str
    description: Optional[str] = None
    subject: Optional[str] = None
    due_date: Optional[datetime] = None
    attachments: List[str] = Field(default_factory=list)  # URLs
    published: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "assignments"
        indexes = ["college_id", "created_by", "published"]
