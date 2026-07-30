from beanie import PydanticObjectId

from app.models.result import Result


def _calc_grade(total: float | None) -> str | None:
    if total is None:
        return None
    if total >= 90:
        return "A+"
    if total >= 80:
        return "A"
    if total >= 70:
        return "B"
    if total >= 60:
        return "C"
    return "F"


async def create_or_update_result(college_id: PydanticObjectId, payload: dict):
    # payload should have student_id, subject, internal_marks, practical_marks
    student_id = payload.get("student_id")
    subject = payload.get("subject")
    internal = payload.get("internal_marks")
    practical = payload.get("practical_marks")
    exam_name = payload.get("exam_name")

    total = None
    if internal is not None or practical is not None:
        total = (internal or 0) + (practical or 0)

    grade = _calc_grade(total)

    # Upsert by college_id + student + subject + exam
    existing = await Result.find_one(
        Result.college_id == college_id,
        Result.student_id == student_id,
        Result.subject == subject,
        Result.exam_name == exam_name,
    )
    if existing:
        existing.internal_marks = internal
        existing.practical_marks = practical
        existing.total_marks = total
        existing.grade = grade
        from app.core.deps import utcnow
        existing.updated_at = utcnow()
        await existing.save()
        return existing

    r = Result(
        college_id=college_id,
        student_id=student_id,
        faculty_id=payload.get("faculty_id"),
        created_by=payload.get("created_by"),
        subject=subject,
        exam_name=exam_name,
        internal_marks=internal,
        practical_marks=practical,
        total_marks=total,
        grade=grade,
    )
    await r.insert()
    return r


async def list_results_for_student(college_id: PydanticObjectId, student_id: PydanticObjectId, limit: int = 100, skip: int = 0):
    return await Result.find(Result.college_id == college_id, Result.student_id == student_id).skip(skip).limit(limit).to_list()
