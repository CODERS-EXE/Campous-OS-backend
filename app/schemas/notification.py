from datetime import datetime
from typing import Literal, Optional, List, Dict, Any

from pydantic import BaseModel, Field


class NotificationCreate(BaseModel):
    title: str
    body: str
    type: Literal[
        "assignment", "attendance", "results", "fee_reminder", "outpass",
        "hostel_room", "announcement", "broadcast", "placement", "exam_schedule",
        "timetable", "leave", "event", "deadline", "system", "general"
    ] = "general"
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    target_scope: Literal["all", "department", "role", "user"] = "all"
    department: Optional[str] = None
    role: Optional[str] = None
    action_url: Optional[str] = None
    event_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class NotificationBroadcast(BaseModel):
    """Schema for broadcasting notifications to multiple roles or entire college/platform"""
    title: str
    body: str
    type: Literal[
        "assignment", "attendance", "results", "fee_reminder", "outpass",
        "hostel_room", "announcement", "broadcast", "placement", "exam_schedule",
        "timetable", "leave", "event", "deadline", "system", "general"
    ] = "broadcast"
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    target_scope: Literal["all", "college", "role"] = "all"
    target_roles: Optional[List[str]] = Field(default_factory=list)  # For multi-role broadcast
    college_id: Optional[str] = None  # For super_admin to target specific college
    action_url: Optional[str] = None
    event_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class NotificationResponse(BaseModel):
    id: str
    title: str
    body: str
    type: str = "general"
    priority: str
    created_at: datetime
    is_read: bool = False
    action_url: Optional[str] = None
    event_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
