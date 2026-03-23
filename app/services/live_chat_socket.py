import json
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from app.services.session_service import SessionService
from app.services.websocket_manager import manager
from app.core.timezone_utils import format_ist_datetime, format_ist_time


class LiveChatSocketManager:
    def __init__(self):
        self.agent_rooms: Dict[str, List[str]] = {}  # workspace_id -> [session_ids]
        
    async def notify_new_session(self, session, workspace_id: str):
        """Notify agents of new visitor session via existing WebSocket manager."""
        # Get IP metadata safely
        ip_meta = session.ip_metadata_dict
        
        session_data = {
            "type": "VISITOR_JOINED",
            "session_id": session.session_id,
            "visitor_uuid": session.visitor_uuid,
            "session_status": session.session_status,
            "current_mode": session.current_mode,
            "agent_name": session.agent_name,
            "is_locked": session.is_locked,
            "lead_name": session.lead_name or f"Visitor #{str(session.visitor_uuid)[-6:].upper()}",
            "lead_company": session.lead_company,
            "lead_email": session.lead_email,
            "lead_phone": session.lead_phone,
            "lead_score": session.lead_score or 0,
            "lead_status": self._get_lead_status(session.lead_score or 0),
            "spam_flag": session.spam_flag or False,
            "last_message_at": session.last_activity_at.isoformat() if session.last_activity_at else None,
            "message_count": session.message_count or 0,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "repeat_visitor": False,
            "previous_session_count": 0,
            "initial_ip": ip_meta.get("ip") or session.initial_ip,
            "country": session.country,
            "city": session.city,
            "browser": ip_meta.get("browser") or session.browser or "Unknown",
            "os": ip_meta.get("os") or session.os or "Unknown",
            "device_type": ip_meta.get("device_type") or session.device_type or "desktop",
            "created_at_ist": format_ist_datetime(session.created_at),
            "last_message_ist": format_ist_datetime(session.last_activity_at),
            "lead_insights": getattr(session, 'lead_insights', None),
        }
        
        # Broadcast to all connected agents using existing WebSocket manager
        await self._broadcast_to_dashboard(session_data)

    async def notify_session_updated(self, session, workspace_id: str):
        """Notify agents of session updates."""
        # Get IP metadata safely
        ip_meta = session.ip_metadata_dict
        
        session_data = {
            "type": "SESSION_UPDATED",
            "session_id": session.session_id,
            "visitor_uuid": session.visitor_uuid,
            "session_status": session.session_status,
            "current_mode": session.current_mode,
            "agent_name": session.agent_name,
            "is_locked": session.is_locked,
            "lead_name": session.lead_name or f"Visitor #{str(session.visitor_uuid)[-6:].upper()}",
            "lead_company": session.lead_company,
            "lead_email": session.lead_email,
            "lead_phone": session.lead_phone,
            "lead_score": session.lead_score or 0,
            "lead_status": self._get_lead_status(session.lead_score or 0),
            "spam_flag": session.spam_flag or False,
            "last_message_at": session.last_activity_at.isoformat() if session.last_activity_at else None,
            "message_count": session.message_count or 0,
            "created_at_ist": format_ist_datetime(session.created_at),
            "last_message_ist": format_ist_datetime(session.last_activity_at),
            "lead_insights": getattr(session, 'lead_insights', None),
        }
        
        await self._broadcast_to_dashboard(session_data)

    async def notify_lead_form_submitted(self, session, lead_data: dict, workspace_id: str):
        """Notify agents when visitor submits lead form."""
        await self._broadcast_to_dashboard({
            'type': 'LEAD_FORM_SUBMITTED',
            'session_id': session.session_id,
            'visitor_uuid': session.visitor_uuid,
            'lead_data': {
                'fullName': lead_data.get('name') or lead_data.get('fullName', ''),
                'interest': lead_data.get('interest', ''),
                'email': lead_data.get('email'),
                'phone': lead_data.get('phone'),
                'company': lead_data.get('company'),
                'submittedAt': format_ist_time(datetime.utcnow())
            }
        })

    async def notify_message(self, message, session, workspace_id: str):
        """Notify agents of new message."""
        message_data = {
            'type': 'NEW_MESSAGE',
            'id': message.id,
            'session_id': session.visitor_uuid,
            'message_type': message.message_type,
            'message_text': message.message_text,
            'created_at_utc': message.created_at.isoformat() if message.created_at else None,
            'created_at_ist': format_ist_datetime(message.created_at),
        }
        
        await self._broadcast_to_dashboard(message_data)

    async def notify_typing(self, visitor_uuid: str, is_typing: bool, workspace_id: str):
        """Notify agents of typing status."""
        await self._broadcast_to_dashboard({
            'type': 'TYPING_STATUS',
            'session_id': visitor_uuid,
            'is_typing': is_typing
        })

    async def _broadcast_to_dashboard(self, data: dict):
        """Broadcast data to dashboard using existing WebSocket infrastructure."""
        # For now, we'll use the existing socket_manager broadcast
        # This integrates with your existing WebSocket system
        try:
            from app.core.socket_manager import socket_manager
            await socket_manager.broadcast_event(data.get("type", "UPDATE"), data)
        except Exception as e:
            print(f"Dashboard broadcast failed: {e}")
            # Continue without WebSocket - REST API still works

    def _get_lead_status(self, score: int) -> str:
        """Convert numeric score to status string."""
        if score >= 70:
            return "HOT"
        elif score >= 40:
            return "WARM"
        else:
            return "COLD"


# Global instance
live_chat_socket = None

def get_live_chat_socket() -> LiveChatSocketManager:
    global live_chat_socket
    return live_chat_socket

def init_live_chat_socket():
    global live_chat_socket
    live_chat_socket = LiveChatSocketManager()