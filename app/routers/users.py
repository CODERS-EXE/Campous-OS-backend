from typing import Annotated, List

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.constants import UserRole
from app.core.deps import get_tenant_college, get_tenant_scoped_user, require_roles
from app.models.college import College
from app.models.faculty import Faculty
from app.models.student import Student
from app.models.user import User
from app.schemas.profile import (
    DashboardStats,
    FacultyProfileResponse,
    StudentProfileResponse,
    UserCreateRequest,
    UserSummaryResponse,
    UserUpdateRequest,
)
from app.services.users import create_user, delete_user, get_dashboard_stats, update_user

router = APIRouter(prefix="/users", tags=["users"])


def _to_user_response(user: User) -> UserSummaryResponse:
    return UserSummaryResponse(
        id=str(user.id),
        name=user.name,
        email=user.email,
        role=user.role,
        profile=user.profile.model_dump(),
        is_verified=user.is_verified,
        created_at=user.created_at,
    )


@router.get("/dashboard/stats", response_model=DashboardStats)
async def dashboard_stats(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    stats = await get_dashboard_stats(college.id, user.id)
    return DashboardStats(**stats)


@router.get("/students", response_model=List[StudentProfileResponse])
async def list_students(
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.FACULTY))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    # If faculty, restrict to assigned students only
    if user.role == UserRole.FACULTY.value:
        faculty = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == college.id)
        if not faculty:
            return []
        # faculty.student_ids expected to be list of student user_ids (PydanticObjectId)
        if not faculty.student_ids:
            return []
        students = await Student.find(Student.college_id == college.id, In(Student.user_id, faculty.student_ids)).to_list()
    else:
        students = await Student.find(Student.college_id == college.id).to_list()

    result = []
    for s in students:
        u = await User.get(s.user_id)
        if u:
            result.append(
                StudentProfileResponse(
                    id=str(s.id),
                    user_id=str(u.id),
                    name=u.name,
                    email=u.email,
                    roll_no=s.roll_no,
                    department=s.department,
                    course=s.course,
                    year=s.year,
                    semester=s.semester,
                    avatar_url=u.profile.avatar_url,
                    emergency_contact=s.emergency_contact,
                    blood_group=s.blood_group,
                    created_at=s.created_at,
                )
            )
    return result


