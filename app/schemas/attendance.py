from datetime import datetime
from typing import List

from pydantic import BaseModel


class StudentAttendanceIn(BaseModel):
    student_id: str
    status: str


class AttendanceCreate(BaseModel):
    subject: str
    date: datetime
    session_name: str | None = None
    records: List[StudentAttendanceIn]


class StudentAttendanceOut(BaseModel):
    student_id: str
    status: str
    marked_by: str | None = None


class AttendanceOut(BaseModel):
    id: str
    faculty_id: str
    subject: str
    date: datetime
    session_name: str | None
    records: List[StudentAttendanceOut]
    created_at: datetime
