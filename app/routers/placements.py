"""
Placements Router
Complete placement management endpoints for companies, drives, applications, interviews, and offers
"""
import logging
from typing import List, Optional, Annotated
from datetime import datetime
import csv
import io

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from beanie import PydanticObjectId

from app.core.constants import UserRole
from app.core.deps import get_current_user, get_tenant_college, get_tenant_scoped_user, require_roles, resolve_tenant
from app.core.websocket_manager import manager
from app.models.college import College
from app.models.user import User
from app.models.student import Student
from app.models.company import Company, CompanyContact
from app.models.placement_drive import PlacementDrive, EligibilityCriteria, PackageDetails, DriveLocation
from app.models.student_application import StudentApplication
from app.models.interview_round import InterviewRound
from app.models.placement_offer import PlacementOffer
from app.services.notification_service import notify_placement_drive_created, notify_placement_selected

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/placements", tags=["placements"])


# ==================== COMPANY ENDPOINTS ====================

@router.get("/companies", status_code=200)
async def list_companies(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    search: Optional[str] = None,
    industry: Optional[str] = None,
    tier: Optional[str] = None,
    is_active: Optional[bool] = None,
    limit: int = 50,
    skip: int = 0,
):
    """List all companies for the college with optional filters"""
    query = {"college_id": college.id}
    
    if search:
        query["name"] = {"$regex": search, "$options": "i"}
    if industry:
        query["industry"] = industry
    if tier:
        query["tier"] = tier
    if is_active is not None:
        query["is_active"] = is_active
    
    companies = await Company.find(query).skip(skip).limit(limit).to_list()
    total = await Company.find(query).count()
    
    return {
        "companies": companies,
        "total": total,
        "limit": limit,
        "skip": skip
    }


