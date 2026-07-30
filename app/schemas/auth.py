from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    college_subdomain: Optional[str] = None


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=8)
    role: str = "student"
    college_subdomain: str
    roll_no: Optional[str] = None
    department: Optional[str] = None
    year: Optional[int] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str
    college_id: Optional[str] = None
    profile: dict
    is_verified: bool

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    tokens: TokenResponse
    user: UserResponse
    college: Optional[dict] = None
