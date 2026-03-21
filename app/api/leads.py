
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional

from uuid import UUID
from datetime import datetime, timezone

from app.core.dependencies import get_db
from app.core.config import settings
from app.models.auth import User
from app.api.deps import require_role
from app.models.lead import Lead, LeadStatusHistory, LeadStatus
from app.models.chat_session import ChatSession, SessionStatus, ConversationMode
from app.models.chat_message import ChatMessage
from app.core.utils import is_valid_uuid

from app.schemas.chatbot import (
    LeadResponse, 
    LeadSubmitRequest, 
    StatusUpdateRequest, 
    LeadStatusHistoryResponse,
    PaginatedLeadResponse
)
from app.services import lead_service

logger = logging.getLogger(__name__)

# ── Simple In-Memory Rate Limiter ──────────────────────────────────────────
# Key: IP, Value: List of timestamps
from collections import defaultdict
from time import time
_submission_track: defaultdict = defaultdict(list)
RATE_LIMIT_STRIKES = 3
RATE_LIMIT_WINDOW = 300 # 5 minutes

router = APIRouter(prefix="/leads", tags=["Leads Admin"])


@router.post("/submit", summary="Submit chatbot lead form")
async def submit_lead(
    request: Request,
    lead_req: LeadSubmitRequest,
    db: Session = Depends(get_db)
):
    """
    Enterprise Lead Submission Flow (Orchestration).
    Delegates all business logic to services.
    """
    from app.services import lead_service, session_service
    from app.core.config import settings as app_settings
    from app.core.socket_manager import socket_manager
    from app.api.live_chat import format_session_for_crm

    try:
        # 0. Anti-Bot Protection (Honeypot)
        if lead_req.hp_field and lead_req.hp_field.strip() != "":
             logger.warning(f"Honeypot triggered from IP {request.client.host if request.client else 'unknown'}")
             return {"success": True, "message": "Thank you. Our team will contact you soon."} # Fake success for bots

        # 0.1 Rate Limiting (IP-based)
        client_ip = request.client.host if request.client else "unknown"
        now = time()
        # Clean old strikes
        _submission_track[client_ip] = [t for t in _submission_track[client_ip] if now - t < RATE_LIMIT_WINDOW]
        if len(_submission_track[client_ip]) >= RATE_LIMIT_STRIKES:
             logger.warning(f"Rate limit exceeded for IP {client_ip}")
             raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
        
        _submission_track[client_ip].append(now)

        # 1. Get Session & Tenant (if possible)
        session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
        chat_session = None
        current_tenant_id = settings.DEFAULT_TENANT_ID 

        # Priority 1: Use visitor_uuid from body
        if lead_req.visitor_uuid:
            chat_session = db.query(ChatSession).filter(
                ChatSession.visitor_uuid == lead_req.visitor_uuid,
                ChatSession.is_deleted == False
            ).order_by(ChatSession.last_activity_utc.desc()).first()
        
        # Priority 2: Fallback to session_id cookie if visitor_uuid didn't find anything
        if not chat_session and session_id and is_valid_uuid(session_id):
            chat_session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()

        if chat_session:
            current_tenant_id = chat_session.tenant_id
        elif session_id:
             logger.warning(f"No active session found for session_id: {session_id} or visitor_uuid: {lead_req.visitor_uuid}")

        # 1.1 Extract Identification for Lead (DEPRECATED metadata columns)
        lead_metadata = {}

        # 2. Process Lead (Create or Update Duplicate)
        lead, is_duplicate = lead_service.create_or_update_lead(
            db, 
            lead_req, 
            tenant_id=current_tenant_id, 
            source="chatbot",
            session_id=str(chat_session.session_id) if chat_session else None,
            metadata=lead_metadata
        )

        # 3. Update session if exists (link lead to session)
        if chat_session:
            # Update session with lead information
            chat_session.lead_id = str(lead.id)
            chat_session.lead_name = lead_req.full_name
            chat_session.lead_email = lead_req.business_email
            chat_session.lead_phone = lead_req.contact_number
            chat_session.lead_company = lead_req.company_name
            chat_session.last_activity_at = datetime.now(timezone.utc)
            chat_session.last_activity_utc = datetime.now(timezone.utc)
            
            # 3.1 Insert Automated History Message
            system_msg = ChatMessage(
                session_id=chat_session.session_id,
                message=f"System: Lead form submitted. Name: {lead_req.full_name}, Email: {lead_req.business_email}, Phone: {lead_req.contact_number}, Company: {lead_req.company_name}",
                role="system",
                sender_type="system",
                created_at=datetime.now(timezone.utc)
            )
            db.add(system_msg)
            db.commit()
            
            # 🔥 Broadcast SESSION_UPDATED to Dashboard (Real-time CRM Sync)
            session_item = format_session_for_crm(chat_session)
            await socket_manager.broadcast_event(
                "SESSION_UPDATED", 
                session_item
            )
            
            # Also broadcast the new system message
            await socket_manager.broadcast_event(
                "NEW_MESSAGE",
                {
                    "session_id": chat_session.session_id,
                    "message": system_msg.message,
                    "role": "system",
                    "created_at": system_msg.created_at.isoformat()
                }
            )
            logger.info(f"Updated session {chat_session.session_id} with lead {lead.id}")
        else:
            logger.warning("No session_id cookie found during lead submission")

        return {
            "success": True,
            "message": "Thank you. Our team will contact you soon.",
            "warning": "This email matches an existing record. Your request has been updated." if is_duplicate else None,
            "reference_id": str(lead.id)
        }
    except IntegrityError as e:
        db.rollback()
        error_msg = str(e.orig) if hasattr(e, 'orig') else str(e)
        logger.error(f"[LeadSubmit] Database integrity error: {error_msg}")
        
        if "FOREIGN KEY" in error_msg:
             raise HTTPException(status_code=500, detail="Administrative Error: Linked resource (Tenant/User) not found. Please contact support.")
        
        raise HTTPException(status_code=409, detail="A lead with this email or phone already exists.")
    except Exception as e:
        db.rollback()
        logger.exception(f"[LeadSubmit] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Lead submission failed: {str(e)}")




