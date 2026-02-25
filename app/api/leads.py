
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional

from uuid import UUID
from datetime import datetime, timezone

from app.core.dependencies import get_db
from app.models.lead import Lead, LeadStatusHistory, LeadStatus
from app.models.chat_session import ChatSession, SessionStatus, ConversationMode

from app.schemas.chatbot import (
    LeadResponse, 
    ConversationResponse, 
    LeadSubmitRequest, 
    StatusUpdateRequest, 
    LeadStatusHistoryResponse
)
from app.services import lead_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leads", tags=["Leads Admin"])


@router.post("/submit", summary="Submit chatbot lead form")
def submit_lead(
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

    try:
        # 1. Process Lead (Create or Update Duplicate)
        lead, is_duplicate = lead_service.create_or_update_lead(db, lead_req, source="chatbot")

        # 2. Trigger Agent Takeover if session exists
        session_id = request.cookies.get(app_settings.SESSION_COOKIE_NAME)
        takeover_triggered = False
        if session_id:
            takeover_triggered = session_service.trigger_agent_takeover(db, session_id, str(lead.id))

        return {
            "success": True,
            "message": "Thank you. Our team will contact you soon.",
            "warning": "This email matches an existing record. Your request has been updated." if is_duplicate else None,
            "reference_id": str(lead.id),
            "takeover_triggered": takeover_triggered
        }
    except IntegrityError as e:
        db.rollback()
        logger.error(f"[LeadSubmit] Database integrity error: {e}")
        raise HTTPException(status_code=409, detail="A lead with this email already exists.")
    except Exception as e:
        db.rollback()
        logger.exception(f"[LeadSubmit] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Lead submission failed: {str(e)}")




@router.get("/", response_model=List[LeadResponse], summary="Get all leads")
def get_leads(
    skip: int = 0,
    limit: int = 50,
    status: Optional[LeadStatus] = None,
    db: Session = Depends(get_db)
):
    """
    Retrieve leads with pagination and optional status filter.
    Pagination limit is capped at 100 to prevent system overload.
    """
    if limit > 100:
        limit = 100
        
    query = db.query(Lead).filter(Lead.is_deleted == False)

    if status:

        query = query.filter(Lead.status == status)
    
    return (
        query.order_by(Lead.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )



@router.get("/{id}", response_model=LeadResponse, summary="Get lead by ID")
def get_lead(id: UUID, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == id, Lead.is_deleted == False).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead



@router.patch("/{id}/status", response_model=LeadResponse, summary="Update lead status (controlled)")
def update_lead_status(
    id: UUID, 
    update_req: StatusUpdateRequest, 
    db: Session = Depends(get_db)
):
    """
    Update lead status using controlled lifecycle transitions.
    """
    try:
        updated_lead = lead_service.update_lead_status(
            db, 
            str(id), 
            update_req.status, 
            update_req.changed_by,
            update_req.source,
            update_req.version
        )
        return updated_lead
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))



@router.get("/{id}/history", response_model=List[LeadStatusHistoryResponse], summary="Get lead status audit trail")
def get_lead_history(id: UUID, db: Session = Depends(get_db)):
    """
    Retrieve history of status changes for a lead.
    """
    return lead_service.get_lead_history(db, str(id))


@router.get(
    "/{leadId}/conversations",
    summary="Get conversations for a lead"
)
def get_conversations(leadId: UUID, db: Session = Depends(get_db)):
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
def delete_lead(id: UUID, db: Session = Depends(get_db)):
    """
    Soft-delete a lead by marking is_deleted = True.
    """
    success = lead_service.soft_delete_lead(db, str(id))
    if not success:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"status": "success", "message": "Lead soft-deleted"}

