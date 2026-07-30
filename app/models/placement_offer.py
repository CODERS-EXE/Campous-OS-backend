"""
Placement Offer Model
Tracks job offers made to students
"""
from datetime import datetime, timezone, date
from typing import Optional, Literal

from beanie import Document, PydanticObjectId
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PlacementOffer(Document):
    """Job offer made to a student"""
    college_id: PydanticObjectId
    drive_id: PydanticObjectId
    student_id: PydanticObjectId
    application_id: PydanticObjectId
    company_id: PydanticObjectId
    
    # Student details
    student_name: str
    student_roll_no: str
    student_department: str
    student_email: str
    
    # Offer details
    role: str
    location: str
    package_ctc: float  # in LPA
    base_salary: Optional[float] = None
    joining_bonus: Optional[float] = None
    
    # Dates
    offer_date: datetime = Field(default_factory=utcnow)
    offer_valid_till: Optional[date] = None
    expected_joining_date: Optional[date] = None
    actual_joining_date: Optional[date] = None
    
    # Documents
    offer_letter_url: Optional[str] = None
    acceptance_letter_url: Optional[str] = None
    
    # Offer status
    status: Literal[
        "pending",
        "sent",
        "accepted",
        "rejected",
        "withdrawn",
        "expired",
        "joined"
    ] = "pending"
    
    # Additional details
    bond_duration_months: Optional[int] = None
    probation_period_months: Optional[int] = None
    remarks: Optional[str] = None
    rejection_reason: Optional[str] = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=utcnow)
    accepted_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utcnow)
    
    # Metadata
    created_by: Optional[PydanticObjectId] = None
    
    class Settings:
        name = "placement_offers"
        indexes = [
            "college_id",
            "drive_id",
            "student_id",
            "company_id",
            "status",
            "offer_date",
            [("college_id", 1), ("status", 1)],
            [("student_id", 1), ("offer_date", -1)],
            [("drive_id", 1), ("status", 1)],
            [("company_id", 1), ("status", 1)]
        ]