@router.get("/faculty", response_model=List[FacultyProfileResponse])
async def list_faculty(
    _: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    faculty_list = await Faculty.find(Faculty.college_id == college.id).to_list()
    result = []
    for f in faculty_list:
        u = await User.get(f.user_id)
        if u:
            result.append(
                FacultyProfileResponse(
                    id=str(f.id),
                    user_id=str(u.id),
                    name=u.name,
                    email=u.email,
                    department=f.department,
                    course=f.course,
                    year=f.year,
                    semester=f.semester,
                    designation=f.designation,
                    status=f.status,
                    subjects=f.subjects,
                    student_ids=[str(sid) for sid in f.student_ids],
                    avatar_url=u.profile.avatar_url,
                    created_at=f.created_at,
                )
            )
    return result


@router.get("/parents", response_model=list[UserSummaryResponse])
async def list_parents(
    _: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    parents = await User.find(User.college_id == college.id, User.role == UserRole.PARENT.value).to_list()
    return [_to_user_response(u) for u in parents]


@router.get("/wardens", response_model=list[UserSummaryResponse])
async def list_wardens(
    _: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    wardens = await User.find(User.college_id == college.id, User.role == UserRole.WARDEN.value).to_list()
    return [_to_user_response(u) for u in wardens]


@router.post("", response_model=UserSummaryResponse, status_code=201)
async def create_college_user(
    body: UserCreateRequest,
    _: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    try:
        user = await create_user(
            name=body.name,
            email=body.email,
            password=body.password,
            role=body.role,
            college=college,
            course=body.course,
            designation=body.designation,
            status=body.status,
            hostel=body.hostel,
            phone=body.phone,
            student_ids=body.student_ids,
            roll_no=body.roll_no,
            department=body.department,
            year=body.year,
            semester=body.semester or 1,
            subjects=body.subjects,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _to_user_response(user)


@router.patch("/{user_id}")
async def update_college_user(
    user_id: str,
    body: UserUpdateRequest,
    _: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    user = await User.get(PydanticObjectId(user_id))
    if not user or user.college_id != college.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.role == UserRole.SUPER_ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot modify super admin")

    try:
        updated_user = await update_user(
        user,
        name=body.name,
        email=body.email,
        department=body.department,
        course=body.course,
        designation=body.designation,
        status=body.status,
        hostel=body.hostel,
        phone=body.phone,
        student_ids=body.student_ids,
        subjects=body.subjects,
        roll_no=body.roll_no,
        year=body.year,
        semester=body.semester,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Return appropriate response based on role
    if updated_user.role == UserRole.FACULTY.value:
        faculty = await Faculty.find_one(Faculty.user_id == updated_user.id, Faculty.college_id == college.id)
        if faculty:
            return FacultyProfileResponse(
                id=str(faculty.id),
                user_id=str(updated_user.id),
                name=updated_user.name,
                email=updated_user.email,
                department=faculty.department,
                course=faculty.course,
                year=faculty.year,
                semester=faculty.semester,
                designation=faculty.designation,
                status=faculty.status,
                subjects=faculty.subjects,
                student_ids=[str(sid) for sid in faculty.student_ids],
                avatar_url=updated_user.profile.avatar_url,
                created_at=faculty.created_at,
            )
    elif updated_user.role == UserRole.STUDENT.value:
        student = await Student.find_one(Student.user_id == updated_user.id, Student.college_id == college.id)
        if student:
            return StudentProfileResponse(
                id=str(student.id),
                user_id=str(updated_user.id),
                name=updated_user.name,
                email=updated_user.email,
                roll_no=student.roll_no,
                department=student.department,
                course=student.course,
                year=student.year,
                semester=student.semester,
                avatar_url=updated_user.profile.avatar_url,
                emergency_contact=updated_user.profile.emergency_contact,
                blood_group=updated_user.profile.blood_group,
                created_at=student.created_at,
            )

    return _to_user_response(updated_user)


@router.delete("/{user_id}")
async def delete_college_user(
    user_id: str,
    _: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    user = await User.get(PydanticObjectId(user_id))
    if not user or user.college_id != college.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.role == UserRole.SUPER_ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot delete super admin")

    await delete_user(user)
    return {"ok": True}


@router.get("/me/profile")
async def my_profile(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    if user.role == UserRole.STUDENT.value:
        student = await Student.find_one(Student.user_id == user.id, Student.college_id == college.id)
        if not student:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student profile not found")
        return StudentProfileResponse(
            id=str(student.id),
            user_id=str(user.id),
            name=user.name,
            email=user.email,
            roll_no=student.roll_no,
            department=student.department,
            year=student.year,
            semester=student.semester,
            avatar_url=user.profile.avatar_url,
            emergency_contact=student.emergency_contact,
            blood_group=student.blood_group,
        )
    if user.role == UserRole.FACULTY.value:
        faculty = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == college.id)
        if not faculty:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Faculty profile not found")
        return FacultyProfileResponse(
            id=str(faculty.id),
            user_id=str(user.id),
            name=user.name,
            email=user.email,
            department=faculty.department,
            year=faculty.year,
            semester=faculty.semester,
            subjects=faculty.subjects,
            avatar_url=user.profile.avatar_url,
        )
    return {"id": str(user.id), "name": user.name, "email": user.email, "role": user.role}


@router.get("/my-children", response_model=List[StudentProfileResponse])
async def get_my_children(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Get assigned children for a parent"""
    if user.role != UserRole.PARENT.value:
        raise HTTPException(status_code=403, detail="Only parents can access this endpoint")

    child_ids = user.profile.student_ids or []
    if not child_ids:
        return []

    # student_ids are stored as user_ids (strings)
    result = []
    for sid in child_ids:
        try:
            child_user = await User.get(PydanticObjectId(sid))
            if not child_user or child_user.college_id != college.id:
                continue
            student = await Student.find_one(
                Student.user_id == child_user.id,
                Student.college_id == college.id
            )
            if student:
                result.append(StudentProfileResponse(
                    id=str(student.id),
                    user_id=str(child_user.id),
                    name=child_user.name,
                    email=child_user.email,
                    roll_no=student.roll_no,
                    department=student.department,
                    course=student.course,
                    year=student.year,
                    semester=student.semester,
                    avatar_url=child_user.profile.avatar_url,
                ))
        except Exception:
            continue
    return result


# Assign students to faculty
@router.patch("/faculty/{faculty_user_id}/assign-students")
async def assign_students_to_faculty(
    faculty_user_id: str,
    student_ids: List[str],
    _: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Assign students to a faculty member (College Admin only)"""
    faculty = await Faculty.find_one(
        Faculty.user_id == PydanticObjectId(faculty_user_id),
        Faculty.college_id == college.id
    )
    if not faculty:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Faculty not found")
    
    # Convert string IDs to PydanticObjectId
    faculty.student_ids = [PydanticObjectId(sid) for sid in student_ids if PydanticObjectId.is_valid(sid)]
    await faculty.save()
    
    return {"message": f"Assigned {len(faculty.student_ids)} students to faculty", "count": len(faculty.student_ids)}
