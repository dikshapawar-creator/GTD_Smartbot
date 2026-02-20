
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List
from uuid import UUID
from datetime import datetime, timezone

from app.core.dependencies import get_db
from app.models.lead import Lead
from app.models.conversation import Conversation
from app.schemas.chatbot import LeadResponse, ConversationResponse, LeadSubmitRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leads", tags=["Leads Admin"])


@router.post("/submit", summary="Submit chatbot lead form")
def submit_lead(
    lead_req: LeadSubmitRequest,
    db: Session = Depends(get_db)
):
    """
    Simplified Lead Submission.
    Validates via Pydantic and checks for duplicate emails.
    """
    # ── 1. Duplicate email detection ────────────────────────────────────────
    normalized_email = lead_req.business_email.strip().lower()
    existing = db.query(Lead).filter(Lead.email == normalized_email).first()
    if existing:
        raise HTTPException(status_code=409, detail="A lead with this email already exists.")

    # ── 2. Create Lead record ───────────────────────────────────────────────
    new_lead = Lead(
        name       = lead_req.full_name,
        email      = normalized_email,
        company    = lead_req.company_name,
        website    = lead_req.website,
        phone      = lead_req.contact_number,
        status     = "NEW",
        created_at = datetime.now(timezone.utc),
    )

    try:
        db.add(new_lead)
        db.commit()
        db.refresh(new_lead)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Duplicate lead detected.")

    return {
        "success": True,
        "message": "Thank you. Our team will contact you soon.",
        "reference_id": str(new_lead.id),
    }


@router.get("/", response_model=List[LeadResponse], summary="Get all leads")
def get_leads(db: Session = Depends(get_db)):
    return db.query(Lead).order_by(Lead.created_at.desc()).all()


@router.get("/{id}", response_model=LeadResponse, summary="Get lead by ID")
def get_lead(id: UUID, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.get(
    "/{leadId}/conversations",
    response_model=List[ConversationResponse],
    summary="Get conversations for a lead"
)
def get_conversations(leadId: UUID, db: Session = Depends(get_db)):
    return db.query(Conversation).filter(Conversation.lead_id == leadId).all()
