"""
Test updating second faculty to same Year/Semester to verify no duplicate assignments
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


async def test_second_faculty():
    # Initialize MongoDB
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB_NAME]
    await init_beanie(database=db, document_models=[Faculty, Student, User, College])
    
    print("🧪 Testing Second Faculty Assignment to Same Year/Semester\n")
    
    # Get second faculty
    faculty_list = await Faculty.find().to_list()
    if len(faculty_list) < 2:
        print("❌ Need at least 2 faculty members")
        return
    
    second_faculty_doc = faculty_list[1]
    user = await User.get(second_faculty_doc.user_id)
    
    print(f"👤 Faculty: {user.name}")
    print(f"   Before: Dept={second_faculty_doc.department}, Year={second_faculty_doc.year}, Sem={second_faculty_doc.semester}")
    print(f"   Students: {len(second_faculty_doc.student_ids)}")
    
    # Update to Year 3, Semester 5 (same as first faculty)
    print("\n🔄 Updating to Year=3, Semester=5 (same as first faculty)...")
    
    await update_user(
        user=user,
        year=3,
        semester=5,
    )
    
    # Check both faculty
    print("\n📊 Final Assignment State:")
    print("=" * 60)
    
    for fac_doc in await Faculty.find().to_list():
        fac_user = await User.get(fac_doc.user_id)
        print(f"\n👤 {fac_user.name}")
        print(f"   {fac_doc.department} Y{fac_doc.year}S{fac_doc.semester}")
        print(f"   Students: {len(fac_doc.student_ids)}")
        
        if fac_doc.student_ids:
            for sid in fac_doc.student_ids:
                student = await Student.find_one(Student.user_id == sid)
                if student:
                    s_user = await User.get(student.user_id)
                    print(f"      - {s_user.name}")
    
    # Check if students are assigned to multiple faculty
    print("\n\n⚠️  Checking for Duplicate Assignments:")
    print("-" * 60)
    
    all_student_assignments = {}
    for fac_doc in await Faculty.find().to_list():
        fac_user = await User.get(fac_doc.user_id)
        for sid in fac_doc.student_ids:
            if sid not in all_student_assignments:
                all_student_assignments[sid] = []
            all_student_assignments[sid].append(fac_user.name)
    
    duplicates_found = False
    for sid, faculty_names in all_student_assignments.items():
        if len(faculty_names) > 1:
            student = await Student.find_one(Student.user_id == sid)
            s_user = await User.get(sid)
            print(f"❌ {s_user.name} is assigned to {len(faculty_names)} faculty:")
            for fn in faculty_names:
                print(f"   - {fn}")
            duplicates_found = True
    
    if not duplicates_found:
        print("✅ No duplicate assignments found - Each student assigned to exactly one faculty!")
    
    client.close()


if __name__ == "__main__":
    asyncio.run(test_second_faculty())
