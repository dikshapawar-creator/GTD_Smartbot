"""
ChatMessage model — stores every individual chat message under a session.
Optimized with indexing for fast retrieval and history pagination.
"""
from sqlalchemy import (
    Column, BigInteger, String, Text, DateTime, ForeignKey, Index
)
from app.db.session import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # FK references chat_sessions.session_id (UUID string)
    session_id = Column(
        String(36),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # 'user' or 'bot'
    message_type = Column(String(10), nullable=False)

    message_text = Column(Text, nullable=False)

    # Dual timestamps
    created_at_utc = Column(DateTime, nullable=False, index=True)
    created_at_local = Column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_chat_messages_session_time", "session_id", "created_at_utc"),
    )
