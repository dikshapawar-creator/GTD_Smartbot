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
        # Don't convert UUIDs to lowercase - maintain original case
        self._clients[session_id] = ws
        logger.info(f"✅ [WS_CLIENT] Client connected for session {session_id}")
        logger.info(f"📊 [WS_CLIENT] Total connected clients: {len(self._clients)}")
        logger.info(f"📊 [WS_CLIENT] All client sessions: {list(self._clients.keys())}")

    async def connect_agent(self, session_id: str, ws: WebSocket):
        # Don't convert UUIDs to lowercase - maintain original case
        self._agents[session_id] = ws
        logger.info(f"✅ [WS_AGENT] Agent connected for session {session_id}")
        logger.info(f"📊 [WS_AGENT] Total connected agents: {len(self._agents)}")
        logger.info(f"📊 [WS_AGENT] All agent sessions: {list(self._agents.keys())}")

    # ── Disconnect ───────────────────────────────────────────────────────

    def disconnect_client(self, session_id: str):
        # Don't convert UUIDs to lowercase - maintain original case
        if session_id in self._clients:
            self._clients.pop(session_id, None)
            logger.info(f"❌ [WS_CLIENT] Client disconnected for session {session_id}")
            logger.info(f"📊 [WS_CLIENT] Remaining clients: {list(self._clients.keys())}")
        else:
            logger.warning(f"⚠️ [WS_CLIENT] Attempted to disconnect non-existent client: {session_id}")

    def disconnect_agent(self, session_id: str):
        # Don't convert UUIDs to lowercase - maintain original case
        if session_id in self._agents:
            self._agents.pop(session_id, None)
            logger.info(f"❌ [WS_AGENT] Agent disconnected for session {session_id}")
            logger.info(f"📊 [WS_AGENT] Remaining agents: {list(self._agents.keys())}")
        else:
            logger.warning(f"⚠️ [WS_AGENT] Attempted to disconnect non-existent agent: {session_id}")

    # ── Send ─────────────────────────────────────────────────────────────

    async def send_to_client(self, session_id: str, data: dict):
        # Try exact match first, then case-insensitive variations
        session_variations = [
            session_id,                    # Original case
            session_id.lower(),           # Lowercase
            session_id.upper(),           # Uppercase
        ]
        
        ws = None
        matched_id = None
        
        for variation in session_variations:
            if variation in self._clients:
                ws = self._clients[variation]
                matched_id = variation
                break
        
        if ws:
            try:
                await ws.send_json(data)
                logger.info(f"✅ [WS] Message sent to client {matched_id} (original: {session_id})")
            except Exception as e:
                logger.error(f"❌ [WS] Failed to send to client {matched_id}: {e}")
                self.disconnect_client(matched_id)
        else:
            logger.warning(f"⚠️ [WS] No active socket for client {session_id}. Available: {list(self._clients.keys())}")

    async def send_to_agent(self, session_id: str, data: dict):
        # Try exact match first, then case-insensitive variations
        session_variations = [
            session_id,                    # Original case
            session_id.lower(),           # Lowercase
            session_id.upper(),           # Uppercase
        ]
        
        ws = None
        matched_id = None
        
        for variation in session_variations:
            if variation in self._agents:
                ws = self._agents[variation]
                matched_id = variation
                break
        
        if ws:
            try:
                await ws.send_json(data)
                logger.info(f"✅ [WS] Message sent to agent {matched_id} (original: {session_id})")
            except Exception as e:
                logger.error(f"❌ [WS] Failed to send to agent {matched_id}: {e}")
                self.disconnect_agent(matched_id)
        else:
            logger.warning(f"⚠️ [WS] No active socket for agent {session_id}. Available: {list(self._agents.keys())}")

    # ── Utilities ────────────────────────────────────────────────────────

    def has_client(self, session_id: str) -> bool:
        # Check all case variations
        return (session_id in self._clients or 
                session_id.lower() in self._clients or 
                session_id.upper() in self._clients)

    def has_agent(self, session_id: str) -> bool:
        # Check all case variations
        return (session_id in self._agents or 
                session_id.lower() in self._agents or 
                session_id.upper() in self._agents)


# Singleton instance — imported by ws_chat and live_chat
manager = ConnectionManager()
