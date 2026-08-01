"""
Exam Management Router
Comprehensive API for exam scheduling, marks entry, grade calculation, and results
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File
from typing import List, Optional
from datetime import datetime, timedelta
from bson import ObjectId
from beanie.operators import In

from app.models.exam import Exam
from app.models.subject_exam import SubjectExam
from app.models.question_paper import QuestionPaper, QuestionSection
from app.models.student_exam import StudentExam
from app.models.exam_result import ExamResult, SubjectResult
from app.models.grade_scale import GradeScale, GradeRange
from app.models.user import User
from app.models.student import Student
from app.core.deps import get_current_user
from app.schemas.exam import ExamCreate, ExamUpdate, SubjectExamCreate, SubjectExamUpdate
from app.services.notification_service import notify_exam_scheduled, notify_results_published

router = APIRouter(prefix="/exams", tags=["exams"])



# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def generate_hall_ticket_number(exam_id: str, student_id: str, college_id: str) -> str:
    """Generate unique hall ticket number"""
    year = datetime.utcnow().year
    # Format: HT-YEAR-EXAMID-STUDENTID
    return f"HT{year}{str(exam_id)[-4:]}{str(student_id)[-4:]}"


async def calculate_grade(marks: float, grade_scale: GradeScale) -> tuple[str, float]:
    """
    Calculate grade and grade points based on marks
    Returns: (grade, grade_points)
    """
    for range_item in grade_scale.ranges:
        if range_item.min_marks <= marks <= range_item.max_marks:
            return range_item.grade, range_item.grade_points
    
    # Default to fail if no range matches
    return "F", 0.0


async def calculate_sgpa(subject_results: List[SubjectResult]) -> float:
    """
    Calculate Semester Grade Point Average (SGPA)
    SGPA = Σ(Grade Points × Credits) / Σ(Credits)
    """
    total_grade_points = 0.0
    total_credits = 0
    
    for subject in subject_results:
        if subject.grade_points is not None and subject.result_status == "pass":
            total_grade_points += subject.grade_points * subject.credits
            total_credits += subject.credits
    
    if total_credits == 0:
        return 0.0
    
    return round(total_grade_points / total_credits, 2)


async def calculate_cgpa(student_id: ObjectId, current_sgpa: float, current_credits: int) -> float:
    """
    Calculate Cumulative Grade Point Average (CGPA)
    """
    # Get all published results for student
    previous_results = await ExamResult.find(
        ExamResult.student_id == student_id,
        ExamResult.is_published == True
    ).to_list()
    
    total_grade_points = current_sgpa * current_credits
    total_credits = current_credits
    
    for result in previous_results:
        if result.sgpa and result.total_credits:
            total_grade_points += result.sgpa * result.total_credits
            total_credits += result.total_credits
    
    if total_credits == 0:
        return 0.0
    
    return round(total_grade_points / total_credits, 2)


# ============================================================================
# EXAM CRUD ENDPOINTS
# ============================================================================

@router.post("/", response_model=dict)
async def create_exam(
    payload: ExamCreate,
    background_tasks: BackgroundTasks = None,
    current_user: User = Depends(get_current_user)
):
    """Create a new exam (College Admin only)"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    exam = Exam(
        name=payload.name,
        exam_type=payload.exam_type,
        academic_year=payload.academic_year,
        semester=payload.semester,
        start_date=payload.start_date,
        end_date=payload.end_date,
        description=payload.description,
        status="scheduled",
        college_id=current_user.college_id,
        created_by=current_user.id
    )
    
    await exam.insert()

    # Auto-notify students and faculty about the new exam
    if background_tasks:
        background_tasks.add_task(
            notify_exam_scheduled,
            college_id=exam.college_id,
            exam_name=exam.name,
            start_date=exam.start_date.strftime("%Y-%m-%d"),
            created_by=exam.created_by,
        )

    return {"id": str(exam.id), "message": "Exam created successfully"}


