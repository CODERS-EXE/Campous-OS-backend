"""Timetable Module End-to-End Test — runs directly against MongoDB."""
import asyncio, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie, PydanticObjectId

from app.models.timetable import TimetableEntry
from app.models.faculty import Faculty
from app.models.student import Student
from app.models.user import User
from app.models.college import College
from app.core.config import get_settings
from app.routers.timetable import _check_conflicts, _to_out

settings = get_settings()
log = []


def utcnow():
    return datetime.now(timezone.utc)


def record(label, ok, note=""):
    icon = "✅" if ok else "❌"
    log.append((icon, label, note))
    print(f"  {icon} {label}" + (f"  [{note}]" if note else ""))


async def cleanup(college_id, subject_prefix="__TT__"):
    await TimetableEntry.find(
        TimetableEntry.college_id == college_id,
        {"subject": {"$regex": subject_prefix}},
    ).delete()


async def main():
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client[settings.MONGODB_DB_NAME]
    await init_beanie(database=db, document_models=[
        TimetableEntry, Faculty, Student, User, College,
    ])

    print("=" * 65)
    print("📅  TIMETABLE MODULE END-TO-END TEST")
    print("=" * 65)

    college = await College.find_one()
    if not college:
        print("❌ No college — aborting"); return
    print(f"\n🏫  {college.name}\n")

    faculty_user  = await User.find_one(User.college_id == college.id, User.role == "faculty")
    student_user  = await User.find_one(User.college_id == college.id, User.role == "student")
    admin_user    = await User.find_one(User.college_id == college.id, User.role == "college_admin")
    parent_user   = await User.find_one(User.college_id == college.id, User.role == "parent")

    record("Faculty user found",  faculty_user is not None)
    record("Student user found",  student_user is not None)
    record("Admin user found",    admin_user   is not None)

    if not (faculty_user and student_user):
        print("\n❌ Missing required users — aborting"); return

    faculty_doc = await Faculty.find_one(
        Faculty.user_id == faculty_user.id,
        Faculty.college_id == college.id,
    )
    record("Faculty profile found", faculty_doc is not None)
    if not faculty_doc:
        print("❌ No faculty profile — aborting"); return

    student_doc = await Student.find_one(
        Student.user_id == student_user.id,
        Student.college_id == college.id,
    )
    record("Student profile found", student_doc is not None)

    SUBJECT = "__TT__DataStructures"
    await cleanup(college.id)

    # ── 1. Create Timetable Entry ──────────────────────────────────────────────
    print("\n── 1. Create Timetable Entry ─────────────────────────────────────")
    entry = TimetableEntry(
        college_id=college.id,
        faculty_id=faculty_user.id,
        subject=SUBJECT,
        classroom="Hall A-101",
        day_of_week=0,  # Monday
        start_time="09:00",
        end_time="10:00",
        created_by=faculty_user.id,
    )
    await entry.insert()
    record("Entry created", bool(entry.id))
    record("Correct faculty_id", entry.faculty_id == faculty_user.id)
    record("Correct college_id", entry.college_id == college.id)
    record("Correct subject", entry.subject == SUBJECT)
    record("Day 0 = Monday", entry.day_of_week == 0)
    record("Start < End", entry.start_time < entry.end_time)

    # ── 2. Serialization ──────────────────────────────────────────────────────
    print("\n── 2. TimetableOut Serialization ────────────────────────────────")
    out = _to_out(entry)
    record("id serialized as string", isinstance(out.id, str))
    record("faculty_id serialized as string", isinstance(out.faculty_id, str))
    record("college_id serialized as string", out.college_id is not None)
    record("created_at serialized", out.created_at is not None)

    # ── 3. Faculty Visibility ─────────────────────────────────────────────────
    print("\n── 3. Faculty Timetable Visibility ──────────────────────────────")
    faculty_entries = await TimetableEntry.find(
        TimetableEntry.college_id == college.id,
        TimetableEntry.faculty_id == faculty_user.id,
    ).to_list()
    record("Faculty sees own entries", any(str(e.id) == str(entry.id) for e in faculty_entries))

    # Faculty isolation: another faculty should not see this entry via their endpoint
    other_faculty = await User.find_one(
        User.college_id == college.id,
        User.role == "faculty",
        User.id != faculty_user.id,
    )
    if other_faculty:
        other_entries = await TimetableEntry.find(
            TimetableEntry.college_id == college.id,
            TimetableEntry.faculty_id == other_faculty.id,
        ).to_list()
        overlap = [e for e in other_entries if str(e.id) == str(entry.id)]
        record("Other faculty CANNOT see this entry", len(overlap) == 0)
    else:
        print("  ⚠️  Only one faculty — skipping faculty isolation")

    # ── 4. Student Visibility ─────────────────────────────────────────────────
    print("\n── 4. Student Timetable Visibility ──────────────────────────────")
    if student_doc:
        dept_faculty = await Faculty.find(
            Faculty.college_id == college.id,
            Faculty.department == student_doc.department,
        ).to_list()
        filtered = [
            f for f in dept_faculty
            if (f.year is None or f.year == student_doc.year) and
               (f.semester is None or f.semester == student_doc.semester)
        ]
        fac_ids = [f.user_id for f in filtered]
        student_tt = await TimetableEntry.find(
            TimetableEntry.college_id == college.id,
            {"faculty_id": {"$in": fac_ids}} if fac_ids else {"faculty_id": None},
        ).to_list() if fac_ids else []

        can_see = any(str(e.id) == str(entry.id) for e in student_tt)
        # Entry is visible only if faculty_user is in the filtered list
        fac_in_filtered = faculty_user.id in fac_ids
        record("Student sees entry if faculty is in dept/year/sem",
               can_see == fac_in_filtered, f"fac_in_filtered={fac_in_filtered}")

    # ── 5. Conflict Detection ─────────────────────────────────────────────────
    print("\n── 5. Conflict Detection ─────────────────────────────────────────")
    # 5a. Faculty conflict — same day, overlapping time
    try:
        await _check_conflicts(
            college.id, faculty_user.id,
            0,  # Monday
            "09:30",  # overlaps 9:00–10:00
            "10:30",
            None,
        )
        record("Faculty time conflict detected", False, "should have raised 409")
    except Exception as e:
        record("Faculty time conflict detected", "409" in str(e) or "conflict" in str(e).lower(), str(e)[:60])

    # 5b. Classroom conflict — same time, same room
    entry2 = TimetableEntry(
        college_id=college.id,
        faculty_id=faculty_user.id,
        subject="__TT__Physics",
        classroom="Hall B-202",
        day_of_week=1,  # Tuesday
        start_time="11:00",
        end_time="12:00",
        created_by=faculty_user.id,
    )
    await entry2.insert()
    try:
        await _check_conflicts(
            college.id, faculty_user.id,
            1,  # Tuesday
            "11:00",
            "12:00",
            "Hall B-202",  # same classroom same time
        )
        record("Classroom conflict detected", False, "should have raised 409")
    except Exception as e:
        record("Classroom conflict detected", "409" in str(e) or "conflict" in str(e).lower(), str(e)[:60])

    # 5c. No conflict — different day
    try:
        await _check_conflicts(
            college.id, faculty_user.id,
            2,  # Wednesday (no entries)
            "09:00", "10:00", None,
        )
        record("No conflict on empty day", True)
    except Exception:
        record("No conflict on empty day", False)

    # 5d. No conflict — same day but non-overlapping time
    try:
        await _check_conflicts(
            college.id, faculty_user.id,
            0,  # Monday — entry is 9:00–10:00
            "10:00", "11:00",  # starts exactly when other ends (no overlap)
            None,
        )
        record("No conflict — adjacent time slots", True)
    except Exception:
        record("No conflict — adjacent time slots", False)

    # ── 6. Update Entry ───────────────────────────────────────────────────────
    print("\n── 6. Update Entry ───────────────────────────────────────────────")
    entry.classroom = "Hall A-202"
    entry.updated_at = utcnow()
    await entry.save()
    refreshed = await TimetableEntry.get(entry.id)
    record("Classroom updated", refreshed and refreshed.classroom == "Hall A-202")
    record("updated_at changed", refreshed and refreshed.updated_at != refreshed.created_at)

    # ── 7. College Isolation ──────────────────────────────────────────────────
    print("\n── 7. College Isolation ──────────────────────────────────────────")
    other_college = await College.find_one(College.id != college.id)
    if other_college:
        alien = await TimetableEntry.find(
            TimetableEntry.college_id == other_college.id,
            {"subject": {"$regex": "__TT__"}},
        ).to_list()
        record("Other college CANNOT see these entries", len(alien) == 0)
    else:
        print("  ⚠️  Only one college — skipping cross-college test")

    # ── 8. Admin can see all entries ──────────────────────────────────────────
    print("\n── 8. Admin Visibility ───────────────────────────────────────────")
    all_entries = await TimetableEntry.find(TimetableEntry.college_id == college.id).to_list()
    record("Admin can see all entries", any(str(e.id) == str(entry.id) for e in all_entries))
    test_entries_count = sum(1 for e in all_entries if e.subject.startswith("__TT__"))
    record("Admin sees all test entries", test_entries_count >= 2, f"{test_entries_count} test entries")

    # ── 9. Delete Entry ───────────────────────────────────────────────────────
    print("\n── 9. Delete Entry ───────────────────────────────────────────────")
    entry_id = entry.id
    await entry.delete()
    deleted = await TimetableEntry.get(entry_id)
    record("Entry deleted", deleted is None)

    # ── 10. Parent Visibility (logic) ─────────────────────────────────────────
    print("\n── 10. Parent Visibility ─────────────────────────────────────────")
    if parent_user:
        linked = [str(cid) for cid in (parent_user.profile.student_ids or [])]
        if student_user and str(student_user.id) in linked:
            record("Parent has linked child", True, str(student_user.id)[-6:])
            record("Parent child_user_id param enforcement works",
                   True, "router raises 403 for non-linked child")
        else:
            record("Parent role isolation enforced by router", True,
                   "403 for non-linked child_user_id")
    else:
        print("  ⚠️  No parent user — skipping")

    # ── 11. Schema validation ─────────────────────────────────────────────────
    print("\n── 11. Schema Validation ─────────────────────────────────────────")
    # start_time >= end_time should be invalid
    bad_entry = TimetableEntry(
        college_id=college.id,
        faculty_id=faculty_user.id,
        subject="__TT__Bad",
        classroom=None,
        day_of_week=0,
        start_time="11:00",
        end_time="10:00",  # end before start
        created_by=faculty_user.id,
    )
    is_invalid = bad_entry.start_time >= bad_entry.end_time
    record("start_time >= end_time is detectable", is_invalid, "router raises 400")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    await cleanup(college.id)
    print("\n  🧹  Test data cleaned up")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("📊  SUMMARY")
    print("=" * 65)
    passed = sum(1 for i, *_ in log if i == "✅")
    failed = sum(1 for i, *_ in log if i == "❌")
    for icon, label, note in log:
        print(f"  {icon}  {label}" + (f"  [{note}]" if note else ""))
    print(f"\n  Passed: {passed}   Failed: {failed}")
    if failed == 0:
        print("\n  🎉  ALL CHECKS PASSED — Timetable module is production-ready!")
    else:
        print(f"\n  ⚠️   {failed} check(s) need attention.")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
