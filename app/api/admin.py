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
from app.models.blocked import BlockedVisitor

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
    
    from app.services.session_service import SessionService
    session_service = SessionService(db)
    active_sessions = session_service.get_active_sessions(tenant_id=tenant_id)
    active_chats = len(active_sessions)

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

    from app.services.websocket_manager import manager
    stale_cutoff = datetime.utcnow() - timedelta(hours=1)
    
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
                "status": "ACTIVE" if (manager.has_client(s.visitor_uuid) or (s.last_activity_at >= stale_cutoff if s.last_activity_at else False)) else "ENDED",
                "last_activity": s.last_activity_utc.isoformat(),
                "mode": s.conversation_mode
            } for s in recent_sessions
        ]
    }

# ── Security & IP Management ──────────────────────────────────────────

@router.get("/security/blocked-ips")
def list_blocked_ips(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """List all manually blocked visitor IPs."""
    blocked = db.query(BlockedVisitor).filter(
        BlockedVisitor.tenant_id == current_user.tenant_id
    ).order_by(BlockedVisitor.blocked_at.desc()).all()
    
    return [
        {
            "id": b.id,
            "ip": b.ip_address,
            "fingerprint": b.visitor_fingerprint,
            "reason": b.reason,
            "time": b.blocked_at.isoformat()
        } for b in blocked
    ]

@router.post("/security/block-ip")
def block_visitor_ip(
    ip_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """Manually block a specific IP address."""
    ip = ip_data.get("ip")
    if not ip:
        return {"error": "IP address is required"}
        
    # Check if already blocked
    existing = db.query(BlockedVisitor).filter(
        BlockedVisitor.tenant_id == current_user.tenant_id,
        BlockedVisitor.ip_address == ip
    ).first()
    
    if existing:
        return {"message": "IP already blocked", "id": existing.id}
        
    new_block = BlockedVisitor(
        tenant_id=current_user.tenant_id,
        ip_address=ip,
        reason=ip_data.get("reason", "Manual block"),
        blocked_at=datetime.utcnow()
    )
    db.add(new_block)
    db.commit()
    db.refresh(new_block)
    
    return {"message": "IP blocked successfully", "id": new_block.id}

@router.delete("/security/unblock-ip/{block_id}")
def unblock_visitor_ip(
    block_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """Remove an IP block record."""
    block = db.query(BlockedVisitor).filter(
        BlockedVisitor.id == block_id,
        BlockedVisitor.tenant_id == current_user.tenant_id
    ).first()
    
    if not block:
        return {"error": "Block record not found"}
        
    db.delete(block)
    db.commit()
    return {"message": "IP unblocked successfully"}

@router.patch("/security/block-ip/{block_id}")
def update_block_reason(
    block_id: int,
    data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """Update the reason for a blocked IP."""
    block = db.query(BlockedVisitor).filter(
        BlockedVisitor.id == block_id,
        BlockedVisitor.tenant_id == current_user.tenant_id
    ).first()
    
    if not block:
        return {"error": "Block record not found"}
        
    reason = data.get("reason")
    if reason:
        block.reason = reason
        db.commit()
        db.refresh(block)
        
    return {"message": "Reason updated successfully", "reason": block.reason}
