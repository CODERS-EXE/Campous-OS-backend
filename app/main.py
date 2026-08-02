from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from slowapi import Limiter, _rate_limit_exceeded_handler
# pyrefly: ignore [missing-import]
from slowapi.errors import RateLimitExceeded
# pyrefly: ignore [missing-import]
from slowapi.util import get_remote_address
from jose import JWTError, jwt

from app.core.config import get_settings
from app.core.websocket_manager import manager
from app.db.mongo import close_db, init_db
from app.routers import ai, assignments, attendance, auth, bus, colleges, exams, fees, hostel, library, notifications, placements, results, timetable, users, search
from app.models.user import User

logger = logging.getLogger(__name__)

settings = get_settings()
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

from bson.errors import InvalidId
from fastapi.responses import JSONResponse

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.exception_handler(InvalidId)
async def invalid_id_exception_handler(request, exc):
    return JSONResponse(status_code=400, content={"detail": "Invalid ID format"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(colleges.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(attendance.router, prefix="/api/v1")
app.include_router(assignments.router, prefix="/api/v1")
app.include_router(results.router, prefix="/api/v1")
app.include_router(timetable.router, prefix="/api/v1")
app.include_router(hostel.router, prefix="/api/v1")
app.include_router(ai.router, prefix="/api/v1")
app.include_router(bus.router, prefix="/api/v1")
app.include_router(fees.router, prefix="/api/v1")
app.include_router(library.router, prefix="/api/v1")
app.include_router(placements.router, prefix="/api/v1")
app.include_router(exams.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/")
async def root():
    return {"message": "CampusOS API", "docs": "/docs"}


@app.post("/api/v1/setup/seed")
async def seed_database():
    """One-time setup endpoint to seed database with super admin and demo data"""
    from app.models.user import User
    from app.models.college import College
    from app.models.student import Student
    from app.models.faculty import Faculty
    from app.models.notification import Notification, NotificationTarget
    from app.core.security import hash_password
    from app.core.constants import UserRole
    
    # Check if super admin exists
    super_admin = await User.find_one(User.email == "admin@campusos.com")
    if super_admin:
        return {"message": "Database already seeded", "status": "skipped"}
    
    # Create super admin
    super_admin = User(
        role=UserRole.SUPER_ADMIN.value,
        name="Platform Admin",
        email="admin@campusos.com",
        password_hash=hash_password("admin123"),
        is_verified=True,
    )
    await super_admin.insert()
    
    # Create demo college
    college = College(name="Demo University", subdomain="demo", theme_color="#2563eb")
    await college.insert()
    
    # College admin
    college_admin = User(
        college_id=college.id,
        role=UserRole.COLLEGE_ADMIN.value,
        name="Demo Admin",
        email="admin@demo.edu",
        password_hash=hash_password("Demo@123"),
        is_verified=True,
    )
    await college_admin.insert()
    
    # Student
    student_user = User(
        college_id=college.id,
        role=UserRole.STUDENT.value,
        name="Alice Student",
        email="alice@demo.edu",
        password_hash=hash_password("Demo@123"),
        is_verified=True,
    )
    await student_user.insert()
    student = Student(
        college_id=college.id,
        user_id=student_user.id,
        roll_no="CS2024001",
        department="Computer Science",
        year=2,
        semester=3,
    )
    await student.insert()
    
    # Faculty
    faculty_user = User(
        college_id=college.id,
        role=UserRole.FACULTY.value,
        name="Dr. Bob Faculty",
        email="bob@demo.edu",
        password_hash=hash_password("Demo@123"),
        is_verified=True,
    )
    await faculty_user.insert()
    faculty = Faculty(
        college_id=college.id,
        user_id=faculty_user.id,
        department="Computer Science",
        subjects=["Data Structures", "Algorithms"],
    )
    await faculty.insert()
    
    # Welcome notification
    notification = Notification(
        college_id=college.id,
        target=NotificationTarget(scope="all"),
        title="Welcome to CampusOS!",
        body="Your smart campus platform is ready. Explore your dashboard to get started.",
        priority="normal",
        created_by=college_admin.id,
    )
    await notification.insert()
    
    return {
        "message": "Database seeded successfully",
        "accounts": {
            "super_admin": "admin@campusos.com / admin123",
            "college_admin": "admin@demo.edu / Demo@123",
            "student": "alice@demo.edu / Demo@123",
            "faculty": "bob@demo.edu / Demo@123"
        }
    }


# pyrefly: ignore [missing-import]
from beanie import PydanticObjectId

async def get_user_from_token(token: str) -> User:
    """Validate JWT token and return user"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if not user_id or not PydanticObjectId.is_valid(user_id):
            return None
        user = await User.get(PydanticObjectId(user_id))
        return user
    except Exception as exc:
        logger.warning(f"Failed to authenticate WebSocket token: {exc}")
        return None


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    token: str = Query(...)
):
    """
    WebSocket endpoint for real-time notifications
    Requires JWT token in query parameter: /ws/{user_id}?token=<jwt_token>
    """
    # Authenticate user with JWT token
    user = await get_user_from_token(token)
    
    if not user or str(user.id) != user_id:
        await websocket.accept()
        await websocket.close(code=1008, reason="Unauthorized")
        logger.warning(f"WebSocket authentication failed for user_id={user_id}")
        return

    
    # Get user details for connection
    role = user.role
    college_id = str(user.college_id) if user.college_id else None
    tenant_id = user.tenant_id if hasattr(user, 'tenant_id') else None
    
    # Connect to WebSocket manager
    await manager.connect(
        websocket=websocket,
        user_id=user_id,
        role=role,
        college_id=college_id,
        tenant_id=tenant_id
    )
    
    try:
        # Keep connection alive and handle incoming messages
        while True:
            data = await websocket.receive_text()
            
            # Handle heartbeat/ping messages
            if data == "ping":
                await websocket.send_text("pong")
            
            # Handle other client messages (can be extended)
            elif data.startswith("{"):
                try:
                    import json
                    message = json.loads(data)
                    
                    # Handle read receipts
                    if message.get("type") == "read_receipt":
                        notification_id = message.get("notification_id")
                        logger.info(f"Read receipt from {user_id} for notification {notification_id}")
                    
                    # Echo back acknowledgment
                    await manager.send_personal_message(
                        json.dumps({"type": "ack", "received": True}),
                        user_id
                    )
                except json.JSONDecodeError:
                    pass
                    
    except WebSocketDisconnect:
        manager.disconnect(user_id)
        logger.info(f"WebSocket disconnected normally: user={user_id}")
    except Exception as e:
        manager.disconnect(user_id)
        logger.error(f"WebSocket error for user={user_id}: {e}")


@app.get("/api/v1/ws/stats")
async def websocket_stats():
    """Get WebSocket connection statistics (for monitoring)"""
    return manager.get_connection_stats()
