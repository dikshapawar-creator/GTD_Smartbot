"""
Spam detection logic to block malicious bots and persistent spammers.
"""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from collections import Counter
from sqlalchemy.orm import Session
from app.models.chat_message import ChatMessage
from app.models.chat_session import ChatSession

DISPOSABLE_EMAILS = [
    "mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com"
]

def check_message_spam(db: Session, session: ChatSession, new_message: str) -> bool:
    """Returns True if message is considered spam, False otherwise."""
    if not new_message:
        return False
        
    text_lower = new_message.lower()
    
    # 1. Message Frequency Check ( > 5 msgs in 10s )
    recent_messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session.session_id,
        ChatMessage.message_type == "user",
        ChatMessage.created_at_utc >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=10)
    ).count()
    
    if recent_messages >= 5:
        return True
        
    # 2. Repeated Message Detection
    last_msgs = db.query(ChatMessage.message_text).filter(
        ChatMessage.session_id == session.session_id,
        ChatMessage.message_type == "user",
    ).order_by(ChatMessage.created_at_utc.desc()).limit(4).all()
    
    if len(last_msgs) >= 3:
        texts = [m[0].lower().strip() for m in last_msgs]
        # If the last 3 messages are identical to the new one
        if texts.count(new_message.lower().strip()) >= 3:
            return True

    # 3. Suspicious Links
    urls = re.findall(r'(https?://[^\s]+|www\.[^\s]+)', text_lower)
    if len(urls) > 2:
        return True
    
    suspicious_keywords = ["casino", "crypto", "bet", ".bit"]
    if any(sw in text_lower for sw in suspicious_keywords) and len(urls) > 0:
        return True

    # 4. Random Character Detection (Gibberish)
    if len(new_message) > 15:
        # Check if contains no spaces and looks like random chars or numbers
        if not ' ' in new_message and (new_message.isalpha() or new_message.isalnum()):
            # Count consonant clusters or pure random
            return True
            
        if re.match(r'^[!@#$%^&*()_+={}\[\]|\\:;"\'<>,.?/~`\-\s]+$', new_message):
            return True # pure punctuation
            
        if re.match(r'^[0-9]+$', new_message):
            return True

    # 5. Disposable Email Detection
    email_pattern = r'[\w\.-]+@([\w\.-]+\.\w+)'
    match = re.search(email_pattern, text_lower)
    if match:
        domain = match.group(1)
        if any(d in domain for d in DISPOSABLE_EMAILS):
            return True
            
    # 6. IP Abuse Detection handled via Middleware or connection logic?
    # For now we'll check sessions created by this IP
    if session.initial_ip:
        recent_sessions = db.query(ChatSession).filter(
            ChatSession.initial_ip == session.initial_ip,
            ChatSession.started_at_utc >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        ).count()
        if recent_sessions > 5:
            return True

    return False
