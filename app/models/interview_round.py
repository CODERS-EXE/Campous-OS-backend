"""
Interview Round Model
Tracks interview rounds for placement drives
"""
from datetime import datetime, timezone
from typing import Optional, Literal

from beanie import Document, PydanticObjectId
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InterviewRound(Document):
    """Interview round for a student in a placement drive"""
    college_id: PydanticObjectId
    drive_id: PydanticObjectId
    student_id: PydanticObjectId
    application_id: PydanticObjectId
    
    # Round details
    round_number: int = 1
    round_type: Literal[
        "aptitude",
        "coding",
        "technical",
        "hr",
        "group_discussion",
        "case_study",
        "presentation",
        "other"
    ]
    round_name: Optional[str] = None  # e.g., "Technical Round 1"
    
    # Scheduling
    scheduled_at: Optional[datetime] = None
    duration_minutes: Optional[int] = 60
    location: Optional[str] = None  # Physical location or meeting link
    meeting_link: Optional[str] = None
    
    # Interviewers
    interviewer_names: Optional[str] = None
    panel_size: Optional[int] = 1
    
    # Result
    status: Literal[
        "scheduled",
        "in_progress",
        "completed",
        "cleared",
        "not_cleared",
        "absent",
        "rescheduled",
        "cancelled"
    ] = "scheduled"
    
    result: Optional[Literal["pass", "fail", "hold"]] = None
    score: Optional[float] = None  # Out of 10 or 100
    feedback: Optional[str] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utcnow)
    
    # Metadata
    created_by: Optional[PydanticObjectId] = None
    
    class Settings:
        name = "interview_rounds"
        indexes = [
            "college_id",
            "drive_id",
            "student_id",
            "application_id",
            "status",
            "scheduled_at",
            [("drive_id", 1), ("student_id", 1), ("round_number", 1)],
            [("student_id", 1), ("scheduled_at", 1)],
            [("drive_id", 1), ("scheduled_at", 1)]
        ]
