"""
Company Model for Placement Management
Stores information about companies visiting for campus recruitment
"""
from datetime import datetime, timezone
from typing import Optional, List

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field, HttpUrl


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CompanyContact(BaseModel):
    """Contact information for company HR/Recruiter"""
    name: str
    email: str
    phone: Optional[str] = None
    designation: Optional[str] = None


class Company(Document):
    """Company visiting for campus placements"""
    college_id: PydanticObjectId
    name: str
    description: Optional[str] = None
    website: Optional[HttpUrl] = None
    logo_url: Optional[str] = None
    
    # Company details
    industry: str  # IT, Finance, Consulting, Manufacturing, etc.
    location: str  # Headquarters location
    tier: str = "tier_2"  # tier_1, tier_2, tier_3 (for filtering)
    employee_count: Optional[int] = None
    
    # Contact information
    contacts: List[CompanyContact] = Field(default_factory=list)
    
    # Metadata
    is_active: bool = True
    created_by: Optional[PydanticObjectId] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    
    # Statistics (computed)
    total_drives: int = 0
    total_placements: int = 0
    average_package: Optional[float] = None
    highest_package: Optional[float] = None
    
    class Settings:
        name = "companies"
        indexes = [
            "college_id",
            "name",
            "industry",
            "tier",
            [("college_id", 1), ("is_active", 1)],
            [("college_id", 1), ("name", 1)]
        ]
