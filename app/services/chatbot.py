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
from app.services.intent_service import detect_intent, IntentType

logger = logging.getLogger(__name__)

from app.models.intent_config import IntentConfig

class ChatbotService:
    @staticmethod
    def _get_dynamic_response(db: Session, intent_key: str, default: str, tenant_id: int) -> str:
        """Fetch response template for a given intent and tenant."""
        from app.models.intent_config import IntentConfig
        
        config = db.query(IntentConfig).filter(
            IntentConfig.intent_key == intent_key,
            IntentConfig.tenant_id == tenant_id,
            IntentConfig.is_active == True
        ).first()
        
        response = config.response_text if (config and config.response_text) else default
        
        # ⚡ CRITICAL: Fix potential UTF-16 encoding issues (null bytes)
        # This prevents character-by-character streaming on some environments.
        if isinstance(response, str) and ('\x00' in response or '\u0000' in response):
            response = response.replace('\x00', '').replace('\u0000', '')
            logger.warning(f"Fixed UTF-16 encoding in intent response for {intent_key}")
            
        return str(response) if response is not None else ""

    @staticmethod
    def get_state_question(db: Session, state: ChatState) -> str:
        """Dynamic replacement for hardcoded STATE_QUESTIONS."""
        state_map = {
            ChatState.START: ("WELCOME_QUESTION", "Welcome! Are you interested in Import or Export?"),
            ChatState.TRADE_TYPE: ("TRADE_TYPE_QUESTION", "To provide you with the most accurate trade data for your region, please Book a Demo with our experts."),
            ChatState.COUNTRY: ("COUNTRY_QUESTION", "Our database covers 80+ countries. Please use the form below to select your target market and get started."),
            ChatState.PRODUCT: ("PRODUCT_QUESTION", "Great choice! To get detailed insights on this product, please Book a Demo with our experts."),
            ChatState.COMPLETE: ("EXTRA_HELP_QUESTION", "Is there anything else I can help you with?"),
            ChatState.ENDED: ("FALLBACK_GENERIC", "Thank you. We will arrange a call for you shortly.")
        }
        key, default = state_map.get(state, ("UNKNOWN", "How can I help you?"))
        return ChatbotService._get_dynamic_response(db, key, default, 1) # Fallback to 1 for generic questions if needed, or pass session.tenant_id

    @staticmethod
    def _clean_bot_response(text: str) -> str:
        """
        Enterprise-grade response cleanser. 
        Detects and removes conversational lead-gathering phrases (PII requests)
        and replaces them with a nudge to use the formal Lead Form/CTA.
        """
        import re
        if not text:
            return ""
        
        # Fix potential UTF-16 encoding issues first
        if '\x00' in text:
            text = text.replace('\x00', '')
            
        # Target phrases like "Please share your email", "Provide your name", etc.
        patterns = [
            r"please (?:share|provide|tell me|give me|send me) your (?:name|email|phone|contact|company|website|business email|full name)[^.!?]*[.!?]?",
            r"(?:share|provide|tell me|give me|send me) your (?:name|email|phone|contact|company|website|business email|full name)[^.!?]*[.!?]?",
            r"which company do you (?:represent|work for)[^.!?]*[.!?]?",
            r"what is your (?:email|phone|contact|company|website)[^.!?]*[.!?]?",
            r"finally, what are your specific requirements [^.!?]*[.!?]?"
        ]
        
        cleaned = text
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
            
        # Add the Book Demo nudge if we stripped something out
        if cleaned.strip() != text.strip():
            nudge = " Please click on \"Book Demo\" and our team will get in touch with you."
            if nudge not in cleaned:
                cleaned = cleaned.strip() + nudge
                
        return cleaned.strip()

    @staticmethod
    def check_urgent(message: str) -> bool:
        """
        Checks for urgent keywords in the user message.
        """
        urgent_keywords = ["urgent", "asap", "immediately", "now", "fast", "quick", "need help", "need assistance","urgent requirement","I want today","I want now"]
        msg_lower = message.lower()
        return any(word in msg_lower for word in urgent_keywords)

    @staticmethod
    def handle_message(db: Session, chat_session: ChatSession, user_message: str, commit: bool = True) -> Dict[str, Any]:
        """
        Handles a message with Simplified Bot Flow:
        1. Check Urgent (WhatsApp redirect)
        2. Intent Match (from DB or fallbacks)
        3. Simple Fallback with Loop Prevention
        """
        session_id = chat_session.session_id

        # A. Save user message (priority)
        session_service.save_message(db, chat_session, user_message, "user", commit=commit)

        # B. Urgent Keyword Handling (TOP PRIORITY)
        if ChatbotService.check_urgent(user_message):
            urgent_msg = ChatbotService._get_dynamic_response(
                db, 
                "URGENT_SUPPORT", 
                "We understand your request is urgent. For immediate assistance, please contact us on WhatsApp: +91 8527376675",
                chat_session.tenant_id
            )
            session_service.save_message(db, chat_session, urgent_msg, "bot", commit=commit)
            session_service.update_chat_state(db, chat_session, ChatState.COMPLETE, commit=commit)
            return {
                "message": urgent_msg,
                "state": ChatState.COMPLETE.value,
                "type": "MESSAGE",
                "intent": "urgent"
            }

        # C. Intent Detection (Dynamic)
        intent_key = detect_intent(db, user_message, chat_session.tenant_id)
        logger.info(f"Detected intent: {intent_key} for session {session_id} (Tenant {chat_session.tenant_id})")

        intent_response = None
        
        # Force specialized intent from the ACTIVE tenant
        from app.models.intent_config import IntentConfig
        config = db.query(IntentConfig).filter(
            IntentConfig.intent_key == intent_key,
            IntentConfig.tenant_id == chat_session.tenant_id,
            IntentConfig.is_active == True
        ).first()
        if config and config.response_text:
            intent_response = config.response_text
        
        if intent_response and intent_key != "UNKNOWN":
            logger.info(f"Intent response found (Source: {'DB' if config else 'Hardcoded'}): {intent_key}")
            # Intent found -> Reset fallback sentinel if it was set
            
            # 🔧 FIX: Map specific informative intents to valid ChatStates
            new_state = chat_session.chat_state or ChatState.START.value
            
            if intent_key == "GREETING":
                new_state = ChatState.START.value
            elif intent_key in [
                "DEMO", "REQUEST_DEMO", "SALES_DEMO", 
                "LEAD_COLLECTION", "PRICING_INQUIRY"
            ]:
                new_state = ChatState.COMPLETE.value
            elif intent_key == "HANDOFF":
                new_state = ChatState.HANDOFF_SENT.value
            
            # Ensure new_state is a string and valid (fallback to START if unknown)
            try:
                # Validate if it's one of the ChatState enum values
                ChatState(new_state)
            except ValueError:
                new_state = ChatState.START.value
                
            session_service.update_chat_state(db, chat_session, new_state, commit=commit)
            
            # CLEANSE: Remove PII requests
            intent_response = ChatbotService._clean_bot_response(intent_response)
            session_service.save_message(db, chat_session, intent_response, "bot", commit=commit)
            
            # Use Multi-CTA for every intent response for consistency
            return {
                "message": intent_response,
                "state": str(chat_session.chat_state).upper(),
                "type": "CTA",
                "ctas": [
                    {"label": "Book Demo", "action": "OPEN_LEAD_FORM", "icon": "🚀", "type": "secondary"},
                    {"label": "Connect with Data Expert", "action": "HANDOFF", "icon": "💬", "type": "secondary"}
                ],
                "intent": intent_key
            }

        logger.warning(f"No specific intent response found for intent_key: {intent_key}. Falling back to general logic.")

        # D. NO INTENT FOUND -> FALLBACK LOGIC (Loop Prevention)
        last_state = chat_session.chat_state
        
        if last_state == ChatState.FALLBACK:
            # Repeated fallback -> Short silence message
            repeat_msg = ChatbotService._get_dynamic_response(
                db, 
                "FALLBACK_REPEAT", 
                """We’ve received your message and will get back to you soon.
 
For more details, feel free to reach us anytime:
💬- https://wa.me
📞 WhatsApp: +91 8527376675
 
We’ll be happy to assist you with complete support.""",
                chat_session.tenant_id
            )
            session_service.save_message(db, chat_session, repeat_msg, "bot", commit=commit)
            return {
                "message": repeat_msg,
                "state": ChatState.FALLBACK.value,
                "type": "MESSAGE"
            }
        
        # First fallback -> Standardized message
        fallback_msg = ChatbotService._get_dynamic_response(
            db, 
            "FALLBACK_GENERIC", 
            "Thank you for reaching out. A representative will be with you shortly to assist you further.",
            chat_session.tenant_id
        )
        
        session_service.update_chat_state(db, chat_session, ChatState.FALLBACK.value, commit=commit)
        session_service.save_message(db, chat_session, fallback_msg, "bot", commit=commit)
        
        return {
            "message": fallback_msg,
            "state": ChatState.FALLBACK.value,
            "type": "CTA",
            "ctas": [
                {"label": "Book Demo", "action": "OPEN_LEAD_FORM", "icon": "🚀", "type": "secondary"},
                {"label": "Connect with Data Expert", "action": "HANDOFF", "icon": "💬", "type": "secondary"}
            ]
        }
