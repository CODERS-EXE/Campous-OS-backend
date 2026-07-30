from datetime import datetime, timezone
from typing import Annotated, Optional

from beanie import PydanticObjectId
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.constants import UserRole
from app.core.security import decode_token
from app.models.college import College
from app.models.user import User

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(security)],
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = await User.get(PydanticObjectId(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


async def resolve_tenant(
    x_college_id: Annotated[Optional[str], Header(alias="X-College-Id")] = None,
    x_college_subdomain: Annotated[Optional[str], Header(alias="X-College-Subdomain")] = None,
) -> Optional[College]:
    if x_college_id:
        college = await College.get(PydanticObjectId(x_college_id))
        if college and college.status == "active":
            return college
    if x_college_subdomain:
        college = await College.find_one(College.subdomain == x_college_subdomain.lower())
        if college and college.status == "active":
            return college
    return None


async def get_tenant_college(
    college: Annotated[Optional[College], Depends(resolve_tenant)],
) -> College:
    if not college:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="College context required")
    return college


def require_roles(*roles: UserRole):
    allowed = {r.value for r in roles}

    async def checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return checker


async def get_tenant_scoped_user(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
) -> User:
    if user.role == UserRole.SUPER_ADMIN.value:
        return user
    if user.college_id != college.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-tenant access denied")
    return user


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
