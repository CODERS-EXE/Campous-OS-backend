"""
Notifications Router
Provides full CRUD, broadcast, filtering, pagination, search, and analytics.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.constants import UserRole
from app.core.deps import (
    get_current_user,
    get_tenant_college,
    get_tenant_scoped_user,
    require_roles,
    resolve_tenant,
)
from app.core.websocket_manager import manager
from app.models.college import College
from app.models.notification import Notification, NotificationTarget
from app.models.user import User
from app.schemas.notification import (
    NotificationBroadcast,
    NotificationCreate,
    NotificationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])

VALID_TYPES = {
    "assignment", "attendance", "results", "fee_reminder", "outpass",
    "hostel_room", "announcement", "broadcast", "placement", "exam_schedule",
    "timetable", "leave", "event", "deadline", "system", "general",
}

VALID_PRIORITIES = {"low", "normal", "high", "urgent"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_response(n: Notification, user_id: PydanticObjectId) -> NotificationResponse:
    return NotificationResponse(
        id=str(n.id),
        title=n.title,
        body=n.body,
        type=n.type,
        priority=n.priority,
        created_at=n.created_at,
        is_read=user_id in n.read_by,
        action_url=n.action_url,
        event_metadata=n.event_metadata,
    )


def _ws_payload(n: Notification) -> Dict[str, Any]:
    return {
        "id": str(n.id),
        "title": n.title,
        "body": n.body,
        "type": n.type,
        "priority": n.priority,
        "created_at": n.created_at.isoformat(),
        "action_url": n.action_url,
        "event_metadata": n.event_metadata,
    }


# ---------------------------------------------------------------------------
# GET /notifications – list with pagination, search, filters
# ---------------------------------------------------------------------------

@router.get("", response_model=List[NotificationResponse])
async def list_notifications(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[Optional[College], Depends(resolve_tenant)] = None,
    unread_only: bool = Query(False),
    notification_type: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """List notifications for current user with pagination, search, and filters."""
    # Super admin can see all notifications across colleges, others see only their college
    if user.role == UserRole.SUPER_ADMIN.value:
        query = Notification.find()
    else:
        if not college:
            raise HTTPException(status_code=400, detail="College context required")
        query = Notification.find(Notification.college_id == college.id)

    if notification_type and notification_type in VALID_TYPES:
        query = query.find(Notification.type == notification_type)

    if priority and priority in VALID_PRIORITIES:
        query = query.find(Notification.priority == priority)

    if from_date:
        query = query.find(Notification.created_at >= from_date)

    if to_date:
        query = query.find(Notification.created_at <= to_date)

    notifications = await query.sort(-Notification.created_at).skip(skip).limit(limit).to_list()

    result: List[NotificationResponse] = []
    for n in notifications:
        is_read = user.id in n.read_by
        if unread_only and is_read:
            continue
        # Basic search against title + body
        if search:
            term = search.lower()
            if term not in n.title.lower() and term not in n.body.lower():
                continue
        result.append(_to_response(n, user.id))

    return result


# ---------------------------------------------------------------------------
# GET /notifications/unread – unread list (shorthand, no pagination)
# ---------------------------------------------------------------------------

@router.get("/unread", response_model=List[NotificationResponse])
async def list_unread_notifications(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    limit: int = Query(20, ge=1, le=100),
):
    """Return only unread notifications for the current user."""
    notifications = (
        await Notification.find(Notification.college_id == college.id)
        .sort(-Notification.created_at)
        .limit(limit * 3)  # over-fetch to account for read filtering
        .to_list()
    )
    result = [_to_response(n, user.id) for n in notifications if user.id not in n.read_by]
    return result[:limit]


# ---------------------------------------------------------------------------
# GET /notifications/count – unread count
# ---------------------------------------------------------------------------

@router.get("/count")
async def get_notification_count(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Return total and unread notification counts."""
    all_notifs = await Notification.find(Notification.college_id == college.id).to_list()
    total = len(all_notifs)
    unread = sum(1 for n in all_notifs if user.id not in n.read_by)
    return {"total": total, "unread_count": unread}


# ---------------------------------------------------------------------------
# GET /notifications/unread/count – legacy compat endpoint
# ---------------------------------------------------------------------------

