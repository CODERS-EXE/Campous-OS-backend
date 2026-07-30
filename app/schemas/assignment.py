from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class AssignmentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    subject: Optional[str] = None
    due_date: Optional[datetime] = None
    attachments: List[str] = []


class AssignmentOut(BaseModel):
    id: str
    created_by: str
    title: str
    description: Optional[str] = None
    subject: Optional[str] = None
    due_date: Optional[datetime] = None
    attachments: List[str] = []
    published: bool
    created_at: datetime


class SubmissionCreate(BaseModel):
    assignment_id: str
    files: List[str] = []


class SubmissionOut(BaseModel):
    id: str
    assignment_id: str
    student_id: str
    files: List[str]
    submitted_at: datetime
    marks_awarded: float | None = None
