"""
One-time migration script:
Assigns all existing students to faculty of the same department (branch).
Run once: python -m scripts.migrate_assign_students
"""
import asyncio
from app.db.mongo import init_db, close_db
from app.models.faculty import Faculty
from app.models.student import Student
from app.models.college import College


async def migrate():
    await init_db()

    colleges = await College.find_all().to_list()
    print(f"Found {len(colleges)} college(s)")

    total_assigned = 0

    for college in colleges:
        print(f"\nProcessing college: {college.name}")

        students = await Student.find(Student.college_id == college.id).to_list()
        faculty_list = await Faculty.find(Faculty.college_id == college.id).to_list()

        print(f"  Students: {len(students)}, Faculty: {len(faculty_list)}")

        for fac in faculty_list:
            # Find all students in same department
            dept_students = [
                s for s in students
                if s.department and fac.department and
                s.department.strip().lower() == fac.department.strip().lower()
            ]

            # Add students not already assigned
            newly_added = 0
            for student in dept_students:
                if student.user_id not in fac.student_ids:
                    fac.student_ids.append(student.user_id)
                    newly_added += 1

            if newly_added > 0:
                await fac.save()
                print(f"  Faculty '{fac.department}': assigned {newly_added} new students (total: {len(fac.student_ids)})")
                total_assigned += newly_added

    print(f"\n✅ Migration complete! Total students assigned: {total_assigned}")
    await close_db()


if __name__ == "__main__":
    asyncio.run(migrate())