@router.get("/unread/count")
async def get_unread_count(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[Optional[College], Depends(resolve_tenant)] = None,
):
    """Get count of unread notifications (legacy compatible)."""
    # Super admin without college context gets 0
    if not college:
        return {"unread_count": 0}
    
    all_notifs = await Notification.find(Notification.college_id == college.id).to_list()
    unread_count = sum(1 for n in all_notifs if user.id not in n.read_by)
    return {"unread_count": unread_count}


# ---------------------------------------------------------------------------
# GET /notifications/history – full history with stats (admin)
# ---------------------------------------------------------------------------

@router.get("/history", response_model=List[NotificationResponse])
async def notification_history(
    user: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
    college_id_param: Optional[str] = Query(None, alias="college_id"),
    notification_type: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """Full notification history for admins with filters."""
    # Determine which college to scope to
    if user.role == UserRole.COLLEGE_ADMIN:
        cid = user.college_id
    elif college_id_param:
        cid = PydanticObjectId(college_id_param)
    else:
        cid = None  # super_admin sees all

    query = Notification.find()
    if cid:
        query = query.find(Notification.college_id == cid)
    if notification_type:
        query = query.find(Notification.type == notification_type)
    if priority:
        query = query.find(Notification.priority == priority)
    if from_date:
        query = query.find(Notification.created_at >= from_date)
    if to_date:
        query = query.find(Notification.created_at <= to_date)

    notifications = await query.sort(-Notification.created_at).skip(skip).limit(limit).to_list()
    return [_to_response(n, user.id) for n in notifications]


# ---------------------------------------------------------------------------
# GET /notifications/analytics – delivery analytics (admin)
# ---------------------------------------------------------------------------

@router.get("/analytics")
async def notification_analytics(
    user: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
    college_id_param: Optional[str] = Query(None, alias="college_id"),
):
    """
    Return notification delivery analytics:
    total sent, read counts, priority breakdown, type breakdown, role breakdown.
    """
    if user.role == UserRole.COLLEGE_ADMIN:
        cid = user.college_id
    elif college_id_param:
        cid = PydanticObjectId(college_id_param)
    else:
        cid = None

    query = Notification.find()
    if cid:
        query = query.find(Notification.college_id == cid)

    notifications = await query.to_list()

    total_sent = len(notifications)
    total_read = sum(1 for n in notifications if n.read_by)
    total_unread = total_sent - total_read

    type_breakdown: Dict[str, int] = {}
    priority_breakdown: Dict[str, int] = {}

    for n in notifications:
        type_breakdown[n.type] = type_breakdown.get(n.type, 0) + 1
        priority_breakdown[n.priority] = priority_breakdown.get(n.priority, 0) + 1

    return {
        "total_sent": total_sent,
        "total_read": total_read,
        "total_unread": total_unread,
        "read_rate": round((total_read / total_sent * 100) if total_sent else 0, 1),
        "type_breakdown": type_breakdown,
        "priority_breakdown": priority_breakdown,
        "active_connections": manager.get_connection_stats()["total_connections"],
    }


# ---------------------------------------------------------------------------
# POST /notifications – create + broadcast
# ---------------------------------------------------------------------------

@router.post("", response_model=NotificationResponse, status_code=201)
async def create_notification(
    body: NotificationCreate,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.FACULTY))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Create and broadcast a new notification (college_admin / faculty)."""
    notification = Notification(
        college_id=college.id,
        target=NotificationTarget(scope=body.target_scope, department=body.department, role=body.role),
        title=body.title,
        body=body.body,
        type=body.type,
        priority=body.priority,
        action_url=body.action_url,
        event_metadata=body.event_metadata or {},
        created_by=user.id,
    )
    await notification.insert()

    await manager.send_notification(
        notification_data=_ws_payload(notification),
        target_scope=body.target_scope,
        target_role=body.role,
        college_id=str(college.id),
    )

    logger.info("Notification created: %s by %s", notification.id, user.email)
    return _to_response(notification, user.id)


# ---------------------------------------------------------------------------
# POST /notifications/broadcast
# ---------------------------------------------------------------------------

@router.post("/broadcast", response_model=NotificationResponse, status_code=201)
async def broadcast_notification(
    body: NotificationBroadcast,
    user: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
):
    """Broadcast notification to multiple roles, one college, or the entire platform."""
    college_id: Optional[PydanticObjectId] = None
    if user.role == UserRole.COLLEGE_ADMIN:
        college_id = user.college_id
    elif user.role == UserRole.SUPER_ADMIN and body.college_id:
        college_id = PydanticObjectId(body.college_id)

    target_role = body.target_roles[0] if body.target_roles and len(body.target_roles) == 1 else None
    notification = Notification(
        college_id=college_id,
        target=NotificationTarget(scope=body.target_scope, role=target_role),
        title=body.title,
        body=body.body,
        type=body.type,
        priority=body.priority,
        action_url=body.action_url,
        event_metadata=body.event_metadata or {},
        created_by=user.id,
    )
    await notification.insert()

    payload = _ws_payload(notification)
    cid_str = str(college_id) if college_id else None

    if body.target_roles and len(body.target_roles) > 0:
        ws_msg = json.dumps({"type": "notification", "data": payload})
        await manager.broadcast_to_roles(message=ws_msg, roles=body.target_roles, college_id=cid_str)
    else:
        await manager.send_notification(
            notification_data=payload,
            target_scope=body.target_scope,
            college_id=cid_str,
        )

    logger.info("Broadcast created: %s by %s scope=%s", notification.id, user.email, body.target_scope)
    return _to_response(notification, user.id)


# ---------------------------------------------------------------------------
# PUT /notifications/read/{id}  (also keep POST compat)
# ---------------------------------------------------------------------------

@router.put("/read/{notification_id}")
async def put_mark_read(
    notification_id: str,
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[Optional[College], Depends(resolve_tenant)] = None,
):
    """Mark a single notification as read (PUT)."""
    n = await Notification.get(PydanticObjectId(notification_id))
    if not n:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    
    # Super admin can mark any notification, others must match college
    if user.role != UserRole.SUPER_ADMIN.value:
        if not college or n.college_id != college.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    
    if user.id not in n.read_by:
        n.read_by.append(user.id)
        await n.save()
    return {"ok": True}


@router.post("/{notification_id}/read")
async def post_mark_read(
    notification_id: str,
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[Optional[College], Depends(resolve_tenant)] = None,
):
    """Mark a single notification as read (POST – legacy compat)."""
    n = await Notification.get(PydanticObjectId(notification_id))
    if not n:
        return {"ok": False, "message": "Notification not found"}
    
    # Super admin can mark any notification, others must match college
    if user.role != UserRole.SUPER_ADMIN.value:
        if not college or n.college_id != college.id:
            return {"ok": False, "message": "Notification not found"}
    
    if user.id not in n.read_by:
        n.read_by.append(user.id)
        await n.save()
    return {"ok": True, "message": "Notification marked as read"}


# ---------------------------------------------------------------------------
# PUT /notifications/read-all
# ---------------------------------------------------------------------------

@router.put("/read-all")
async def put_mark_all_read(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[Optional[College], Depends(resolve_tenant)] = None,
):
    """Mark all notifications as read (PUT)."""
    # Super admin marks all across colleges, others only their college
    if user.role == UserRole.SUPER_ADMIN.value:
        notifications = await Notification.find().to_list()
    else:
        if not college:
            raise HTTPException(status_code=400, detail="College context required")
        notifications = await Notification.find(Notification.college_id == college.id).to_list()
    
    count = 0
    for n in notifications:
        if user.id not in n.read_by:
            n.read_by.append(user.id)
            await n.save()
            count += 1
    return {"ok": True, "count": count}


@router.post("/mark-all-read")
async def post_mark_all_read(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Mark all notifications as read (POST – legacy compat)."""
    notifications = await Notification.find(Notification.college_id == college.id).to_list()
    count = 0
    for n in notifications:
        if user.id not in n.read_by:
            n.read_by.append(user.id)
            await n.save()
            count += 1
    return {"ok": True, "message": f"Marked {count} notifications as read", "count": count}


# ---------------------------------------------------------------------------
# DELETE /notifications/{id}
# ---------------------------------------------------------------------------

@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    user: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
):
    """Delete a notification (admin only)."""
    n = await Notification.get(PydanticObjectId(notification_id))
    if not n:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if user.role == UserRole.COLLEGE_ADMIN and n.college_id != user.college_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-college access denied")
    await n.delete()
    logger.info("Notification deleted: %s by %s", notification_id, user.email)
    return {"ok": True, "message": "Notification deleted"}
