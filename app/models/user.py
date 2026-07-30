from datetime import datetime, timezone
from typing import Optional

# pyrefly: ignore [missing-import]
from beanie import Document, Link, PydanticObjectId
from pydantic import BaseModel, EmailStr, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserProfile(BaseModel):
    phone: Optional[str] = None
    designation: Optional[str] = None
    status: Optional[str] = None
    hostel: Optional[str] = None
    student_ids: list[str] = Field(default_factory=list)
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    emergency_contact: Optional[str] = None
    blood_group: Optional[str] = None


class User(Document):
    college_id: Optional[PydanticObjectId] = None
    role: str
    name: str
    email: EmailStr
    password_hash: str
    profile: UserProfile = Field(default_factory=UserProfile)
    is_active: bool = True
    is_verified: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "users"
        indexes = ["email", "college_id", "role"]