@router.get("/", response_model=PaginatedLeadResponse, summary="Get all leads (Filtered & Paginated)")
def get_leads(
    search: Optional[str] = None,
    status: Optional[str] = None,
    country: Optional[str] = None,
    trade_type: Optional[str] = None,
    product: Optional[str] = None,
    source: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page: int = 1,
    limit: int = 20,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """
    Scalable CRM endpoint for lead management.
    Handles searching, filtering, sorting, and pagination in the DB.
    """
    leads, total = lead_service.get_filtered_leads(
        db,
        tenant_id=current_user.tenant_id,
        search=search,
        status=status,
        country=country,
        trade_type=trade_type,
        product=product,
        source=source,
        start_date=start_date,
        end_date=end_date,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order
    )
    
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "data": leads
    }



@router.get("/{id}", response_model=LeadResponse, summary="Get lead by ID")
def get_lead(
    id: UUID, 
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    lead = db.query(Lead).filter(
        Lead.id == id, 
        Lead.tenant_id == current_user.tenant_id,
        Lead.is_deleted == False
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead



@router.patch("/{id}/status", response_model=LeadResponse, summary="Update lead status (controlled)")
def update_lead_status(
    id: UUID, 
    update_req: StatusUpdateRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """
    Update lead status using controlled lifecycle transitions.
    """
    try:
        updated_lead = lead_service.update_lead_status(
            db, 
            str(id), 
            update_req.status, 
            tenant_id=current_user.tenant_id,
            changed_by=update_req.changed_by,
            source=update_req.source,
            expected_version=update_req.version
        )
        return updated_lead
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))



@router.get("/{id}/history", response_model=List[LeadStatusHistoryResponse], summary="Get lead status audit trail")
def get_lead_history(
    id: UUID, 
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """
    Retrieve history of status changes for a lead.
    """
    return lead_service.get_lead_history(db, str(id), tenant_id=current_user.tenant_id)


@router.get(
    "/{leadId}/conversations",
    summary="Get conversations for a lead"
)
def get_conversations(
    leadId: UUID, 
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """
    Retrieve all messages associated with a lead by joining sessions.
    """
    from app.models.chat_message import ChatMessage
    
    return (
        db.query(ChatMessage)
        .join(ChatSession, ChatSession.session_id == ChatMessage.session_id)
        .filter(ChatSession.lead_id == str(leadId))
        .order_by(ChatMessage.created_at_utc.asc())
        .all()
    )



@router.delete("/{id}", summary="Soft delete a lead")
def delete_lead(
    id: UUID, 
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(2))
):
    """
    Soft-delete a lead by marking is_deleted = True.
    """
    success = lead_service.soft_delete_lead(db, str(id), tenant_id=current_user.tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"status": "success", "message": "Lead soft-deleted"}



