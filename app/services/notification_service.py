"""
Notification Service
Central helper for creating and pushing notifications across all modules.
Import and call `notify_*` helpers from any router to send real-time notifications.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from beanie import PydanticObjectId

from app.core.websocket_manager import manager
from app.models.notification import Notification, NotificationTarget

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Core send function
# ---------------------------------------------------------------------------

async def send_notification(
    *,
    college_id: Optional[PydanticObjectId],
    title: str,
    body: str,
    notification_type: str = "general",
    priority: str = "normal",
    target_scope: str = "all",
    target_role: Optional[str] = None,
    target_user_id: Optional[str] = None,
    action_url: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    created_by: Optional[PydanticObjectId] = None,
) -> Notification:
    """
    Create a Notification document and push it via WebSocket.
    Returns the saved Notification for reference.
    """
    notification = Notification(
        college_id=college_id,
        target=NotificationTarget(
            scope=target_scope,
            role=target_role,
        ),
        title=title,
        body=body,
        type=notification_type,
        priority=priority,
        action_url=action_url,
        event_metadata=metadata or {},
        created_by=created_by,
        created_at=_utcnow(),
    )
    await notification.insert()

    # Build WS payload
    ws_data: Dict[str, Any] = {
        "id": str(notification.id),
        "title": notification.title,
        "body": notification.body,
        "type": notification.type,
        "priority": notification.priority,
        "created_at": notification.created_at.isoformat(),
        "action_url": notification.action_url,
        "event_metadata": notification.event_metadata,
    }

    await manager.send_notification(
        notification_data=ws_data,
        target_scope=target_scope,
        target_role=target_role,
        target_user_id=target_user_id,
        college_id=str(college_id) if college_id else None,
    )

    logger.info(
        "Notification sent: type=%s scope=%s college=%s",
        notification_type,
        target_scope,
        college_id,
    )
    return notification


# ---------------------------------------------------------------------------
# Auto-trigger helpers – one per domain event
# ---------------------------------------------------------------------------

async def notify_assignment_created(
    college_id: PydanticObjectId,
    assignment_title: str,
    subject: str,
    due_date: str,
    assignment_id: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify students when a new assignment is posted."""
    await send_notification(
        college_id=college_id,
        title=f"New Assignment: {assignment_title}",
        body=f"A new assignment for {subject} has been posted. Due: {due_date}",
        notification_type="assignment",
        priority="normal",
        target_scope="role",
        target_role="student",
        action_url="/student/assignments",
        metadata={"assignment_id": assignment_id, "subject": subject},
        created_by=created_by,
    )


