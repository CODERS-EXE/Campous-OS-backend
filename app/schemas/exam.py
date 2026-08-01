from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class ExamCreate(BaseModel):
    name: str = Field(..., description="Exam name (e.g. Mid-Term Exam)")
    exam_type: str = Field("mid_term", description="Type: internal, mid_term, end_term, supplementary")
    academic_year: str = Field(..., description="Academic year (e.g. 2024-2025)")
    semester: int = Field(..., ge=1, le=8, description="Semester number")
    start_date: datetime = Field(..., description="Exam start date")
    end_date: datetime = Field(..., description="Exam end date")
    description: Optional[str] = Field(None, description="Exam description")


class ExamUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    description: Optional[str] = None


class SubjectExamCreate(BaseModel):
    subject_id: Optional[str] = None
    subject_name: str
    subject_code: str
    exam_date: datetime
    start_time: str
    end_time: str
    duration_minutes: int
    max_marks: int
    passing_marks: int
    credits: int = 3
    room_numbers: List[str] = Field(default_factory=list)
    internal_marks_weight: int = 30
    external_marks_weight: int = 70


class SubjectExamUpdate(BaseModel):
    exam_date: Optional[datetime] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    room_numbers: Optional[List[str]] = None
    status: Optional[str] = None
