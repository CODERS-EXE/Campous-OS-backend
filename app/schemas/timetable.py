from pydantic import BaseModel, field_validator
from typing import Optional


def _norm_time(v: str) -> str:
    """Normalise HH:MM or HH:MM:SS to HH:MM."""
    if v and len(v) == 8 and v.count(":") == 2:
        return v[:5]
    return v


class TimetableCreate(BaseModel):
    faculty_id: str
    subject: str
    classroom: Optional[str] = None
    day_of_week: int          # 0 = Monday … 6 = Sunday
    start_time: str           # "HH:MM"
    end_time: str             # "HH:MM"

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def normalise_time(cls, v):
        return _norm_time(str(v))


class TimetableUpdate(BaseModel):
    subject:     Optional[str] = None
    classroom:   Optional[str] = None
    day_of_week: Optional[int] = None
    start_time:  Optional[str] = None
    end_time:    Optional[str] = None

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def normalise_time(cls, v):
        if v is None:
            return v
        return _norm_time(str(v))


class TimetableOut(BaseModel):
    id: str
    faculty_id: str
    subject: str
    classroom: Optional[str] = None
    day_of_week: int
    start_time: str
    end_time: str
    college_id: Optional[str] = None
    created_at: Optional[str] = None
