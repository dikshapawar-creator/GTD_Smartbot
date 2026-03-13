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
    ChatState.COMPLETE: "Is there anything else I can help you with?",
    ChatState.ENDED: "Thank you for reaching out to us. Have a great day!"
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
        lead = None
        if chat_session.lead_id:
             lead = db.query(Lead).filter(Lead.id == chat_session.lead_id).first()
             
        if not lead:
             # If no lead exists for this session yet, create one
             # 🚨 SECURITY: Provide default values for required B2B fields to avoid SQL IntegrityError
             placeholder_email = f"pending_{chat_session.session_id}@gtdservice.local"
             lead = Lead(
                 name="Visitor",
                 email=placeholder_email, # email is required in model
                 phone="Pending",
                 company="Pending",
                 status="IN_PROGRESS",
                 source="chatbot",
                 tenant_id=chat_session.tenant_id
             )
             db.add(lead)
             db.flush() # Get the ID
             chat_session.lead_id = str(lead.id)
             db.commit()

        # 3. Process State Machine
        next_state = current_state
        bot_response = ""
        
        if current_state == ChatState.TRADE_TYPE:
            lead.trade_type = user_message
            next_state = ChatState.COUNTRY
            bot_response = STATE_QUESTIONS[ChatState.TRADE_TYPE] # "Which country..."
            
        elif current_state == ChatState.COUNTRY:
            lead.country_interested = user_message
            next_state = ChatState.PRODUCT
            bot_response = STATE_QUESTIONS[ChatState.COUNTRY] # "What product..."
            
        elif current_state == ChatState.PRODUCT:
            lead.product = user_message
            # STOP asking for Name/Email/Phone. 
            # Redirect to CTA.
            next_state = ChatState.COMPLETE ## Or remain in PRODUCT? Let's say COMPLETE for now or a new terminal state.
            bot_response = "Great choice! To get detailed insights on this product, please Book a Demo with our experts."
            
        elif current_state == ChatState.START:
             # Basic state transition if they answer the first question
             # But usually the first question is handled by the welcome message.
             # If they reply to "Import or Export?", we assume it's trade type.
             lead.trade_type = user_message
             next_state = ChatState.COUNTRY
             bot_response = STATE_QUESTIONS[ChatState.TRADE_TYPE]

        elif current_state == ChatState.COMPLETE:
            # They replied after the CTA — acknowledge and end gracefully
            next_state = ChatState.ENDED
            bot_response = "Thank you! Our team will reach out to you shortly. Have a wonderful day! 🎉"

        elif current_state == ChatState.ENDED:
            # Session is truly done — don't respond again
            next_state = ChatState.ENDED
            bot_response = ""  # Silence — session is over

        else:
            # Unexpected state — recover with a CTA nudge
            next_state = ChatState.COMPLETE
            bot_response = "I'd be happy to help! You can book a demo with our experts for a personalized walkthrough."

        # 4. Update state in DB session row
        session_service.update_chat_state(db, chat_session, next_state)
        
        # 5. Save bot response
        session_service.save_message(db, chat_session, bot_response, "bot")

        # 6. Return response with CTA if we reached the CTA point
        if next_state == ChatState.COMPLETE and current_state == ChatState.PRODUCT:
             return {
                "message": bot_response,
                "state": next_state,
                "type": "CTA",
                "cta_label": "Book Demo",
                "action": "OPEN_LEAD_FORM"
            }

        return {
            "message": bot_response if bot_response else STATE_QUESTIONS.get(next_state, "How can I help you?"),
            "state": next_state
        }
