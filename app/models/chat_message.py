"""
ChatMessage model — stores every individual chat message under a session.
Optimized with indexing for fast retrieval and history pagination.
"""
from sqlalchemy import (
    Column, BigInteger, String, Text, DateTime, ForeignKey, Index, Integer
)
from app.db.session import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, default=1, index=True)

    # FK references chat_sessions.session_id (String UUID)
    session_id = Column(String(36), nullable=False, index=True)

    # 'user', 'bot', 'agent', or 'system'
    message_type = Column(String(10), nullable=False)

    message_text = Column(Text, nullable=False)

    # Dual timestamps
    created_at = Column(DateTime, nullable=False, index=True)
    created_at_utc = Column(DateTime, nullable=False, index=True)
    created_at_local = Column(DateTime, nullable=False)

    __table_args__ = (
        # ── Primary pagination pattern: all messages for a session, ordered by time
        # Covers: WHERE session_id = ? ORDER BY created_at_utc ASC LIMIT ? OFFSET ?
        Index("ix_chat_messages_session_time", "session_id", "created_at_utc"),
    )

    @property
    def created_at_ist(self) -> str:
        """Format UTC timestamp to IST string for frontend consistency."""
        if not self.created_at_utc:
            return ""
        from datetime import timezone, timedelta
        # UTC to IST (+5:30)
        ist_time = self.created_at_utc.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30)))
        return ist_time.strftime("%d %b %Y, %I:%M %p")
