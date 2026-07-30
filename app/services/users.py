from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.core.constants import UserRole
from app.core.deps import utcnow
from app.core.security import hash_password
from app.models.college import College
from app.models.faculty import Faculty
from app.models.student import Student
from app.models.user import User, UserProfile


async def create_college_with_admin(
    name: str,
    subdomain: str,
    theme_color: str,
    plan: str,
    admin_name: str,
    admin_email: str,
    admin_password: str,
) -> tuple[College, User]:
    existing = await College.find_one(College.subdomain == subdomain.lower())
    if existing:
        raise ValueError("Subdomain already taken")

    existing_user = await User.find_one(User.email == admin_email.lower())
    if existing_user:
        raise ValueError("Admin email already registered")

    college = College(
        name=name,
        subdomain=subdomain.lower(),
        theme_color=theme_color,
        plan=plan,
    )
    await college.insert()

    admin = User(
        college_id=college.id,
        role=UserRole.COLLEGE_ADMIN.value,
        name=admin_name,
        email=admin_email.lower(),
        password_hash=hash_password(admin_password),
        is_verified=True,
    )
    await admin.insert()
    return college, admin


async def create_user(
    name: str,
    email: str,
    password: str,
    role: str,
    college: College,
    roll_no: Optional[str] = None,
    department: Optional[str] = None,
    course: Optional[str] = None,
    year: Optional[int] = None,
    semester: int = 1,
    subjects: Optional[list[str]] = None,
    designation: Optional[str] = None,
    status: Optional[str] = None,
    hostel: Optional[str] = None,
    phone: Optional[str] = None,
    student_ids: Optional[list[str]] = None,
) -> User:
    if role not in {
        UserRole.STUDENT.value,
        UserRole.FACULTY.value,
        UserRole.PARENT.value,
        UserRole.WARDEN.value,
    }:
        raise ValueError("Invalid role")

    existing = await User.find_one(User.email == email.lower())
    if existing:
        raise ValueError("Email already registered")

    user = User(
        college_id=college.id,
        role=role,
        name=name,
        email=email.lower(),
        password_hash=hash_password(password),
        is_verified=True,
        profile=UserProfile(
            phone=phone,
            designation=designation,
            status=status,
            hostel=hostel,
            student_ids=student_ids or [],
        ),
    )
    await user.insert()

    if role == UserRole.STUDENT.value:
        if not all([roll_no, department, year, course]):
            raise ValueError("Student registration requires roll_no, department, course, and year")
        student = Student(
            college_id=college.id,
            user_id=user.id,
            roll_no=roll_no,
            department=department,
            course=course,
            year=year,
            semester=semester,
        )
        await student.insert()
    elif role == UserRole.FACULTY.value:
        faculty = Faculty(
            college_id=college.id,
            user_id=user.id,
            department=department or "General",
            designation=designation,
            status=status or "active",
            subjects=subjects or [],
        )
        await faculty.insert()

    return user


async def register_user(
    name: str,
    email: str,
    password: str,
    role: str,
    college: College,
    roll_no: Optional[str] = None,
    department: Optional[str] = None,
    course: Optional[str] = None,
    year: Optional[int] = None,
) -> User:
    if role not in {UserRole.STUDENT.value, UserRole.FACULTY.value, UserRole.PARENT.value}:
        raise ValueError("Invalid role for registration")
    return await create_user(
        name=name,
        email=email,
        password=password,
        role=role,
        college=college,
        roll_no=roll_no,
        department=department,
        course=course,
        year=year,
    )


async def update_user(
    user: User,
    name: Optional[str] = None,
    email: Optional[str] = None,
    password: Optional[str] = None,
    department: Optional[str] = None,
    course: Optional[str] = None,
    designation: Optional[str] = None,
    status: Optional[str] = None,
    hostel: Optional[str] = None,
    phone: Optional[str] = None,
    student_ids: Optional[list[str]] = None,
    subjects: Optional[list[str]] = None,
    roll_no: Optional[str] = None,
    year: Optional[int] = None,
    semester: Optional[int] = None,
) -> User:
    if email and email.lower() != user.email:
        existing = await User.find_one(User.email == email.lower())
        if existing:
            raise ValueError("Email already registered")
        user.email = email.lower()
    if name:
        user.name = name
    if password:
        user.password_hash = hash_password(password)
    if phone is not None:
        user.profile.phone = phone
    if student_ids is not None:
        user.profile.student_ids = student_ids
    if hostel is not None:
        user.profile.hostel = hostel
    if status is not None:
        user.profile.status = status
    user.updated_at = utcnow()
    await user.save()

    if user.role == UserRole.STUDENT.value:
        student = await Student.find_one(Student.user_id == user.id, Student.college_id == user.college_id)
        if not student:
            raise ValueError("Student profile not found")
        if roll_no is not None:
            student.roll_no = roll_no
        if department is not None:
            student.department = department
        if course is not None:
            student.course = course
        if year is not None:
            student.year = year
        if semester is not None:
            student.semester = semester
        await student.save()
    elif user.role == UserRole.FACULTY.value:
        faculty = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == user.college_id)
        if not faculty:
            raise ValueError("Faculty profile not found")
        if department is not None:
            faculty.department = department
        if designation is not None:
            faculty.designation = designation
        if status is not None:
            faculty.status = status
        if subjects is not None:
            faculty.subjects = subjects
        await faculty.save()

    return user


async def delete_user(user: User) -> None:
    if user.role == UserRole.STUDENT.value:
        student = await Student.find_one(Student.user_id == user.id, Student.college_id == user.college_id)
        if student:
            await student.delete()
    elif user.role == UserRole.FACULTY.value:
        faculty = await Faculty.find_one(Faculty.user_id == user.id, Faculty.college_id == user.college_id)
        if faculty:
            await faculty.delete()
    await user.delete()


async def get_dashboard_stats(college_id, user_id) -> dict:
    from app.models.notification import Notification

    total_students = await Student.find(Student.college_id == college_id).count()
    total_faculty = await Faculty.find(Faculty.college_id == college_id).count()
    notifications = await Notification.find(Notification.college_id == college_id).to_list()
    unread = sum(1 for n in notifications if user_id not in n.read_by)
    return {
        "total_students": total_students,
        "total_faculty": total_faculty,
        "unread_notifications": unread,
        "attendance_rate": None,
    }
