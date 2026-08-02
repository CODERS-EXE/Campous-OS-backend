"""
Quick test to update faculty with year/semester via update logic
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.models.faculty import Faculty
from app.models.student import Student
from app.models.user import User
from app.models.college import College
from app.services.users import update_user
from app.core.config import get_settings

settings = get_settings()


async def test_update():
    # Initialize MongoDB
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB_NAME]
    await init_beanie(database=db, document_models=[Faculty, Student, User, College])
    
    print("🧪 Testing Faculty Update with Year/Semester\n")
    
    # Get first faculty
    faculty_doc = await Faculty.find_one()
    if not faculty_doc:
        print("❌ No faculty found")
        return
    
    user = await User.get(faculty_doc.user_id)
    print(f"👤 Faculty: {user.name}")
    print(f"   Before: Dept={faculty_doc.department}, Year={faculty_doc.year}, Sem={faculty_doc.semester}")
    print(f"   Students: {len(faculty_doc.student_ids)}")
    
    # Update to Year 3, Semester 5 (matching the students)
    print("\n🔄 Updating to Year=3, Semester=5...")
    
    updated_user = await update_user(
        user=user,
        year=3,
        semester=5,
    )
    
    # Fetch updated faculty
    faculty_doc = await Faculty.find_one(Faculty.user_id == user.id)
    print(f"\n✅ After: Dept={faculty_doc.department}, Year={faculty_doc.year}, Sem={faculty_doc.semester}")
    print(f"   Students: {len(faculty_doc.student_ids)}")
    
    if faculty_doc.student_ids:
        print(f"\n   Assigned Students:")
        for sid in faculty_doc.student_ids:
            student = await Student.find_one(Student.user_id == sid)
            if student:
                s_user = await User.get(student.user_id)
                print(f"      - {s_user.name}: {student.department} Y{student.year}S{student.semester}")
    
    client.close()


if __name__ == "__main__":
    asyncio.run(test_update())
