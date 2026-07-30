from typing import List
from beanie import PydanticObjectId

from app.models.assignment import Assignment
from app.models.submission import Submission


async def create_assignment(college_id: PydanticObjectId, created_by: PydanticObjectId, payload: dict):
    a = Assignment(college_id=college_id, created_by=created_by, **payload)
    await a.insert()
    return a


async def update_assignment(assignment_id: PydanticObjectId, college_id: PydanticObjectId, payload: dict):
    a = await Assignment.get(assignment_id)
    if not a or a.college_id != college_id:
        return None
    for k, v in payload.items():
        setattr(a, k, v)
    from app.core.deps import utcnow
    a.updated_at = utcnow()
    await a.save()
    return a


async def list_assignments(college_id: PydanticObjectId, created_by: PydanticObjectId | None = None, limit: int = 100, skip: int = 0):
    q = Assignment.find(Assignment.college_id == college_id)
    if created_by:
        q = q.find(Assignment.created_by == created_by)
    return await q.sort(-Assignment.created_at).skip(skip).limit(limit).to_list()


async def create_submission(college_id: PydanticObjectId, payload: dict):
    # Ensure created_by set (student submitting)
    if "created_by" not in payload:
        payload["created_by"] = payload.get("student_id")
    # Ensure timestamps
    from app.core.deps import utcnow
    payload.setdefault("created_at", utcnow())
    payload.setdefault("updated_at", utcnow())
    s = Submission(college_id=college_id, **payload)
    await s.insert()
    return s


async def list_submissions_for_assignment(college_id: PydanticObjectId, assignment_id: PydanticObjectId, limit: int = 100, skip: int = 0):
    return await Submission.find(Submission.college_id == college_id, Submission.assignment_id == assignment_id).skip(skip).limit(limit).to_list()
