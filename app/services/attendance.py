from datetime import datetime, timezone
from typing import List
from beanie import PydanticObjectId

from app.models.attendance import Attendance, StudentAttendance


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_attendance(
    college_id: PydanticObjectId,
    faculty_id: PydanticObjectId,
    subject: str,
    date,
    session_name: str | None,
    records: List[dict],
) -> Attendance:
    att = Attendance(
        college_id=college_id,
        faculty_id=faculty_id,
        subject=subject,
        date=date,
        session_name=session_name,
        records=[StudentAttendance(**r) for r in records],
        created_by=faculty_id,
    )
    await att.insert()
    return att


async def update_attendance(
    att_id: PydanticObjectId,
    college_id: PydanticObjectId,
    records: List[dict],
) -> Attendance | None:
    att = await Attendance.get(att_id)
    if not att or att.college_id != college_id:
        return None
    att.records = [StudentAttendance(**r) for r in records]
    att.updated_at = utcnow()
    await att.save()
    return att


async def get_attendance_for_faculty(
    college_id: PydanticObjectId,
    faculty_id: PydanticObjectId,
    limit: int = 50,
) -> List[Attendance]:
    return await (
        Attendance.find(
            Attendance.college_id == college_id,
            Attendance.faculty_id == faculty_id,
        )
        .sort(-Attendance.date)
        .limit(limit)
        .to_list()
    )


async def get_attendance_by_id(att_id: PydanticObjectId) -> Attendance | None:
    return await Attendance.get(att_id)
