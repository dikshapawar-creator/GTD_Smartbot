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

THANK_YOU_MESSAGE = """Thank you. We will arrange a call for you shortly.

You can discuss all your questions with our team during the meeting.

Regarding your data and requirements, our team will provide you with the appropriate solution."""

STATE_QUESTIONS = {
    ChatState.START: "Welcome! Are you interested in Import or Export?",
    ChatState.TRADE_TYPE: "To provide you with the most accurate trade data for your region, please Book a Demo with our experts.",
    ChatState.COUNTRY: "Our database covers 80+ countries. Please use the form below to select your target market and get started.",
    ChatState.PRODUCT: "Great choice! To get detailed insights on this product, please Book a Demo with our experts.",
    ChatState.COMPLETE: "Is there anything else I can help you with?",
    ChatState.ENDED: THANK_YOU_MESSAGE
}

class ChatbotService:
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
    def handle_message(db: Session, chat_session: ChatSession, user_message: str) -> Dict[str, Any]:
        """
        Handles a message with Simplified Bot Flow:
        1. Check Urgent (WhatsApp redirect)
        2. Intent Match (from DB or fallbacks)
        3. Simple Fallback with Loop Prevention
        """
        session_id = chat_session.session_id

        # A. Save user message (priority)
        session_service.save_message(db, chat_session, user_message, "user")

        # B. Urgent Keyword Handling (TOP PRIORITY)
        if ChatbotService.check_urgent(user_message):
            urgent_msg = """We understand your request is urgent.

For immediate assistance, please contact us on WhatsApp:
💬 https://wa.me/918527376675
📞 +91 8527376675

Our team will assist you quickly."""
            session_service.save_message(db, chat_session, urgent_msg, "bot")
            session_service.update_chat_state(db, chat_session, ChatState.COMPLETE)
            return {
                "message": urgent_msg,
                "state": ChatState.COMPLETE,
                "type": "MESSAGE",
                "intent": "urgent"
            }

        # C. Intent Detection (Dynamic)
        intent_key = detect_intent(db, user_message)
        logger.info(f"Detected intent: {intent_key} for session {session_id}")

        intent_response = None
        
        # Check for specialized intent in DB first
        from app.models.intent_config import IntentConfig
        config = db.query(IntentConfig).filter(IntentConfig.intent_key == intent_key).first()
        if config and config.response_text:
            intent_response = config.response_text
        
        # Hardcoded High-Value Fallbacks (if DB is empty)
        if not intent_response:
            fallback_map = {
                "GREETING": "Hello! I'm your GTT Trade Assistant. How can I help you explore global trade today?",
                "IMPORT_EXPORT": "We provide comprehensive data for both Import and Export. Which one country are you looking for?",
                "BUYER_SEARCH": "We have detailed records of 20M+ buyers across 80+ countries. Are you looking for buyers for a specific product?",
                "SUPPLIER_SEARCH": "Our database includes millions of verified global suppliers. Looking for a supplier in a specific region?",
                "HS_CODE_SEARCH": "I can help you find HS Codes and tariff details for any product. What are you looking for?",
                "COMPETITOR_ANALYSIS": "Want to track what your competitors are shipping? We provide real-time competitor intelligence.",
                "SHIPMENT_RECORDS": "We provide detailed bill of lading and manifest data for 80+ countries. Want to see a sample?",
                "COUNTRY_TRADE_ANALYSIS": "We have in-depth trade reports for almost every country. Which region interests you?",
                "PRODUCT_MARKET_RESEARCH": "Get insights into global demand and supply trends for your products. Tell me the product name!",
                "PRICING_INQUIRY": "We have flexible plans for every business size. Please use the demo form below to discuss the best pricing for your needs.",
                "REQUEST_DEMO": THANK_YOU_MESSAGE,
                "LEAD_COLLECTION": THANK_YOU_MESSAGE,
                "SALES_DEMO": THANK_YOU_MESSAGE,
                "DEMO": THANK_YOU_MESSAGE,
                "HANDOFF": "I'll connect you with an expert. In the meantime, feel free to book a demo for a priority consultation.",
                "DATA_PROVIDER_DATASOURCE": "We collaborate with data providers who can supply import-export or customs trade data.\nIf you are interested in selling or साझेदारी, please share your company details and type of data you can provide.",
                "API_ACCESS_REQUEST": "We offer API access for seamless integration of trade data into your system.\nPlease share your use case and technical requirements, and our team will assist you with API details and access."
            }
            intent_response = fallback_map.get(intent_key)

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
                
            session_service.update_chat_state(db, chat_session, new_state)
            
            # CLEANSE: Remove PII requests
            intent_response = ChatbotService._clean_bot_response(intent_response)
            session_service.save_message(db, chat_session, intent_response, "bot")
            
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
            repeat_msg = "Our team will connect with you shortly."
            session_service.save_message(db, chat_session, repeat_msg, "bot")
            return {
                "message": repeat_msg,
                "state": ChatState.FALLBACK.value,
                "type": "MESSAGE"
            }
        
        # First fallback -> Standardized message
        fallback_msg = THANK_YOU_MESSAGE
        
        session_service.update_chat_state(db, chat_session, ChatState.FALLBACK.value)
        session_service.save_message(db, chat_session, fallback_msg, "bot")
        
        return {
            "message": fallback_msg,
            "state": ChatState.FALLBACK.value,
            "type": "CTA",
            "ctas": [
                {"label": "Book Demo", "action": "OPEN_LEAD_FORM", "icon": "🚀", "type": "secondary"},
                {"label": "Connect with Data Expert", "action": "HANDOFF", "icon": "💬", "type": "secondary"}
            ]
        }
