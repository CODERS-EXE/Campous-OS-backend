from datetime import datetime, timezone
from typing import Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AiChatMessage(Document):
    college_id: Optional[PydanticObjectId] = None
    user_id: PydanticObjectId
    role: str
    sender: str  # "user" or "assistant"
    content: str
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "ai_chat_messages"
        indexes = ["user_id", "college_id", "created_at"]
