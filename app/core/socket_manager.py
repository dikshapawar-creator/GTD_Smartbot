import logging
from typing import Dict, List, Set, Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class WebSocketManager:
    """
    Centralized manager for real-time CRM updates.
    Handles broadcasting session state changes to tenant-specific agent dashboards.
    """
    def __init__(self):
        # tenant_connections[tenant_id] = Set[WebSocket]
        self.tenant_connections: Dict[int, Set[WebSocket]] = {}
        # user_connections[user_id] = Set[WebSocket] (for direct messages)
        self.user_connections: Dict[int, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int, tenant_id: int):
        # Register for tenant-wide broadcasts
        if tenant_id not in self.tenant_connections:
            self.tenant_connections[tenant_id] = set()
        self.tenant_connections[tenant_id].add(websocket)

        # Register for user-specific messages
        if user_id not in self.user_connections:
            self.user_connections[user_id] = set()
        self.user_connections[user_id].add(websocket)
        
        logger.debug(f"WS connected: user={user_id}, tenant={tenant_id}")

    def disconnect(self, websocket: WebSocket, user_id: int, tenant_id: int):
        if tenant_id in self.tenant_connections:
            self.tenant_connections[tenant_id].discard(websocket)
            if not self.tenant_connections[tenant_id]:
                self.tenant_connections.pop(tenant_id, None)
        
        if user_id in self.user_connections:
            self.user_connections[user_id].discard(websocket)
            if not self.user_connections[user_id]:
                self.user_connections.pop(user_id, None)
        
        logger.debug(f"WS disconnected: user={user_id}, tenant={tenant_id}")

    async def broadcast_event(self, event_type: str, data: Any, tenant_id: int = None):
        """Broadcasts an event to connected dashboard clients, optionally scoped by tenant."""
        target_pool = set()
        
        if tenant_id:
            target_pool = self.tenant_connections.get(tenant_id, set())
        else:
            # Fallback: broadcast to ALL (use with caution, mostly for system updates)
            for pool in self.tenant_connections.values():
                target_pool.update(pool)

        if not target_pool:
            return

        payload = {"type": event_type, **(data if isinstance(data, dict) else {"data": data})}
        
        dead_connections = set()
        for connection in list(target_pool):
            try:
                await connection.send_json(payload)
            except Exception as e:
                logger.error(f"Failed to broadcast: {e}")
                dead_connections.add(connection)
        
        # Cleanup
        if tenant_id and tenant_id in self.tenant_connections:
            for dead in dead_connections:
                self.tenant_connections[tenant_id].discard(dead)

# Global Instance
socket_manager = WebSocketManager()
