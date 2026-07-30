from datetime import datetime
from typing import List
from beanie import Document
from pydantic import Field, BaseModel
from bson import ObjectId


class GradeRange(BaseModel):
    """Individual grade range in grading scale"""
    grade: str = Field(..., description="Letter grade (A+, A, B+, etc.)")
    min_marks: float = Field(..., ge=0, description="Minimum marks for this grade")
    max_marks: float = Field(..., ge=0, description="Maximum marks for this grade")
    grade_points: float = Field(..., ge=0, description="Grade points (for GPA calculation)")
    description: str = Field(..., description="Grade description (Excellent, Good, etc.)")


class GradeScale(Document):
    """
    GradeScale model for configurable grading system
    Defines how marks are converted to grades and grade points
    """
    college_id: ObjectId = Field(..., description="College reference")
    
    # Scale details
    scale_name: str = Field(..., description="Name of grading scale (e.g., 10-Point Scale)")
    description: str = Field(default="", description="Description of the scale")
    
    # Grading ranges
    ranges: List[GradeRange] = Field(..., description="Grade ranges from highest to lowest")
    
    # Scale configuration
    max_grade_points: float = Field(default=10.0, description="Maximum grade points (usually 10 or 4)")
    passing_grade_points: float = Field(default=4.0, description="Minimum grade points to pass")
    
    # Status
    is_active: bool = Field(default=True, description="Whether this scale is currently active")
    effective_from: datetime = Field(default_factory=datetime.utcnow, description="Effective from date")
    effective_to: Optional[datetime] = Field(None, description="Effective until date")
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[ObjectId] = Field(None, description="Admin who created")
    
    class Settings:
        name = "grade_scales"
        indexes = [
            "college_id",
            "is_active",
            [("college_id", 1), ("is_active", 1)],
        ]

    class Config:
        json_schema_extra = {
            "example": {
                "scale_name": "10-Point Grading Scale",
                "description": "Standard 10-point grading system",
                "ranges": [
                    {
                        "grade": "A+",
                        "min_marks": 90,
                        "max_marks": 100,
                        "grade_points": 10.0,
                        "description": "Outstanding"
                    },
                    {
                        "grade": "A",
                        "min_marks": 80,
                        "max_marks": 89,
                        "grade_points": 9.0,
                        "description": "Excellent"
                    },
                    {
                        "grade": "B+",
                        "min_marks": 70,
                        "max_marks": 79,
                        "grade_points": 8.0,
                        "description": "Very Good"
                    },
                    {
                        "grade": "B",
                        "min_marks": 60,
                        "max_marks": 69,
                        "grade_points": 7.0,
                        "description": "Good"
                    },
                    {
                        "grade": "C",
                        "min_marks": 50,
                        "max_marks": 59,
                        "grade_points": 6.0,
                        "description": "Average"
                    },
                    {
                        "grade": "D",
                        "min_marks": 40,
                        "max_marks": 49,
                        "grade_points": 5.0,
                        "description": "Pass"
                    },
                    {
                        "grade": "F",
                        "min_marks": 0,
                        "max_marks": 39,
                        "grade_points": 0.0,
                        "description": "Fail"
                    }
                ],
                "max_grade_points": 10.0,
                "passing_grade_points": 5.0
            }
        }
