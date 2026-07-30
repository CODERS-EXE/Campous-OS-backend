from pydantic import BaseModel
from typing import Optional


class ResultCreate(BaseModel):
    student_id: str
    subject: str
    exam_name: str | None = None
    internal_marks: float | None = None
    practical_marks: float | None = None


class ResultOut(BaseModel):
    id: str
    student_id: str
    subject: str
    exam_name: str | None = None
    internal_marks: float | None = None
    practical_marks: float | None = None
    total_marks: float | None = None
    grade: str | None = None
