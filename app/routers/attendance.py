from typing import Annotated, List, Optional
from datetime import datetime
from beanie import PydanticObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.core.deps import get_tenant_college, get_tenant_scoped_user, require_roles
from app.models.college import College
from app.models.attendance import Attendance
from app.models.faculty import Faculty
from app.models.student import Student
from app.schemas.attendance import AttendanceCreate, AttendanceOut
from app.services.attendance import create_attendance, get_attendance_for_faculty, update_attendance, get_attendance_by_id
from app.core.constants import UserRole
from app.models.user import User
from app.services.notification_service import notify_attendance_marked

router = APIRouter(prefix="/attendance", tags=["attendance"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _att_to_out(att: Attendance) -> AttendanceOut:
    return AttendanceOut(
        id=str(att.id),
        faculty_id=str(att.faculty_id),
        subject=att.subject,
        date=att.date,
        session_name=att.session_name,
        records=[
            {"student_id": str(r.student_id), "status": r.status, "marked_by": str(r.marked_by) if r.marked_by else None}
            for r in att.records
        ],
        created_at=att.created_at,
        updated_at=att.updated_at,
    )


# ── Create Attendance ──────────────────────────────────────────────────────────

@router.post("", response_model=AttendanceOut, status_code=201)
async def create_attendance_endpoint(
    body: AttendanceCreate,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    faculty_doc = None
    if user.role == UserRole.FACULTY.value:
        faculty_doc = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == college.id)
        if not faculty_doc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty mapping not found")
        if not faculty_doc.subjects or body.subject not in faculty_doc.subjects:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subject for this faculty")
        if not faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No students assigned to this faculty")

        # Duplicate check: same faculty + subject + date already exists?
        existing = await Attendance.find_one(
            Attendance.college_id == college.id,
            Attendance.faculty_id == user.id,
            Attendance.subject == body.subject,
            {"date": {"$gte": body.date.replace(hour=0, minute=0, second=0, microsecond=0),
                      "$lt": body.date.replace(hour=23, minute=59, second=59, microsecond=999999)}}
        )
        if existing and not body.session_name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Attendance for '{body.subject}' on this date already exists. Use a session name to differentiate, or edit the existing record."
            )

    validated_records = []
    for rec in body.records:
        sid = PydanticObjectId(rec.student_id)
        student = await Student.find_one(Student.user_id == sid, Student.college_id == college.id)
        if not student:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Student {rec.student_id} not found in this college")
        if user.role == UserRole.FACULTY.value and sid not in faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Student {rec.student_id} not assigned to this faculty")
        if rec.status not in ("present", "absent", "late"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status '{rec.status}' — must be present, absent, or late")
        validated_records.append({"student_id": sid, "status": rec.status, "marked_by": user.id if user.role == UserRole.FACULTY.value else None})

    att = await create_attendance(college.id, user.id, body.subject, body.date, body.session_name, validated_records)

    date_str = body.date.strftime("%Y-%m-%d") if hasattr(body.date, "strftime") else str(body.date)
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

    return _att_to_out(att)


# ── Faculty's own attendance records ──────────────────────────────────────────

@router.get("/mine", response_model=List[AttendanceOut])
async def my_attendance(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    limit: int = Query(default=50, ge=1, le=200),
):
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only faculty or admin can access this endpoint")
    items = await get_attendance_for_faculty(college.id, user.id, limit=limit)
    return [_att_to_out(att) for att in items]


# ── Student / Parent attendance view ──────────────────────────────────────────

@router.get("/student", response_model=List[AttendanceOut])
async def student_attendance(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Return attendance for logged-in student, or parent's linked children."""
    if user.role not in (UserRole.STUDENT.value, UserRole.PARENT.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students or parents can access this endpoint")

    target_ids: List[PydanticObjectId] = []
    if user.role == UserRole.STUDENT.value:
        target_ids = [user.id]
    else:
        raw_ids = user.profile.student_ids if user.profile else []
        target_ids = [PydanticObjectId(str(cid)) for cid in raw_ids if PydanticObjectId.is_valid(str(cid))]
        if not target_ids:
            return []

    items = await Attendance.find(
        Attendance.college_id == college.id,
        {"records.student_id": {"$in": target_ids}},
    ).sort(-Attendance.date).to_list()

    return [_att_to_out(att) for att in items]


# ── Admin: all attendance for college ─────────────────────────────────────────

@router.get("", response_model=List[AttendanceOut])
async def list_all_attendance(
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
    subject: Optional[str] = None,
    faculty_user_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    """College admin: list all attendance records with optional filters."""
    filters = [Attendance.college_id == college.id]
    if subject:
        filters.append(Attendance.subject == subject)
    if faculty_user_id:
        filters.append(Attendance.faculty_id == PydanticObjectId(faculty_user_id))
    items = await Attendance.find(*filters).sort(-Attendance.date).limit(limit).to_list()
    return [_att_to_out(att) for att in items]


# ── Analytics endpoint for admin ──────────────────────────────────────────────

@router.get("/analytics", response_model=dict)
async def attendance_analytics(
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """College admin: aggregate attendance analytics."""
    all_att = await Attendance.find(Attendance.college_id == college.id).to_list()

    total_sessions = len(all_att)
    total_records = sum(len(a.records) for a in all_att)
    present_count = sum(1 for a in all_att for r in a.records if r.status == "present")
    absent_count  = sum(1 for a in all_att for r in a.records if r.status == "absent")
    late_count    = sum(1 for a in all_att for r in a.records if r.status == "late")
    overall_pct   = round((present_count / total_records * 100), 1) if total_records > 0 else 0.0

    # Subject-wise
    subject_map: dict = {}
    for att in all_att:
        s = att.subject
        if s not in subject_map:
            subject_map[s] = {"present": 0, "absent": 0, "late": 0, "total": 0}
        for r in att.records:
            subject_map[s]["total"] += 1
            subject_map[s][r.status] = subject_map[s].get(r.status, 0) + 1

    subject_stats = [
        {
            "subject": s,
            "total": v["total"],
            "present": v["present"],
            "absent": v["absent"],
            "late": v["late"],
            "percentage": round(v["present"] / v["total"] * 100, 1) if v["total"] > 0 else 0.0,
        }
        for s, v in subject_map.items()
    ]

    # Low attendance students (<75%)
    from app.models.student import Student as StudentModel
    students = await StudentModel.find(StudentModel.college_id == college.id).to_list()
    from app.models.user import User as UserModel
    low_attendance = []
    for stu in students:
        stu_records = [r for a in all_att for r in a.records if r.student_id == stu.user_id]
        if not stu_records:
            continue
        prs = sum(1 for r in stu_records if r.status in ("present", "late"))
        pct = round(prs / len(stu_records) * 100, 1)
        if pct < 75:
            u = await UserModel.get(stu.user_id)
            low_attendance.append({
                "student_name": u.name if u else str(stu.user_id),
                "roll_no": stu.roll_no,
                "department": stu.department,
                "attendance_percentage": pct,
                "total_classes": len(stu_records),
                "present": prs,
            })

    return {
        "total_sessions": total_sessions,
        "total_records": total_records,
        "present_count": present_count,
        "absent_count": absent_count,
        "late_count": late_count,
        "overall_percentage": overall_pct,
        "subject_stats": subject_stats,
        "low_attendance_students": sorted(low_attendance, key=lambda x: x["attendance_percentage"]),
    }


# ── Update Attendance ──────────────────────────────────────────────────────────

@router.patch("/{attendance_id}", response_model=AttendanceOut)
async def edit_attendance(
    attendance_id: str,
    body: AttendanceCreate,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    att_doc = await get_attendance_by_id(PydanticObjectId(attendance_id))
    if not att_doc or att_doc.college_id != college.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance not found")

    faculty_doc = None
    if user.role == UserRole.FACULTY.value:
        # Faculty can only edit their OWN attendance records
        if att_doc.faculty_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only edit your own attendance records")
        faculty_doc = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == college.id)
        if not faculty_doc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty mapping not found")
        if not faculty_doc.subjects or body.subject not in faculty_doc.subjects:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subject for this faculty")
        if not faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No students assigned to this faculty")

    validated_records = []
    for rec in body.records:
        sid = PydanticObjectId(rec.student_id)
        student = await Student.find_one(Student.user_id == sid, Student.college_id == college.id)
        if not student:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Student {rec.student_id} not found in this college")
        if user.role == UserRole.FACULTY.value and sid not in faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Student {rec.student_id} not assigned to this faculty")
        if rec.status not in ("present", "absent", "late"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status '{rec.status}'")
        validated_records.append({"student_id": sid, "status": rec.status, "marked_by": user.id if user.role == UserRole.FACULTY.value else None})

    att = await update_attendance(PydanticObjectId(attendance_id), college.id, validated_records)
    if not att:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance not found")
    return _att_to_out(att)


# ── Delete Attendance ──────────────────────────────────────────────────────────

@router.delete("/{attendance_id}")
async def delete_attendance(
    attendance_id: str,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    att_doc = await get_attendance_by_id(PydanticObjectId(attendance_id))
    if not att_doc or att_doc.college_id != college.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance not found")

    if user.role == UserRole.FACULTY.value and att_doc.faculty_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own attendance records")

    await att_doc.delete()
    return {"ok": True, "message": "Attendance record deleted"}


# ── Get single attendance ──────────────────────────────────────────────────────

@router.get("/{attendance_id}", response_model=AttendanceOut)
async def get_attendance(
    attendance_id: str,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    att = await get_attendance_by_id(PydanticObjectId(attendance_id))
    if not att or att.college_id != college.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance not found")
    return _att_to_out(att)
