from datetime import datetime
from typing import Optional
from beanie import Document, PydanticObjectId
from pydantic import Field


class StudentExam(Document):
    """
    StudentExam model for tracking individual student's exam participation and marks
    Represents a student's attempt at a specific subject exam
    """
    subject_exam_id: PydanticObjectId = Field(..., description="Reference to SubjectExam")
    exam_id: PydanticObjectId = Field(..., description="Reference to parent Exam")
    student_id: PydanticObjectId = Field(..., description="Reference to Student")
    
    # Student details (denormalized for quick access)
    student_name: str = Field(..., description="Student name")
    student_roll_number: str = Field(..., description="Student roll number")
    
    # Hall ticket
    hall_ticket_number: str = Field(..., description="Generated hall ticket number")
    seat_number: Optional[str] = Field(None, description="Assigned seat number")
    room_number: Optional[str] = Field(None, description="Assigned exam room")
    
    # Attendance
    attendance: str = Field(default="not_marked", description="Attendance: present, absent, not_marked")
    attendance_marked_at: Optional[datetime] = Field(None, description="When attendance was marked")
    attendance_marked_by: Optional[PydanticObjectId] = Field(None, description="Faculty who marked")
    
    # Marks
    internal_marks: Optional[float] = Field(None, ge=0, description="Internal assessment marks")
    external_marks: Optional[float] = Field(None, ge=0, description="External exam marks")
    total_marks: Optional[float] = Field(None, ge=0, description="Total marks (internal + external)")
    
    # Grading
    grade: Optional[str] = Field(None, description="Letter grade (A, B, C, etc.)")
    grade_points: Optional[float] = Field(None, ge=0, description="Grade points for GPA calculation")
    result_status: str = Field(default="pending", description="Status: pass, fail, absent, pending")
    
    # Marks entry tracking
    internal_marks_entered_by: Optional[PydanticObjectId] = Field(None, description="Faculty who entered internal marks")
    external_marks_entered_by: Optional[PydanticObjectId] = Field(None, description="Faculty who entered external marks")
    internal_marks_entered_at: Optional[datetime] = Field(None)
    external_marks_entered_at: Optional[datetime] = Field(None)
    
    # Additional info
    remarks: Optional[str] = Field(None, description="Additional remarks or notes")
    is_improvement_exam: bool = Field(default=False, description="Is this an improvement attempt")
    attempt_number: int = Field(default=1, ge=1, description="Exam attempt number")
    
    # Multi-tenant
    college_id: PydanticObjectId = Field(..., description="College reference")
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Settings:
        name = "student_exams"
        indexes = [
            "subject_exam_id",
            "exam_id",
            "student_id",
            "hall_ticket_number",
            "college_id",
            [("exam_id", 1), ("student_id", 1)],
            [("subject_exam_id", 1), ("student_id", 1)],
        ]

    class Config:
        json_schema_extra = {
            "example": {
                "subject_exam_id": "507f1f77bcf86cd799439013",
                "exam_id": "507f1f77bcf86cd799439011",
                "student_id": "507f1f77bcf86cd799439014",
                "student_name": "John Doe",
                "student_roll_number": "CS2020001",
                "hall_ticket_number": "HT202400001",
                "seat_number": "A-15",
                "room_number": "Hall-A",
                "attendance": "present",
                "internal_marks": 28.5,
                "external_marks": 65.0,
                "total_marks": 93.5,
                "grade": "A",
                "grade_points": 9.0,
                "result_status": "pass"
            }
        }
