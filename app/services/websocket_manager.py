"""
WebSocket Connection Manager — In-memory bi-directional relay.
Maps session_id → (client_socket, agent_socket) for real-time chat.
"""
import logging
from typing import Dict, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Thread-safe in-memory WebSocket connection tracker."""

    def __init__(self):
        # session_id → WebSocket
        self._clients: Dict[str, WebSocket] = {}
        self._agents: Dict[str, WebSocket] = {}

    # ── Connect ──────────────────────────────────────────────────────────

    async def connect_client(self, session_id: str, ws: WebSocket):
        await ws.accept()
        self._clients[session_id] = ws
        logger.info({"event": "ws_client_connected", "session_id": session_id})

    async def connect_agent(self, session_id: str, ws: WebSocket):
        await ws.accept()
        self._agents[session_id] = ws
        logger.info({"event": "ws_agent_connected", "session_id": session_id})

    # ── Disconnect ───────────────────────────────────────────────────────

    def disconnect_client(self, session_id: str):
        self._clients.pop(session_id, None)
        logger.info({"event": "ws_client_disconnected", "session_id": session_id})

    def disconnect_agent(self, session_id: str):
        self._agents.pop(session_id, None)
        logger.info({"event": "ws_agent_disconnected", "session_id": session_id})

    # ── Send ─────────────────────────────────────────────────────────────

    async def send_to_client(self, session_id: str, data: dict):
        ws = self._clients.get(session_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect_client(session_id)

    async def send_to_agent(self, session_id: str, data: dict):
        ws = self._agents.get(session_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect_agent(session_id)

    # ── Utilities ────────────────────────────────────────────────────────

    def has_client(self, session_id: str) -> bool:
        return session_id in self._clients

    def has_agent(self, session_id: str) -> bool:
        return session_id in self._agents


# Singleton instance — imported by ws_chat and live_chat
manager = ConnectionManager()
