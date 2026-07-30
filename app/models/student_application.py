"""
Student Application Model
Tracks student applications to placement drives
"""
from datetime import datetime, timezone
from typing import Optional, Literal

from beanie import Document, PydanticObjectId
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StudentApplication(Document):
    """Student application to a placement drive"""
    college_id: PydanticObjectId
    drive_id: PydanticObjectId
    student_id: PydanticObjectId
    
    # Application details
    resume_url: Optional[str] = None
    cover_letter: Optional[str] = None
    portfolio_url: Optional[str] = None
    
    # Student details snapshot (at time of application)
    student_name: str
    student_email: str
    student_roll_no: str
    student_department: str
    student_cgpa: Optional[float] = None
    student_year: Optional[int] = None
    
    # Application status
    status: Literal[
        "applied",
        "under_review",
        "shortlisted",
        "interview_scheduled",
        "selected",
        "rejected",
        "withdrawn",
        "offer_accepted",
        "offer_rejected"
    ] = "applied"
    
    # Additional info
    remarks: Optional[str] = None
    rejection_reason: Optional[str] = None
    
    # Timestamps
    applied_at: datetime = Field(default_factory=utcnow)
    reviewed_at: Optional[datetime] = None
    status_updated_at: datetime = Field(default_factory=utcnow)
    
    # Metadata
    reviewed_by: Optional[PydanticObjectId] = None  # Faculty/Admin who reviewed
    
    class Settings:
        name = "student_applications"
        indexes = [
            "college_id",
            "drive_id",
            "student_id",
            "status",
            [("drive_id", 1), ("student_id", 1)],  # Unique application per drive
            [("college_id", 1), ("status", 1)],
            [("student_id", 1), ("applied_at", -1)],
            [("drive_id", 1), ("status", 1)]
        ]
