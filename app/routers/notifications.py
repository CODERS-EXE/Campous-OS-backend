from typing import Annotated, List, Optional
import logging

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.constants import UserRole
from app.core.deps import get_tenant_college, get_tenant_scoped_user, require_roles
from app.core.websocket_manager import manager
from app.models.college import College
from app.models.notification import Notification, NotificationTarget
from app.models.user import User
from app.schemas.notification import NotificationCreate, NotificationResponse, NotificationBroadcast

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=List[NotificationResponse])
async def list_notifications(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    unread_only: bool = False,
    notification_type: Optional[str] = None,
    limit: int = 50,
):
    """List notifications for current user with optional filters"""
    query = Notification.find(Notification.college_id == college.id)
    
    # Filter by type if specified
    if notification_type:
        query = query.find(Notification.type == notification_type)
    
    notifications = await query.sort(-Notification.created_at).limit(limit).to_list()
    
    result = []
    for n in notifications:
        is_read = user.id in n.read_by
        
        # Skip if filtering for unread only
        if unread_only and is_read:
            continue
        
        result.append(
            NotificationResponse(
                id=str(n.id),
                title=n.title,
                body=n.body,
                type=n.type,
                priority=n.priority,
                created_at=n.created_at,
                is_read=is_read,
                action_url=n.action_url,
                event_metadata=n.event_metadata,
            )
        )
    
    return result


@router.get("/unread/count")
async def get_unread_count(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Get count of unread notifications for current user"""
    all_notifications = await Notification.find(
        Notification.college_id == college.id
    ).to_list()
    
    unread_count = sum(1 for n in all_notifications if user.id not in n.read_by)
    
    return {"unread_count": unread_count}


@router.post("", response_model=NotificationResponse, status_code=201)
async def create_notification(
    body: NotificationCreate,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.FACULTY))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Create and broadcast a new notification"""
    notification = Notification(
        college_id=college.id,
        target=NotificationTarget(
            scope=body.target_scope,
            department=body.department,
            role=body.role,
        ),
        title=body.title,
        body=body.body,
        type=body.type if hasattr(body, 'type') else "general",
        priority=body.priority,
        action_url=body.action_url if hasattr(body, 'action_url') else None,
        event_metadata=body.event_metadata if hasattr(body, 'event_metadata') else {},
        created_by=user.id,
    )
    await notification.insert()
    
    # Broadcast via WebSocket
    notification_data = {
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
        notification_data=notification_data,
        target_scope=body.target_scope,
        target_role=body.role,
        college_id=str(college.id)
    )
    
    logger.info(f"Notification created and broadcast: {notification.id} by {user.email}")
    
    return NotificationResponse(
        id=str(notification.id),
        title=notification.title,
        body=notification.body,
        type=notification.type,
        priority=notification.priority,
        created_at=notification.created_at,
        is_read=False,
        action_url=notification.action_url,
        event_metadata=notification.event_metadata,
    )


@router.post("/broadcast", response_model=NotificationResponse, status_code=201)
async def broadcast_notification(
    body: NotificationBroadcast,
    user: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
):
    """
    Broadcast notification to multiple roles or entire college/platform
    Super Admin: can broadcast platform-wide
    College Admin: can broadcast within their college
    """
    # Determine college_id based on user role
    college_id = None
    if user.role == UserRole.COLLEGE_ADMIN:
        college_id = user.college_id
    elif user.role == UserRole.SUPER_ADMIN and body.college_id:
        college_id = PydanticObjectId(body.college_id)
    
    # Create notification
    notification = Notification(
        college_id=college_id,
        target=NotificationTarget(
            scope=body.target_scope,
            role=body.target_roles[0] if body.target_roles and len(body.target_roles) == 1 else None,
        ),
        title=body.title,
        body=body.body,
        type=body.type,
        priority=body.priority,
        action_url=body.action_url,
        event_metadata=body.event_metadata or {},
        created_by=user.id,
    )
    await notification.insert()
    
    # Prepare notification data for WebSocket
    notification_data = {
        "id": str(notification.id),
        "title": notification.title,
        "body": notification.body,
        "type": notification.type,
        "priority": notification.priority,
        "created_at": notification.created_at.isoformat(),
        "action_url": notification.action_url,
        "event_metadata": notification.event_metadata,
    }
    
    # Broadcast to multiple roles if specified
    if body.target_roles and len(body.target_roles) > 0:
        await manager.broadcast_to_roles(
            message=f'{{"type": "notification", "data": {notification_data}}}',
            roles=body.target_roles,
            college_id=str(college_id) if college_id else None
        )
    else:
        # Broadcast to all
        await manager.send_notification(
            notification_data=notification_data,
            target_scope=body.target_scope,
            college_id=str(college_id) if college_id else None
        )
    
    logger.info(f"Broadcast notification created: {notification.id} by {user.email}, scope={body.target_scope}")
    
    return NotificationResponse(
        id=str(notification.id),
        title=notification.title,
        body=notification.body,
        type=notification.type,
        priority=notification.priority,
        created_at=notification.created_at,
        is_read=False,
        action_url=notification.action_url,
        event_metadata=notification.event_metadata,
    )


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Mark a single notification as read"""
    notification = await Notification.get(PydanticObjectId(notification_id))
    if not notification or notification.college_id != college.id:
        return {"ok": False, "message": "Notification not found"}
    if user.id not in notification.read_by:
        notification.read_by.append(user.id)
        await notification.save()
    return {"ok": True, "message": "Notification marked as read"}


@router.post("/mark-all-read")
async def mark_all_read(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Mark all notifications as read for current user"""
    notifications = await Notification.find(
        Notification.college_id == college.id
    ).to_list()
    
    updated_count = 0
    for notification in notifications:
        if user.id not in notification.read_by:
            notification.read_by.append(user.id)
            await notification.save()
            updated_count += 1
    
    return {
        "ok": True,
        "message": f"Marked {updated_count} notifications as read",
        "count": updated_count
    }


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    user: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.COLLEGE_ADMIN))],
):
    """Delete a notification (admin only)"""
    notification = await Notification.get(PydanticObjectId(notification_id))
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found"
        )
    
    # College admin can only delete notifications from their college
    if user.role == UserRole.COLLEGE_ADMIN and notification.college_id != user.college_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete notifications from other colleges"
        )
    
    await notification.delete()
    logger.info(f"Notification deleted: {notification_id} by {user.email}")
    
    return {"ok": True, "message": "Notification deleted successfully"}
