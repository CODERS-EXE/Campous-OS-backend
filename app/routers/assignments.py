from typing import Annotated, List
from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_tenant_college, get_tenant_scoped_user
from app.models.college import College
from app.models.assignment import Assignment
from app.models.faculty import Faculty
from app.models.student import Student
from app.schemas.assignment import AssignmentCreate, AssignmentOut, SubmissionCreate, SubmissionOut
from app.services.assignments import create_assignment, list_assignments, update_assignment, create_submission, list_submissions_for_assignment
from app.core.constants import UserRole
from app.models.user import User
from beanie import PydanticObjectId
from fastapi import HTTPException, status

router = APIRouter(prefix="/assignments", tags=["assignments"])


@router.post("", response_model=AssignmentOut, status_code=201)
async def create_assignment_endpoint(
    body: AssignmentCreate,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    # If faculty, ensure subject belongs to them and they have students
    if user.role == UserRole.FACULTY.value:
        faculty_doc = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == college.id)
        if not faculty_doc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty mapping not found")
        if not faculty_doc.subjects or (body.subject and body.subject not in faculty_doc.subjects):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subject for this faculty")
        if not faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No students assigned to this faculty")

    a = await create_assignment(college.id, user.id, body.model_dump())
    return AssignmentOut(
        id=str(a.id),
        created_by=str(a.created_by),
        title=a.title,
        description=a.description,
        subject=a.subject,
        due_date=a.due_date,
        attachments=a.attachments,
        published=a.published,
        created_at=a.created_at,
    )


@router.get("", response_model=List[AssignmentOut])
async def list_assignments_endpoint(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    limit: int = 100,
    skip: int = 0,
):
    items = await list_assignments(college.id, user.id if user.role==UserRole.FACULTY.value else None, limit=limit, skip=skip)
    return [
        AssignmentOut(
            id=str(a.id),
            created_by=str(a.created_by),
            title=a.title,
            description=a.description,
            subject=a.subject,
            due_date=a.due_date,
            attachments=a.attachments,
            published=a.published,
            created_at=a.created_at,
        )
        for a in items
    ]


@router.patch("/{assignment_id}", response_model=AssignmentOut)
async def edit_assignment(
    assignment_id: str,
    body: AssignmentCreate,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    if user.role == UserRole.FACULTY.value:
        faculty_doc = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == college.id)
        if not faculty_doc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty mapping not found")
        assignment_doc = await Assignment.get(PydanticObjectId(assignment_id))
        if not assignment_doc or assignment_doc.college_id != college.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
        if assignment_doc.created_by != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty cannot edit another faculty's assignment")
        if body.subject and body.subject not in faculty_doc.subjects:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subject for this faculty")

    a = await update_assignment(PydanticObjectId(assignment_id), college.id, body.model_dump())
    if not a:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    return AssignmentOut(
        id=str(a.id),
        created_by=str(a.created_by),
        title=a.title,
        description=a.description,
        subject=a.subject,
        due_date=a.due_date,
        attachments=a.attachments,
        published=a.published,
        created_at=a.created_at,
    )


@router.post("/submit", response_model=SubmissionOut, status_code=201)
async def submit_assignment(
    body: SubmissionCreate,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    # only students submit
    if user.role != UserRole.STUDENT.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students can submit")

    # verify student exists and belongs to college
    student = await Student.find_one(Student.user_id == user.id, Student.college_id == college.id)
    if not student:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student profile not found in this college")

    # verify assignment belongs to same college
    assignment = await Assignment.get(PydanticObjectId(body.assignment_id))
    if not assignment or assignment.college_id != college.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    payload = {"assignment_id": PydanticObjectId(body.assignment_id), "student_id": user.id, "files": body.files}
    # create_submission will set created_by if missing
    s = await create_submission(college.id, payload)
    return SubmissionOut(
        id=str(s.id),
        assignment_id=str(s.assignment_id),
        student_id=str(s.student_id),
        files=s.files,
        submitted_at=s.submitted_at,
        marks_awarded=s.marks_awarded,
    )


@router.get("/{assignment_id}/submissions", response_model=List[SubmissionOut])
async def list_submissions(assignment_id: str, user: Annotated[User, Depends(get_tenant_scoped_user)], college: Annotated[College, Depends(get_tenant_college)], limit: int = 100, skip: int = 0):
    # faculty or admin can view
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    # fetch submissions, then if faculty, filter to only assigned students
    subs = await list_submissions_for_assignment(college.id, PydanticObjectId(assignment_id), limit=limit, skip=skip)
    if user.role == UserRole.FACULTY.value:
        faculty_doc = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == college.id)
        if not faculty_doc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty mapping not found")
        if not faculty_doc.student_ids:
            # No access
            return []
        subs = [s for s in subs if s.student_id in faculty_doc.student_ids]

    return [
        SubmissionOut(
            id=str(s.id),
            assignment_id=str(s.assignment_id),
            student_id=str(s.student_id),
            files=s.files,
            submitted_at=s.submitted_at,
            marks_awarded=s.marks_awarded,
        )
        for s in subs
    ]
