"""
Placement Drive Model
Represents a recruitment drive organized by a company at a college
"""
from datetime import datetime, timezone
from typing import Optional, List, Literal

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EligibilityCriteria(BaseModel):
    """Eligibility criteria for placement drive"""
    min_cgpa: float = 0.0
    allowed_branches: List[str] = Field(default_factory=list)  # ["CSE", "IT", "ECE", etc.]
    max_backlogs: int = 0
    max_gap_years: int = 0
    min_percentage_10th: Optional[float] = None
    min_percentage_12th: Optional[float] = None
    year_of_study: Optional[List[int]] = None  # [3, 4] for 3rd and 4th year


class DriveLocation(BaseModel):
    """Job location details"""
    city: str
    state: Optional[str] = None
    country: str = "India"
    is_remote: bool = False
    is_hybrid: bool = False


class PackageDetails(BaseModel):
    """Salary package breakdown"""
    ctc: float  # Cost to Company (in LPA)
    base_salary: Optional[float] = None
    variable_pay: Optional[float] = None
    joining_bonus: Optional[float] = None
    stock_options: Optional[str] = None
    other_benefits: Optional[str] = None


class PlacementDrive(Document):
    """Recruitment drive for campus placements"""
    college_id: PydanticObjectId
    company_id: PydanticObjectId
    
    # Drive details
    title: str
    description: Optional[str] = None
    role: str  # Software Engineer, Data Analyst, etc.
    role_type: Literal["full_time", "internship", "both"] = "full_time"
    
    # Package
    package: PackageDetails
    
    # Location
    locations: List[DriveLocation] = Field(default_factory=list)
    
    # Eligibility
    eligibility: EligibilityCriteria = Field(default_factory=EligibilityCriteria)
    
    # Important dates
    start_date: datetime  # Registration start
    deadline: datetime  # Registration deadline
    interview_start_date: Optional[datetime] = None
    expected_joining_date: Optional[datetime] = None
    
    # Drive status
    status: Literal["draft", "open", "closed", "completed", "cancelled"] = "draft"
    
    # Additional details
    total_positions: Optional[int] = None
    job_description_url: Optional[str] = None
    selection_process: Optional[str] = None  # "Aptitude -> Technical -> HR"
    bond_duration: Optional[int] = None  # in months
    
    # Statistics
    total_applications: int = 0
    shortlisted_count: int = 0
    selected_count: int = 0
    
    # Metadata
    created_by: Optional[PydanticObjectId] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    
    class Settings:
        name = "placement_drives"
        indexes = [
            "college_id",
            "company_id",
            "status",
            "deadline",
            [("college_id", 1), ("status", 1)],
            [("college_id", 1), ("deadline", 1)],
            [("college_id", 1), ("company_id", 1)],
            [("college_id", 1), ("created_at", -1)]
        ]
