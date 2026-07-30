from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings
from app.models.ai import AiChatMessage
from app.models.assignment import Assignment
from app.models.attendance import Attendance
from app.models.bus import Bus, BusLocation, BusRoute, StudentBusAssignment
from app.models.college import College
from app.models.company import Company
from app.models.exam import Exam
from app.models.exam_result import ExamResult
from app.models.fees import FeeStructure, Invoice, Payment, Receipt, StudentFee
from app.models.grade_scale import GradeScale
from app.models.library import Book, BookCategory, BookIssue
from app.models.faculty import Faculty
from app.models.hostel import HostelBuilding, HostelRequest, Outpass, Room, RoomAllocation
from app.models.interview_round import InterviewRound
from app.models.notification import Notification
from app.models.placement_drive import PlacementDrive
from app.models.placement_offer import PlacementOffer
from app.models.question_paper import QuestionPaper
from app.models.result import Result
from app.models.student import Student
from app.models.student_application import StudentApplication
from app.models.student_exam import StudentExam
from app.models.subject_exam import SubjectExam
from app.models.submission import Submission
from app.models.timetable import TimetableEntry
from app.models.user import User

settings = get_settings()
client: AsyncIOMotorClient | None = None


async def init_db() -> None:
    global client
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    await init_beanie(
        database=client[settings.MONGODB_DB_NAME],
        document_models=[
            College,
            User,
            Student,
            Faculty,
            Notification,
            Attendance,
            Assignment,
            Submission,
            Result,
            TimetableEntry,
            HostelBuilding,
            Room,
            RoomAllocation,
            HostelRequest,
            Outpass,
            AiChatMessage,
            Bus,
            BusRoute,
            BusLocation,
            StudentBusAssignment,
            FeeStructure,
            StudentFee,
            Payment,
            Invoice,
            Receipt,
            BookCategory,
            Book,
            BookIssue,
            Company,
            PlacementDrive,
            StudentApplication,
            InterviewRound,
            PlacementOffer,
            Exam,
            SubjectExam,
            QuestionPaper,
            StudentExam,
            ExamResult,
            GradeScale,
        ],
    )


async def close_db() -> None:
    global client
    if client:
        client.close()
        client = None