async def notify_attendance_marked(
    college_id: PydanticObjectId,
    student_user_id: str,
    subject: str,
    date: str,
    status: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify a student when their attendance is marked."""
    emoji = "✅" if status == "present" else "❌"
    await send_notification(
        college_id=college_id,
        title=f"{emoji} Attendance Marked",
        body=f"Your attendance for {subject} on {date} has been marked as {status}.",
        notification_type="attendance",
        priority="low",
        target_scope="user",
        target_user_id=student_user_id,
        action_url="/student/attendance",
        metadata={"subject": subject, "date": date, "status": status},
        created_by=created_by,
    )


async def notify_exam_scheduled(
    college_id: PydanticObjectId,
    exam_name: str,
    start_date: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify all students and faculty when an exam is scheduled."""
    for role in ("student", "faculty"):
        await send_notification(
            college_id=college_id,
            title=f"Exam Scheduled: {exam_name}",
            body=f"The exam '{exam_name}' is scheduled starting {start_date}. Check the timetable.",
            notification_type="exam_schedule",
            priority="high",
            target_scope="role",
            target_role=role,
            action_url="/student/hall-ticket" if role == "student" else "/faculty/exams",
            metadata={"exam_name": exam_name, "start_date": start_date},
            created_by=created_by,
        )


async def notify_results_published(
    college_id: PydanticObjectId,
    exam_name: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify students and parents when exam results are published."""
    for role in ("student", "parent"):
        await send_notification(
            college_id=college_id,
            title="📊 Results Published",
            body=f"Results for '{exam_name}' are now available. Click to view your scorecard.",
            notification_type="results",
            priority="high",
            target_scope="role",
            target_role=role,
            action_url="/student/exam-results" if role == "student" else "/parent/exam-results",
            metadata={"exam_name": exam_name},
            created_by=created_by,
        )


async def notify_fee_generated(
    college_id: PydanticObjectId,
    student_user_id: str,
    amount: float,
    due_date: str,
    student_fee_id: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify student + parent when a fee is assigned."""
    msg = f"A fee of ₹{amount:.2f} has been generated. Due by {due_date}."
    await send_notification(
        college_id=college_id,
        title="💰 Fee Generated",
        body=msg,
        notification_type="fee_reminder",
        priority="high",
        target_scope="user",
        target_user_id=student_user_id,
        action_url="/student/fees",
        metadata={"student_fee_id": student_fee_id, "amount": amount, "due_date": due_date},
        created_by=created_by,
    )


async def notify_fee_paid(
    college_id: PydanticObjectId,
    student_user_id: str,
    amount: float,
    transaction_id: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify student when a fee payment is confirmed."""
    await send_notification(
        college_id=college_id,
        title="✅ Payment Confirmed",
        body=f"Your payment of ₹{amount:.2f} (Txn: {transaction_id}) has been confirmed.",
        notification_type="fee_reminder",
        priority="normal",
        target_scope="user",
        target_user_id=student_user_id,
        action_url="/student/fees",
        metadata={"amount": amount, "transaction_id": transaction_id},
        created_by=created_by,
    )


async def notify_book_issued(
    college_id: PydanticObjectId,
    user_id: str,
    book_title: str,
    due_date: str,
    issue_id: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify user when a library book is issued."""
    await send_notification(
        college_id=college_id,
        title="📚 Book Issued",
        body=f"'{book_title}' has been issued to you. Return by {due_date}.",
        notification_type="general",
        priority="low",
        target_scope="user",
        target_user_id=user_id,
        action_url="/student/library",
        metadata={"issue_id": issue_id, "book_title": book_title, "due_date": due_date},
        created_by=created_by,
    )


async def notify_book_overdue(
    college_id: PydanticObjectId,
    user_id: str,
    book_title: str,
    overdue_days: int,
    fine_amount: float,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify user about overdue book and fine."""
    await send_notification(
        college_id=college_id,
        title="⚠️ Library Book Overdue",
        body=f"'{book_title}' is {overdue_days} day(s) overdue. Fine accrued: ₹{fine_amount:.2f}.",
        notification_type="deadline",
        priority="high",
        target_scope="user",
        target_user_id=user_id,
        action_url="/student/library",
        metadata={"book_title": book_title, "overdue_days": overdue_days, "fine": fine_amount},
        created_by=created_by,
    )


async def notify_placement_drive_created(
    college_id: PydanticObjectId,
    company_name: str,
    role_name: str,
    deadline: str,
    drive_id: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify students when a new placement drive is created."""
    await send_notification(
        college_id=college_id,
        title=f"💼 New Placement Drive: {company_name}",
        body=f"{company_name} is hiring for '{role_name}'. Apply before {deadline}.",
        notification_type="placement",
        priority="high",
        target_scope="role",
        target_role="student",
        action_url="/student/placements",
        metadata={"drive_id": drive_id, "company": company_name, "role": role_name, "deadline": deadline},
        created_by=created_by,
    )


async def notify_placement_selected(
    college_id: PydanticObjectId,
    student_user_id: str,
    company_name: str,
    role_name: str,
    application_id: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify student when selected in a placement drive."""
    await send_notification(
        college_id=college_id,
        title=f"🎉 Congratulations! Selected at {company_name}",
        body=f"You have been selected for '{role_name}' at {company_name}. Check your placement portal.",
        notification_type="placement",
        priority="high",
        target_scope="user",
        target_user_id=student_user_id,
        action_url="/student/placement-applications",
        metadata={"application_id": application_id, "company": company_name, "role": role_name},
        created_by=created_by,
    )


async def notify_outpass_approved(
    college_id: PydanticObjectId,
    student_user_id: str,
    from_date: str,
    to_date: str,
    outpass_id: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify student when their outpass request is approved."""
    await send_notification(
        college_id=college_id,
        title="✅ Outpass Approved",
        body=f"Your outpass from {from_date} to {to_date} has been approved.",
        notification_type="outpass",
        priority="normal",
        target_scope="user",
        target_user_id=student_user_id,
        action_url="/student/hostel",
        metadata={"outpass_id": outpass_id, "from_date": from_date, "to_date": to_date},
        created_by=created_by,
    )


async def notify_outpass_rejected(
    college_id: PydanticObjectId,
    student_user_id: str,
    reason: str,
    outpass_id: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify student when their outpass request is rejected."""
    await send_notification(
        college_id=college_id,
        title="❌ Outpass Rejected",
        body=f"Your outpass request has been rejected. Reason: {reason}",
        notification_type="outpass",
        priority="normal",
        target_scope="user",
        target_user_id=student_user_id,
        action_url="/student/hostel",
        metadata={"outpass_id": outpass_id, "reason": reason},
        created_by=created_by,
    )


async def notify_room_changed(
    college_id: PydanticObjectId,
    student_user_id: str,
    new_room: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Notify student when their hostel room is changed."""
    await send_notification(
        college_id=college_id,
        title="🏠 Room Allocation Changed",
        body=f"Your hostel room has been changed to {new_room}.",
        notification_type="hostel_room",
        priority="normal",
        target_scope="user",
        target_user_id=student_user_id,
        action_url="/student/hostel",
        metadata={"new_room": new_room},
        created_by=created_by,
    )


async def notify_emergency(
    college_id: Optional[PydanticObjectId],
    title: str,
    body: str,
    created_by: Optional[PydanticObjectId] = None,
) -> None:
    """Broadcast emergency alert to entire college (or all if college_id is None)."""
    scope = "college" if college_id else "all"
    await send_notification(
        college_id=college_id,
        title=f"🚨 EMERGENCY: {title}",
        body=body,
        notification_type="broadcast",
        priority="urgent",
        target_scope=scope,
        metadata={"alert_type": "emergency"},
        created_by=created_by,
    )
