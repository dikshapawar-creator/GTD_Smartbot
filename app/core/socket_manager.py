import logging
from typing import Dict, List, Set, Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class WebSocketManager:
    """
    Centralized manager for real-time CRM updates.
    Handles broadcasting session state changes to all connected agent dashboards.
    """
    def __init__(self):
        # active_connections[user_id] = Set[WebSocket]
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        # broadcast_rooms: global subscription for CRM dashboard
        self.broadcast_pool: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        self.broadcast_pool.add(websocket)
        logger.debug(f"WebSocket connected for user {user_id}. Pool size: {len(self.broadcast_pool)}")

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        if websocket in self.broadcast_pool:
            self.broadcast_pool.remove(websocket)
        logger.debug(f"WebSocket disconnected for user {user_id}. Pool size: {len(self.broadcast_pool)}")

    async def broadcast_event(self, event_type: str, data: Any):
        """Broadcasts an event to all connected dashboard clients."""
        if not self.broadcast_pool:
            return

        payload = {
            "type": event_type,
            "data": data
        }
        
        # Create a copy of the pool to iterate over to avoid modification errors
        dead_connections = set()
        for connection in self.broadcast_pool:
            try:
                await connection.send_json(payload)
            except Exception as e:
                logger.error(f"Failed to broadcast to connection: {e}")
                dead_connections.add(connection)
        
        # Cleanup stale connections
        for dead in dead_connections:
            self.broadcast_pool.remove(dead)

# Global Instance
socket_manager = WebSocketManager()
