from typing import Annotated, List
# pyrefly: ignore [missing-import]
from beanie import PydanticObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.core.deps import get_tenant_college, get_tenant_scoped_user
from app.models.college import College
from app.models.assignment import Assignment
from app.models.faculty import Faculty
from app.models.student import Student
from app.schemas.assignment import AssignmentCreate, AssignmentOut, SubmissionCreate, SubmissionOut
from app.services.assignments import create_assignment, list_assignments, update_assignment, create_submission, list_submissions_for_assignment
from app.core.constants import UserRole
from app.models.user import User
# pyrefly: ignore [missing-import]
from beanie import PydanticObjectId
from fastapi import HTTPException, status
from app.services.notification_service import notify_assignment_created

router = APIRouter(prefix="/assignments", tags=["assignments"])


@router.post("", response_model=AssignmentOut, status_code=201)
async def create_assignment_endpoint(
    body: AssignmentCreate,
    background_tasks: BackgroundTasks,
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

    # Auto-notify students about the new assignment
    due_str = str(body.due_date) if body.due_date else "TBD"
    background_tasks.add_task(
        notify_assignment_created,
        college_id=college.id,
        assignment_title=a.title,
        subject=a.subject or "General",
        due_date=due_str,
        assignment_id=str(a.id),
        created_by=user.id,
    )

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
    # Faculty sees their own assignments
    # Students see published assignments from their assigned faculty
    # Admin sees all assignments
    
    if user.role == UserRole.STUDENT.value:
        # Student should see only published assignments from faculty who have them assigned
        student = await Student.find_one(Student.user_id == user.id, Student.college_id == college.id)
        if not student:
            return []
        
        # Find all faculty who have this student assigned
        all_faculty = await Faculty.find(Faculty.college_id == college.id).to_list()
        faculty_list = [f for f in all_faculty if user.id in f.student_ids]
        
        if not faculty_list:
            return []
        
        faculty_user_ids = [f.user_id for f in faculty_list]
        
        # Get published assignments ONLY from faculty assigned to this student
        from beanie.operators import In as BeanieIn
        items = await Assignment.find(
            Assignment.college_id == college.id,
            Assignment.published == True,
            BeanieIn(Assignment.created_by, faculty_user_ids)
        ).sort(-Assignment.created_at).skip(skip).limit(limit).to_list()
        
    elif user.role == UserRole.FACULTY.value:
        # Faculty sees their own assignments
        items = await list_assignments(college.id, user.id, limit=limit, skip=skip)
        
    elif user.role == UserRole.PARENT.value:
        # Parent sees published assignments for their children
        child_ids = user.profile.student_ids or []
        if not child_ids:
            return []
        
        child_user_ids = [PydanticObjectId(sid) for sid in child_ids if PydanticObjectId.is_valid(sid)]
        
        # Find faculty who have these children assigned
        all_faculty = await Faculty.find(
            Faculty.college_id == college.id,
        ).to_list()
        
        # Filter faculty who have any of the children assigned
        faculty_list = [f for f in all_faculty if any(cid in f.student_ids for cid in child_user_ids)]
        
        if not faculty_list:
            return []
        
        faculty_ids = [f.user_id for f in faculty_list]
        
        # Get published assignments
        from beanie.operators import In as BeanieIn
        items = await Assignment.find(
            Assignment.college_id == college.id,
            Assignment.published == True,
            BeanieIn(Assignment.created_by, faculty_ids)
        ).sort(-Assignment.created_at).skip(skip).limit(limit).to_list()
    else:
        # Admin sees all
        items = await list_assignments(college.id, None, limit=limit, skip=skip)
    
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


@router.get("/my-submissions", response_model=List[SubmissionOut])
async def my_submissions(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    limit: int = 100,
    skip: int = 0,
):
    """Get submissions for logged-in student OR parent's children"""
    from app.models.submission import Submission
    
    if user.role == UserRole.STUDENT.value:
        # Student sees their own submissions
        subs = await Submission.find(
            Submission.college_id == college.id,
            Submission.student_id == user.id
        ).skip(skip).limit(limit).to_list()
        
    elif user.role == UserRole.PARENT.value:
        # Parent sees children's submissions
        child_ids = user.profile.student_ids or []
        if not child_ids:
            return []
        
        child_user_ids = [PydanticObjectId(sid) for sid in child_ids if PydanticObjectId.is_valid(sid)]
        
        subs = await Submission.find(
            Submission.college_id == college.id,
            Submission.student_id.in_(child_user_ids)
        ).skip(skip).limit(limit).to_list()
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students or parents can access this endpoint")
    
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


@router.patch("/submissions/{submission_id}/grade", response_model=SubmissionOut)
async def grade_submission(
    submission_id: str,
    marks: float,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Award marks/grade to a submission (Faculty or Admin only)"""
    if user.role not in (UserRole.FACULTY.value, UserRole.COLLEGE_ADMIN.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    from app.models.submission import Submission
    submission = await Submission.get(PydanticObjectId(submission_id))
    if not submission or submission.college_id != college.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    # If faculty, verify they created the assignment and student is assigned
    if user.role == UserRole.FACULTY.value:
        faculty_doc = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == college.id)
        if not faculty_doc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Faculty mapping not found")
        
        # Check if student is assigned
        if submission.student_id not in faculty_doc.student_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student not assigned to this faculty")
        
        # Check if assignment was created by this faculty
        assignment = await Assignment.get(submission.assignment_id)
        if not assignment or assignment.created_by != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot grade submission for another faculty's assignment")

    # Award marks
    submission.marks_awarded = marks
    from app.core.deps import utcnow
    submission.updated_at = utcnow()
    await submission.save()

    return SubmissionOut(
        id=str(submission.id),
        assignment_id=str(submission.assignment_id),
        student_id=str(submission.student_id),
        files=submission.files,
        submitted_at=submission.submitted_at,
        marks_awarded=submission.marks_awarded,
    )
