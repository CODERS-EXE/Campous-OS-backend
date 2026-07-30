from typing import Annotated, List
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_tenant_college, get_tenant_scoped_user
from app.models.college import College
from app.models.timetable import TimetableEntry
from app.schemas.timetable import TimetableCreate, TimetableOut
from app.core.constants import UserRole
from app.models.user import User

router = APIRouter(prefix="/timetable", tags=["timetable"])


@router.post("", response_model=TimetableOut, status_code=201)
async def create_timetable_entry(
    body: TimetableCreate,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if user.role == UserRole.FACULTY.value and str(user.id) != body.faculty_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty cannot create timetable entries for another faculty")
    entry = TimetableEntry(
        college_id=college.id,
        faculty_id=PydanticObjectId(body.faculty_id),
        subject=body.subject,
        classroom=body.classroom,
        day_of_week=body.day_of_week,
        start_time=body.start_time,
        end_time=body.end_time,
        created_by=user.id,
    )
    await entry.insert()
    return TimetableOut(
        id=str(entry.id),
        faculty_id=str(entry.faculty_id),
        subject=entry.subject,
        classroom=entry.classroom,
        day_of_week=entry.day_of_week,
        start_time=entry.start_time,
        end_time=entry.end_time,
    )


@router.get("/faculty/{faculty_id}", response_model=List[TimetableOut])
async def get_faculty_timetable(faculty_id: str, user: Annotated[User, Depends(get_tenant_scoped_user)], college: Annotated[College, Depends(get_tenant_college)]):
    # faculty can fetch their own timetable; admins can fetch any
    if user.role == UserRole.FACULTY.value and str(user.id) != faculty_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    items = await TimetableEntry.find(TimetableEntry.college_id == college.id, TimetableEntry.faculty_id == PydanticObjectId(faculty_id)).sort(TimetableEntry.day_of_week).to_list()
    return [
        TimetableOut(
            id=str(e.id),
            faculty_id=str(e.faculty_id),
            subject=e.subject,
            classroom=e.classroom,
            day_of_week=e.day_of_week,
            start_time=e.start_time,
            end_time=e.end_time,
        )
        for e in items
    ]
