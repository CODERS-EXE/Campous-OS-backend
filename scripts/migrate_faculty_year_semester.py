"""
Migration script to add year and semester fields to existing Faculty documents.
This script will:
1. Add year and semester fields to all existing faculty documents
2. Re-assign students to faculty based on department + year + semester matching
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.models.faculty import Faculty
from app.models.student import Student
from app.core.config import get_settings

settings = get_settings()


async def migrate_faculty_year_semester():
    """Migrate faculty to include year and semester fields"""
    
    # Initialize MongoDB connection
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB_NAME]
    
    # Initialize Beanie with the Faculty and Student models
    await init_beanie(database=db, document_models=[Faculty, Student])
    
    print("🔧 Starting Faculty Year/Semester Migration...")
    
    # Get all faculty members
    faculty_list = await Faculty.find_all().to_list()
    print(f"📋 Found {len(faculty_list)} faculty members")
    
    # Update each faculty with default values if not set
    updated_count = 0
    for faculty in faculty_list:
        # Only update if year or semester is not set
        if faculty.year is None or faculty.semester is None:
            print(f"\n👤 Updating Faculty: {faculty.user_id}")
            print(f"   Department: {faculty.department}")
            
            # Set default year and semester if not already set
            if faculty.year is None:
                faculty.year = 1  # Default to 1st year
            if faculty.semester is None:
                faculty.semester = 1  # Default to 1st semester
            
            # Clear existing student assignments for re-matching
            old_count = len(faculty.student_ids)
            faculty.student_ids = []
            
            # Find matching students based on department + year + semester
            matching_students = await Student.find(
                Student.college_id == faculty.college_id,
                Student.department == faculty.department,
                Student.year == faculty.year,
                Student.semester == faculty.semester,
            ).to_list()
            
            # Assign matching students
            faculty.student_ids = [s.user_id for s in matching_students]
            
            await faculty.save()
            
            print(f"   ✅ Updated: year={faculty.year}, semester={faculty.semester}")
            print(f"   📊 Students: {old_count} → {len(faculty.student_ids)}")
            updated_count += 1
        else:
            print(f"✓ Faculty {faculty.user_id} already has year={faculty.year}, semester={faculty.semester}")
    
    print(f"\n✅ Migration Complete!")
    print(f"   Total Faculty: {len(faculty_list)}")
    print(f"   Updated: {updated_count}")
    print(f"   Skipped: {len(faculty_list) - updated_count}")
    
    # Close the connection
    client.close()


if __name__ == "__main__":
    asyncio.run(migrate_faculty_year_semester())
