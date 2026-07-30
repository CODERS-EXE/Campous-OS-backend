from datetime import datetime, timezone
from typing import List, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FeeStructure(Document):
    college_id: PydanticObjectId
    name: str  # e.g., "Tuition Fee", "Hostel Fee", "Exam Fee"
    code: str  # e.g., "TUIT-2026"
    description: Optional[str] = None
    amount: float
    academic_year: str  # e.g., "2026-2027"
    semester: Optional[int] = None  # e.g., 1, 2 or None for full year
    department: Optional[str] = "All"
    course: Optional[str] = "All"
    status: str = "active"  # "active", "inactive"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "fee_structures"
        indexes = ["college_id", "academic_year", "code"]


class StudentFee(Document):
    college_id: PydanticObjectId
    student_id: PydanticObjectId  # Student user_id
    fee_structure_id: PydanticObjectId
    fee_name: str
    academic_year: str
    semester: Optional[int] = 1
    total_amount: float
    discount: float = 0.0
    net_amount: float
    paid_amount: float = 0.0
    due_amount: float
    status: str = "unpaid"  # "unpaid", "partially_paid", "paid"
    due_date: datetime
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "student_fees"
        indexes = ["college_id", "student_id", "fee_structure_id", "status"]


class Payment(Document):
    college_id: PydanticObjectId
    student_id: PydanticObjectId  # Student user_id
    student_fee_id: Optional[PydanticObjectId] = None
    amount: float
    payment_mode: str = "online"  # "online", "offline"
    payment_method: str = "UPI"  # "UPI", "Card", "NetBanking", "Cash", "Cheque"
    transaction_id: str
    status: str = "pending"  # "pending", "approved", "rejected"
    payment_date: datetime = Field(default_factory=utcnow)
    approved_by: Optional[str] = None  # user_id of approver
    remarks: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "payments"
        indexes = ["college_id", "student_id", "status", "transaction_id"]


class Invoice(Document):
    college_id: PydanticObjectId
    student_id: PydanticObjectId  # Student user_id
    invoice_number: str
    academic_year: str
    semester: Optional[int] = None
    student_fee_ids: List[str] = Field(default_factory=list)
    total_amount: float
    discount_amount: float = 0.0
    payable_amount: float
    paid_amount: float = 0.0
    due_amount: float
    due_date: datetime
    status: str = "unpaid"  # "unpaid", "partially_paid", "paid"
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "invoices"
        indexes = ["college_id", "student_id", "invoice_number", "status"]


class Receipt(Document):
    college_id: PydanticObjectId
    payment_id: PydanticObjectId
    receipt_number: str
    invoice_id: Optional[PydanticObjectId] = None
    student_id: PydanticObjectId  # Student user_id
    amount_paid: float
    payment_date: datetime
    payment_method: str
    transaction_id: str
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "receipts"
        indexes = ["college_id", "payment_id", "receipt_number", "student_id"]
