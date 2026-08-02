from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class StudentProfileResponse(BaseModel):
    id: str
    user_id: str
    name: str
    email: EmailStr
    roll_no: str
    department: str
    course: Optional[str] = None
    year: int
    semester: int
    avatar_url: Optional[str] = None
    emergency_contact: Optional[str] = None
    blood_group: Optional[str] = None
    created_at: Optional[datetime] = None


class FacultyProfileResponse(BaseModel):
    id: str
    user_id: str
    name: str
    email: EmailStr
    department: str
    course: Optional[str] = None
    year: Optional[int] = None
    semester: Optional[int] = None
    designation: Optional[str] = None
    status: Optional[str] = None
    subjects: list[str]
    student_ids: list[str] = Field(default_factory=list)
    avatar_url: Optional[str] = None
    created_at: Optional[datetime] = None


class DashboardStats(BaseModel):
    total_students: int = 0
    total_faculty: int = 0
    unread_notifications: int = 0
    attendance_rate: Optional[float] = None


class UserCreateRequest(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=8)
    role: Literal["student", "faculty", "parent", "warden"]
    department: Optional[str] = None
    course: Optional[str] = None
    designation: Optional[str] = None
    status: Optional[str] = None
    hostel: Optional[str] = None
    phone: Optional[str] = None
    student_ids: Optional[list[str]] = None
    subjects: Optional[list[str]] = None
    roll_no: Optional[str] = None
    year: Optional[int] = None
    semester: Optional[int] = None


class UserUpdateRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(default=None, min_length=8)
    department: Optional[str] = None
    course: Optional[str] = None
    designation: Optional[str] = None
    status: Optional[str] = None
    hostel: Optional[str] = None
    phone: Optional[str] = None
    student_ids: Optional[list[str]] = None
    subjects: Optional[list[str]] = None
    roll_no: Optional[str] = None
    year: Optional[int] = None
    semester: Optional[int] = None


class UserSummaryResponse(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str
    profile: dict
    is_verified: bool
    created_at: Optional[datetime] = None
