from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.core.constants import CollegePlan, CollegeStatus


class CollegeCreate(BaseModel):
    name: str
    subdomain: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9-]+$")
    theme_color: str = "#2563eb"
    plan: CollegePlan = CollegePlan.FREE
    admin_name: str
    admin_email: EmailStr
    admin_password: str = Field(min_length=8)


class CollegeUpdate(BaseModel):
    name: Optional[str] = None
    logo_url: Optional[str] = None
    theme_color: Optional[str] = None
    plan: Optional[CollegePlan] = None
    status: Optional[CollegeStatus] = None


class CollegeResponse(BaseModel):
    id: str
    name: str
    subdomain: str
    logo_url: Optional[str] = None
    theme_color: str
    plan: str
    status: str
    created_at: datetime