@router.post("/companies", status_code=201)
async def create_company(
    company_data: dict,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Create a new company (College Admin only)"""
    company = Company(
        college_id=college.id,
        name=company_data["name"],
        description=company_data.get("description"),
        website=company_data.get("website"),
        logo_url=company_data.get("logo_url"),
        industry=company_data["industry"],
        location=company_data["location"],
        tier=company_data.get("tier", "tier_2"),
        employee_count=company_data.get("employee_count"),
        contacts=[CompanyContact(**c) for c in company_data.get("contacts", [])],
        created_by=user.id,
    )
    
    await company.insert()
    logger.info(f"Company created: {company.name} by {user.email}")
    
    return company


@router.get("/companies/{company_id}")
async def get_company(
    company_id: str,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Get company details"""
    company = await Company.get(PydanticObjectId(company_id))
    
    if not company or company.college_id != college.id:
        raise HTTPException(status_code=404, detail="Company not found")
    
    return company


@router.patch("/companies/{company_id}")
async def update_company(
    company_id: str,
    update_data: dict,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Update company details"""
    company = await Company.get(PydanticObjectId(company_id))
    
    if not company or company.college_id != college.id:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Update allowed fields
    for field in ["name", "description", "website", "logo_url", "industry", 
                  "location", "tier", "employee_count", "is_active"]:
        if field in update_data:
            setattr(company, field, update_data[field])
    
    if "contacts" in update_data:
        company.contacts = [CompanyContact(**c) for c in update_data["contacts"]]
    
    company.updated_at = datetime.utcnow()
    await company.save()
    
    return company


@router.delete("/companies/{company_id}")
async def delete_company(
    company_id: str,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Delete a company"""
    company = await Company.get(PydanticObjectId(company_id))
    
    if not company or company.college_id != college.id:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Check if company has active drives
    active_drives = await PlacementDrive.find(
        {"company_id": company.id, "status": {"$in": ["open", "draft"]}}
    ).count()
    
    if active_drives > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete company with {active_drives} active placement drives"
        )
    
    await company.delete()
    return {"ok": True, "message": "Company deleted successfully"}


# ==================== PLACEMENT DRIVE ENDPOINTS ====================

@router.get("/drives", status_code=200)
async def list_placement_drives(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    status: Optional[str] = None,
    company_id: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
):
    """List all placement drives"""
    query = {"college_id": college.id}
    
    if status:
        query["status"] = status
    if company_id:
        query["company_id"] = PydanticObjectId(company_id)
    
    drives = await PlacementDrive.find(query).sort(-PlacementDrive.created_at).skip(skip).limit(limit).to_list()
    total = await PlacementDrive.find(query).count()
    
    # Populate company details
    result = []
    for drive in drives:
        company = await Company.get(drive.company_id)
        drive_dict = drive.dict()
        drive_dict["company"] = company.dict() if company else None
        result.append(drive_dict)
    
    return {
        "drives": result,
        "total": total,
        "limit": limit,
        "skip": skip
    }


@router.post("/drives", status_code=201)
async def create_placement_drive(
    drive_data: dict,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Create a new placement drive"""
    # Validate company exists
    company = await Company.get(PydanticObjectId(drive_data["company_id"]))
    if not company or company.college_id != college.id:
        raise HTTPException(status_code=404, detail="Company not found")
    
    drive = PlacementDrive(
        college_id=college.id,
        company_id=company.id,
        title=drive_data["title"],
        description=drive_data.get("description"),
        role=drive_data["role"],
        role_type=drive_data.get("role_type", "full_time"),
        package=PackageDetails(**drive_data["package"]),
        locations=[DriveLocation(**loc) for loc in drive_data.get("locations", [])],
        eligibility=EligibilityCriteria(**drive_data.get("eligibility", {})),
        start_date=datetime.fromisoformat(drive_data["start_date"]),
        deadline=datetime.fromisoformat(drive_data["deadline"]),
        interview_start_date=datetime.fromisoformat(drive_data["interview_start_date"]) if drive_data.get("interview_start_date") else None,
        expected_joining_date=datetime.fromisoformat(drive_data["expected_joining_date"]) if drive_data.get("expected_joining_date") else None,
        status=drive_data.get("status", "draft"),
        total_positions=drive_data.get("total_positions"),
        job_description_url=drive_data.get("job_description_url"),
        selection_process=drive_data.get("selection_process"),
        bond_duration=drive_data.get("bond_duration"),
        created_by=user.id,
    )
    
    await drive.insert()
    logger.info(f"Placement drive created: {drive.title} by {user.email}")
    
    # Send notification to eligible students if drive is open
    if drive.status == "open":
        deadline_str = drive.deadline.strftime("%Y-%m-%d") if drive.deadline else "TBD"
        background_tasks.add_task(
            notify_placement_drive_created,
            college_id=college.id,
            company_name=company.name,
            role_name=drive.role,
            deadline=deadline_str,
            drive_id=str(drive.id),
            created_by=user.id,
        )
    
    return drive


@router.get("/drives/{drive_id}")
async def get_placement_drive(
    drive_id: str,
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Get placement drive details"""
    drive = await PlacementDrive.get(PydanticObjectId(drive_id))
    
    if not drive or drive.college_id != college.id:
        raise HTTPException(status_code=404, detail="Placement drive not found")
    
    # Get company details
    company = await Company.get(drive.company_id)
    
    drive_dict = drive.dict()
    drive_dict["company"] = company.dict() if company else None
    
    # If student, check eligibility and application status
    if user.role == UserRole.STUDENT:
        student = await Student.find_one({"user_id": user.id})
        if student:
            # Check eligibility
            is_eligible = check_student_eligibility(student, drive.eligibility)
            drive_dict["is_eligible"] = is_eligible
            drive_dict["eligibility_reasons"] = get_eligibility_reasons(student, drive.eligibility)
            
            # Check if already applied
            application = await StudentApplication.find_one({
                "drive_id": drive.id,
                "student_id": student.id
            })
            drive_dict["has_applied"] = application is not None
            drive_dict["application_status"] = application.status if application else None
    
    return drive_dict


@router.patch("/drives/{drive_id}")
async def update_placement_drive(
    drive_id: str,
    update_data: dict,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Update placement drive"""
    drive = await PlacementDrive.get(PydanticObjectId(drive_id))
    
    if not drive or drive.college_id != college.id:
        raise HTTPException(status_code=404, detail="Placement drive not found")
    
    # Update fields
    for field in ["title", "description", "role", "role_type", "status", 
                  "total_positions", "job_description_url", "selection_process", "bond_duration"]:
        if field in update_data:
            setattr(drive, field, update_data[field])
    
    if "package" in update_data:
        drive.package = PackageDetails(**update_data["package"])
    
    if "eligibility" in update_data:
        drive.eligibility = EligibilityCriteria(**update_data["eligibility"])
    
    if "locations" in update_data:
        drive.locations = [DriveLocation(**loc) for loc in update_data["locations"]]
    
    for date_field in ["start_date", "deadline", "interview_start_date", "expected_joining_date"]:
        if date_field in update_data and update_data[date_field]:
            setattr(drive, date_field, datetime.fromisoformat(update_data[date_field]))
    
    drive.updated_at = datetime.utcnow()
    await drive.save()
    
    return drive


@router.delete("/drives/{drive_id}")
async def delete_placement_drive(
    drive_id: str,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Delete a placement drive"""
    drive = await PlacementDrive.get(PydanticObjectId(drive_id))
    
    if not drive or drive.college_id != college.id:
        raise HTTPException(status_code=404, detail="Placement drive not found")
    
    # Check if drive has applications
    applications_count = await StudentApplication.find({"drive_id": drive.id}).count()
    
    if applications_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete drive with {applications_count} applications. Close the drive instead."
        )
    
    await drive.delete()
    return {"ok": True, "message": "Placement drive deleted successfully"}


# ==================== HELPER FUNCTIONS ====================

def check_student_eligibility(student: Student, criteria: EligibilityCriteria) -> bool:
    """Check if student meets eligibility criteria"""
    # Check CGPA
    if hasattr(student, 'cgpa') and student.cgpa:
        if student.cgpa < criteria.min_cgpa:
            return False
    
    # Check branch
    if criteria.allowed_branches and len(criteria.allowed_branches) > 0:
        if student.department not in criteria.allowed_branches:
            return False
    
    # Check backlogs
    if hasattr(student, 'backlogs') and student.backlogs:
        if student.backlogs > criteria.max_backlogs:
            return False
    
    # Check year
    if criteria.year_of_study and len(criteria.year_of_study) > 0:
        if hasattr(student, 'year') and student.year:
            if student.year not in criteria.year_of_study:
                return False
    
    return True


def get_eligibility_reasons(student: Student, criteria: EligibilityCriteria) -> List[str]:
    """Get reasons why student is eligible or not"""
    reasons = []
    
    # CGPA check
    if hasattr(student, 'cgpa') and student.cgpa:
        if student.cgpa < criteria.min_cgpa:
            reasons.append(f"CGPA {student.cgpa} is below minimum {criteria.min_cgpa}")
        else:
            reasons.append(f"✓ CGPA {student.cgpa} meets requirement")
    
    # Branch check
    if criteria.allowed_branches and len(criteria.allowed_branches) > 0:
        if student.department not in criteria.allowed_branches:
            reasons.append(f"Branch {student.department} not in allowed list: {', '.join(criteria.allowed_branches)}")
        else:
            reasons.append(f"✓ Branch {student.department} is allowed")
    
    # Backlogs check
    if hasattr(student, 'backlogs'):
        if student.backlogs > criteria.max_backlogs:
            reasons.append(f"Backlogs {student.backlogs} exceed maximum {criteria.max_backlogs}")
        else:
            reasons.append(f"✓ Backlogs {student.backlogs} within limit")
    
    return reasons


# ==================== STUDENT APPLICATION ENDPOINTS ====================

@router.get("/applications", status_code=200)
async def list_applications(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    drive_id: Optional[str] = None,
    student_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
):
    """List applications - filtered by role"""
    query = {"college_id": college.id}
    
    if drive_id:
        query["drive_id"] = PydanticObjectId(drive_id)
    
    # Students can only see their own applications
    if user.role == UserRole.STUDENT:
        student = await Student.find_one({"user_id": user.id})
        if student:
            query["student_id"] = student.id
    elif student_id:
        query["student_id"] = PydanticObjectId(student_id)
    
    if status:
        query["status"] = status
    
    applications = await StudentApplication.find(query).sort(-StudentApplication.applied_at).skip(skip).limit(limit).to_list()
    total = await StudentApplication.find(query).count()
    
    # Populate drive and company details
    result = []
    for app in applications:
        drive = await PlacementDrive.get(app.drive_id)
        company = await Company.get(drive.company_id) if drive else None
        
        app_dict = app.dict()
        app_dict["drive"] = drive.dict() if drive else None
        app_dict["company"] = company.dict() if company else None
        result.append(app_dict)
    
    return {
        "applications": result,
        "total": total,
        "limit": limit,
        "skip": skip
    }


@router.post("/applications", status_code=201)
async def apply_to_drive(
    application_data: dict,
    user: Annotated[User, Depends(require_roles(UserRole.STUDENT))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Student applies to a placement drive"""
    drive = await PlacementDrive.get(PydanticObjectId(application_data["drive_id"]))
    
    if not drive or drive.college_id != college.id:
        raise HTTPException(status_code=404, detail="Placement drive not found")
    
    if drive.status != "open":
        raise HTTPException(status_code=400, detail="Placement drive is not open for applications")
    
    if drive.deadline < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Application deadline has passed")
    
    # Get student details
    student = await Student.find_one({"user_id": user.id})
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found")
    
    # Check if already applied
    existing = await StudentApplication.find_one({
        "drive_id": drive.id,
        "student_id": student.id
    })
    
    if existing:
        raise HTTPException(status_code=400, detail="Already applied to this drive")
    
    # Check eligibility
    is_eligible = check_student_eligibility(student, drive.eligibility)
    if not is_eligible:
        reasons = get_eligibility_reasons(student, drive.eligibility)
        raise HTTPException(
            status_code=400,
            detail=f"Not eligible for this drive. Reasons: {'; '.join(reasons)}"
        )
    
    # Create application
    application = StudentApplication(
        college_id=college.id,
        drive_id=drive.id,
        student_id=student.id,
        resume_url=application_data.get("resume_url"),
        cover_letter=application_data.get("cover_letter"),
        portfolio_url=application_data.get("portfolio_url"),
        student_name=student.name,
        student_email=student.email,
        student_roll_no=student.roll_no,
        student_department=student.department,
        student_cgpa=student.cgpa if hasattr(student, 'cgpa') else None,
        student_year=student.year if hasattr(student, 'year') else None,
        status="applied",
    )
    
    await application.insert()
    
    # Update drive statistics
    drive.total_applications += 1
    await drive.save()
    
    # Send notification to college admin
    await manager.send_notification(
        notification_data={
            "id": str(application.id),
            "title": "New Placement Application",
            "body": f"{student.name} applied for {drive.title}",
            "type": "placement",
            "action_url": f"/college-admin/applications",
        },
        target_scope="role",
        target_role="college_admin",
        college_id=str(college.id)
    )
    
    logger.info(f"Application created: {student.name} -> {drive.title}")
    
    return application


@router.patch("/applications/{application_id}/status")
async def update_application_status(
    application_id: str,
    status_data: dict,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.FACULTY))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Update application status (Admin/Faculty only)"""
    application = await StudentApplication.get(PydanticObjectId(application_id))
    
    if not application or application.college_id != college.id:
        raise HTTPException(status_code=404, detail="Application not found")
    
    new_status = status_data["status"]
    application.status = new_status
    application.status_updated_at = datetime.utcnow()
    application.reviewed_by = user.id
    
    if "remarks" in status_data:
        application.remarks = status_data["remarks"]
    
    if new_status == "rejected" and "rejection_reason" in status_data:
        application.rejection_reason = status_data["rejection_reason"]
    
    await application.save()
    
    # Update drive statistics
    drive = await PlacementDrive.get(application.drive_id)
    if new_status == "shortlisted":
        drive.shortlisted_count += 1
    elif new_status == "selected":
        drive.selected_count += 1
    await drive.save()
    
    # Resolve the student's User ID once for all notification targets in this function
    student_doc = await Student.get(application.student_id)
    notif_target_user_id = (
        str(student_doc.user_id) if student_doc else str(application.student_id)
    )

    # Send targeted notification for "selected" status via notification service
    if new_status == "selected":
        company = await Company.get(drive.company_id)
        company_name = company.name if company else drive.title
        background_tasks.add_task(
            notify_placement_selected,
            college_id=college.id,
            student_user_id=notif_target_user_id,
            company_name=company_name,
            role_name=drive.role,
            application_id=str(application.id),
            created_by=user.id,
        )
    elif new_status in ("shortlisted", "interview_scheduled", "rejected"):
        # Use existing WebSocket manager for other status updates
        status_messages = {
            "shortlisted": "You have been shortlisted",
            "interview_scheduled": "Your interview has been scheduled",
            "rejected": "Application status updated",
        }
        await manager.send_notification(
            notification_data={
                "id": str(application.id),
                "title": f"Application Update: {drive.title}",
                "body": status_messages.get(new_status, "Status updated"),
                "type": "placement",
                "priority": "normal",
                "action_url": "/student/placement-applications",
            },
            target_scope="user",
            target_user_id=notif_target_user_id,
            college_id=str(college.id)
        )

    return application


@router.delete("/applications/{application_id}")
async def withdraw_application(
    application_id: str,
    user: Annotated[User, Depends(require_roles(UserRole.STUDENT))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Student withdraws application"""
    application = await StudentApplication.get(PydanticObjectId(application_id))
    
    if not application or application.college_id != college.id:
        raise HTTPException(status_code=404, detail="Application not found")
    
    # Verify student owns this application
    student = await Student.find_one({"user_id": user.id})
    if not student or application.student_id != student.id:
        raise HTTPException(status_code=403, detail="Not authorized to withdraw this application")
    
    if application.status in ["selected", "offer_accepted"]:
        raise HTTPException(status_code=400, detail="Cannot withdraw after selection/offer acceptance")
    
    application.status = "withdrawn"
    application.status_updated_at = datetime.utcnow()
    await application.save()
    
    # Update drive statistics
    drive = await PlacementDrive.get(application.drive_id)
    drive.total_applications -= 1
    await drive.save()
    
    return {"ok": True, "message": "Application withdrawn successfully"}


# ==================== INTERVIEW ROUND ENDPOINTS ====================

@router.get("/interviews", status_code=200)
async def list_interviews(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    drive_id: Optional[str] = None,
    student_id: Optional[str] = None,
    status: Optional[str] = None,
):
    """List interview rounds"""
    query = {"college_id": college.id}
    
    if drive_id:
        query["drive_id"] = PydanticObjectId(drive_id)
    
    # Students can only see their own interviews
    if user.role == UserRole.STUDENT:
        student = await Student.find_one({"user_id": user.id})
        if student:
            query["student_id"] = student.id
    elif student_id:
        query["student_id"] = PydanticObjectId(student_id)
    
    if status:
        query["status"] = status
    
    interviews = await InterviewRound.find(query).sort(InterviewRound.scheduled_at).to_list()
    
    # Populate details
    result = []
    for interview in interviews:
        drive = await PlacementDrive.get(interview.drive_id)
        company = await Company.get(drive.company_id) if drive else None
        
        interview_dict = interview.dict()
        interview_dict["drive"] = drive.dict() if drive else None
        interview_dict["company"] = company.dict() if company else None
        result.append(interview_dict)
    
    return {"interviews": result}


@router.post("/interviews", status_code=201)
async def schedule_interview(
    interview_data: dict,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.FACULTY))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Schedule interview round"""
    application = await StudentApplication.get(PydanticObjectId(interview_data["application_id"]))
    
    if not application or application.college_id != college.id:
        raise HTTPException(status_code=404, detail="Application not found")
    
    interview = InterviewRound(
        college_id=college.id,
        drive_id=application.drive_id,
        student_id=application.student_id,
        application_id=application.id,
        round_number=interview_data["round_number"],
        round_type=interview_data["round_type"],
        round_name=interview_data.get("round_name"),
        scheduled_at=datetime.fromisoformat(interview_data["scheduled_at"]),
        duration_minutes=interview_data.get("duration_minutes", 60),
        location=interview_data.get("location"),
        meeting_link=interview_data.get("meeting_link"),
        interviewer_names=interview_data.get("interviewer_names"),
        panel_size=interview_data.get("panel_size", 1),
        status="scheduled",
        created_by=user.id,
    )
    
    await interview.insert()
    
    # Update application status
    application.status = "interview_scheduled"
    await application.save()
    
    # Send notification to student
    student_doc = await Student.get(application.student_id)
    await manager.send_notification(
        notification_data={
            "id": str(interview.id),
            "title": "Interview Scheduled",
            "body": f"{interview.round_name or interview.round_type} on {interview.scheduled_at.strftime('%b %d, %Y at %I:%M %p')}",
            "type": "placement",
            "priority": "high",
            "action_url": "/student/applications",
        },
        target_scope="user",
        target_user_id=str(student_doc.user_id) if student_doc else str(application.student_id),
        college_id=str(college.id)
    )
    
    return interview


@router.patch("/interviews/{interview_id}")
async def update_interview(
    interview_id: str,
    update_data: dict,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.FACULTY))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Update interview round"""
    interview = await InterviewRound.get(PydanticObjectId(interview_id))
    
    if not interview or interview.college_id != college.id:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    for field in ["status", "result", "score", "feedback", "location", "meeting_link"]:
        if field in update_data:
            setattr(interview, field, update_data[field])
    
    if "scheduled_at" in update_data:
        interview.scheduled_at = datetime.fromisoformat(update_data["scheduled_at"])
    
    if update_data.get("status") == "completed":
        interview.completed_at = datetime.utcnow()
    
    interview.updated_at = datetime.utcnow()
    await interview.save()
    
    return interview


# ==================== PLACEMENT OFFER ENDPOINTS ====================

@router.get("/offers", status_code=200)
async def list_offers(
    user: Annotated[User, Depends(get_tenant_scoped_user)],
    college: Annotated[College, Depends(get_tenant_college)],
    drive_id: Optional[str] = None,
    student_id: Optional[str] = None,
    status: Optional[str] = None,
):
    """List placement offers"""
    query = {"college_id": college.id}
    
    if drive_id:
        query["drive_id"] = PydanticObjectId(drive_id)
    
    # Students can only see their own offers
    if user.role == UserRole.STUDENT:
        student = await Student.find_one({"user_id": user.id})
        if student:
            query["student_id"] = student.id
    elif student_id:
        query["student_id"] = PydanticObjectId(student_id)
    
    if status:
        query["status"] = status
    
    offers = await PlacementOffer.find(query).sort(-PlacementOffer.offer_date).to_list()
    
    # Populate details
    result = []
    for offer in offers:
        drive = await PlacementDrive.get(offer.drive_id)
        company = await Company.get(offer.company_id)
        
        offer_dict = offer.dict()
        offer_dict["drive"] = drive.dict() if drive else None
        offer_dict["company"] = company.dict() if company else None
        result.append(offer_dict)
    
    return {"offers": result}


@router.post("/offers", status_code=201)
async def create_offer(
    offer_data: dict,
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Create placement offer"""
    application = await StudentApplication.get(PydanticObjectId(offer_data["application_id"]))
    
    if not application or application.college_id != college.id:
        raise HTTPException(status_code=404, detail="Application not found")
    
    drive = await PlacementDrive.get(application.drive_id)
    
    offer = PlacementOffer(
        college_id=college.id,
        drive_id=drive.id,
        student_id=application.student_id,
        application_id=application.id,
        company_id=drive.company_id,
        student_name=application.student_name,
        student_roll_no=application.student_roll_no,
        student_department=application.student_department,
        student_email=application.student_email,
        role=drive.role,
        location=offer_data["location"],
        package_ctc=offer_data["package_ctc"],
        base_salary=offer_data.get("base_salary"),
        joining_bonus=offer_data.get("joining_bonus"),
        expected_joining_date=offer_data.get("expected_joining_date"),
        offer_letter_url=offer_data.get("offer_letter_url"),
        bond_duration_months=offer_data.get("bond_duration_months"),
        probation_period_months=offer_data.get("probation_period_months"),
        status="sent",
        created_by=user.id,
    )
    
    await offer.insert()
    
    # Update application status
    application.status = "offer_accepted"
    await application.save()
    
    # Send notification
    student_doc = await Student.get(application.student_id)
    await manager.send_notification(
        notification_data={
            "id": str(offer.id),
            "title": "🎉 Placement Offer Received!",
            "body": f"Offer from {(await Company.get(drive.company_id)).name} - {offer.package_ctc} LPA",
            "type": "placement",
            "priority": "urgent",
            "action_url": "/student/applications",
        },
        target_scope="user",
        target_user_id=str(student_doc.user_id) if student_doc else str(application.student_id),
        college_id=str(college.id)
    )
    
    return offer


@router.patch("/offers/{offer_id}/accept")
async def accept_offer(
    offer_id: str,
    user: Annotated[User, Depends(require_roles(UserRole.STUDENT))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Student accepts offer"""
    offer = await PlacementOffer.get(PydanticObjectId(offer_id))
    
    if not offer or offer.college_id != college.id:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    # Verify student owns this offer
    student = await Student.find_one({"user_id": user.id})
    if not student or offer.student_id != student.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    offer.status = "accepted"
    offer.accepted_at = datetime.utcnow()
    await offer.save()
    
    return {"ok": True, "message": "Offer accepted successfully"}


@router.patch("/offers/{offer_id}/reject")
async def reject_offer(
    offer_id: str,
    rejection_data: dict,
    user: Annotated[User, Depends(require_roles(UserRole.STUDENT))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Student rejects offer"""
    offer = await PlacementOffer.get(PydanticObjectId(offer_id))
    
    if not offer or offer.college_id != college.id:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    student = await Student.find_one({"user_id": user.id})
    if not student or offer.student_id != student.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    offer.status = "rejected"
    offer.rejected_at = datetime.utcnow()
    offer.rejection_reason = rejection_data.get("reason")
    await offer.save()
    
    return {"ok": True, "message": "Offer rejected"}


# ==================== ANALYTICS ENDPOINTS ====================

@router.get("/analytics/stats")
async def get_placement_stats(
    user: Annotated[User, Depends(get_current_user)],
    college: Annotated[Optional[College], Depends(resolve_tenant)] = None,
):
    """Get placement statistics for the college or all colleges (super admin)"""
    from app.models.college import College as CollegeModel
    
    if user.role == UserRole.SUPER_ADMIN.value:
        # Super admin — aggregate across all colleges
        colleges = await CollegeModel.find_all().to_list()
        total_companies = await Company.find({"is_active": True}).count()
        total_drives = await PlacementDrive.find({}).count()
        active_drives = await PlacementDrive.find({"status": "open"}).count()
        total_applications = await StudentApplication.find({}).count()
        placed_count = await StudentApplication.find({"status": "placed"}).count()
        
        # Highest package across all colleges
        all_apps = await StudentApplication.find({}).to_list()
        packages = [app.offered_package for app in all_apps if app.offered_package and app.offered_package > 0]
        highest_package = max(packages) if packages else 0
        avg_package = sum(packages) / len(packages) if packages else 0
        
        return {
            "total_companies": total_companies,
            "total_drives": total_drives,
            "active_drives": active_drives,
            "total_applications": total_applications,
            "placed_students": placed_count,
            "highest_package": highest_package,
            "average_package": round(avg_package, 2),
        }
    
    # College admin/faculty — specific college
    if not college:
        raise HTTPException(status_code=400, detail="College context required")
    
    # Total companies
    total_companies = await Company.find({"college_id": college.id, "is_active": True}).count()
    
    # Total drives
    total_drives = await PlacementDrive.find({"college_id": college.id}).count()
    active_drives = await PlacementDrive.find({"college_id": college.id, "status": "open"}).count()
    
    # Applications
    total_applications = await StudentApplication.find({"college_id": college.id}).count()
    
    # Offers
    offers = await PlacementOffer.find({"college_id": college.id, "status": "accepted"}).to_list()
    total_placed = len(offers)
    
    # Package statistics
    if offers:
        packages = [offer.package_ctc for offer in offers]
        highest_package = max(packages)
        average_package = sum(packages) / len(packages)
        lowest_package = min(packages)
    else:
        highest_package = 0
        average_package = 0
        lowest_package = 0
    
    # Students
    total_students = await Student.find({"college_id": college.id}).count()
    placement_percentage = (total_placed / total_students * 100) if total_students > 0 else 0
    
    return {
        "total_companies": total_companies,
        "total_drives": total_drives,
        "active_drives": active_drives,
        "total_applications": total_applications,
        "total_placed": total_placed,
        "highest_package": highest_package,
        "average_package": average_package,
        "lowest_package": lowest_package,
        "placement_percentage": placement_percentage,
        "total_students": total_students,
    }


@router.get("/analytics/export-csv")
async def export_placements_csv(
    user: Annotated[User, Depends(require_roles(UserRole.COLLEGE_ADMIN, UserRole.SUPER_ADMIN))],
    college: Annotated[College, Depends(get_tenant_college)],
):
    """Export placement data as CSV"""
    
    offers = await PlacementOffer.find({"college_id": college.id}).to_list()
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow([
        "Student Name", "Roll No", "Department", "Company", "Role", 
        "Package (LPA)", "Location", "Status", "Offer Date"
    ])
    
    # Data rows
    for offer in offers:
        company = await Company.get(offer.company_id)
        writer.writerow([
            offer.student_name,
            offer.student_roll_no,
            offer.student_department,
            company.name if company else "N/A",
            offer.role,
            offer.package_ctc,
            offer.location,
            offer.status,
            offer.offer_date.strftime("%Y-%m-%d") if offer.offer_date else "N/A"
        ])
    
    output.seek(0)
    
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=placements_{college.name}_{datetime.utcnow().strftime('%Y%m%d')}.csv"}
    )
