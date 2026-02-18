from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from app.core.dependencies import get_db
from app.models.lead import Lead
from app.models.conversation import Conversation
from app.schemas.chatbot import LeadResponse, ConversationResponse

router = APIRouter(prefix="/leads", tags=["Leads Admin"])

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
