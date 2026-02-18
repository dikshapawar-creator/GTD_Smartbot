import logging
from sqlalchemy.orm import Session
from uuid import UUID, uuid4
from typing import Dict, Any, Optional
from app.schemas.chatbot import ChatState
from app.models.lead import Lead
from app.models.conversation import Conversation

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

# In-memory session storage (consider Redis for production persistent state)
session_storage: Dict[UUID, Dict[str, Any]] = {}

class ChatbotService:
    @staticmethod
    def start_chat(db: Session) -> Dict[str, Any]:
        session_id = uuid4()
        logger.info(f"Starting new chat session: {session_id}")
        
        lead = Lead(id=session_id, status="IN_PROGRESS")
        db.add(lead)
        db.commit()
        db.refresh(lead)

        session_storage[session_id] = {
            "state": ChatState.TRADE_TYPE,
            "lead_id": session_id
        }

        message = STATE_QUESTIONS[ChatState.START]
        ChatbotService.save_message(db, session_id, message, "bot")

        return {
            "sessionId": session_id,
            "message": message,
            "state": ChatState.START
        }

    @staticmethod
    def handle_message(db: Session, session_id: UUID, user_message: str) -> Dict[str, Any]:
        if session_id not in session_storage:
            logger.warning(f"Invalid session ID attempt: {session_id}")
            return {"error": "Invalid session ID"}

        current_session = session_storage[session_id]
        current_state = current_session["state"]
        lead_id = current_session["lead_id"]

        ChatbotService.save_message(db, lead_id, user_message, "user")

        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
             logger.error(f"Lead not found for session_id: {session_id}")
             return {"error": "Lead not found"}
        
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

        db.commit()
        session_storage[session_id]["state"] = next_state
        
        bot_response = STATE_QUESTIONS[next_state]
        ChatbotService.save_message(db, lead_id, bot_response, "bot")

        return {
            "sessionId": session_id,
            "message": bot_response,
            "state": next_state
        }

    @staticmethod
    def save_message(db: Session, lead_id: UUID, message: str, sender: str):
        conversation = Conversation(
            lead_id=lead_id,
            message=message,
            sender=sender
        )
        db.add(conversation)
        db.commit()
