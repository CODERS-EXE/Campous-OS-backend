import csv
import io
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.core.constants import UserRole
from app.core.deps import get_current_user, get_tenant_college, require_roles
from app.models.college import College
from app.models.fees import FeeStructure, Invoice, Payment, Receipt, StudentFee
from app.models.student import Student
from app.models.user import User
from app.services.notification_service import notify_fee_generated, notify_fee_paid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


router = APIRouter(prefix="/fees", tags=["fees"])


# ---------------- SCHEMAS ---------------- #

class FeeStructureCreateRequest(BaseModel):
    name: str
    code: str
    description: Optional[str] = None
    amount: float
    academic_year: str
    semester: Optional[int] = None
    department: Optional[str] = "All"
    course: Optional[str] = "All"


class FeeStructureUpdateRequest(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    academic_year: Optional[str] = None
    semester: Optional[int] = None
    department: Optional[str] = None
    course: Optional[str] = None
    status: Optional[str] = None


class FeeAssignRequest(BaseModel):
    fee_structure_id: str
    due_date: str  # YYYY-MM-DD
    discount: float = 0.0
    department: Optional[str] = None
    year: Optional[int] = None
    semester: Optional[int] = None
    student_ids: Optional[List[str]] = None  # Specific list of user_ids if provided


class OnlinePaymentRequest(BaseModel):
    student_fee_id: Optional[str] = None
    amount: float
    payment_method: str = "UPI"
    transaction_id: str
    remarks: Optional[str] = None


class OfflinePaymentRequest(BaseModel):
    student_id: str
    student_fee_id: Optional[str] = None
    amount: float
    payment_method: str = "Cash"  # Cash, Cheque, DD
    transaction_id: str
    remarks: Optional[str] = None


class InvoiceGenerateRequest(BaseModel):
    student_id: str
    academic_year: str
    semester: Optional[int] = None
    due_date: str  # YYYY-MM-DD


# ---------------- FEE STRUCTURE CRUD ---------------- #

@router.get("/structures")
async def get_fee_structures(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    academic_year: Optional[str] = None,
    semester: Optional[int] = None,
    department: Optional[str] = None,
):
    query_args = [FeeStructure.college_id == college.id]
    if academic_year:
        query_args.append(FeeStructure.academic_year == academic_year)
    if semester:
        query_args.append(FeeStructure.semester == semester)
    if department and department != "All":
        query_args.append((FeeStructure.department == department) | (FeeStructure.department == "All"))

    structures = await FeeStructure.find(*query_args).to_list()
    return structures


@router.post("/structures", status_code=status.HTTP_201_CREATED)
async def create_fee_structure(
    req: FeeStructureCreateRequest,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    existing = await FeeStructure.find_one(
        FeeStructure.college_id == college.id,
        FeeStructure.code == req.code,
        FeeStructure.academic_year == req.academic_year,
    )
    if existing:
        raise HTTPException(status_code=400, detail="Fee structure with code and academic year already exists")

    structure = FeeStructure(
        college_id=college.id,
        name=req.name,
        code=req.code,
        description=req.description,
        amount=req.amount,
        academic_year=req.academic_year,
        semester=req.semester,
        department=req.department or "All",
        course=req.course or "All",
    )
    await structure.insert()
    return structure


@router.patch("/structures/{structure_id}")
async def update_fee_structure(
    structure_id: str,
    req: FeeStructureUpdateRequest,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    struct = await FeeStructure.get(PydanticObjectId(structure_id))
    if not struct or struct.college_id != college.id:
        raise HTTPException(status_code=404, detail="Fee structure not found")

    update_data = req.model_dump(exclude_unset=True)
    if update_data:
        update_data["updated_at"] = utcnow()
        await struct.update({"$set": update_data})
    return struct


@router.delete("/structures/{structure_id}")
async def delete_fee_structure(
    structure_id: str,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    struct = await FeeStructure.get(PydanticObjectId(structure_id))
    if not struct or struct.college_id != college.id:
        raise HTTPException(status_code=404, detail="Fee structure not found")
    await struct.delete()
    return {"ok": True, "message": "Fee structure deleted"}


# ---------------- ASSIGN FEES ---------------- #

@router.post("/assign")
async def assign_fees(
    req: FeeAssignRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    struct = await FeeStructure.get(PydanticObjectId(req.fee_structure_id))
    if not struct or struct.college_id != college.id:
        raise HTTPException(status_code=404, detail="Fee structure not found")

    due_dt = datetime.fromisoformat(req.due_date.replace("Z", "+00:00")) if "T" in req.due_date else datetime.strptime(req.due_date, "%Y-%m-%d")

    # Find target students
    if req.student_ids and len(req.student_ids) > 0:
        student_docs = await Student.find(
            Student.college_id == college.id,
            {"user_id": {"$in": [PydanticObjectId(sid) for sid in req.student_ids]}},
        ).to_list()
    else:
        filters = [Student.college_id == college.id]
        if req.department and req.department != "All":
            filters.append(Student.department == req.department)
        if req.year:
            filters.append(Student.year == req.year)
        if req.semester:
            filters.append(Student.semester == req.semester)
        student_docs = await Student.find(*filters).to_list()

    if not student_docs:
        raise HTTPException(status_code=400, detail="No matching students found to assign fee")

    assigned_count = 0
    for st in student_docs:
        # Check if already assigned
        existing = await StudentFee.find_one(
            StudentFee.college_id == college.id,
            StudentFee.student_id == st.user_id,
            StudentFee.fee_structure_id == struct.id,
        )
        if existing:
            continue

        net_amt = max(0.0, struct.amount - req.discount)
        sf = StudentFee(
            college_id=college.id,
            student_id=st.user_id,
            fee_structure_id=struct.id,
            fee_name=struct.name,
            academic_year=struct.academic_year,
            semester=struct.semester or st.semester,
            total_amount=struct.amount,
            discount=req.discount,
            net_amount=net_amt,
            paid_amount=0.0,
            due_amount=net_amt,
            status="unpaid",
            due_date=due_dt,
        )
        await sf.insert()
        assigned_count += 1

        # Auto-notify student about new fee
        background_tasks.add_task(
            notify_fee_generated,
            college_id=college.id,
            student_user_id=str(st.user_id),
            amount=net_amt,
            due_date=req.due_date,
            student_fee_id=str(sf.id),
            created_by=user.id,
        )

    return {"ok": True, "assigned_count": assigned_count, "total_target": len(student_docs)}


# ---------------- STUDENT FEE DETAILS ---------------- #

@router.get("/student/details")
async def get_student_fee_details(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    student_id: Optional[str] = None,
):
    target_user_id = user.id
    if user.role == UserRole.STUDENT.value:
        target_user_id = user.id
    elif user.role == UserRole.PARENT.value:
        if student_id:
            target_user_id = PydanticObjectId(student_id)
        elif user.profile and user.profile.student_ids and len(user.profile.student_ids) > 0:
            target_user_id = PydanticObjectId(user.profile.student_ids[0])
        else:
            raise HTTPException(status_code=400, detail="No student associated with parent profile")
    elif user.role in [UserRole.COLLEGE_ADMIN.value, UserRole.SUPER_ADMIN.value, UserRole.WARDEN.value]:
        if not student_id:
            raise HTTPException(status_code=400, detail="student_id query parameter required")
        target_user_id = PydanticObjectId(student_id)

    student_fees = await StudentFee.find(
        StudentFee.college_id == college.id,
        StudentFee.student_id == target_user_id,
    ).to_list()

    total_net = sum(sf.net_amount for sf in student_fees)
    total_paid = sum(sf.paid_amount for sf in student_fees)
    total_due = sum(sf.due_amount for sf in student_fees)

    payments = await Payment.find(
        Payment.college_id == college.id,
        Payment.student_id == target_user_id,
    ).sort("-payment_date").to_list()

    invoices = await Invoice.find(
        Invoice.college_id == college.id,
        Invoice.student_id == target_user_id,
    ).sort("-created_at").to_list()

    receipts = await Receipt.find(
        Receipt.college_id == college.id,
        Receipt.student_id == target_user_id,
    ).sort("-payment_date").to_list()

    return {
        "summary": {
            "total_net": total_net,
            "total_paid": total_paid,
            "total_due": total_due,
            "fee_count": len(student_fees),
        },
        "student_fees": student_fees,
        "payments": payments,
        "invoices": invoices,
        "receipts": receipts,
    }


# ---------------- PAYMENTS ---------------- #

@router.post("/pay/online")
async def submit_online_payment(
    req: OnlinePaymentRequest,
    user: Annotated[User, Depends(require_roles(UserRole.STUDENT, UserRole.PARENT))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    student_fee = None
    if req.student_fee_id:
        student_fee = await StudentFee.get(PydanticObjectId(req.student_fee_id))
        if not student_fee or student_fee.college_id != college.id:
            raise HTTPException(status_code=404, detail="Student fee record not found")

    payment = Payment(
        college_id=college.id,
        student_id=user.id,
        student_fee_id=student_fee.id if student_fee else None,
        amount=req.amount,
        payment_mode="online",
        payment_method=req.payment_method,
        transaction_id=req.transaction_id,
        status="pending",
        remarks=req.remarks or "Online portal payment",
    )
    await payment.insert()
    return {"ok": True, "payment": payment, "message": "Payment submitted and pending admin approval"}


@router.post("/pay/offline")
async def record_offline_payment(
    req: OfflinePaymentRequest,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    student_user_id = PydanticObjectId(req.student_id)
    student_fee = None
    if req.student_fee_id:
        student_fee = await StudentFee.get(PydanticObjectId(req.student_fee_id))

    payment = Payment(
        college_id=college.id,
        student_id=student_user_id,
        student_fee_id=student_fee.id if student_fee else None,
        amount=req.amount,
        payment_mode="offline",
        payment_method=req.payment_method,
        transaction_id=req.transaction_id or f"OFF-{int(utcnow().timestamp())}",
        status="approved",
        approved_by=str(user.id),
        remarks=req.remarks or "Offline cash/cheque payment",
    )
    await payment.insert()

    # Update Student Fee record if provided or apply to oldest due
    if student_fee:
        student_fee.paid_amount += req.amount
        student_fee.due_amount = max(0.0, student_fee.net_amount - student_fee.paid_amount)
        if student_fee.due_amount == 0:
            student_fee.status = "paid"
        else:
            student_fee.status = "partially_paid"
        student_fee.updated_at = utcnow()
        await student_fee.save()
    else:
        # Apply to unpaid student fees
        s_fees = await StudentFee.find(
            StudentFee.college_id == college.id,
            StudentFee.student_id == student_user_id,
            StudentFee.status != "paid",
        ).to_list()
        rem = req.amount
        for sf in s_fees:
            if rem <= 0:
                break
            pay_amt = min(rem, sf.due_amount)
            sf.paid_amount += pay_amt
            sf.due_amount -= pay_amt
            rem -= pay_amt
            sf.status = "paid" if sf.due_amount == 0 else "partially_paid"
            sf.updated_at = utcnow()
            await sf.save()

    # Generate Receipt
    receipt_count = await Receipt.find(Receipt.college_id == college.id).count()
    rec_num = f"REC-{college.id.binary.hex()[:4].upper()}-{receipt_count + 1:04d}"
    receipt = Receipt(
        college_id=college.id,
        payment_id=payment.id,
        receipt_number=rec_num,
        student_id=student_user_id,
        amount_paid=req.amount,
        payment_date=payment.payment_date,
        payment_method=req.payment_method,
        transaction_id=payment.transaction_id,
    )
    await receipt.insert()

    return {"ok": True, "payment": payment, "receipt": receipt}


@router.post("/payments/{payment_id}/approve")
async def approve_payment(
    payment_id: str,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    payment = await Payment.get(PydanticObjectId(payment_id))
    if not payment or payment.college_id != college.id:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.status == "approved":
        raise HTTPException(status_code=400, detail="Payment is already approved")

    payment.status = "approved"
    payment.approved_by = str(user.id)
    payment.updated_at = utcnow()
    await payment.save()

    # Apply to student fee
    if payment.student_fee_id:
        sf = await StudentFee.get(payment.student_fee_id)
        if sf:
            sf.paid_amount += payment.amount
            sf.due_amount = max(0.0, sf.net_amount - sf.paid_amount)
            sf.status = "paid" if sf.due_amount == 0 else "partially_paid"
            sf.updated_at = utcnow()
            await sf.save()
    else:
        s_fees = await StudentFee.find(
            StudentFee.college_id == college.id,
            StudentFee.student_id == payment.student_id,
            StudentFee.status != "paid",
        ).to_list()
        rem = payment.amount
        for sf in s_fees:
            if rem <= 0:
                break
            pay_amt = min(rem, sf.due_amount)
            sf.paid_amount += pay_amt
            sf.due_amount -= pay_amt
            rem -= pay_amt
            sf.status = "paid" if sf.due_amount == 0 else "partially_paid"
            sf.updated_at = utcnow()
            await sf.save()

    # Generate Receipt
    receipt_count = await Receipt.find(Receipt.college_id == college.id).count()
    rec_num = f"REC-{college.id.binary.hex()[:4].upper()}-{receipt_count + 1:04d}"
    receipt = Receipt(
        college_id=college.id,
        payment_id=payment.id,
        receipt_number=rec_num,
        student_id=payment.student_id,
        amount_paid=payment.amount,
        payment_date=payment.payment_date,
        payment_method=payment.payment_method,
        transaction_id=payment.transaction_id,
    )
    await receipt.insert()

    # Auto-notify student that payment is confirmed
    background_tasks.add_task(
        notify_fee_paid,
        college_id=college.id,
        student_user_id=str(payment.student_id),
        amount=payment.amount,
        transaction_id=payment.transaction_id,
        created_by=user.id,
    )

    return {"ok": True, "payment": payment, "receipt": receipt}


@router.post("/payments/{payment_id}/reject")
async def reject_payment(
    payment_id: str,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    payment = await Payment.get(PydanticObjectId(payment_id))
    if not payment or payment.college_id != college.id:
        raise HTTPException(status_code=404, detail="Payment not found")

    payment.status = "rejected"
    payment.approved_by = str(user.id)
    payment.updated_at = utcnow()
    await payment.save()
    return {"ok": True, "payment": payment}


@router.get("/payments")
async def get_payments(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    status_filter: Optional[str] = None,
    student_id: Optional[str] = None,
):
    filters = [Payment.college_id == college.id]
    if status_filter:
        filters.append(Payment.status == status_filter)
    if student_id:
        filters.append(Payment.student_id == PydanticObjectId(student_id))
    elif user.role == UserRole.STUDENT.value:
        filters.append(Payment.student_id == user.id)

    payments = await Payment.find(*filters).sort("-payment_date").to_list()
    return payments


# ---------------- INVOICE & RECEIPT GENERATION ---------------- #

@router.post("/invoices/generate")
async def generate_invoice(
    req: InvoiceGenerateRequest,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    student_user_id = PydanticObjectId(req.student_id)
    unpaid_fees = await StudentFee.find(
        StudentFee.college_id == college.id,
        StudentFee.student_id == student_user_id,
        StudentFee.status != "paid",
    ).to_list()

    if not unpaid_fees:
        raise HTTPException(status_code=400, detail="No pending fees found to generate invoice")

    tot_amt = sum(sf.total_amount for sf in unpaid_fees)
    disc_amt = sum(sf.discount for sf in unpaid_fees)
    pay_amt = sum(sf.net_amount for sf in unpaid_fees)
    paid_amt = sum(sf.paid_amount for sf in unpaid_fees)
    due_amt = sum(sf.due_amount for sf in unpaid_fees)

    inv_count = await Invoice.find(Invoice.college_id == college.id).count()
    inv_num = f"INV-{college.id.binary.hex()[:4].upper()}-{inv_count + 1:04d}"

    due_dt = datetime.fromisoformat(req.due_date.replace("Z", "+00:00")) if "T" in req.due_date else datetime.strptime(req.due_date, "%Y-%m-%d")

    invoice = Invoice(
        college_id=college.id,
        student_id=student_user_id,
        invoice_number=inv_num,
        academic_year=req.academic_year,
        semester=req.semester,
        student_fee_ids=[str(sf.id) for sf in unpaid_fees],
        total_amount=tot_amt,
        discount_amount=disc_amt,
        payable_amount=pay_amt,
        paid_amount=paid_amt,
        due_amount=due_amt,
        due_date=due_dt,
        status="paid" if due_amt == 0 else ("partially_paid" if paid_amt > 0 else "unpaid"),
    )
    await invoice.insert()
    return invoice


@router.get("/invoices/{invoice_id}/download")
async def download_invoice(
    invoice_id: str,
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    inv = await Invoice.get(PydanticObjectId(invoice_id))
    if not inv or inv.college_id != college.id:
        raise HTTPException(status_code=404, detail="Invoice not found")

    st_user = await User.get(inv.student_id)
    student_name = st_user.name if st_user else "Student"

    content = f"""
====================================================================
                        INVOICE - CAMPUSOS
====================================================================
College: {college.name}
Invoice Number: {inv.invoice_number}
Date Generated: {inv.created_at.strftime('%Y-%m-%d')}
Academic Year: {inv.academic_year}
--------------------------------------------------------------------
Student ID: {inv.student_id}
Student Name: {student_name}
Due Date: {inv.due_date.strftime('%Y-%m-%d')}
--------------------------------------------------------------------
Total Billed Amount: ₹{inv.total_amount:,.2f}
Discount Applied:    ₹{inv.discount_amount:,.2f}
Payable Amount:     ₹{inv.payable_amount:,.2f}
Paid Amount:        ₹{inv.paid_amount:,.2f}
--------------------------------------------------------------------
BALANCE DUE:        ₹{inv.due_amount:,.2f}
Status:             {inv.status.upper()}
====================================================================
Thank you for using CampusOS Fees Portal.
"""
    return Response(
        content=content.strip(),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{inv.invoice_number}.txt"'},
    )


@router.get("/receipts/{receipt_id}/download")
async def download_receipt(
    receipt_id: str,
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    rec = await Receipt.get(PydanticObjectId(receipt_id))
    if not rec or rec.college_id != college.id:
        raise HTTPException(status_code=404, detail="Receipt not found")

    st_user = await User.get(rec.student_id)
    student_name = st_user.name if st_user else "Student"

    content = f"""
====================================================================
                    PAYMENT RECEIPT - CAMPUSOS
====================================================================
College: {college.name}
Receipt Number: {rec.receipt_number}
Payment Date: {rec.payment_date.strftime('%Y-%m-%d %H:%M')}
--------------------------------------------------------------------
Student ID: {rec.student_id}
Student Name: {student_name}
Payment Method: {rec.payment_method}
Transaction Ref: {rec.transaction_id}
--------------------------------------------------------------------
AMOUNT PAID:        ₹{rec.amount_paid:,.2f}
Status:             SUCCESSFUL / APPROVED
====================================================================
This is an official computer-generated receipt from CampusOS.
"""
    return Response(
        content=content.strip(),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{rec.receipt_number}.txt"'},
    )


# ---------------- PENDING DUES & ANALYTICS ---------------- #

@router.get("/dues")
async def get_pending_dues(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    search: Optional[str] = None,
    academic_year: Optional[str] = None,
    semester: Optional[int] = None,
    department: Optional[str] = None,
):
    # Fetch all unpaid student fees for college
    filters = [StudentFee.college_id == college.id, StudentFee.due_amount > 0]
    if academic_year:
        filters.append(StudentFee.academic_year == academic_year)
    if semester:
        filters.append(StudentFee.semester == semester)

    student_fees = await StudentFee.find(*filters).to_list()
    if not student_fees:
        return []

    # Map to student details
    student_user_ids = list({sf.student_id for sf in student_fees})
    users_list = await User.find({"_id": {"$in": student_user_ids}}).to_list()
    students_list = await Student.find(
        Student.college_id == college.id,
        {"user_id": {"$in": student_user_ids}},
    ).to_list()

    user_map = {u.id: u for u in users_list}
    student_map = {st.user_id: st for st in students_list}

    dues_list = []
    for sf in student_fees:
        u = user_map.get(sf.student_id)
        st = student_map.get(sf.student_id)

        st_dept = st.department if st else "N/A"
        st_roll = st.roll_no if st else "N/A"
        st_name = u.name if u else "Unknown Student"
        st_email = u.email if u else ""

        if department and st_dept.lower() != department.lower():
            continue

        if search:
            q = search.lower()
            if q not in st_name.lower() and q not in st_roll.lower() and q not in st_email.lower() and q not in sf.fee_name.lower():
                continue

        dues_list.append({
            "student_fee_id": str(sf.id),
            "student_id": str(sf.student_id),
            "student_name": st_name,
            "roll_no": st_roll,
            "department": st_dept,
            "fee_name": sf.fee_name,
            "academic_year": sf.academic_year,
            "semester": sf.semester,
            "net_amount": sf.net_amount,
            "paid_amount": sf.paid_amount,
            "due_amount": sf.due_amount,
            "due_date": sf.due_date.strftime("%Y-%m-%d"),
            "status": sf.status,
        })

    return dues_list


@router.get("/analytics")
async def get_fee_analytics(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[Optional[College], Depends(get_tenant_college)] = None,
):
    if user.role == UserRole.SUPER_ADMIN.value:
        colleges = await College.find_all().to_list()
        all_fees = await StudentFee.find_all().to_list()
        total_billed = sum(sf.net_amount for sf in all_fees)
        total_paid = sum(sf.paid_amount for sf in all_fees)
        total_due = sum(sf.due_amount for sf in all_fees)

        college_stats = []
        for col in colleges:
            col_fees = [sf for sf in all_fees if sf.college_id == col.id]
            cBilled = sum(sf.net_amount for sf in col_fees)
            cPaid = sum(sf.paid_amount for sf in col_fees)
            cDue = sum(sf.due_amount for sf in col_fees)
            college_stats.append({
                "college_id": str(col.id),
                "college_name": col.name,
                "total_billed": cBilled,
                "total_paid": cPaid,
                "total_due": cDue,
                "collection_rate": round((cPaid / cBilled * 100), 1) if cBilled > 0 else 100.0,
            })

        return {
            "total_billed": total_billed,
            "total_paid": total_paid,
            "total_due": total_due,
            "collection_rate": round((total_paid / total_billed * 100), 1) if total_billed > 0 else 100.0,
            "college_stats": college_stats,
        }

    if not college:
        raise HTTPException(status_code=400, detail="College context required")

    fees = await StudentFee.find(StudentFee.college_id == college.id).to_list()
    payments = await Payment.find(Payment.college_id == college.id, Payment.status == "approved").to_list()

    total_billed = sum(sf.net_amount for sf in fees)
    total_paid = sum(sf.paid_amount for sf in fees)
    total_due = sum(sf.due_amount for sf in fees)

    online_paid = sum(p.amount for p in payments if p.payment_mode == "online")
    offline_paid = sum(p.amount for p in payments if p.payment_mode == "offline")

    pending_payments_count = await Payment.find(Payment.college_id == college.id, Payment.status == "pending").count()

    return {
        "total_billed": total_billed,
        "total_paid": total_paid,
        "total_due": total_due,
        "collection_rate": round((total_paid / total_billed * 100), 1) if total_billed > 0 else 100.0,
        "online_paid": online_paid,
        "offline_paid": offline_paid,
        "pending_approval_count": pending_payments_count,
        "fee_records_count": len(fees),
    }


@router.get("/export")
async def export_fee_report(
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    student_fees = await StudentFee.find(StudentFee.college_id == college.id).to_list()
    student_user_ids = list({sf.student_id for sf in student_fees})
    users_list = await User.find({"_id": {"$in": student_user_ids}}).to_list()
    students_list = await Student.find(
        Student.college_id == college.id,
        {"user_id": {"$in": student_user_ids}},
    ).to_list()

    user_map = {u.id: u for u in users_list}
    student_map = {st.user_id: st for st in students_list}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Student Name",
        "Roll No",
        "Department",
        "Fee Name",
        "Academic Year",
        "Semester",
        "Net Amount",
        "Paid Amount",
        "Due Amount",
        "Status",
        "Due Date",
    ])

    for sf in student_fees:
        u = user_map.get(sf.student_id)
        st = student_map.get(sf.student_id)
        writer.writerow([
            u.name if u else "N/A",
            st.roll_no if st else "N/A",
            st.department if st else "N/A",
            sf.fee_name,
            sf.academic_year,
            sf.semester or 1,
            f"{sf.net_amount:.2f}",
            f"{sf.paid_amount:.2f}",
            f"{sf.due_amount:.2f}",
            sf.status,
            sf.due_date.strftime("%Y-%m-%d"),
        ])

    csv_data = output.getvalue()
    output.close()

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="fee_report_{college.name.replace(" ", "_")}.csv"'},
    )
