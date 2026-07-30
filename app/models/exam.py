from datetime import datetime
from typing import Optional
from beanie import Document
from pydantic import Field
from bson import ObjectId


class Exam(Document):
    """
    Exam model for managing exam schedules
    Represents a complete examination (Mid-term, End-term, etc.)
    """
    name: str = Field(..., description="Exam name (e.g., Mid-Term Exam, End-Term Exam)")
    exam_type: str = Field(..., description="Type: internal, mid_term, end_term, supplementary")
    academic_year: str = Field(..., description="Academic year (e.g., 2023-2024)")
    semester: int = Field(..., ge=1, le=8, description="Semester number (1-8)")
    start_date: datetime = Field(..., description="Exam start date")
    end_date: datetime = Field(..., description="Exam end date")
    status: str = Field(default="scheduled", description="Status: scheduled, ongoing, completed, cancelled")
    description: Optional[str] = Field(None, description="Exam description and instructions")
    
    # Multi-tenant
    college_id: ObjectId = Field(..., description="College reference")
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[ObjectId] = Field(None, description="Admin who created")
    
    # Statistics
    total_subjects: int = Field(default=0, description="Number of subjects in exam")
    total_students: int = Field(default=0, description="Number of students enrolled")
    results_published: bool = Field(default=False, description="Whether results are published")
    published_at: Optional[datetime] = Field(None, description="Result publication timestamp")
    
    class Settings:
        name = "exams"
        indexes = [
            "college_id",
            "status",
            "academic_year",
            "semester",
            [("college_id", 1), ("academic_year", 1), ("semester", 1)],
        ]

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Mid-Term Exam - Fall 2024",
                "exam_type": "mid_term",
                "academic_year": "2023-2024",
                "semester": 5,
                "start_date": "2024-03-01T09:00:00Z",
                "end_date": "2024-03-15T17:00:00Z",
                "status": "scheduled",
                "description": "Mid-term examination for all departments"
            }
        }
