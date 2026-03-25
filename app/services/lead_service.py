import logging
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session
from app.models.lead import Lead, LeadStatusHistory, LeadStatus
from app.schemas.chatbot import LeadSubmitRequest
from datetime import datetime, timezone
from app.core.config import settings
from app.services.audit_service import AuditService

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
    tenant_id: int = settings.DEFAULT_TENANT_ID,
    changed_by: str = "system",
    source: str = "api",
    expected_version: Optional[int] = None
) -> Lead:
    """
    Controlled status transition with audit logging and optimistic locking.
    """
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.tenant_id == tenant_id).first()
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
        tenant_id=tenant_id,
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


def get_lead_history(db: Session, lead_id: str, tenant_id: int = settings.DEFAULT_TENANT_ID) -> List[LeadStatusHistory]:
    """
    Retrieve audit trail for a lead.
    """
    return db.query(LeadStatusHistory).filter(LeadStatusHistory.lead_id == str(lead_id), LeadStatusHistory.tenant_id == tenant_id).order_by(LeadStatusHistory.changed_at.desc()).all()


def create_or_update_lead(
    db: Session,
    lead_req: LeadSubmitRequest,
    tenant_id: int = settings.DEFAULT_TENANT_ID,
    source: str = "chatbot",
    session_id: Optional[str] = None,
    metadata: Optional[dict] = None
) -> Tuple[Lead, bool]:
    """
    Enterprise Lead Merge Logic:
    - Checks for duplicates by Business Email OR contact number (only non-deleted leads).
    - If a session_id is provided, tries to update the existing IN_PROGRESS lead.
    - Promotes status to NEW.
    - Respects soft-delete: deleted leads stay deleted, creates new lead instead.
    """
    normalized_email = lead_req.business_email.strip().lower()
    normalized_phone = lead_req.contact_number.strip()

    # 1. Primary check: Existing ACTIVE lead by email or phone (respect soft delete)
    lead = db.query(Lead).filter(
        (Lead.email == normalized_email) | (Lead.phone == normalized_phone),
        Lead.tenant_id == tenant_id,
        Lead.is_deleted == False  # Only find active leads, respect deletions
    ).first()

    # 2. Secondary check: Existing session-based lead (IN_PROGRESS)
    # Look for lead linked to this session, not by session_id as lead ID
    session_lead = None
    if session_id:
        from app.models.chat_session import ChatSession
        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id,
            ChatSession.tenant_id == tenant_id
        ).first()
        if session and session.lead_id:
            session_lead = db.query(Lead).filter(
                Lead.id == session.lead_id,
                Lead.is_deleted == False
            ).first()

    is_duplicate = False
    
    # CASE 1: Duplicate found globally (active lead)
    if lead:
        is_duplicate = True
        lead.name = lead_req.full_name
        lead.company = lead_req.company_name
        lead.website = lead_req.website
        lead.email = normalized_email
        lead.phone = normalized_phone
        lead.status = LeadStatus.NEW # Promote to NEW
        if session_id:
            lead.session_id = session_id
        # DO NOT restore deleted leads - they stay deleted
        lead.updated_at = datetime.now(timezone.utc)
        
        # Log promotion
        AuditService.log_action(
            db, 
            action=f"Lead updated: {lead.email}", 
            tenant_id=tenant_id
        )

        # 1.1 Update visitor identification if provided (DEPRECATED for Lead)
        if metadata:
            pass

        if session_lead and session_lead.id != lead.id:
            lead.trade_type = session_lead.trade_type or lead.trade_type
            lead.country_interested = session_lead.country_interested or lead.country_interested
            lead.product = session_lead.product or lead.product
            # visitor_uuid should already be identical or merged by now
    
    # CASE 2: No global duplicate, but we have a session lead to complete
    elif session_lead:
        lead = session_lead
        lead.name = lead_req.full_name
        lead.company = lead_req.company_name
        lead.website = lead_req.website
        lead.email = normalized_email
        lead.phone = normalized_phone
        lead.status = LeadStatus.NEW # Promote to NEW
        if session_id:
            lead.session_id = session_id
        lead.updated_at = datetime.now(timezone.utc)

        if metadata:
            pass

        # Log completion
        AuditService.log_action(
            db, 
            action=f"Lead completed: {lead.email}", 
            tenant_id=tenant_id
        )
    
    # CASE 3: Brand new lead (or deleted lead exists but we create new one)
    else:
        lead = Lead(
            name       = lead_req.full_name,
            email      = normalized_email,
            company    = lead_req.company_name,
            website    = lead_req.website,
            phone      = normalized_phone,
            status     = LeadStatus.NEW,
            source     = source,
            tenant_id  = tenant_id,
            session_id = session_id,
            created_at = datetime.now(timezone.utc)
        )
        db.add(lead)
        db.flush() # Get ID

        # Log creation
        AuditService.log_action(
            db, 
            action=f"New Lead: {lead.email}", 
            tenant_id=tenant_id
        )

    db.commit()
    db.refresh(lead)
    
    logger.info(f"Lead processed: {lead.email} | New: {not is_duplicate} | Status: {lead.status}")
    return lead, is_duplicate


def soft_delete_lead(db: Session, lead_id: str, tenant_id: int = settings.DEFAULT_TENANT_ID) -> bool:
    """
    Enterprise Soft-Delete: Mark as deleted but preserve for audit.
    """
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.tenant_id == tenant_id, Lead.is_deleted == False).first()
    if not lead:
        return False
    
    lead.is_deleted = True
    db.commit()
    logger.info(f"Lead {lead_id} soft-deleted")
    return True


def get_filtered_leads(
    db: Session,
    tenant_id: int,
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
    sort_order: str = "desc"
) -> Tuple[List[Lead], int]:
    """
    Scalable Lead Filtering with Pagination and Sorting.
    """
    query = db.query(Lead).filter(Lead.tenant_id == tenant_id, Lead.is_deleted == False)

    # Filtering
    if status:
        query = query.filter(Lead.status == status)
    if country:
        query = query.filter(Lead.country_interested == country)
    if trade_type:
        query = query.filter(Lead.trade_type == trade_type)
    if product:
        query = query.filter(Lead.product.ilike(f"%{product}%"))
    if source:
        query = query.filter(Lead.source == source)
    
    # Date Range
    if start_date:
        query = query.filter(Lead.created_at >= start_date)
    if end_date:
        query = query.filter(Lead.created_at <= end_date)

    # Search (Global)
    if search:
        search_filter = (
            Lead.name.ilike(f"%{search}%") |
            Lead.email.ilike(f"%{search}%") |
            Lead.company.ilike(f"%{search}%") |
            Lead.phone.ilike(f"%{search}%")
        )
        query = query.filter(search_filter)

    # Total count before pagination
    total = query.count()

    # Sorting
    sort_attr = getattr(Lead, sort_by, Lead.created_at)
    if sort_order.lower() == "desc":
        query = query.order_by(sort_attr.desc())
    else:
        query = query.order_by(sort_attr.asc())

    # Pagination
    offset = (page - 1) * limit
    leads = query.offset(offset).limit(limit).all()

    return leads, total


