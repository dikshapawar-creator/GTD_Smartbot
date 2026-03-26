from sqlalchemy.orm import Query
from fastapi import HTTPException, status
import logging

logger = logging.getLogger(__name__)

def apply_tenant_filter(query: Query, model, tenant_id: int) -> Query:
    """
    Centralized utility to enforce tenant isolation at the query level.
    Ensures that any query strictly filtered by the provided tenant_id.
    """
    if tenant_id is None:
        logger.error(f"Attempted tenant-filtered query with NULL tenant_id for model {model.__name__}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context required for this operation."
        )
    
    # Check if model has tenant_id column
    if not hasattr(model, 'tenant_id'):
        logger.warning(f"Model {model.__name__} does not have a tenant_id column. Filtering may be incomplete.")
        return query
        
    return query.filter(model.tenant_id == tenant_id)

def verify_tenant_access(current_user_tenant_ids: list, target_tenant_id: int, is_super_admin: bool = False):
    """
    Strictly verify if a user has access to a specific tenant.
    """
    if is_super_admin:
        return True
    
    if target_tenant_id not in current_user_tenant_ids:
        logger.warning(f"Access Denied: User attempted to access tenant {target_tenant_id} without permission.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied for this workspace."
        )
    return True
