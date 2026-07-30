from datetime import datetime
from typing import Optional, List
from beanie import Document
from pydantic import Field, BaseModel
from bson import ObjectId


class QuestionSection(BaseModel):
    """Section within a question paper"""
    section_name: str = Field(..., description="Section name (A, B, C, etc.)")
    instructions: str = Field(..., description="Section-specific instructions")
    marks: int = Field(..., ge=0, description="Marks for this section")


class QuestionPaper(Document):
    """
    QuestionPaper model for storing question paper metadata
    Actual paper files stored in cloud storage
    """
    subject_exam_id: ObjectId = Field(..., description="Reference to SubjectExam")
    
    # Paper details
    paper_code: str = Field(..., description="Unique paper code")
    paper_title: str = Field(..., description="Question paper title")
    paper_url: Optional[str] = Field(None, description="Cloud storage URL for paper PDF")
    
    # Structure
    total_marks: int = Field(..., ge=0, description="Total marks")
    total_questions: int = Field(default=0, ge=0, description="Total number of questions")
    sections: List[QuestionSection] = Field(default_factory=list, description="Paper sections")
    
    # Instructions
    general_instructions: str = Field(default="", description="General instructions for students")
    time_allowed_minutes: int = Field(..., ge=30, description="Time allowed in minutes")
    
    # Question types
    has_objective: bool = Field(default=False, description="Has MCQ/objective questions")
    has_subjective: bool = Field(default=True, description="Has descriptive questions")
    has_practical: bool = Field(default=False, description="Has practical component")
    
    # Access control
    is_confidential: bool = Field(default=True, description="Paper confidentiality flag")
    accessible_from: Optional[datetime] = Field(None, description="When students can access")
    
    # Multi-tenant
    college_id: ObjectId = Field(..., description="College reference")
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    uploaded_by: Optional[ObjectId] = Field(None, description="Faculty who uploaded")
    
    class Settings:
        name = "question_papers"
        indexes = [
            "subject_exam_id",
            "paper_code",
            "college_id",
        ]

    class Config:
        json_schema_extra = {
            "example": {
                "subject_exam_id": "507f1f77bcf86cd799439013",
                "paper_code": "CS301-MT-2024",
                "paper_title": "Data Structures - Mid Term",
                "total_marks": 100,
                "total_questions": 10,
                "time_allowed_minutes": 180,
                "general_instructions": "Answer all questions. Use of calculators not allowed."
            }
        }
