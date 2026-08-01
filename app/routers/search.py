from typing import Annotated, List
from fastapi import APIRouter, Depends, Query

from app.core.deps import get_current_user
from app.core.constants import UserRole
from app.models.user import User
from app.models.college import College
from app.models.notification import Notification

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def global_search(
    q: str = Query(..., min_length=2, max_length=100),
    user: Annotated[User, Depends(get_current_user)] = None,
):
    """Global search across colleges, users, and notifications (super admin only for now)"""
    
    results = []
    query = q.strip().lower()
    
    # For super admin — search across all colleges
    if user.role == UserRole.SUPER_ADMIN.value:
        # Search colleges
        colleges = await College.find().to_list()
        for college in colleges:
            if query in college.name.lower() or query in college.subdomain.lower():
                results.append({
                    "id": str(college.id),
                    "type": "college",
                    "title": college.name,
                    "subtitle": f"{college.subdomain}.campusos.local",
                    "url": f"/super-admin/colleges"
                })
        
        # Search notifications
        notifications = await Notification.find().sort(-Notification.created_at).limit(50).to_list()
        for notif in notifications:
            if query in notif.title.lower() or query in notif.body.lower():
                results.append({
                    "id": str(notif.id),
                    "type": "notification",
                    "title": notif.title,
                    "subtitle": notif.body[:60] + ("..." if len(notif.body) > 60 else ""),
                    "url": f"/super-admin/notifications"
                })
        
        # Limit results
        results = results[:10]
    
    else:
        # For college users — search within their college (future enhancement)
        # For now, return empty for non-super-admin
        pass
    
    return results
