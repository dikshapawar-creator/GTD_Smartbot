from sqlalchemy.orm import Session
from app.models.auth import Tenant
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class TenantService:
    @staticmethod
    def get_tenant_by_api_key(db: Session, api_key: str) -> Optional[Tenant]:
        """
        Retrieve tenant by API key. 
        In production, this should be cached (e.g., Redis).
        """
        return db.query(Tenant).filter(Tenant.api_key == api_key, Tenant.is_active == True).first()

    @staticmethod
    def get_tenant_by_domain(db: Session, domain: str) -> Optional[Tenant]:
        """
        Retrieve tenant by domain.
        In production, this should be cached.
        """
        return db.query(Tenant).filter(Tenant.domain == domain, Tenant.is_active == True).first()

    @staticmethod
    def get_tenant_by_id(db: Session, tenant_id: int) -> Optional[Tenant]:
        """
        Retrieve tenant by ID.
        """
        return db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.is_active == True).first()
