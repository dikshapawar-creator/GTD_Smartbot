"""
Leads API — Enterprise lead management and form submission.
Handles secure lead capture with automated geolocation and source tracking.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from datetime import datetime
import pytz

from app.core.dependencies import get_db
from app.models.lead import Lead
from app.models.conversation import Conversation
from app.schemas.chatbot import LeadResponse, ConversationResponse, LeadSubmitRequest
from app.services import geo_service

router = APIRouter(prefix="/leads", tags=["Leads Admin"])

@router.post("/submit", summary="Submit enterprise lead form")
def submit_lead(request: Request, lead_req: LeadSubmitRequest, db: Session = Depends(get_db)):
    """
    Submits an enterprise lead form. 
    Maintains security by auto-resolving IP and Country on the backend.
    """
    # 1. Capture Client IP (Proxy-aware)
    client_ip = geo_service.extract_client_ip(
        forwarded_for=request.headers.get("X-Forwarded-For"),
        real_ip=request.headers.get("X-Real-IP"),
        remote_addr=request.client.host if request.client else "127.0.0.1"
    )
    
    # 2. Lookup Geolocation
    country, city, tz_name = geo_service.lookup_ip_geo(client_ip)
    
    # 3. Handle Timestamps
    now_utc = datetime.utcnow()
    try:
        user_tz = pytz.timezone(tz_name or "UTC")
        now_local = datetime.now(user_tz)
    except Exception:
        now_local = now_utc

    # 4. Create Lead Record
    # Note: Mapping business_email to email, company_name to company
    new_lead = Lead(
        name=lead_req.full_name,
        email=lead_req.business_email,
        company=lead_req.company_name,
        phone=lead_req.contact_number,
        # trade_type or product could be added from session if needed, 
        # but here we focus on form submission
        status="NEW",
        created_at=now_utc  
    )
    # Adding extra metadata could require a separate table or extending Lead model
    # For now, we reuse the existing Lead model fields
    
    db.add(new_lead)
    db.commit()
    db.refresh(new_lead)

    return {
        "success": True, 
        "message": "Thank you. Our team will contact you shortly."
    }

@router.get("/", response_model=List[LeadResponse], summary="Get all leads")
def get_leads(db: Session = Depends(get_db)):
    return db.query(Lead).all()

@router.get("/{id}", response_model=LeadResponse, summary="Get lead by ID")
def get_lead(id: UUID, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead

@router.get("/{leadId}/conversations", response_model=List[ConversationResponse], summary="Get conversations for a lead")
def get_conversations(leadId: UUID, db: Session = Depends(get_db)):
    return db.query(Conversation).filter(Conversation.lead_id == leadId).all()
