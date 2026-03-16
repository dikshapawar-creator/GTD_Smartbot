from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta, timezone

from app.api.deps import require_role
from app.core.dependencies import get_db
from app.models.auth import User, AuditLog
from app.models.lead import Lead, LeadStatus
from app.models.chat_session import ChatSession, SessionStatus
from app.models.chat_message import ChatMessage

router = APIRouter(prefix="/admin", tags=["Administration (High Privilege)"])

@router.get("/stats")
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """
    Enterprise Dashboard Analytics: Represents real business data.
    """
    tenant_id = current_user.tenant_id
    tenant_name = current_user.tenant.name if current_user.tenant else "System Workspace"

    # 1. KPI Metrics
    total_leads = db.query(func.count(Lead.id)).filter(Lead.tenant_id == tenant_id, Lead.is_deleted == False).scalar()
    new_leads = db.query(func.count(Lead.id)).filter(
        Lead.tenant_id == tenant_id, 
        Lead.status == LeadStatus.NEW, 
        Lead.is_deleted == False
    ).scalar()
    
    active_chats = db.query(func.count(ChatSession.id)).filter(
        ChatSession.tenant_id == tenant_id,
        ChatSession.session_status == SessionStatus.ACTIVE,
        ChatSession.is_deleted == False
    ).scalar()

    total_messages = db.query(func.count(ChatMessage.id)).join(
        ChatSession, ChatSession.session_id == ChatMessage.session_id
    ).filter(ChatSession.tenant_id == tenant_id).scalar()

    # 2. Recent Activities (Last 5 Leads)
    recent_leads = db.query(Lead).filter(
        Lead.tenant_id == tenant_id,
        Lead.is_deleted == False
    ).order_by(Lead.created_at.desc()).limit(5).all()

    # 3. Recent Conversations (Last 5 Sessions)
    recent_sessions = db.query(ChatSession).filter(
        ChatSession.tenant_id == tenant_id,
        ChatSession.is_deleted == False
    ).order_by(ChatSession.last_activity_utc.desc()).limit(5).all()

    return {
        "kpis": {
            "total_leads": total_leads,
            "new_leads": new_leads,
            "active_chats": active_chats,
            "total_messages": total_messages
        },
        "tenant_name": tenant_name,
        "notifications": [
             {
                 "id": str(log.id),
                 "message": log.action,
                 "time": log.created_at.isoformat()
             } for log in db.query(AuditLog).filter(
                 AuditLog.tenant_id == tenant_id,
                 ~AuditLog.action.ilike("%LOGIN%"),
                 ~AuditLog.action.ilike("%LOGOUT%"),
                 ~AuditLog.action.ilike("%BOOTSTRAP%")
             ).order_by(AuditLog.created_at.desc()).limit(10).all()
        ] if db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id).first() else [
             {
                 "id": "welcome_1",
                 "message": f"Welcome to the {tenant_name} portal. Setup your first chat session.",
                 "time": datetime.now(timezone.utc).isoformat()
             }
        ],
        "recent_leads": [
            {
                "id": str(l.id),
                "name": l.name,
                "email": l.email,
                "company": l.company,
                "status": l.status,
                "created_at": l.created_at.isoformat()
            } for l in recent_leads
        ],
        "recent_sessions": [
            {
                "session_id": s.session_id,
                "client_ip": s.initial_ip,
                "country": s.country,
                "status": s.session_status,
                "last_activity": s.last_activity_utc.isoformat(),
                "mode": s.conversation_mode
            } for s in recent_sessions
        ]
    }
