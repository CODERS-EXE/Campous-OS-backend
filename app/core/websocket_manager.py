"""
WebSocket Connection Manager for Real-time Notifications
Handles WebSocket connections, broadcasts, and role-based filtering
"""
from typing import Dict, List, Set
from fastapi import WebSocket
from beanie import PydanticObjectId
import json
import logging

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections for real-time notifications
    Supports role-based and college-specific broadcasting
    """

    def __init__(self):
        # Structure: {user_id: {websocket: WebSocket, role: str, college_id: str, tenant_id: str}}
        self.active_connections: Dict[str, Dict] = {}
        # Index for fast lookup by college_id
        self.college_connections: Dict[str, Set[str]] = {}
        # Index for fast lookup by role
        self.role_connections: Dict[str, Set[str]] = {}

    async def connect(
        self, 
        websocket: WebSocket, 
        user_id: str, 
        role: str, 
        college_id: str = None,
        tenant_id: str = None
    ):
        """Connect a new WebSocket client"""
        await websocket.accept()
        
        # Store connection info
        self.active_connections[user_id] = {
            "websocket": websocket,
            "role": role,
            "college_id": college_id,
            "tenant_id": tenant_id
        }
        
        # Index by college
        if college_id:
            if college_id not in self.college_connections:
                self.college_connections[college_id] = set()
            self.college_connections[college_id].add(user_id)
        
        # Index by role
        if role not in self.role_connections:
            self.role_connections[role] = set()
        self.role_connections[role].add(user_id)
        
        logger.info(f"WebSocket connected: user={user_id}, role={role}, college={college_id}")
        
        # Send connection success message
        await self.send_personal_message(
            json.dumps({
                "type": "connection",
                "status": "connected",
                "message": "Real-time notifications active"
            }),
            user_id
        )

    def disconnect(self, user_id: str):
        """Disconnect a WebSocket client"""
        if user_id in self.active_connections:
            conn_info = self.active_connections[user_id]
            
            # Remove from college index
            college_id = conn_info.get("college_id")
            if college_id and college_id in self.college_connections:
                self.college_connections[college_id].discard(user_id)
                if not self.college_connections[college_id]:
                    del self.college_connections[college_id]
            
            # Remove from role index
            role = conn_info.get("role")
            if role and role in self.role_connections:
                self.role_connections[role].discard(user_id)
                if not self.role_connections[role]:
                    del self.role_connections[role]
            
            # Remove connection
            del self.active_connections[user_id]
            logger.info(f"WebSocket disconnected: user={user_id}")

    async def send_personal_message(self, message: str, user_id: str):
        """Send a message to a specific user"""
        if user_id in self.active_connections:
            try:
                websocket = self.active_connections[user_id]["websocket"]
                await websocket.send_text(message)
            except Exception as e:
                logger.error(f"Error sending message to {user_id}: {e}")
                self.disconnect(user_id)

    async def broadcast_to_all(self, message: str):
        """Broadcast message to all connected users"""
        disconnected = []
        for user_id, conn_info in self.active_connections.items():
            try:
                await conn_info["websocket"].send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to {user_id}: {e}")
                disconnected.append(user_id)
        
        # Clean up disconnected users
        for user_id in disconnected:
            self.disconnect(user_id)

    async def broadcast_to_college(self, message: str, college_id: str):
        """Broadcast message to all users in a specific college"""
        if college_id not in self.college_connections:
            return
        
        user_ids = list(self.college_connections[college_id])
        disconnected = []
        
        for user_id in user_ids:
            if user_id in self.active_connections:
                try:
                    websocket = self.active_connections[user_id]["websocket"]
                    await websocket.send_text(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to college user {user_id}: {e}")
                    disconnected.append(user_id)
        
        # Clean up disconnected users
        for user_id in disconnected:
            self.disconnect(user_id)

    async def broadcast_to_role(self, message: str, role: str, college_id: str = None):
        """Broadcast message to all users with a specific role, optionally filtered by college"""
        if role not in self.role_connections:
            return
        
        user_ids = list(self.role_connections[role])
        disconnected = []
        
        for user_id in user_ids:
            if user_id in self.active_connections:
                conn_info = self.active_connections[user_id]
                
                # Filter by college if specified
                if college_id and conn_info.get("college_id") != college_id:
                    continue
                
                try:
                    await conn_info["websocket"].send_text(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to role user {user_id}: {e}")
                    disconnected.append(user_id)
        
        # Clean up disconnected users
        for user_id in disconnected:
            self.disconnect(user_id)

    async def broadcast_to_roles(self, message: str, roles: List[str], college_id: str = None):
        """Broadcast message to multiple roles"""
        for role in roles:
            await self.broadcast_to_role(message, role, college_id)

    async def send_notification(
        self,
        notification_data: dict,
        target_scope: str = "all",
        target_role: str = None,
        target_user_id: str = None,
        college_id: str = None
    ):
        """
        Send notification based on target scope
        Scope: all, role, user, college
        """
        message = json.dumps({
            "type": "notification",
            "data": notification_data
        })
        
        if target_scope == "user" and target_user_id:
            # Send to specific user
            await self.send_personal_message(message, target_user_id)
        
        elif target_scope == "role" and target_role:
            # Send to all users with specific role
            await self.broadcast_to_role(message, target_role, college_id)
        
        elif target_scope == "college" and college_id:
            # Send to all users in college
            await self.broadcast_to_college(message, college_id)
        
        elif target_scope == "all":
            # Send to everyone (super admin broadcasts)
            if college_id:
                await self.broadcast_to_college(message, college_id)
            else:
                await self.broadcast_to_all(message)

    def get_connection_stats(self) -> dict:
        """Get current connection statistics"""
        return {
            "total_connections": len(self.active_connections),
            "colleges": len(self.college_connections),
            "roles": {role: len(users) for role, users in self.role_connections.items()},
            "connected_users": list(self.active_connections.keys())
        }

    def is_user_connected(self, user_id: str) -> bool:
        """Check if a user is currently connected"""
        return user_id in self.active_connections


# Global connection manager instance
manager = ConnectionManager()
