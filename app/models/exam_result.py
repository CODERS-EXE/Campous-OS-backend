from datetime import datetime
from typing import Optional, List
from beanie import Document, PydanticObjectId
from pydantic import Field, BaseModel


class SubjectResult(BaseModel):
    """Individual subject result within semester"""
    subject_exam_id: PydanticObjectId
    subject_name: str
    subject_code: str
    credits: int
    internal_marks: Optional[float] = None
    external_marks: Optional[float] = None
    total_marks: Optional[float] = None
    grade: Optional[str] = None
    grade_points: Optional[float] = None
    result_status: str = "pending"  # pass, fail, absent


class ExamResult(Document):
    """
    ExamResult model for consolidated semester results
    Stores overall performance with SGPA/CGPA
    """
    exam_id: PydanticObjectId = Field(..., description="Reference to Exam")
    student_id: PydanticObjectId = Field(..., description="Reference to Student")
    
    # Student details (denormalized)
    student_name: str = Field(..., description="Student name")
    student_roll_number: str = Field(..., description="Student roll number")
    student_email: Optional[str] = Field(None, description="Student email")
    
    # Academic info
    academic_year: str = Field(..., description="Academic year")
    semester: int = Field(..., ge=1, le=8, description="Semester number")
    branch: str = Field(..., description="Student branch/department")
    
    # Subjects
    subjects: List[SubjectResult] = Field(default_factory=list, description="Subject-wise results")
    total_subjects: int = Field(default=0, description="Total subjects")
    subjects_passed: int = Field(default=0, description="Number of subjects passed")
    subjects_failed: int = Field(default=0, description="Number of subjects failed")
    
    # Credits
    total_credits: int = Field(default=0, description="Total credits for semester")
    credits_earned: int = Field(default=0, description="Credits earned (passed subjects)")
    
    # GPA calculation
    sgpa: Optional[float] = Field(None, ge=0, le=10, description="Semester Grade Point Average")
    cgpa: Optional[float] = Field(None, ge=0, le=10, description="Cumulative Grade Point Average")
    percentage: Optional[float] = Field(None, ge=0, le=100, description="Overall percentage")
    
    # Status
    result_status: str = Field(default="pending", description="Status: pass, fail, pending, withheld")
    has_backlogs: bool = Field(default=False, description="Whether student has backlogs")
    backlog_count: int = Field(default=0, description="Number of backlogs")
    
    # Publication
    is_published: bool = Field(default=False, description="Whether result is published to student")
    published_at: Optional[datetime] = Field(None, description="Publication timestamp")
    published_by: Optional[PydanticObjectId] = Field(None, description="Admin who published")
    
    # Ranking
    rank: Optional[int] = Field(None, description="Rank in class/semester")
    
    # Multi-tenant
    college_id: PydanticObjectId = Field(..., description="College reference")
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Settings:
        name = "exam_results"
        indexes = [
            "exam_id",
            "student_id",
            "college_id",
            "is_published",
            [("exam_id", 1), ("student_id", 1)],
            [("college_id", 1), ("academic_year", 1), ("semester", 1)],
        ]

    class Config:
        json_schema_extra = {
            "example": {
                "exam_id": "507f1f77bcf86cd799439011",
                "student_id": "507f1f77bcf86cd799439014",
                "student_name": "John Doe",
                "student_roll_number": "CS2020001",
                "academic_year": "2023-2024",
                "semester": 5,
                "branch": "Computer Science",
                "total_subjects": 6,
                "subjects_passed": 5,
                "subjects_failed": 1,
                "total_credits": 24,
                "credits_earned": 20,
                "sgpa": 8.5,
                "cgpa": 8.2,
                "percentage": 85.0,
                "result_status": "pass",
                "has_backlogs": True,
                "backlog_count": 1
            }
        }
