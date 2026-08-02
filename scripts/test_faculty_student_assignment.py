"""
Test script to verify Faculty-Student assignment based on Department + Year + Semester
"""
import asyncio
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie, PydanticObjectId
from app.models.faculty import Faculty
from app.models.student import Student
from app.models.user import User
from app.models.college import College
from app.core.config import get_settings

settings = get_settings()


async def test_assignment_logic():
    """Test faculty-student assignment logic"""
    
    # Initialize MongoDB
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB_NAME]
    await init_beanie(database=db, document_models=[Faculty, Student, User, College])
    
    print("🧪 Testing Faculty-Student Assignment Logic\n")
    print("=" * 80)
    
    # Get a sample college
    college = await College.find_one()
    if not college:
        print("❌ No college found in database")
        return
    
    print(f"🏫 Testing with College: {college.name} (ID: {college.id})\n")
    
    # Test 1: List all faculty with their assignments
    print("📋 TEST 1: Faculty Assignment Overview")
    print("-" * 80)
    
    faculty_list = await Faculty.find(Faculty.college_id == college.id).to_list()
    print(f"Total Faculty: {len(faculty_list)}\n")
    
    for fac in faculty_list:
        user = await User.get(fac.user_id)
        print(f"👤 {user.name if user else 'Unknown'}")
        print(f"   Department: {fac.department}")
        print(f"   Year: {fac.year if fac.year else 'Not Set'}")
        print(f"   Semester: {fac.semester if fac.semester else 'Not Set'}")
        print(f"   Subjects: {', '.join(fac.subjects) if fac.subjects else 'None'}")
        print(f"   Assigned Students: {len(fac.student_ids)}")
        
        if fac.student_ids:
            # Show assigned students
            for sid in fac.student_ids[:3]:  # Show first 3
                student = await Student.find_one(Student.user_id == sid)
                if student:
                    s_user = await User.get(student.user_id)
                    print(f"      - {s_user.name if s_user else 'Unknown'} (Y{student.year}S{student.semester}, {student.department})")
            if len(fac.student_ids) > 3:
                print(f"      ... and {len(fac.student_ids) - 3} more")
        print()
    
    # Test 2: Verify matching logic
    print("\n📋 TEST 2: Verify Department + Year + Semester Matching")
    print("-" * 80)
    
    for fac in faculty_list:
        if not fac.year or not fac.semester:
            continue
            
        user = await User.get(fac.user_id)
        print(f"\n👤 Faculty: {user.name if user else 'Unknown'}")
        print(f"   Match Criteria: {fac.department} + Year {fac.year} + Semester {fac.semester}")
        
        # Find students that should match
        expected_students = await Student.find(
            Student.college_id == college.id,
            Student.department == fac.department,
            Student.year == fac.year,
            Student.semester == fac.semester,
        ).to_list()
        
        print(f"   Expected Students: {len(expected_students)}")
        print(f"   Assigned Students: {len(fac.student_ids)}")
        
        # Check if all assigned students match criteria
        mismatches = []
        for sid in fac.student_ids:
            student = await Student.find_one(Student.user_id == sid)
            if student:
                if (student.department != fac.department or 
                    student.year != fac.year or 
                    student.semester != fac.semester):
                    mismatches.append(student)
        
        if mismatches:
            print(f"   ⚠️  {len(mismatches)} MISMATCHED students found:")
            for s in mismatches:
                s_user = await User.get(s.user_id)
                print(f"      - {s_user.name if s_user else 'Unknown'}: {s.department} Y{s.year}S{s.semester}")
        else:
            print(f"   ✅ All assigned students match criteria")
    
    # Test 3: Check for unassigned students
    print("\n\n📋 TEST 3: Unassigned Students")
    print("-" * 80)
    
    all_students = await Student.find(Student.college_id == college.id).to_list()
    assigned_student_ids = set()
    for fac in faculty_list:
        assigned_student_ids.update(fac.student_ids)
    
    unassigned = [s for s in all_students if s.user_id not in assigned_student_ids]
    
    print(f"Total Students: {len(all_students)}")
    print(f"Assigned Students: {len(assigned_student_ids)}")
    print(f"Unassigned Students: {len(unassigned)}\n")
    
    if unassigned:
        print("Unassigned Students:")
        for s in unassigned[:10]:  # Show first 10
            s_user = await User.get(s.user_id)
            print(f"   - {s_user.name if s_user else 'Unknown'}: {s.department} Y{s.year}S{s.semester}")
            
            # Check if there's a matching faculty
            matching_fac = await Faculty.find_one(
                Faculty.college_id == college.id,
                Faculty.department == s.department,
                Faculty.year == s.year,
                Faculty.semester == s.semester,
            )
            if matching_fac:
                fac_user = await User.get(matching_fac.user_id)
                print(f"      ⚠️  Matching faculty exists: {fac_user.name if fac_user else 'Unknown'}")
            else:
                print(f"      ℹ️  No matching faculty for {s.department} Y{s.year}S{s.semester}")
        
        if len(unassigned) > 10:
            print(f"   ... and {len(unassigned) - 10} more")
    
    # Summary
    print("\n\n" + "=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)
    print(f"✅ Total Faculty: {len(faculty_list)}")
    print(f"✅ Faculty with Year/Semester: {sum(1 for f in faculty_list if f.year and f.semester)}")
    print(f"✅ Total Students: {len(all_students)}")
    print(f"✅ Assigned Students: {len(assigned_student_ids)}")
    print(f"⚠️  Unassigned Students: {len(unassigned)}")
    
    client.close()


if __name__ == "__main__":
    asyncio.run(test_assignment_logic())
