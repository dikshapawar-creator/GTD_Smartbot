"""
Session API — Enterprise session lifecycle and metrics endpoints.
Sets secure HTTP-only cookies and handles admin metrics.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

from app.core.dependencies import get_db
from app.core.config import settings
from app.services import session_service, geo_service
from app.schemas.chatbot import ChatState, SessionInitResponse
from app.models.chat_session import ChatSession
from app.models.chat_message import ChatMessage

router = APIRouter(prefix="/chat", tags=["Session Management"])

@router.post("/session/init", response_model=SessionInitResponse)
def initialize_session(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Initializes a new session or restores an existing valid one.
    Sets/restores an HTTP-only cookie.
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    
    # 1. Check if existing session in cookie is valid/active
    if session_id:
        active_session = session_service.get_active_session(db, session_id)
        if active_session:
            return {
                "session_token": active_session.session_id,
                "message": f"Welcome back! Continue with {active_session.chat_state}",
                "state": active_session.chat_state
            }

    # 2. Extract Geolocation (Proxy-aware)
    client_ip = geo_service.extract_client_ip(
        forwarded_for=request.headers.get("X-Forwarded-For"),
        real_ip=request.headers.get("X-Real-IP"),
        remote_addr=request.client.host if request.client else "127.0.0.1"
    )
    country, city, tz = geo_service.lookup_ip_geo(client_ip)

    # 3. Create new session in DB
    new_session = session_service.create_session(db, client_ip, country, city, tz)

    # 4. Set HTTP-only Cookie
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=new_session.session_id,
        httponly=True,
        secure=True, # Should be True in prod (HTTPS)
        samesite="lax",
        max_age=settings.SESSION_EXPIRY_MINUTES * 60
    )

    return {
        "session_token": new_session.session_id,
        "message": "Welcome! Are you interested in Import or Export?",
        "state": ChatState.START
    }


@router.post("/session/end")
def end_session(request: Request, response: Response, db: Session = Depends(get_db)):
    """Ends the session and clears the cookie."""
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        session_service.expire_session(db, session_id)
    
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"status": "session_ended"}


@router.get("/admin/metrics")
def get_chat_metrics(db: Session = Depends(get_db)):
    """
    Basic analytics aggregation for the dashboard.
    """
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total_sessions = db.query(func.count(ChatSession.id)).scalar()
    active_sessions = db.query(func.count(ChatSession.id)).filter(ChatSession.is_active == True).scalar()
    sessions_today = db.query(func.count(ChatSession.id)).filter(ChatSession.started_at_utc >= today_start).scalar()
    
    top_countries = (
        db.query(ChatSession.country, func.count(ChatSession.id))
        .group_by(ChatSession.country)
        .order_by(func.count(ChatSession.id).desc())
        .limit(5)
        .all()
    )

    avg_messages = db.query(func.avg(ChatSession.total_messages)).filter(ChatSession.total_messages > 0).scalar() or 0

    return {
        "total_sessions": total_sessions,
        "active_sessions": active_sessions,
        "sessions_today": sessions_today,
        "avg_messages_per_session": round(float(avg_messages), 2),
        "top_countries": {c: count for c, count in top_countries}
    }
