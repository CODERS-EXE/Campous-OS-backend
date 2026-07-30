from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.constants import UserRole
from app.core.deps import get_current_user, require_roles, utcnow
from app.models.college import College
from app.models.user import User
from app.schemas.college import CollegeCreate, CollegeResponse, CollegeUpdate
from app.services.users import create_college_with_admin

router = APIRouter(prefix="/colleges", tags=["colleges"])


def _to_response(college: College) -> CollegeResponse:
    return CollegeResponse(
        id=str(college.id),
        name=college.name,
        subdomain=college.subdomain,
        logo_url=college.logo_url,
        theme_color=college.theme_color,
        plan=college.plan,
        status=college.status,
        created_at=college.created_at,
    )


@router.get("/resolve/{subdomain}", response_model=CollegeResponse)
async def resolve_college(subdomain: str):
    college = await College.find_one(College.subdomain == subdomain.lower())
    if not college or college.status != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="College not found")
    return _to_response(college)


@router.get("", response_model=List[CollegeResponse])
async def list_colleges(_: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN))]):
    colleges = await College.find_all().sort(-College.created_at).to_list()
    return [_to_response(c) for c in colleges]


@router.post("", response_model=CollegeResponse, status_code=status.HTTP_201_CREATED)
async def onboard_college(
    body: CollegeCreate,
    _: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN))],
):
    try:
        college, _ = await create_college_with_admin(
            name=body.name,
            subdomain=body.subdomain,
            theme_color=body.theme_color,
            plan=body.plan.value,
            admin_name=body.admin_name,
            admin_email=body.admin_email,
            admin_password=body.admin_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_response(college)


@router.patch("/{college_id}", response_model=CollegeResponse)
async def update_college(
    college_id: str,
    body: CollegeUpdate,
    _: Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN))],
):
    college = await College.get(college_id)
    if not college:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="College not found")

    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(college, key, value.value if hasattr(value, "value") else value)
    college.updated_at = utcnow()
    await college.save()
    return _to_response(college)
