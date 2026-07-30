from datetime import time
from pydantic import BaseModel
from typing import Optional


class TimetableCreate(BaseModel):
    faculty_id: str
    subject: str
    classroom: Optional[str] = None
    day_of_week: int
    start_time: time
    end_time: time


class TimetableOut(BaseModel):
    id: str
    faculty_id: str
    subject: str
    classroom: Optional[str] = None
    day_of_week: int
    start_time: time
    end_time: time
