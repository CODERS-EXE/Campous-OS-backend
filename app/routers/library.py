import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Annotated, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.core.constants import UserRole
from app.core.deps import get_current_user, get_tenant_college, require_roles, resolve_tenant
from app.models.college import College
from app.models.library import Book, BookCategory, BookIssue
from app.models.user import User
from app.services.notification_service import notify_book_issued, notify_book_overdue


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


router = APIRouter(prefix="/library", tags=["library"])

# Default fine per day in Rupees
FINE_PER_DAY = 2.0
DEFAULT_DUE_DAYS = 14  # 2 weeks


# ---------------- SCHEMAS ---------------- #

class CategoryCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None


class CategoryUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class BookCreateRequest(BaseModel):
    title: str
    author: str
    isbn: Optional[str] = None
    publisher: Optional[str] = None
    edition: Optional[str] = None
    year: Optional[int] = None
    category_id: Optional[str] = None
    total_quantity: int = 1
    location: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    language: str = "English"


class BookUpdateRequest(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    isbn: Optional[str] = None
    publisher: Optional[str] = None
    edition: Optional[str] = None
    year: Optional[int] = None
    category_id: Optional[str] = None
    total_quantity: Optional[int] = None
    location: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    language: Optional[str] = None
    status: Optional[str] = None


class IssueBookRequest(BaseModel):
    book_id: str
    user_id: str  # student/faculty user id
    due_days: int = DEFAULT_DUE_DAYS
    remarks: Optional[str] = None


class ReturnBookRequest(BaseModel):
    issue_id: str
    remarks: Optional[str] = None
    is_lost: bool = False
    is_damaged: bool = False


class RenewBookRequest(BaseModel):
    issue_id: str
    additional_days: int = DEFAULT_DUE_DAYS


class PayFineRequest(BaseModel):
    issue_id: str


# ---------------- CATEGORY CRUD ---------------- #

@router.get("/categories")
async def get_categories(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    return await BookCategory.find(BookCategory.college_id == college.id).to_list()


@router.post("/categories", status_code=status.HTTP_201_CREATED)
async def create_category(
    req: CategoryCreateRequest,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    existing = await BookCategory.find_one(
        BookCategory.college_id == college.id,
        BookCategory.name == req.name,
    )
    if existing:
        raise HTTPException(status_code=400, detail="Category with this name already exists")

    cat = BookCategory(
        college_id=college.id,
        name=req.name,
        description=req.description,
    )
    await cat.insert()
    return cat


@router.patch("/categories/{category_id}")
async def update_category(
    category_id: str,
    req: CategoryUpdateRequest,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    cat = await BookCategory.get(PydanticObjectId(category_id))
    if not cat or cat.college_id != college.id:
        raise HTTPException(status_code=404, detail="Category not found")

    update_data = req.model_dump(exclude_unset=True)
    if update_data:
        update_data["updated_at"] = utcnow()
        await cat.update({"$set": update_data})
    return cat


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: str,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    cat = await BookCategory.get(PydanticObjectId(category_id))
    if not cat or cat.college_id != college.id:
        raise HTTPException(status_code=404, detail="Category not found")
    await cat.delete()
    return {"ok": True, "message": "Category deleted"}


# ---------------- BOOK CRUD ---------------- #

@router.get("/books")
async def get_books(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    category_id: Optional[str] = None,
    search: Optional[str] = None,
    available_only: bool = False,
):
    filters = [Book.college_id == college.id, Book.status == "active"]
    if category_id:
        filters.append(Book.category_id == PydanticObjectId(category_id))
    if available_only:
        filters.append(Book.available_quantity > 0)

    books = await Book.find(*filters).to_list()

    if search:
        q = search.lower()
        books = [
            b for b in books
            if q in b.title.lower()
            or q in b.author.lower()
            or (b.isbn and q in b.isbn.lower())
            or (b.publisher and q in b.publisher.lower())
        ]
    return books


@router.get("/books/{book_id}")
async def get_book(
    book_id: str,
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    book = await Book.get(PydanticObjectId(book_id))
    if not book or book.college_id != college.id:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@router.post("/books", status_code=status.HTTP_201_CREATED)
async def create_book(
    req: BookCreateRequest,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    cat_name = None
    if req.category_id:
        cat = await BookCategory.get(PydanticObjectId(req.category_id))
        if cat:
            cat_name = cat.name

    book = Book(
        college_id=college.id,
        title=req.title,
        author=req.author,
        isbn=req.isbn,
        publisher=req.publisher,
        edition=req.edition,
        year=req.year,
        category_id=PydanticObjectId(req.category_id) if req.category_id else None,
        category_name=cat_name,
        total_quantity=req.total_quantity,
        available_quantity=req.total_quantity,
        location=req.location,
        description=req.description,
        cover_url=req.cover_url,
        language=req.language,
    )
    await book.insert()
    return book


@router.patch("/books/{book_id}")
async def update_book(
    book_id: str,
    req: BookUpdateRequest,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    book = await Book.get(PydanticObjectId(book_id))
    if not book or book.college_id != college.id:
        raise HTTPException(status_code=404, detail="Book not found")

    update_data = req.model_dump(exclude_unset=True)

    # Update category name if category changed
    if "category_id" in update_data and update_data["category_id"]:
        cat = await BookCategory.get(PydanticObjectId(update_data["category_id"]))
        if cat:
            update_data["category_name"] = cat.name
        update_data["category_id"] = PydanticObjectId(update_data["category_id"])

    # Adjust available quantity if total quantity changed
    if "total_quantity" in update_data:
        issued = book.total_quantity - book.available_quantity
        update_data["available_quantity"] = max(0, update_data["total_quantity"] - issued)

    if update_data:
        update_data["updated_at"] = utcnow()
        await book.update({"$set": update_data})
    return book


@router.delete("/books/{book_id}")
async def delete_book(
    book_id: str,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    book = await Book.get(PydanticObjectId(book_id))
    if not book or book.college_id != college.id:
        raise HTTPException(status_code=404, detail="Book not found")

    active_issues = await BookIssue.find(
        BookIssue.college_id == college.id,
        BookIssue.book_id == book.id,
        BookIssue.status == "issued",
    ).count()
    if active_issues > 0:
        raise HTTPException(status_code=400, detail="Cannot delete a book that has active issues")

    await book.delete()
    return {"ok": True, "message": "Book deleted"}


# ---------------- ISSUE / RETURN / RENEW ---------------- #

@router.post("/issues", status_code=status.HTTP_201_CREATED)
async def issue_book(
    req: IssueBookRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    book = await Book.get(PydanticObjectId(req.book_id))
    if not book or book.college_id != college.id:
        raise HTTPException(status_code=404, detail="Book not found")
    if book.available_quantity <= 0:
        raise HTTPException(status_code=400, detail="No copies available for this book")

    target_user = await User.get(PydanticObjectId(req.user_id))
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if the user already has this book issued
    existing = await BookIssue.find_one(
        BookIssue.college_id == college.id,
        BookIssue.book_id == book.id,
        BookIssue.user_id == target_user.id,
        BookIssue.status == "issued",
    )
    if existing:
        raise HTTPException(status_code=400, detail="User already has this book issued")

    due_dt = utcnow() + timedelta(days=req.due_days)
    issue = BookIssue(
        college_id=college.id,
        book_id=book.id,
        book_title=book.title,
        book_isbn=book.isbn,
        user_id=target_user.id,
        user_name=target_user.name,
        user_role=target_user.role,
        due_date=due_dt,
        remarks=req.remarks,
        issued_by=str(user.id),
    )
    await issue.insert()

    # Decrement available quantity
    book.available_quantity -= 1
    book.updated_at = utcnow()
    await book.save()

    # Auto-notify user that book has been issued
    background_tasks.add_task(
        notify_book_issued,
        college_id=college.id,
        user_id=str(target_user.id),
        book_title=book.title,
        due_date=due_dt.strftime("%Y-%m-%d"),
        issue_id=str(issue.id),
        created_by=user.id,
    )

    return issue


@router.post("/return")
async def return_book(
    req: ReturnBookRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    issue = await BookIssue.get(PydanticObjectId(req.issue_id))
    if not issue or issue.college_id != college.id:
        raise HTTPException(status_code=404, detail="Issue record not found")
    if issue.status == "returned":
        raise HTTPException(status_code=400, detail="Book already returned")

    now = utcnow()
    fine_amount = 0.0
    fine_reason = None

    if req.is_lost:
        # Fine for lost book = rough replacement cost
        fine_amount = 500.0
        fine_reason = "lost"
        new_status = "lost"
    elif req.is_damaged:
        fine_amount = 200.0
        fine_reason = "damaged"
        new_status = "damaged"
    else:
        new_status = "returned"
        if now > issue.due_date:
            overdue_days = (now - issue.due_date).days
            fine_amount = overdue_days * FINE_PER_DAY
            if fine_amount > 0:
                fine_reason = "overdue"

    issue.return_date = now
    issue.status = new_status
    issue.fine_amount = fine_amount
    issue.fine_reason = fine_reason
    issue.remarks = req.remarks or issue.remarks
    issue.returned_by = str(user.id)
    issue.updated_at = now
    await issue.save()

    # Restore available quantity if book is returned (not lost)
    if new_status == "returned":
        book = await Book.get(issue.book_id)
        if book:
            book.available_quantity = min(book.total_quantity, book.available_quantity + 1)
            book.updated_at = now
            await book.save()

    # If overdue, notify user about the fine
    if fine_amount > 0:
        overdue_days = int((now - issue.due_date).days) if now > issue.due_date else 0
        background_tasks.add_task(
            notify_book_overdue,
            college_id=college.id,
            user_id=str(issue.user_id),
            book_title=issue.book_title,
            overdue_days=overdue_days,
            fine_amount=fine_amount,
            created_by=user.id,
        )

    return {"ok": True, "issue": issue, "fine_amount": fine_amount}


@router.post("/renew")
async def renew_book(
    req: RenewBookRequest,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    issue = await BookIssue.get(PydanticObjectId(req.issue_id))
    if not issue or issue.college_id != college.id:
        raise HTTPException(status_code=404, detail="Issue record not found")
    if issue.status != "issued":
        raise HTTPException(status_code=400, detail="Only active issues can be renewed")
    if issue.renewed_count >= issue.max_renewals:
        raise HTTPException(status_code=400, detail=f"Maximum renewals ({issue.max_renewals}) reached")

    issue.due_date = utcnow() + timedelta(days=req.additional_days)
    issue.renewed_count += 1
    issue.status = "issued"
    issue.updated_at = utcnow()
    await issue.save()

    return {"ok": True, "issue": issue}


@router.post("/fines/{issue_id}/pay")
async def pay_fine(
    issue_id: str,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    issue = await BookIssue.get(PydanticObjectId(issue_id))
    if not issue or issue.college_id != college.id:
        raise HTTPException(status_code=404, detail="Issue record not found")
    if issue.fine_paid:
        raise HTTPException(status_code=400, detail="Fine already paid")
    if issue.fine_amount == 0:
        raise HTTPException(status_code=400, detail="No fine to pay for this issue")

    issue.fine_paid = True
    issue.fine_paid_date = utcnow()
    issue.updated_at = utcnow()
    await issue.save()

    return {"ok": True, "issue": issue}


# ---------------- ISSUE QUERIES ---------------- #

@router.get("/issues")
async def get_issues(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    status_filter: Optional[str] = None,
    user_id: Optional[str] = None,
    overdue_only: bool = False,
):
    filters = [BookIssue.college_id == college.id]

    # Students/Faculty see only their own issues
    if user.role in [UserRole.STUDENT.value, UserRole.FACULTY.value]:
        filters.append(BookIssue.user_id == user.id)
    elif user_id:
        filters.append(BookIssue.user_id == PydanticObjectId(user_id))

    if status_filter:
        filters.append(BookIssue.status == status_filter)

    issues = await BookIssue.find(*filters).sort("-issue_date").to_list()

    if overdue_only:
        now = utcnow()
        issues = [i for i in issues if i.status == "issued" and now > i.due_date]

    return issues


@router.get("/my-issues")
async def get_my_issues(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    issues = await BookIssue.find(
        BookIssue.college_id == college.id,
        BookIssue.user_id == user.id,
    ).sort("-issue_date").to_list()

    now = utcnow()
    # Auto-flag overdue in response
    result = []
    for i in issues:
        item = i.model_dump()
        item["id"] = str(i.id)
        item["is_overdue"] = i.status == "issued" and now > i.due_date
        result.append(item)
    return result


# ---------------- ANALYTICS ---------------- #

@router.get("/analytics")
async def get_library_analytics(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[Optional[College], Depends(resolve_tenant)] = None,
):
    from app.models.college import College as CollegeModel

    if user.role == UserRole.SUPER_ADMIN.value:
        colleges = await CollegeModel.find_all().to_list()
        all_issues = await BookIssue.find_all().to_list()
        all_books = await Book.find_all().to_list()

        now = utcnow()
        total_books = len(all_books)
        total_issued = len([i for i in all_issues if i.status == "issued"])
        total_overdue = len([i for i in all_issues if i.status == "issued" and now > i.due_date])
        total_fines = sum(i.fine_amount for i in all_issues)

        college_stats = []
        for col in colleges:
            col_books = [b for b in all_books if b.college_id == col.id]
            col_issues = [i for i in all_issues if i.college_id == col.id]
            college_stats.append({
                "college_id": str(col.id),
                "college_name": col.name,
                "total_books": len(col_books),
                "total_issued": len([i for i in col_issues if i.status == "issued"]),
                "total_overdue": len([i for i in col_issues if i.status == "issued" and now > i.due_date]),
            })

        return {
            "total_books": total_books,
            "total_issued": total_issued,
            "total_overdue": total_overdue,
            "total_fines_collected": total_fines,
            "college_stats": college_stats,
        }

    if not college:
        raise HTTPException(status_code=400, detail="College context required")

    now = utcnow()
    books = await Book.find(Book.college_id == college.id, Book.status == "active").to_list()
    categories = await BookCategory.find(BookCategory.college_id == college.id).to_list()
    all_issues = await BookIssue.find(BookIssue.college_id == college.id).to_list()

    active_issues = [i for i in all_issues if i.status == "issued"]
    overdue_issues = [i for i in active_issues if now > i.due_date]
    returned_issues = [i for i in all_issues if i.status == "returned"]
    fines_pending = [i for i in all_issues if i.fine_amount > 0 and not i.fine_paid]
    fines_collected = [i for i in all_issues if i.fine_amount > 0 and i.fine_paid]

    total_books = len(books)
    total_available = sum(b.available_quantity for b in books)
    total_issued_count = sum(b.total_quantity - b.available_quantity for b in books)

    return {
        "total_books": total_books,
        "total_available": total_available,
        "total_issued": total_issued_count,
        "total_categories": len(categories),
        "active_issues": len(active_issues),
        "overdue_issues": len(overdue_issues),
        "returned_today": len([i for i in returned_issues if i.return_date and i.return_date.date() == now.date()]),
        "pending_fines_amount": sum(i.fine_amount for i in fines_pending),
        "collected_fines_amount": sum(i.fine_amount for i in fines_collected),
    }


# ---------------- EXPORT ---------------- #

@router.get("/export")
async def export_library_report(
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    issues = await BookIssue.find(BookIssue.college_id == college.id).sort("-issue_date").to_list()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Book Title", "ISBN", "Issued To", "Role",
        "Issue Date", "Due Date", "Return Date",
        "Status", "Renewals", "Fine Amount", "Fine Paid",
    ])
    now = utcnow()
    for i in issues:
        writer.writerow([
            i.book_title,
            i.book_isbn or "N/A",
            i.user_name,
            i.user_role,
            i.issue_date.strftime("%Y-%m-%d"),
            i.due_date.strftime("%Y-%m-%d"),
            i.return_date.strftime("%Y-%m-%d") if i.return_date else "Not Returned",
            i.status,
            i.renewed_count,
            f"{i.fine_amount:.2f}",
            "Yes" if i.fine_paid else "No",
        ])

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=\"library_report.csv\""},
    )
