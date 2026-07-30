from typing import Annotated, List
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_tenant_college, get_tenant_scoped_user
from app.models.college import College
from app.models.faculty import Faculty
from app.models.student import Student
from app.schemas.result import ResultCreate, ResultOut
from app.services.results import create_or_update_result, list_results_for_student
from app.core.constants import UserRole
from app.models.user import User
from beanie import PydanticObjectId
from fastapi import HTTPException, status

router = APIRouter(prefix="/results", tags=["results"])


@router.post("", response_model=ResultOut, status_code=201)
async def create_result(
    body: ResultCreate,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    # only faculty, college admin, or super admin enter results
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    payload = body.model_dump()

    # If faculty, validate mapping, subject and student assignment
    if user.role == UserRole.FACULTY.value:
        faculty_doc = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == college.id)
        if not faculty_doc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty mapping not found")
        if not faculty_doc.subjects or payload.get("subject") not in faculty_doc.subjects:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subject for this faculty")
        if not faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No students assigned to this faculty")

        # Verify student is assigned to this faculty and in same college
        sid = PydanticObjectId(payload.get("student_id"))
        student = await Student.find_one(Student.user_id == sid, Student.college_id == college.id)
        if not student:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student not found in this college")
        if sid not in faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student not assigned to this faculty")

        payload["faculty_id"] = user.id

    payload["created_by"] = user.id
    r = await create_or_update_result(college.id, payload)
    return ResultOut(
        id=str(r.id),
        student_id=str(r.student_id),
        subject=r.subject,
        exam_name=r.exam_name,
        internal_marks=r.internal_marks,
        practical_marks=r.practical_marks,
        total_marks=r.total_marks,
        grade=r.grade,
    )


@router.get("/student/{student_id}", response_model=List[ResultOut])
async def results_for_student(student_id: str, user: Annotated[User, Depends(get_tenant_scoped_user)], college: Annotated[College, Depends(get_tenant_college)]):
    # student can view own results; faculty/admin can view within college
    if user.role == UserRole.STUDENT.value and str(user.id) != student_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    if user.role == UserRole.FACULTY.value:
        faculty_doc = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == college.id)
        if not faculty_doc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty mapping not found")
        if not faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No students assigned to this faculty")
        if PydanticObjectId(student_id) not in faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student not assigned to this faculty")

    results = await list_results_for_student(college.id, PydanticObjectId(student_id))
    return [
        ResultOut(
            id=str(r.id),
            student_id=str(r.student_id),
            subject=r.subject,
            exam_name=r.exam_name,
            internal_marks=r.internal_marks,
            practical_marks=r.practical_marks,
            total_marks=r.total_marks,
            grade=r.grade,
        )
        for r in results
    ]