@router.get("/", response_model=List[dict])
async def get_exams(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = None,
    academic_year: Optional[str] = None,
    semester: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    """Get all exams for college"""
    query_filters = [Exam.college_id == current_user.college_id]
    
    if status:
        query_filters.append(Exam.status == status)
    if academic_year:
        query_filters.append(Exam.academic_year == academic_year)
    if semester:
        query_filters.append(Exam.semester == semester)
    
    exams = await Exam.find(*query_filters).skip(skip).limit(limit).to_list()
    
    return [
        {
            "id": str(exam.id),
            "name": exam.name,
            "exam_type": exam.exam_type,
            "academic_year": exam.academic_year,
            "semester": exam.semester,
            "start_date": exam.start_date.isoformat(),
            "end_date": exam.end_date.isoformat(),
            "status": exam.status,
            "description": exam.description,
            "total_subjects": exam.total_subjects,
            "total_students": exam.total_students,
            "results_published": exam.results_published,
            "created_at": exam.created_at.isoformat()
        }
        for exam in exams
    ]


@router.get("/{exam_id}", response_model=dict)
async def get_exam(
    exam_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get single exam details"""
    exam = await Exam.get(ObjectId(exam_id))
    if not exam or exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    return {
        "id": str(exam.id),
        "name": exam.name,
        "exam_type": exam.exam_type,
        "academic_year": exam.academic_year,
        "semester": exam.semester,
        "start_date": exam.start_date.isoformat(),
        "end_date": exam.end_date.isoformat(),
        "status": exam.status,
        "description": exam.description,
        "total_subjects": exam.total_subjects,
        "total_students": exam.total_students,
        "results_published": exam.results_published,
        "published_at": exam.published_at.isoformat() if exam.published_at else None,
        "created_at": exam.created_at.isoformat()
    }


@router.patch("/{exam_id}", response_model=dict)
async def update_exam(
    exam_id: str,
    payload: ExamUpdate,
    current_user: User = Depends(get_current_user)
):
    """Update exam details (College Admin only)"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    exam = await Exam.get(ObjectId(exam_id))
    if not exam or exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    update_data = {}
    if payload.name is not None:
        update_data["name"] = payload.name
    if payload.status is not None:
        update_data["status"] = payload.status
    if payload.start_date is not None:
        update_data["start_date"] = payload.start_date
    if payload.end_date is not None:
        update_data["end_date"] = payload.end_date
    if payload.description is not None:
        update_data["description"] = payload.description
    
    update_data["updated_at"] = datetime.utcnow()
    
    await exam.set(update_data)
    return {"message": "Exam updated successfully"}



@router.delete("/{exam_id}", response_model=dict)
async def delete_exam(
    exam_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete exam and all related data (College Admin only)"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    exam = await Exam.get(ObjectId(exam_id))
    if not exam or exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    # Don't allow deletion if results are published
    if exam.results_published:
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete exam after results are published"
        )
    
    # Cascade delete all related data
    # 1. Delete all subject exams
    subject_exams = await SubjectExam.find(SubjectExam.exam_id == exam.id).to_list()
    for se in subject_exams:
        await se.delete()
    
    # 2. Delete all student exam records (hall tickets, attendance, marks)
    student_exams = await StudentExam.find(StudentExam.exam_id == exam.id).to_list()
    for ste in student_exams:
        await ste.delete()
    
    # 3. Delete all exam results
    exam_results = await ExamResult.find(ExamResult.exam_id == exam.id).to_list()
    for er in exam_results:
        await er.delete()
    
    # 4. Delete the exam itself
    await exam.delete()
    
    return {
        "message": "Exam and all related data deleted successfully",
        "deleted_subjects": len(subject_exams),
        "deleted_student_exams": len(student_exams),
        "deleted_results": len(exam_results)
    }


# ============================================================================
# SUBJECT EXAM ENDPOINTS
# ============================================================================

@router.post("/{exam_id}/subjects", response_model=dict)
async def schedule_subject_exam(
    exam_id: str,
    payload: SubjectExamCreate,
    current_user: User = Depends(get_current_user)
):
    """Schedule subject exam (College Admin only)"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    exam = await Exam.get(ObjectId(exam_id))
    if not exam or exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    # Parse time strings
    from datetime import time
    start = datetime.strptime(payload.start_time, "%H:%M:%S").time() if ":" in payload.start_time and len(payload.start_time) == 8 else datetime.strptime(payload.start_time, "%H:%M").time()
    end = datetime.strptime(payload.end_time, "%H:%M:%S").time() if ":" in payload.end_time and len(payload.end_time) == 8 else datetime.strptime(payload.end_time, "%H:%M").time()
    
    subject_exam = SubjectExam(
        exam_id=exam.id,
        subject_id=ObjectId(payload.subject_id) if payload.subject_id and ObjectId.is_valid(payload.subject_id) else ObjectId(),
        subject_name=payload.subject_name,
        subject_code=payload.subject_code,
        exam_date=payload.exam_date,
        start_time=start,
        end_time=end,
        duration_minutes=payload.duration_minutes,
        max_marks=payload.max_marks,
        passing_marks=payload.passing_marks,
        credits=payload.credits,
        room_numbers=payload.room_numbers,
        internal_marks_weight=payload.internal_marks_weight,
        external_marks_weight=payload.external_marks_weight,
        college_id=current_user.college_id
    )
    
    await subject_exam.insert()
    
    # Update exam subject count
    await exam.inc({Exam.total_subjects: 1})
    
    return {"id": str(subject_exam.id), "message": "Subject exam scheduled successfully"}


@router.get("/{exam_id}/subjects", response_model=List[dict])
async def get_subject_exams(
    exam_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get all subject exams for an exam"""
    exam = await Exam.get(ObjectId(exam_id))
    if not exam or exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    subject_exams = await SubjectExam.find(
        SubjectExam.exam_id == exam.id
    ).sort("+exam_date").to_list()
    
    return [
        {
            "id": str(se.id),
            "subject_id": str(se.subject_id),
            "subject_name": se.subject_name,
            "subject_code": se.subject_code,
            "exam_date": se.exam_date.isoformat(),
            "start_time": se.start_time.isoformat(),
            "end_time": se.end_time.isoformat(),
            "duration_minutes": se.duration_minutes,
            "max_marks": se.max_marks,
            "passing_marks": se.passing_marks,
            "credits": se.credits,
            "room_numbers": se.room_numbers,
            "internal_marks_weight": se.internal_marks_weight,
            "external_marks_weight": se.external_marks_weight,
            "status": se.status,
            "enrolled_students": se.enrolled_students,
            "appeared_students": se.appeared_students,
            "passed_students": se.passed_students
        }
        for se in subject_exams
    ]


@router.patch("/subjects/{subject_exam_id}", response_model=dict)
async def update_subject_exam(
    subject_exam_id: str,
    payload: SubjectExamUpdate,
    current_user: User = Depends(get_current_user)
):
    """Update subject exam details"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    subject_exam = await SubjectExam.get(ObjectId(subject_exam_id))
    if not subject_exam or subject_exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Subject exam not found")
    
    update_data = {}
    if payload.exam_date:
        update_data["exam_date"] = payload.exam_date
    if payload.start_time:
        update_data["start_time"] = datetime.strptime(payload.start_time, "%H:%M:%S").time() if ":" in payload.start_time and len(payload.start_time) == 8 else datetime.strptime(payload.start_time, "%H:%M").time()
    if payload.end_time:
        update_data["end_time"] = datetime.strptime(payload.end_time, "%H:%M:%S").time() if ":" in payload.end_time and len(payload.end_time) == 8 else datetime.strptime(payload.end_time, "%H:%M").time()
    if payload.room_numbers is not None:
        update_data["room_numbers"] = payload.room_numbers
    if payload.status:
        update_data["status"] = payload.status
    
    update_data["updated_at"] = datetime.utcnow()
    
    await subject_exam.set(update_data)
    return {"message": "Subject exam updated successfully"}


@router.delete("/subjects/{subject_exam_id}", response_model=dict)
async def delete_subject_exam(
    subject_exam_id: str,
    current_user: User = Depends(get_current_user)
):
    """Delete scheduled subject exam"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    subject_exam = await SubjectExam.get(ObjectId(subject_exam_id))
    if not subject_exam or subject_exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Subject exam not found")
    
    # Check if marks have been entered
    student_exams_with_marks = await StudentExam.find(
        StudentExam.subject_exam_id == subject_exam.id,
        StudentExam.marks_obtained != None
    ).count()
    
    if student_exams_with_marks > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete subject exam. {student_exams_with_marks} students already have marks entered."
        )
    
    # Delete all student exam records for this subject
    student_exams = await StudentExam.find(StudentExam.subject_exam_id == subject_exam.id).to_list()
    for ste in student_exams:
        await ste.delete()
    
    # Delete the subject exam
    await subject_exam.delete()
    
    return {
        "message": "Subject exam deleted successfully",
        "deleted_hall_tickets": len(student_exams)
    }



# ============================================================================
# HALL TICKET GENERATION
# ============================================================================

@router.post("/{exam_id}/generate-hall-tickets", response_model=dict)
async def generate_hall_tickets(
    exam_id: str,
    student_ids: List[str],
    current_user: User = Depends(get_current_user)
):
    """Generate hall tickets for students (College Admin only)"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    exam = await Exam.get(ObjectId(exam_id))
    if not exam or exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    # Get all subject exams for this exam
    subject_exams = await SubjectExam.find(SubjectExam.exam_id == exam.id).to_list()
    
    if not subject_exams:
        raise HTTPException(status_code=400, detail="No subjects scheduled for this exam")
    
    generated_count = 0
    
    for student_id_str in student_ids:
        student_id = ObjectId(student_id_str)

        # Fetch student name and roll number once per student
        student_user = await User.get(student_id)
        student_doc = await Student.find_one(
            Student.user_id == student_id,
            Student.college_id == current_user.college_id,
        )
        resolved_name = student_user.name if student_user else ""
        resolved_roll = student_doc.roll_no if student_doc else ""
        
        # Generate hall ticket for each subject exam
        for subject_exam in subject_exams:
            # Check if hall ticket already exists
            existing = await StudentExam.find_one(
                StudentExam.subject_exam_id == subject_exam.id,
                StudentExam.student_id == student_id
            )
            
            if existing:
                continue  # Skip if already generated
            
            # Generate hall ticket number
            hall_ticket_number = generate_hall_ticket_number(
                str(exam.id), student_id_str, str(current_user.college_id)
            )
            
            # Create student exam record with resolved student details
            student_exam = StudentExam(
                subject_exam_id=subject_exam.id,
                exam_id=exam.id,
                student_id=student_id,
                student_name=resolved_name,
                student_roll_number=resolved_roll,
                hall_ticket_number=hall_ticket_number,
                college_id=current_user.college_id
            )
            
            await student_exam.insert()
            generated_count += 1
            
            # Update subject exam enrolled count
            await subject_exam.inc({SubjectExam.enrolled_students: 1})
    
    return {
        "message": f"Hall tickets generated successfully",
        "count": generated_count
    }


@router.get("/students/{student_id}/hall-ticket/latest", response_model=dict)
async def get_latest_student_hall_ticket(
    student_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get the latest generated hall ticket for a student"""
    if current_user.role == "student" and str(current_user.id) != student_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    latest_student_exam = await StudentExam.find_one(
        StudentExam.student_id == ObjectId(student_id)
    ).sort("-id")
    
    if not latest_student_exam:
        raise HTTPException(status_code=404, detail="Hall ticket not generated yet")
    
    return await get_student_hall_ticket(student_id=student_id, exam_id=str(latest_student_exam.exam_id), current_user=current_user)


@router.get("/students/{student_id}/hall-ticket/{exam_id}", response_model=dict)
async def get_student_hall_ticket(
    student_id: str,
    exam_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get hall ticket for a student"""
    if current_user.role == "student" and str(current_user.id) != student_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    exam = await Exam.get(ObjectId(exam_id))
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    # Get all student exams for this exam
    student_exams = await StudentExam.find(
        StudentExam.exam_id == exam.id,
        StudentExam.student_id == ObjectId(student_id)
    ).to_list()
    
    if not student_exams:
        raise HTTPException(status_code=404, detail="Hall ticket not generated yet")
    
    # Get subject exam details
    subject_exam_ids = [se.subject_exam_id for se in student_exams]
    subject_exams = await SubjectExam.find(
        In(SubjectExam.id, subject_exam_ids)
    ).to_list()
    
    subject_exam_map = {str(se.id): se for se in subject_exams}
    
    subjects = []
    for student_exam in student_exams:
        subject_exam = subject_exam_map.get(str(student_exam.subject_exam_id))
        if subject_exam:
            subjects.append({
                "subject_name": subject_exam.subject_name,
                "subject_code": subject_exam.subject_code,
                "exam_date": subject_exam.exam_date.isoformat(),
                "start_time": subject_exam.start_time.isoformat(),
                "end_time": subject_exam.end_time.isoformat(),
                "room_number": student_exam.room_number,
                "seat_number": student_exam.seat_number
            })
    
    return {
        "hall_ticket_number": student_exams[0].hall_ticket_number,
        "exam_name": exam.name,
        "academic_year": exam.academic_year,
        "semester": exam.semester,
        "student_name": student_exams[0].student_name,
        "student_roll_number": student_exams[0].student_roll_number,
        "subjects": subjects
    }


# ============================================================================
# ATTENDANCE MARKING
# ============================================================================

@router.patch("/student-exams/{student_exam_id}/attendance", response_model=dict)
async def mark_attendance(
    student_exam_id: str,
    attendance: str,  # present, absent
    current_user: User = Depends(get_current_user)
):
    """Mark student attendance for subject exam (Faculty only)"""
    if current_user.role not in ["super_admin", "college_admin", "faculty"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    student_exam = await StudentExam.get(ObjectId(student_exam_id))
    if not student_exam or student_exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Student exam not found")
    
    await student_exam.set({
        "attendance": attendance,
        "attendance_marked_at": datetime.utcnow(),
        "attendance_marked_by": current_user.id,
        "updated_at": datetime.utcnow()
    })
    
    # Update subject exam appeared count
    if attendance == "present":
        subject_exam = await SubjectExam.get(student_exam.subject_exam_id)
        if subject_exam:
            await subject_exam.inc({SubjectExam.appeared_students: 1})
    
    return {"message": "Attendance marked successfully"}


@router.post("/subjects/{subject_exam_id}/bulk-attendance", response_model=dict)
async def bulk_mark_attendance(
    subject_exam_id: str,
    attendance_data: List[dict],  # [{"student_exam_id": "...", "attendance": "present"}]
    current_user: User = Depends(get_current_user)
):
    """Bulk mark attendance for all students in subject exam"""
    if current_user.role not in ["super_admin", "college_admin", "faculty"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    subject_exam = await SubjectExam.get(ObjectId(subject_exam_id))
    if not subject_exam or subject_exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Subject exam not found")
    
    updated_count = 0
    present_count = 0
    
    for item in attendance_data:
        student_exam = await StudentExam.get(ObjectId(item["student_exam_id"]))
        if student_exam and student_exam.subject_exam_id == subject_exam.id:
            await student_exam.set({
                "attendance": item["attendance"],
                "attendance_marked_at": datetime.utcnow(),
                "attendance_marked_by": current_user.id,
                "updated_at": datetime.utcnow()
            })
            updated_count += 1
            if item["attendance"] == "present":
                present_count += 1
    
    # Update subject exam appeared count
    await subject_exam.set({
        "appeared_students": present_count,
        "updated_at": datetime.utcnow()
    })
    
    return {
        "message": "Bulk attendance marked successfully",
        "updated_count": updated_count,
        "present_count": present_count
    }


# ============================================================================
# MARKS ENTRY
# ============================================================================

@router.patch("/student-exams/{student_exam_id}/marks", response_model=dict)
async def enter_marks(
    student_exam_id: str,
    internal_marks: Optional[float] = None,
    external_marks: Optional[float] = None,
    remarks: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Enter marks for student exam (Faculty only)"""
    if current_user.role not in ["super_admin", "college_admin", "faculty"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    student_exam = await StudentExam.get(ObjectId(student_exam_id))
    if not student_exam or student_exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Student exam not found")
    
    # Get subject exam for max marks validation
    subject_exam = await SubjectExam.get(student_exam.subject_exam_id)
    if not subject_exam:
        raise HTTPException(status_code=404, detail="Subject exam not found")
    
    update_data = {"updated_at": datetime.utcnow()}
    
    if internal_marks is not None:
        max_internal = subject_exam.max_marks * (subject_exam.internal_marks_weight / 100)
        if internal_marks > max_internal:
            raise HTTPException(status_code=400, detail=f"Internal marks cannot exceed {max_internal}")
        update_data["internal_marks"] = internal_marks
        update_data["internal_marks_entered_by"] = current_user.id
        update_data["internal_marks_entered_at"] = datetime.utcnow()
    
    if external_marks is not None:
        max_external = subject_exam.max_marks * (subject_exam.external_marks_weight / 100)
        if external_marks > max_external:
            raise HTTPException(status_code=400, detail=f"External marks cannot exceed {max_external}")
        update_data["external_marks"] = external_marks
        update_data["external_marks_entered_by"] = current_user.id
        update_data["external_marks_entered_at"] = datetime.utcnow()
    
    if remarks:
        update_data["remarks"] = remarks
    
    # Calculate total marks and grade
    current_internal = internal_marks if internal_marks is not None else student_exam.internal_marks or 0
    current_external = external_marks if external_marks is not None else student_exam.external_marks or 0
    total_marks = current_internal + current_external
    
    update_data["total_marks"] = total_marks
    
    # Calculate grade
    grade_scale = await GradeScale.find_one(
        GradeScale.college_id == current_user.college_id,
        GradeScale.is_active == True
    )
    
    if grade_scale:
        grade, grade_points = await calculate_grade(total_marks, grade_scale)
        update_data["grade"] = grade
        update_data["grade_points"] = grade_points
        update_data["result_status"] = "pass" if grade_points >= grade_scale.passing_grade_points else "fail"
    
    await student_exam.set(update_data)
    
    return {"message": "Marks entered successfully", "total_marks": total_marks}


@router.post("/subjects/{subject_exam_id}/bulk-marks", response_model=dict)
async def bulk_upload_marks(
    subject_exam_id: str,
    marks_data: List[dict],  # [{"student_exam_id": "...", "internal_marks": 28, "external_marks": 65}]
    current_user: User = Depends(get_current_user)
):
    """Bulk upload marks for all students in subject exam"""
    if current_user.role not in ["super_admin", "college_admin", "faculty"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    subject_exam = await SubjectExam.get(ObjectId(subject_exam_id))
    if not subject_exam or subject_exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Subject exam not found")
    
    # Get grade scale
    grade_scale = await GradeScale.find_one(
        GradeScale.college_id == current_user.college_id,
        GradeScale.is_active == True
    )
    
    if not grade_scale:
        raise HTTPException(status_code=400, detail="No active grade scale found")
    
    updated_count = 0
    passed_count = 0
    
    for item in marks_data:
        student_exam = await StudentExam.get(ObjectId(item["student_exam_id"]))
        if not student_exam or student_exam.subject_exam_id != subject_exam.id:
            continue
        
        internal_marks = item.get("internal_marks", 0)
        external_marks = item.get("external_marks", 0)
        total_marks = internal_marks + external_marks
        
        grade, grade_points = await calculate_grade(total_marks, grade_scale)
        result_status = "pass" if grade_points >= grade_scale.passing_grade_points else "fail"
        
        await student_exam.set({
            "internal_marks": internal_marks,
            "external_marks": external_marks,
            "total_marks": total_marks,
            "grade": grade,
            "grade_points": grade_points,
            "result_status": result_status,
            "internal_marks_entered_by": current_user.id,
            "external_marks_entered_by": current_user.id,
            "internal_marks_entered_at": datetime.utcnow(),
            "external_marks_entered_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })
        
        updated_count += 1
        if result_status == "pass":
            passed_count += 1
    
    # Update subject exam statistics
    await subject_exam.set({
        "passed_students": passed_count,
        "updated_at": datetime.utcnow()
    })
    
    return {
        "message": "Marks uploaded successfully",
        "updated_count": updated_count,
        "passed_count": passed_count
    }


# ============================================================================
# RESULT CALCULATION AND PUBLISHING
# ============================================================================

@router.post("/{exam_id}/calculate-results", response_model=dict)
async def calculate_exam_results(
    exam_id: str,
    current_user: User = Depends(get_current_user)
):
    """Calculate and generate results for all students (College Admin only)"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    exam = await Exam.get(ObjectId(exam_id))
    if not exam or exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    # Get all student exams for this exam
    student_exams = await StudentExam.find(
        StudentExam.exam_id == exam.id
    ).to_list()
    
    if not student_exams:
        raise HTTPException(status_code=400, detail="No student exams found")
    
    # Group by student
    student_results_map = {}
    for se in student_exams:
        student_id = str(se.student_id)
        if student_id not in student_results_map:
            student_results_map[student_id] = {
                "student_id": se.student_id,
                "student_name": se.student_name,
                "student_roll_number": se.student_roll_number,
                "subjects": []
            }
        
        # Get subject exam details
        subject_exam = await SubjectExam.get(se.subject_exam_id)
        if subject_exam:
            student_results_map[student_id]["subjects"].append(
                SubjectResult(
                    subject_exam_id=subject_exam.id,
                    subject_name=subject_exam.subject_name,
                    subject_code=subject_exam.subject_code,
                    credits=subject_exam.credits,
                    internal_marks=se.internal_marks,
                    external_marks=se.external_marks,
                    total_marks=se.total_marks,
                    grade=se.grade,
                    grade_points=se.grade_points,
                    result_status=se.result_status or "pending"
                )
            )
    
    # Calculate results for each student
    results_created = 0
    
    for student_id, data in student_results_map.items():
        # Check if result already exists
        existing_result = await ExamResult.find_one(
            ExamResult.exam_id == exam.id,
            ExamResult.student_id == ObjectId(student_id)
        )
        
        # Calculate statistics
        total_subjects = len(data["subjects"])
        subjects_passed = sum(1 for s in data["subjects"] if s.result_status == "pass")
        subjects_failed = sum(1 for s in data["subjects"] if s.result_status == "fail")
        
        total_credits = sum(s.credits for s in data["subjects"])
        credits_earned = sum(s.credits for s in data["subjects"] if s.result_status == "pass")
        
        # Calculate SGPA
        sgpa = await calculate_sgpa(data["subjects"])
        
        # Calculate CGPA
        cgpa = await calculate_cgpa(ObjectId(student_id), sgpa, credits_earned)
        
        # Calculate percentage
        total_marks_obtained = sum(s.total_marks or 0 for s in data["subjects"])
        max_possible_marks = total_subjects * 100  # Assuming 100 max per subject
        percentage = (total_marks_obtained / max_possible_marks) * 100 if max_possible_marks > 0 else 0
        
        # Determine overall result status
        result_status = "pass" if subjects_failed == 0 else "fail"
        has_backlogs = subjects_failed > 0
        
        if existing_result:
            # Update existing result
            await existing_result.set({
                "subjects": [s.dict() for s in data["subjects"]],
                "total_subjects": total_subjects,
                "subjects_passed": subjects_passed,
                "subjects_failed": subjects_failed,
                "total_credits": total_credits,
                "credits_earned": credits_earned,
                "sgpa": sgpa,
                "cgpa": cgpa,
                "percentage": round(percentage, 2),
                "result_status": result_status,
                "has_backlogs": has_backlogs,
                "backlog_count": subjects_failed,
                "updated_at": datetime.utcnow()
            })
        else:
            # Create new result
            result = ExamResult(
                exam_id=exam.id,
                student_id=ObjectId(student_id),
                student_name=data["student_name"],
                student_roll_number=data["student_roll_number"],
                academic_year=exam.academic_year,
                semester=exam.semester,
                branch="",  # Will be populated from student record
                subjects=data["subjects"],
                total_subjects=total_subjects,
                subjects_passed=subjects_passed,
                subjects_failed=subjects_failed,
                total_credits=total_credits,
                credits_earned=credits_earned,
                sgpa=sgpa,
                cgpa=cgpa,
                percentage=round(percentage, 2),
                result_status=result_status,
                has_backlogs=has_backlogs,
                backlog_count=subjects_failed,
                college_id=current_user.college_id
            )
            await result.insert()
            results_created += 1
    
    return {
        "message": "Results calculated successfully",
        "results_created": results_created,
        "total_students": len(student_results_map)
    }


@router.post("/{exam_id}/publish-results", response_model=dict)
async def publish_results(
    exam_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """Publish results to students (College Admin only)"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    exam = await Exam.get(ObjectId(exam_id))
    if not exam or exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    # Get all unpublished results
    results = await ExamResult.find(
        ExamResult.exam_id == exam.id,
        ExamResult.is_published == False
    ).to_list()
    
    if not results:
        raise HTTPException(status_code=400, detail="No results to publish")
    
    # Publish all results
    for result in results:
        await result.set({
            "is_published": True,
            "published_at": datetime.utcnow(),
            "published_by": current_user.id,
            "updated_at": datetime.utcnow()
        })
    
    # Update exam
    await exam.set({
        "results_published": True,
        "published_at": datetime.utcnow(),
        "status": "completed",
        "updated_at": datetime.utcnow()
    })

    # Auto-notify students and parents that results are published
    background_tasks.add_task(
        notify_results_published,
        college_id=exam.college_id,
        exam_name=exam.name,
        created_by=current_user.id,
    )

    return {
        "message": "Results published successfully",
        "count": len(results)
    }


@router.get("/students/{student_id}/results/{exam_id}", response_model=dict)
async def get_student_result(
    student_id: str,
    exam_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get student exam result"""
    # Authorization check
    if current_user.role == "student" and str(current_user.id) != student_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    result = await ExamResult.find_one(
        ExamResult.exam_id == ObjectId(exam_id),
        ExamResult.student_id == ObjectId(student_id)
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    
    # Students can only see published results
    if current_user.role == "student" and not result.is_published:
        raise HTTPException(status_code=404, detail="Result not published yet")
    
    return {
        "id": str(result.id),
        "exam_id": str(result.exam_id),
        "student_name": result.student_name,
        "student_roll_number": result.student_roll_number,
        "academic_year": result.academic_year,
        "semester": result.semester,
        "branch": result.branch,
        "subjects": [
            {
                "subject_name": s.subject_name,
                "subject_code": s.subject_code,
                "credits": s.credits,
                "internal_marks": s.internal_marks,
                "external_marks": s.external_marks,
                "total_marks": s.total_marks,
                "grade": s.grade,
                "grade_points": s.grade_points,
                "result_status": s.result_status
            }
            for s in result.subjects
        ],
        "total_subjects": result.total_subjects,
        "subjects_passed": result.subjects_passed,
        "subjects_failed": result.subjects_failed,
        "total_credits": result.total_credits,
        "credits_earned": result.credits_earned,
        "sgpa": result.sgpa,
        "cgpa": result.cgpa,
        "percentage": result.percentage,
        "result_status": result.result_status,
        "has_backlogs": result.has_backlogs,
        "backlog_count": result.backlog_count,
        "is_published": result.is_published,
        "published_at": result.published_at.isoformat() if result.published_at else None
    }


@router.get("/students/{student_id}/all-results", response_model=List[dict])
async def get_all_student_results(
    student_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get all exam results for a student"""
    if current_user.role == "student" and str(current_user.id) != student_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query_filters = [ExamResult.student_id == ObjectId(student_id)]
    
    # Students can only see published results
    if current_user.role == "student":
        query_filters.append(ExamResult.is_published == True)
    
    results = await ExamResult.find(*query_filters).sort("-semester").to_list()
    
    return [
        {
            "id": str(r.id),
            "exam_id": str(r.exam_id),
            "academic_year": r.academic_year,
            "semester": r.semester,
            "sgpa": r.sgpa,
            "cgpa": r.cgpa,
            "percentage": r.percentage,
            "result_status": r.result_status,
            "has_backlogs": r.has_backlogs,
            "backlog_count": r.backlog_count,
            "total_subjects": r.total_subjects,
            "subjects_passed": r.subjects_passed,
            "is_published": r.is_published
        }
        for r in results
    ]


# ============================================================================
# GRADE SCALE ENDPOINTS
# ============================================================================

@router.post("/grade-scales", response_model=dict)
async def create_grade_scale(
    scale_name: str,
    description: str,
    ranges: List[dict],
    max_grade_points: float = 10.0,
    passing_grade_points: float = 4.0,
    current_user: User = Depends(get_current_user)
):
    """Create grade scale (College Admin only)"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Convert dict ranges to GradeRange objects
    grade_ranges = [
        GradeRange(
            grade=r["grade"],
            min_marks=r["min_marks"],
            max_marks=r["max_marks"],
            grade_points=r["grade_points"],
            description=r["description"]
        )
        for r in ranges
    ]
    
    # Deactivate existing active scales
    existing_scales = await GradeScale.find(
        GradeScale.college_id == current_user.college_id,
        GradeScale.is_active == True
    ).to_list()
    
    for scale in existing_scales:
        await scale.set({"is_active": False, "effective_to": datetime.utcnow()})
    
    # Create new scale
    grade_scale = GradeScale(
        college_id=current_user.college_id,
        scale_name=scale_name,
        description=description,
        ranges=grade_ranges,
        max_grade_points=max_grade_points,
        passing_grade_points=passing_grade_points,
        is_active=True,
        created_by=current_user.id
    )
    
    await grade_scale.insert()
    
    return {"id": str(grade_scale.id), "message": "Grade scale created successfully"}


@router.get("/grade-scales/active", response_model=dict)
async def get_active_grade_scale(
    current_user: User = Depends(get_current_user)
):
    """Get active grade scale for college"""
    grade_scale = await GradeScale.find_one(
        GradeScale.college_id == current_user.college_id,
        GradeScale.is_active == True
    )
    
    if not grade_scale:
        raise HTTPException(status_code=404, detail="No active grade scale found")
    
    return {
        "id": str(grade_scale.id),
        "scale_name": grade_scale.scale_name,
        "description": grade_scale.description,
        "ranges": [
            {
                "grade": r.grade,
                "min_marks": r.min_marks,
                "max_marks": r.max_marks,
                "grade_points": r.grade_points,
                "description": r.description
            }
            for r in grade_scale.ranges
        ],
        "max_grade_points": grade_scale.max_grade_points,
        "passing_grade_points": grade_scale.passing_grade_points
    }


# ============================================================================
# ANALYTICS ENDPOINTS
# ============================================================================

@router.get("/analytics/college-stats", response_model=dict)
async def get_college_exam_analytics(
    academic_year: Optional[str] = None,
    semester: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    """Get exam analytics for college (Admin only)"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    query_filters = [] if current_user.role == "super_admin" else [Exam.college_id == current_user.college_id]
    
    if academic_year:
        query_filters.append(Exam.academic_year == academic_year)
    if semester:
        query_filters.append(Exam.semester == semester)
    
    # Get exam statistics
    exams = await Exam.find(*query_filters).to_list()
    
    total_exams = len(exams)
    completed_exams = sum(1 for e in exams if e.status == "completed")
    total_students = sum(e.total_students for e in exams)
    
    # Get results statistics
    result_query_filters = [] if current_user.role == "super_admin" else [ExamResult.college_id == current_user.college_id]
    if academic_year:
        result_query_filters.append(ExamResult.academic_year == academic_year)
    if semester:
        result_query_filters.append(ExamResult.semester == semester)
    
    results = await ExamResult.find(*result_query_filters).to_list()
    
    total_results = len(results)
    passed_students = sum(1 for r in results if r.result_status == "pass")
    failed_students = sum(1 for r in results if r.result_status == "fail")
    
    pass_percentage = (passed_students / total_results * 100) if total_results > 0 else 0
    
    # Calculate average SGPA and CGPA
    sgpa_values = [r.sgpa for r in results if r.sgpa is not None]
    cgpa_values = [r.cgpa for r in results if r.cgpa is not None]
    
    avg_sgpa = sum(sgpa_values) / len(sgpa_values) if sgpa_values else 0
    avg_cgpa = sum(cgpa_values) / len(cgpa_values) if cgpa_values else 0
    
    # Students with backlogs
    students_with_backlogs = sum(1 for r in results if r.has_backlogs)
    
    return {
        "total_exams": total_exams,
        "completed_exams": completed_exams,
        "ongoing_exams": sum(1 for e in exams if e.status == "ongoing"),
        "scheduled_exams": sum(1 for e in exams if e.status == "scheduled"),
        "total_students": total_students,
        "total_results": total_results,
        "passed_students": passed_students,
        "failed_students": failed_students,
        "pass_percentage": round(pass_percentage, 2),
        "students_with_backlogs": students_with_backlogs,
        "average_sgpa": round(avg_sgpa, 2),
        "average_cgpa": round(avg_cgpa, 2)
    }


@router.get("/analytics/subject-performance", response_model=List[dict])
async def get_subject_performance(
    exam_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get subject-wise performance analytics"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    exam = await Exam.get(ObjectId(exam_id))
    if not exam or exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    # Get all subject exams
    subject_exams = await SubjectExam.find(SubjectExam.exam_id == exam.id).to_list()
    
    performance_data = []
    
    for subject_exam in subject_exams:
        # Get all student exams for this subject
        student_exams = await StudentExam.find(
            StudentExam.subject_exam_id == subject_exam.id
        ).to_list()
        
        if not student_exams:
            continue
        
        total_students = len(student_exams)
        appeared = sum(1 for se in student_exams if se.attendance == "present")
        passed = sum(1 for se in student_exams if se.result_status == "pass")
        failed = sum(1 for se in student_exams if se.result_status == "fail")
        absent = sum(1 for se in student_exams if se.attendance == "absent")
        
        # Calculate average marks
        marks_list = [se.total_marks for se in student_exams if se.total_marks is not None]
        avg_marks = sum(marks_list) / len(marks_list) if marks_list else 0
        
        # Calculate pass percentage
        pass_percentage = (passed / appeared * 100) if appeared > 0 else 0
        
        performance_data.append({
            "subject_name": subject_exam.subject_name,
            "subject_code": subject_exam.subject_code,
            "total_students": total_students,
            "appeared": appeared,
            "passed": passed,
            "failed": failed,
            "absent": absent,
            "pass_percentage": round(pass_percentage, 2),
            "average_marks": round(avg_marks, 2),
            "max_marks": subject_exam.max_marks
        })
    
    return performance_data


@router.get("/analytics/export-csv", response_model=dict)
async def export_exam_results_csv(
    exam_id: str,
    current_user: User = Depends(get_current_user)
):
    """Export exam results as CSV (Admin only)"""
    if current_user.role not in ["super_admin", "college_admin"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    exam = await Exam.get(ObjectId(exam_id))
    if not exam or exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    results = await ExamResult.find(ExamResult.exam_id == exam.id).to_list()
    
    if not results:
        raise HTTPException(status_code=404, detail="No results found")
    
    # Build CSV data
    import csv
    from io import StringIO
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "Roll Number", "Student Name", "Semester", "SGPA", "CGPA", 
        "Percentage", "Result Status", "Backlogs", "Total Credits", "Credits Earned"
    ])
    
    # Data rows
    for result in results:
        writer.writerow([
            result.student_roll_number,
            result.student_name,
            result.semester,
            result.sgpa or "N/A",
            result.cgpa or "N/A",
            result.percentage or "N/A",
            result.result_status,
            result.backlog_count,
            result.total_credits,
            result.credits_earned
        ])
    
    csv_content = output.getvalue()
    
    return {
        "filename": f"exam_results_{exam.academic_year}_sem{exam.semester}.csv",
        "content": csv_content,
        "rows": len(results)
    }


# ============================================================================
# FACULTY SPECIFIC ENDPOINTS
# ============================================================================

@router.get("/faculty/assigned-exams", response_model=List[dict])
async def get_faculty_assigned_exams(
    current_user: User = Depends(get_current_user)
):
    """Get exams assigned to faculty for invigilation or marks entry"""
    if current_user.role != "faculty":
        raise HTTPException(status_code=403, detail="Not authorized to access faculty exams")
    
    # Get subject exams where faculty is invigilator
    # This is simplified - in production, you'd have a faculty assignment table
    subject_exams = await SubjectExam.find(
        SubjectExam.college_id == current_user.college_id,
        {"status": {"$in": ["scheduled", "ongoing", "completed"]}}
    ).limit(50).to_list()
    
    return [
        {
            "id": str(se.id),
            "exam_id": str(se.exam_id),
            "subject_name": se.subject_name,
            "subject_code": se.subject_code,
            "exam_date": se.exam_date.isoformat(),
            "start_time": se.start_time.isoformat(),
            "end_time": se.end_time.isoformat(),
            "room_numbers": se.room_numbers,
            "enrolled_students": se.enrolled_students,
            "appeared_students": se.appeared_students,
            "status": se.status
        }
        for se in subject_exams
    ]


@router.get("/subjects/{subject_exam_id}/students", response_model=List[dict])
async def get_subject_exam_students(
    subject_exam_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get all students for a subject exam (Faculty/Admin)"""
    if current_user.role not in ["super_admin", "college_admin", "faculty"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    subject_exam = await SubjectExam.get(ObjectId(subject_exam_id))
    if not subject_exam or subject_exam.college_id != current_user.college_id:
        raise HTTPException(status_code=404, detail="Subject exam not found")
    
    student_exams = await StudentExam.find(
        StudentExam.subject_exam_id == subject_exam.id
    ).to_list()
    
    return [
        {
            "id": str(se.id),
            "student_id": str(se.student_id),
            "student_name": se.student_name,
            "student_roll_number": se.student_roll_number,
            "hall_ticket_number": se.hall_ticket_number,
            "seat_number": se.seat_number,
            "room_number": se.room_number,
            "attendance": se.attendance,
            "internal_marks": se.internal_marks,
            "external_marks": se.external_marks,
            "total_marks": se.total_marks,
            "grade": se.grade,
            "result_status": se.result_status
        }
        for se in student_exams
    ]
