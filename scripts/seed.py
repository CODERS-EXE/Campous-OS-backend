"""Seed demo data for CampusOS."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.constants import UserRole
from app.core.security import hash_password
from app.db.mongo import init_db
from app.models.college import College
from app.models.faculty import Faculty
from app.models.notification import Notification, NotificationTarget
from app.models.student import Student
from app.models.user import User


async def seed():
    await init_db()

    # Super admin
    super_admin = await User.find_one(User.email == "admin@campusos.com")
    if not super_admin:
        super_admin = User(
            role=UserRole.SUPER_ADMIN.value,
            name="Platform Admin",
            email="admin@campusos.com",
            password_hash=hash_password("Admin@123"),
            is_verified=True,
        )
        await super_admin.insert()
        print("Created super admin: admin@campusos.com / Admin@123")

    # Demo college
    college = await College.find_one(College.subdomain == "demo")
    if not college:
        college = College(name="Demo University", subdomain="demo", theme_color="#2563eb")
        await college.insert()

        college_admin = User(
            college_id=college.id,
            role=UserRole.COLLEGE_ADMIN.value,
            name="Demo Admin",
            email="admin@demo.edu",
            password_hash=hash_password("Demo@123"),
            is_verified=True,
        )
        await college_admin.insert()

        student_user = User(
            college_id=college.id,
            role=UserRole.STUDENT.value,
            name="Alice Student",
            email="alice@demo.edu",
            password_hash=hash_password("Demo@123"),
            is_verified=True,
        )
        await student_user.insert()
        student = Student(
            college_id=college.id,
            user_id=student_user.id,
            roll_no="CS2024001",
            department="Computer Science",
            year=2,
            semester=3,
        )
        await student.insert()

        faculty_user = User(
            college_id=college.id,
            role=UserRole.FACULTY.value,
            name="Dr. Bob Faculty",
            email="bob@demo.edu",
            password_hash=hash_password("Demo@123"),
            is_verified=True,
        )
        await faculty_user.insert()
        faculty = Faculty(
            college_id=college.id,
            user_id=faculty_user.id,
            department="Computer Science",
            subjects=["Data Structures", "Algorithms"],
        )
        await faculty.insert()

        notification = Notification(
            college_id=college.id,
            target=NotificationTarget(scope="all"),
            title="Welcome to CampusOS!",
            body="Your smart campus platform is ready. Explore your dashboard to get started.",
            priority="normal",
            created_by=college_admin.id,
        )
        await notification.insert()

        print("Created demo college 'demo' with:")
        print("  College Admin: admin@demo.edu / Demo@123")
        print("  Student:       alice@demo.edu / Demo@123")
        print("  Faculty:       bob@demo.edu / Demo@123")
    else:
        print("Demo data already exists. Skipping.")


if __name__ == "__main__":
    asyncio.run(seed())
