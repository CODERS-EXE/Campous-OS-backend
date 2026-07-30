from datetime import datetime, timezone
from typing import List, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BookCategory(Document):
    college_id: PydanticObjectId
    name: str  # e.g., "Science", "Engineering", "Fiction"
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "book_categories"
        indexes = ["college_id"]


class Book(Document):
    college_id: PydanticObjectId
    title: str
    author: str
    isbn: Optional[str] = None
    publisher: Optional[str] = None
    edition: Optional[str] = None
    year: Optional[int] = None
    category_id: Optional[PydanticObjectId] = None
    category_name: Optional[str] = None
    total_quantity: int = 1
    available_quantity: int = 1
    location: Optional[str] = None  # e.g., "Shelf A-3"
    description: Optional[str] = None
    cover_url: Optional[str] = None
    language: str = "English"
    status: str = "active"  # "active", "inactive"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "books"
        indexes = ["college_id", "isbn", "category_id", "status"]


class BookIssue(Document):
    college_id: PydanticObjectId
    book_id: PydanticObjectId
    book_title: str
    book_isbn: Optional[str] = None
    user_id: PydanticObjectId  # student or faculty user_id
    user_name: str
    user_role: str  # "student" or "faculty"
    issue_date: datetime = Field(default_factory=utcnow)
    due_date: datetime
    return_date: Optional[datetime] = None
    renewed_count: int = 0
    max_renewals: int = 2
    status: str = "issued"  # "issued", "returned", "overdue", "lost", "damaged"
    fine_amount: float = 0.0
    fine_paid: bool = False
    fine_paid_date: Optional[datetime] = None
    fine_reason: Optional[str] = None  # "overdue", "lost", "damaged"
    remarks: Optional[str] = None
    issued_by: Optional[str] = None  # librarian user_id
    returned_by: Optional[str] = None  # librarian user_id
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "book_issues"
        indexes = ["college_id", "book_id", "user_id", "status"]
