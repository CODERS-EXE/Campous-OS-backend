from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.constants import UserRole
from app.core.deps import get_current_user, resolve_tenant
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from beanie import PydanticObjectId

from app.models.college import College
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.users import register_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        name=user.name,
        email=user.email,
        role=user.role,
        college_id=str(user.college_id) if user.college_id else None,
        profile=user.profile.model_dump(),
        is_verified=user.is_verified,
    )


def _college_response(college: College) -> dict:
    return {
        "id": str(college.id),
        "name": college.name,
        "subdomain": college.subdomain,
        "logo_url": college.logo_url,
        "theme_color": college.theme_color,
        "plan": college.plan,
        "status": college.status,
    }


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest):
    user = await User.find_one(User.email == body.email.lower())
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    college: Optional[College] = None
    if user.role != UserRole.SUPER_ADMIN.value:
        if not user.college_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User has no college")
        college = await College.get(user.college_id)
        if not college or college.status != "active":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="College inactive or not found")
        if body.college_subdomain and college.subdomain != body.college_subdomain.lower():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="College mismatch")

    tokens = TokenResponse(
        access_token=create_access_token({"sub": str(user.id), "role": user.role}),
        refresh_token=create_refresh_token({"sub": str(user.id)}),
    )
    return AuthResponse(
        tokens=tokens,
        user=_user_response(user),
        college=_college_response(college) if college else None,
    )


@router.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest):
    college = await College.find_one(College.subdomain == body.college_subdomain.lower())
    if not college or college.status != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="College not found")

    if body.role not in {UserRole.STUDENT.value, UserRole.FACULTY.value, UserRole.PARENT.value}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role for self-registration")

    try:
        user = await register_user(
            name=body.name,
            email=body.email,
            password=body.password,
            role=body.role,
            college=college,
            roll_no=body.roll_no,
            department=body.department,
            year=body.year,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    tokens = TokenResponse(
        access_token=create_access_token({"sub": str(user.id), "role": user.role}),
        refresh_token=create_refresh_token({"sub": str(user.id)}),
    )
    return AuthResponse(
        tokens=tokens,
        user=_user_response(user),
        college=_college_response(college),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest):
    try:
        payload = decode_token(body.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        user_id = payload.get("sub")
        user = await User.get(PydanticObjectId(user_id))
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return TokenResponse(
        access_token=create_access_token({"sub": str(user.id), "role": user.role}),
        refresh_token=create_refresh_token({"sub": str(user.id)}),
    )


@router.get("/me", response_model=UserResponse)
async def me(user: Annotated[User, Depends(get_current_user)]):
    return _user_response(user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: dict,
    user: Annotated[User, Depends(get_current_user)],
):
    """Update own name. Available to all authenticated users."""
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name cannot be empty")
    user.name = name
    await user.save()
    return _user_response(user)


@router.post("/change-password")
async def change_password(
    body: dict,
    user: Annotated[User, Depends(get_current_user)],
):
    """Change own password. Requires current_password + new_password."""
    current_password = body.get("current_password", "")
    new_password = body.get("new_password", "")

    if not current_password or not new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Both current and new password are required")

    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

    if len(new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 8 characters")

    user.password_hash = hash_password(new_password)
    await user.save()
    return {"ok": True, "message": "Password changed successfully"}
