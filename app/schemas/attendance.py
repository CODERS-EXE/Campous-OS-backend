from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class StudentAttendanceIn(BaseModel):
    student_id: str
    status: str  # present / absent / late


class AttendanceCreate(BaseModel):
    subject: str
    date: datetime
    session_name: Optional[str] = None
    records: List[StudentAttendanceIn]


class StudentAttendanceOut(BaseModel):
    student_id: str
    status: str
    marked_by: Optional[str] = None


class AttendanceOut(BaseModel):
    id: str
    faculty_id: str
    subject: str
    date: datetime
    session_name: Optional[str] = None
    records: List[StudentAttendanceOut]
    created_at: datetime
    updated_at: Optional[datetime] = None
