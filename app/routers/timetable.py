from typing import Annotated, List, Optional
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import get_tenant_college, get_tenant_scoped_user, require_roles
from app.models.college import College
from app.models.faculty import Faculty
from app.models.timetable import TimetableEntry
from app.schemas.timetable import TimetableCreate, TimetableOut, TimetableUpdate
from app.core.constants import UserRole
from app.models.user import User

router = APIRouter(prefix="/timetable", tags=["timetable"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_out(e: TimetableEntry) -> TimetableOut:
    return TimetableOut(
        id=str(e.id),
        faculty_id=str(e.faculty_id),
        subject=e.subject,
        classroom=e.classroom,
        day_of_week=e.day_of_week,
        start_time=e.start_time,
        end_time=e.end_time,
        college_id=str(e.college_id),
        created_at=e.created_at.isoformat(),
    )


async def _check_conflicts(
    college_id: PydanticObjectId,
    faculty_id: PydanticObjectId,
    day_of_week: int,
    start_time,
    end_time,
    classroom: Optional[str],
    exclude_id: Optional[PydanticObjectId] = None,
):
    """
    Detect faculty and classroom conflicts.
    Conflict = two entries on the same day whose time windows overlap.
    """
    existing = await TimetableEntry.find(
        TimetableEntry.college_id == college_id,
        TimetableEntry.day_of_week == day_of_week,
    ).to_list()

    for e in existing:
        if exclude_id and e.id == exclude_id:
            continue
        # Time overlap: (s1 < e2) AND (s2 < e1) — works for "HH:MM" strings
        if e.start_time < end_time and start_time < e.end_time:
            if e.faculty_id == faculty_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Faculty already has a session at this time on {['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][day_of_week]} ({e.start_time}–{e.end_time} for {e.subject})",
                )
            if classroom and e.classroom and e.classroom.strip().lower() == classroom.strip().lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Classroom '{classroom}' is already occupied at this time ({e.start_time}–{e.end_time})",
                )


# ── Create ──────────────────────────────────────────────────────────────────────

@router.post("", response_model=TimetableOut, status_code=201)
async def create_timetable_entry(
    body: TimetableCreate,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if user.role == UserRole.FACULTY.value and str(user.id) != body.faculty_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty cannot create entries for another faculty")

    faculty_oid = PydanticObjectId(body.faculty_id)

    if body.start_time >= body.end_time:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start_time must be before end_time")
    if body.day_of_week not in range(7):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="day_of_week must be 0–6")

    await _check_conflicts(college.id, faculty_oid, body.day_of_week, body.start_time, body.end_time, body.classroom)

    entry = TimetableEntry(
        college_id=college.id,
        faculty_id=faculty_oid,
        subject=body.subject,
        classroom=body.classroom,
        day_of_week=body.day_of_week,
        start_time=body.start_time,
        end_time=body.end_time,
        created_by=user.id,
    )
    await entry.insert()
    return _to_out(entry)


# ── Update ──────────────────────────────────────────────────────────────────────

@router.patch("/{entry_id}", response_model=TimetableOut)
async def update_timetable_entry(
    entry_id: str,
    body: TimetableUpdate,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    entry = await TimetableEntry.get(PydanticObjectId(entry_id))
    if not entry or entry.college_id != college.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timetable entry not found")

    if user.role == UserRole.FACULTY.value and entry.faculty_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only edit your own timetable entries")

    # Apply updates
    if body.subject is not None:
        entry.subject = body.subject
    if body.classroom is not None:
        entry.classroom = body.classroom
    if body.day_of_week is not None:
        if body.day_of_week not in range(7):
            raise HTTPException(status_code=400, detail="day_of_week must be 0–6")
        entry.day_of_week = body.day_of_week
    if body.start_time is not None:
        entry.start_time = body.start_time
    if body.end_time is not None:
        entry.end_time = body.end_time

    if entry.start_time >= entry.end_time:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")

    await _check_conflicts(
        college.id, entry.faculty_id, entry.day_of_week,
        entry.start_time, entry.end_time, entry.classroom,
        exclude_id=entry.id,
    )

    from datetime import datetime, timezone
    entry.updated_at = datetime.now(timezone.utc)
    await entry.save()
    return _to_out(entry)


# ── Delete ──────────────────────────────────────────────────────────────────────

@router.delete("/{entry_id}")
async def delete_timetable_entry(
    entry_id: str,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    entry = await TimetableEntry.get(PydanticObjectId(entry_id))
    if not entry or entry.college_id != college.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Timetable entry not found")

    if user.role == UserRole.FACULTY.value and entry.faculty_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own timetable entries")

    await entry.delete()
    return {"ok": True, "message": "Timetable entry deleted"}


# ── Faculty timetable ─────────────────────────────────────────────────────────

@router.get("/faculty/{faculty_user_id}", response_model=List[TimetableOut])
async def get_faculty_timetable(
    faculty_user_id: str,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Get timetable for a specific faculty by their user_id"""
    if user.role == UserRole.FACULTY.value and str(user.id) != faculty_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    
    # Find faculty profile by user_id
    faculty = await Faculty.find_one(
        Faculty.user_id == PydanticObjectId(faculty_user_id),
        Faculty.college_id == college.id
    )
    if not faculty:
        return []  # No faculty profile found
    
    # Get timetable entries for this faculty (faculty_id stores user_id)
    items = await TimetableEntry.find(
        TimetableEntry.college_id == college.id,
        TimetableEntry.faculty_id == PydanticObjectId(faculty_user_id),
    ).sort(TimetableEntry.day_of_week).to_list()
    return [_to_out(e) for e in items]


# ── Student / Parent timetable ────────────────────────────────────────────────

@router.get("/student", response_model=List[TimetableOut])
async def get_student_timetable(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    child_user_id: Optional[str] = Query(default=None, description="Parent: specify child user_id"),
):
    """
    Student  → entries for their department (year/semester scoped via faculty mapping).
    Parent   → entries for specified child (must be a linked child).
    Admin    → all entries for the college.
    """
    from app.models.student import Student as StudentModel
    from app.models.faculty import Faculty

    allowed = (
        UserRole.STUDENT.value, UserRole.PARENT.value,
        UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value,
    )
    if user.role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    if user.role == UserRole.STUDENT.value:
        # Fetch this student's profile to get department/year/semester
        student = await StudentModel.find_one(
            StudentModel.user_id == user.id,
            StudentModel.college_id == college.id,
        )
        if not student:
            return []

        # Find faculty assigned to this student or in the same dept+year+semester
        dept_faculty = await Faculty.find(
            Faculty.college_id == college.id,
            Faculty.department == student.department,
        ).to_list()

        # Further narrow: faculty whose year/semester match (if set on faculty)
        filtered_faculty = []
        for f in dept_faculty:
            year_ok = (f.year is None or f.year == student.year)
            sem_ok  = (f.semester is None or f.semester == student.semester)
            if year_ok and sem_ok:
                filtered_faculty.append(f)

        faculty_ids = [f.user_id for f in filtered_faculty]
        if not faculty_ids:
            return []

        items = await TimetableEntry.find(
            TimetableEntry.college_id == college.id,
            {"faculty_id": {"$in": faculty_ids}},
        ).sort(TimetableEntry.day_of_week).to_list()

    elif user.role == UserRole.PARENT.value:
        # Parent must supply child_user_id and it must be a linked child
        linked_ids = [str(cid) for cid in (user.profile.student_ids or [])]

        if child_user_id:
            if child_user_id not in linked_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorised to view this child's timetable",
                )
            target_uid = PydanticObjectId(child_user_id)
        elif linked_ids:
            target_uid = PydanticObjectId(linked_ids[0])
        else:
            return []

        child_student = await StudentModel.find_one(
            StudentModel.user_id == target_uid,
            StudentModel.college_id == college.id,
        )
        if not child_student:
            return []

        dept_faculty = await Faculty.find(
            Faculty.college_id == college.id,
            Faculty.department == child_student.department,
        ).to_list()

        filtered_faculty = []
        for f in dept_faculty:
            year_ok = (f.year is None or f.year == child_student.year)
            sem_ok  = (f.semester is None or f.semester == child_student.semester)
            if year_ok and sem_ok:
                filtered_faculty.append(f)

        faculty_ids = [f.user_id for f in filtered_faculty]
        if not faculty_ids:
            return []

        items = await TimetableEntry.find(
            TimetableEntry.college_id == college.id,
            {"faculty_id": {"$in": faculty_ids}},
        ).sort(TimetableEntry.day_of_week).to_list()

    else:
        # Admin: all entries for the college
        items = await TimetableEntry.find(
            TimetableEntry.college_id == college.id
        ).sort(TimetableEntry.day_of_week).to_list()

    return [_to_out(e) for e in items]


# ── Admin: all entries (with optional filters) ────────────────────────────────

@router.get("", response_model=List[TimetableOut])
async def list_all_timetable(
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
    faculty_user_id: Optional[str] = None,
    day_of_week: Optional[int] = None,
):
    filters = [TimetableEntry.college_id == college.id]
    if faculty_user_id:
        filters.append(TimetableEntry.faculty_id == PydanticObjectId(faculty_user_id))
    if day_of_week is not None:
        filters.append(TimetableEntry.day_of_week == day_of_week)
    items = await TimetableEntry.find(*filters).sort(TimetableEntry.day_of_week).to_list()
    return [_to_out(e) for e in items]
