from datetime import datetime, timezone
from typing import Literal, Optional, Dict, Any

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NotificationTarget(BaseModel):
    scope: Literal["all", "department", "role", "user", "college"] = "all"
    department: Optional[str] = None
    role: Optional[str] = None
    user_id: Optional[PydanticObjectId] = None


class Notification(Document):
    college_id: Optional[PydanticObjectId] = None  # None for super_admin broadcasts
    target: NotificationTarget = Field(default_factory=NotificationTarget)
    title: str
    body: str
    
    # Notification type for categorization and icons
    type: Literal[
        "assignment",           # New assignment posted
        "attendance",          # Attendance updated
        "results",            # Results published
        "fee_reminder",       # Fee payment reminder
        "outpass",           # Outpass approved/rejected
        "hostel_room",       # Hostel room allocated
        "announcement",      # General announcement
        "broadcast",         # College-wide broadcast
        "placement",        # Placement drive notification
        "exam_schedule",    # Exam schedule published
        "timetable",       # Timetable updated
        "leave",          # Leave approved/rejected
        "event",         # Event notification
        "deadline",      # Deadline reminder
        "system",       # System notification
        "general"      # General notification
    ] = "general"
    
    # Priority level
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    
    # Event metadata for additional context
    event_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    # Example metadata:
    # - assignment_id, subject_id for assignments
    # - attendance_date for attendance
    # - result_id, exam_id for results
    # - outpass_id for outpass
    # - room_number for hostel_room
    
    # Action URL (optional) - for click-through navigation
    action_url: Optional[str] = None
    
    # Tracking
    created_by: Optional[PydanticObjectId] = None
    created_at: datetime = Field(default_factory=utcnow)
    read_by: list[PydanticObjectId] = Field(default_factory=list)
    
    # Delivery tracking for real-time notifications
    delivered_to: list[PydanticObjectId] = Field(default_factory=list)
    
    # Expiry (optional) - for time-sensitive notifications
    expires_at: Optional[datetime] = None

    class Settings:
        name = "notifications"
        indexes = [
            "college_id",
            "created_at",
            "type",
            "priority",
            [("college_id", 1), ("type", 1)],
            [("college_id", 1), ("created_at", -1)]
        ]
