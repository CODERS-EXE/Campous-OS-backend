from datetime import datetime, time
from typing import Optional, List
from beanie import Document
from pydantic import Field
from bson import ObjectId


class SubjectExam(Document):
    """
    SubjectExam model for individual subject examination scheduling
    Each exam has multiple subject exams
    """
    exam_id: ObjectId = Field(..., description="Reference to parent Exam")
    subject_id: ObjectId = Field(..., description="Reference to Subject")
    subject_name: str = Field(..., description="Subject name for quick access")
    subject_code: str = Field(..., description="Subject code")
    
    # Scheduling
    exam_date: datetime = Field(..., description="Date of subject exam")
    start_time: time = Field(..., description="Exam start time")
    end_time: time = Field(..., description="Exam end time")
    duration_minutes: int = Field(..., ge=30, description="Exam duration in minutes")
    
    # Venue
    room_numbers: List[str] = Field(default_factory=list, description="Exam hall/room numbers")
    invigilators: List[str] = Field(default_factory=list, description="Invigilator names")
    
    # Marks
    max_marks: int = Field(..., ge=0, description="Maximum marks for subject")
    internal_marks_weight: int = Field(default=30, ge=0, le=100, description="Internal marks percentage")
    external_marks_weight: int = Field(default=70, ge=0, le=100, description="External marks percentage")
    passing_marks: int = Field(..., ge=0, description="Minimum marks to pass")
    
    # Credits
    credits: int = Field(default=3, ge=1, description="Subject credit hours")
    
    # Status
    status: str = Field(default="scheduled", description="Status: scheduled, ongoing, completed, cancelled")
    
    # Multi-tenant
    college_id: ObjectId = Field(..., description="College reference")
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Statistics
    enrolled_students: int = Field(default=0, description="Number of students enrolled")
    appeared_students: int = Field(default=0, description="Number of students who appeared")
    passed_students: int = Field(default=0, description="Number of students who passed")
    
    class Settings:
        name = "subject_exams"
        indexes = [
            "exam_id",
            "subject_id",
            "college_id",
            "exam_date",
            [("exam_id", 1), ("subject_id", 1)],
        ]

    class Config:
        json_schema_extra = {
            "example": {
                "exam_id": "507f1f77bcf86cd799439011",
                "subject_id": "507f1f77bcf86cd799439012",
                "subject_name": "Data Structures",
                "subject_code": "CS301",
                "exam_date": "2024-03-05T09:00:00Z",
                "start_time": "09:00:00",
                "end_time": "12:00:00",
                "duration_minutes": 180,
                "room_numbers": ["Hall-A", "Hall-B"],
                "max_marks": 100,
                "passing_marks": 40,
                "credits": 4
            }
        }
