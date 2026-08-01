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
