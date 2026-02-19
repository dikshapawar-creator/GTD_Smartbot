"""
ChatbotService — Refactored to use SQL-based sessions.
Removes in-memory dict and delegates storage to SessionService.
"""
import logging
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Dict, Any, Optional

from app.schemas.chatbot import ChatState
from app.models.lead import Lead
from app.models.chat_session import ChatSession
from app.services import session_service

logger = logging.getLogger(__name__)

STATE_QUESTIONS = {
    ChatState.START: "Welcome! Are you interested in Import or Export?",
    ChatState.TRADE_TYPE: "Which country are you interested in?",
    ChatState.COUNTRY: "What product are you dealing with?",
    ChatState.PRODUCT: "Great! May I have your full name?",
    ChatState.NAME: "What is your email address?",
    ChatState.EMAIL: "Which company do you represent?",
    ChatState.COMPANY: "What is your contact phone number?",
    ChatState.PHONE: "Finally, what are your specific requirements?",
    ChatState.REQUIREMENT: "Thank you! Our team will contact you soon.",
    ChatState.COMPLETE: "Is there anything else I can help you with?"
}

class ChatbotService:
    @staticmethod
    def handle_message(db: Session, chat_session: ChatSession, user_message: str) -> Dict[str, Any]:
        """
        Handles a message using the provided DB session object.
        Replaces lead logic while keeping backward compatibility with the 'leads' table.
        """
        current_state = chat_session.chat_state
        session_id = chat_session.session_id

        # 1. Save user message to persistent SQL messages table
        session_service.save_message(db, chat_session, user_message, "user")

        # 2. Backward compatibility: Find or create lead tied to this session
        lead = db.query(Lead).filter(Lead.id == chat_session.session_id).first()
        if not lead:
             # If no lead exists for this session yet, create one
             lead = Lead(id=chat_session.session_id, status="IN_PROGRESS")
             db.add(lead)
             # Note: No need for separate Conversation save here as we use ChatMessage table now

        # 3. Process State Machine
        next_state = current_state
        if current_state == ChatState.TRADE_TYPE:
            lead.trade_type = user_message
            next_state = ChatState.COUNTRY
        elif current_state == ChatState.COUNTRY:
            lead.country_interested = user_message
            next_state = ChatState.PRODUCT
        elif current_state == ChatState.PRODUCT:
            lead.product = user_message
            next_state = ChatState.NAME
        elif current_state == ChatState.NAME:
            lead.name = user_message
            next_state = ChatState.EMAIL
        elif current_state == ChatState.EMAIL:
            lead.email = user_message
            next_state = ChatState.COMPANY
        elif current_state == ChatState.COMPANY:
            lead.company = user_message
            next_state = ChatState.PHONE
        elif current_state == ChatState.PHONE:
            lead.phone = user_message
            next_state = ChatState.REQUIREMENT
        elif current_state == ChatState.REQUIREMENT:
            lead.requirement_type = user_message
            lead.status = "COMPLETE"
            next_state = ChatState.COMPLETE

        # 4. Update state in DB session row
        session_service.update_chat_state(db, chat_session, next_state)
        
        # 5. Get bot response and save it
        bot_response = STATE_QUESTIONS[next_state]
        session_service.save_message(db, chat_session, bot_response, "bot")

        return {
            "message": bot_response,
            "state": next_state
        }
