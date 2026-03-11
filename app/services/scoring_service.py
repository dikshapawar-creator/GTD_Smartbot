"""
ScoringService - Handles the lead scoring logic based on chat behavior.
"""
from typing import Optional
from sqlalchemy.orm import Session
from app.models.chat_session import ChatSession

def calculate_message_score(message_text: str) -> int:
    """Calculates score for an individual message based on defined keywords and patterns."""
    if not message_text:
        return 0
        
    score = 0
    msg = message_text.lower()
    
    if any(word in msg for word in ["price", "cost", "quotation"]):
        score += 30

    if any(word in msg for word in ["import", "export", "shipment"]):
        score += 20

    if any(word in msg for word in ["supplier", "manufacturer"]):
        score += 25
        
    return score

def determine_lead_status(score: int) -> str:
    """Converts a numeric score to a Hot/Warm/Cold category."""
    if score >= 70:
        return "Hot"
    elif score >= 40:
        return "Warm"
    else:
        return "Cold"

def update_session_score(db: Session, session: ChatSession, new_message_text: str) -> ChatSession:
    """Updates the session's overall score by evaluating a new message."""
    # Base score increment logic
    message_score = calculate_message_score(new_message_text)
        
    if message_score > 0:
        session.lead_score += message_score
        
    # Recalculate status
    new_status = determine_lead_status(session.lead_score)
    session.lead_status = new_status
    
    return session
