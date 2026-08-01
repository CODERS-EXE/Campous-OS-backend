from typing import Annotated, List
from beanie import PydanticObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.core.deps import get_tenant_college, get_tenant_scoped_user, require_roles
from app.models.college import College
from app.models.attendance import Attendance
from app.models.faculty import Faculty
from app.models.student import Student
from app.schemas.attendance import AttendanceCreate, AttendanceOut
from app.services.attendance import create_attendance, get_attendance_for_faculty, update_attendance, get_attendance_by_id
from app.core.constants import UserRole
from app.models.user import User
from beanie import PydanticObjectId
from fastapi import HTTPException, status
from app.services.notification_service import notify_attendance_marked

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.post("", response_model=AttendanceOut, status_code=201)
async def create_attendance_endpoint(
    body: AttendanceCreate,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    # Faculty, college admin, or super admin can create
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    # If faculty, validate mapping and subject
    faculty_doc = None
    if user.role == UserRole.FACULTY.value:
        faculty_doc = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == college.id)
        if not faculty_doc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty mapping not found")
        if not faculty_doc.subjects or body.subject not in faculty_doc.subjects:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subject for this faculty")
        # strict: no access if student_ids empty
        if not faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No students assigned to this faculty")

    # Validate each student in records: must exist in same college and be assigned to faculty
    validated_records = []
    for rec in body.records:
        sid = PydanticObjectId(rec.student_id)
        student = await Student.find_one(Student.user_id == sid, Student.college_id == college.id)
        if not student:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Student {rec.student_id} not found in this college")
        if user.role == UserRole.FACULTY.value and sid not in faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Student {rec.student_id} not assigned to this faculty")
        # attach marked_by as faculty user id
        validated_records.append({"student_id": sid, "status": rec.status, "marked_by": user.id if user.role == UserRole.FACULTY.value else None})

    att = await create_attendance(college.id, user.id, body.subject, body.date, body.session_name, validated_records)

    # Auto-notify each student about their attendance status
    date_str = str(body.date)
    for rec in validated_records:
        background_tasks.add_task(
            notify_attendance_marked,
            college_id=college.id,
            student_user_id=str(rec["student_id"]),
            subject=body.subject,
            date=date_str,
            status=rec["status"],
            created_by=user.id,
        )

    return AttendanceOut(
        id=str(att.id),
        faculty_id=str(att.faculty_id),
        subject=att.subject,
        date=att.date,
        session_name=att.session_name,
        records=[{"student_id": str(r.student_id), "status": r.status, "marked_by": str(r.marked_by) if r.marked_by else None} for r in att.records],
        created_at=att.created_at,
    )


@router.get("/mine", response_model=List[AttendanceOut])
async def my_attendance(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    if user.role not in (UserRole.FACULTY.value, UserRole.WARDEN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only faculty can access their attendance")
    items = await get_attendance_for_faculty(college.id, user.id)
    out = []
    for att in items:
        out.append(
            AttendanceOut(
                id=str(att.id),
                faculty_id=str(att.faculty_id),
                subject=att.subject,
                date=att.date,
                session_name=att.session_name,
                records=[{"student_id": str(r.student_id), "status": r.status, "marked_by": str(r.marked_by) if r.marked_by else None} for r in att.records],
                created_at=att.created_at,
            )
        )
    return out


@router.get("/student", response_model=List[AttendanceOut])
async def student_attendance(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Return all attendance sessions for logged-in student OR parent's children."""
    if user.role not in (UserRole.STUDENT.value, UserRole.PARENT.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students or parents can access this endpoint")
    
    # Determine which student IDs to fetch attendance for
    target_student_ids = []
    if user.role == UserRole.STUDENT.value:
        target_student_ids = [user.id]
    elif user.role == UserRole.PARENT.value:
        # Parent — fetch children IDs from profile
        if user.profile and hasattr(user.profile, 'student_ids') and user.profile.student_ids:
            target_student_ids = [PydanticObjectId(sid) for sid in user.profile.student_ids if PydanticObjectId.is_valid(sid)]
        if not target_student_ids:
            return []  # No children linked — return empty
    
    items = await Attendance.find(
        Attendance.college_id == college.id,
        {"records.student_id": {"$in": target_student_ids}},
    ).sort(-Attendance.date).to_list()
    
    out = []
    for att in items:
        out.append(
            AttendanceOut(
                id=str(att.id),
                faculty_id=str(att.faculty_id),
                subject=att.subject,
                date=att.date,
                session_name=att.session_name,
                records=[{"student_id": str(r.student_id), "status": r.status, "marked_by": str(r.marked_by) if r.marked_by else None} for r in att.records],
                created_at=att.created_at,
            )
        )
    return out


@router.patch("/{attendance_id}", response_model=AttendanceOut)
async def edit_attendance(
    attendance_id: str,
    body: AttendanceCreate,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    # Validate attendance exists and belongs to college
    att_doc = await get_attendance_by_id(PydanticObjectId(attendance_id))
    if not att_doc or att_doc.college_id != college.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance not found")

    # If faculty, validate mapping and subject
    faculty_doc = None
    if user.role == UserRole.FACULTY.value:
        faculty_doc = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == college.id)
        if not faculty_doc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty mapping not found")
        if not faculty_doc.subjects or body.subject not in faculty_doc.subjects:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subject for this faculty")
        if not faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No students assigned to this faculty")

    # Validate students
    validated_records = []
    for rec in body.records:
        sid = PydanticObjectId(rec.student_id)
        student = await Student.find_one(Student.user_id == sid, Student.college_id == college.id)
        if not student:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Student {rec.student_id} not found in this college")
        if user.role == UserRole.FACULTY.value and sid not in faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Student {rec.student_id} not assigned to this faculty")
        validated_records.append({"student_id": sid, "status": rec.status, "marked_by": user.id if user.role == UserRole.FACULTY.value else None})

    att = await update_attendance(PydanticObjectId(attendance_id), college.id, validated_records)
    if not att:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance not found")
    return AttendanceOut(
        id=str(att.id),
        faculty_id=str(att.faculty_id),
        subject=att.subject,
        date=att.date,
        session_name=att.session_name,
        records=[{"student_id": str(r.student_id), "status": r.status, "marked_by": str(r.marked_by) if r.marked_by else None} for r in att.records],
        created_at=att.created_at,
    )


@router.get("/{attendance_id}", response_model=AttendanceOut)
async def get_attendance(
    attendance_id: str,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    att = await get_attendance_by_id(PydanticObjectId(attendance_id))
    if not att or att.college_id != college.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance not found")
    return AttendanceOut(
        id=str(att.id),
        faculty_id=str(att.faculty_id),
        subject=att.subject,
        date=att.date,
        session_name=att.session_name,
        records=[{"student_id": str(r.student_id), "status": r.status, "marked_by": str(r.marked_by) if r.marked_by else None} for r in att.records],
        created_at=att.created_at,
    )
