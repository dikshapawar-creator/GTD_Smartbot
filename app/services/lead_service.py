import logging
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session
from app.models.lead import Lead, LeadStatusHistory, LeadStatus
from app.schemas.chatbot import LeadSubmitRequest
from datetime import datetime, timezone


logger = logging.getLogger(__name__)

# ── Lifecycle Rules ────────────────────────────────────────────────────────
# NEW → IN_PROGRESS → QUALIFIED → CLOSED
ALLOWED_TRANSITIONS = {
    LeadStatus.NEW: [LeadStatus.IN_PROGRESS, LeadStatus.CLOSED],
    LeadStatus.IN_PROGRESS: [LeadStatus.QUALIFIED, LeadStatus.CLOSED],
    LeadStatus.QUALIFIED: [LeadStatus.CLOSED],
    LeadStatus.CLOSED: [LeadStatus.IN_PROGRESS]  # Allow reopening if needed
}


def update_lead_status(
    db: Session, 
    lead_id: str, 
    new_status: str, 
    changed_by: str = "system",
    source: str = "api",
    expected_version: Optional[int] = None
) -> Lead:
    """
    Controlled status transition with audit logging and optimistic locking.
    """
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")

    # ── Optimistic Locking ───────────────────────────────────────────────
    if expected_version is not None and lead.version != expected_version:
        logger.warning(f"Concurrency conflict for lead {lead_id}: expected v{expected_version}, found v{lead.version}")
        raise ValueError("Conflict detected: the lead has been updated by another user. Please refresh.")

    old_status = lead.status
    
    # Skip if status is the same
    if old_status == new_status:
        return lead

    # Validate transition
    if new_status not in ALLOWED_TRANSITIONS.get(old_status, []):
        logger.warning(f"Invalid transition attempt: {old_status} -> {new_status} for lead {lead_id}")
        raise ValueError(f"Invalid status transition: {old_status} -> {new_status}")

    # Record history
    history = LeadStatusHistory(
        lead_id=lead.id,
        old_status=old_status,
        new_status=new_status,
        changed_by=changed_by,
        source=source
    )
    
    # Update lead
    lead.status = new_status
    lead.version += 1 # Increment version
    
    db.add(history)
    db.commit()
    db.refresh(lead)

    logger.info(f"Lead {lead_id} status updated: {old_status} -> {new_status} by {changed_by} via {source}")
    return lead


def get_lead_history(db: Session, lead_id: str) -> List[LeadStatusHistory]:
    """
    Retrieve audit trail for a lead.
    """
    return db.query(LeadStatusHistory).filter(LeadStatusHistory.lead_id == str(lead_id)).order_by(LeadStatusHistory.changed_at.desc()).all()


def create_or_update_lead(
    db: Session,
    lead_req: LeadSubmitRequest,
    source: str = "chatbot"
) -> Tuple[Lead, bool]:

    """
    Business logic for lead submission:
    - Normalizes and checks for existing lead.
    - Creates if new, updates timestamp if duplicate.
    - Returns (lead, is_duplicate).
    """
    normalized_email = lead_req.business_email.strip().lower()
    lead = db.query(Lead).filter(Lead.email == normalized_email, Lead.is_deleted == False).first()
    
    is_duplicate = False
    if lead:
        is_duplicate = True
        lead.updated_at = datetime.now(timezone.utc)
    else:
        lead = Lead(
            name       = lead_req.full_name,
            email      = normalized_email,
            company    = lead_req.company_name,
            website    = lead_req.website,
            phone      = lead_req.contact_number,
            status     = LeadStatus.NEW,
            source     = source,
            created_at = datetime.now(timezone.utc),
        )
        db.add(lead)

    db.commit()
    db.refresh(lead)
    
    logger.info(f"Lead processed: {lead.email} | New: {not is_duplicate} | Source: {source}")
    return lead, is_duplicate


def soft_delete_lead(db: Session, lead_id: str) -> bool:
    """
    Enterprise Soft-Delete: Mark as deleted but preserve for audit.
    """
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.is_deleted == False).first()
    if not lead:
        return False
    
    lead.is_deleted = True
    db.commit()
    logger.info(f"Lead {lead_id} soft-deleted")
    return True


