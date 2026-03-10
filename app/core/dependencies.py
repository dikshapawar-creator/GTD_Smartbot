from app.db.session import get_db_with_retry

# ── Hardened DB Dependency ─────────────────────────────────────────────────
# All API routes that use Depends(get_db) automatically get connection retry
# and pool validation via get_db_with_retry.
# This is the SINGLE place to update DB dependency behavior for the whole app.
get_db = get_db_with_retry

