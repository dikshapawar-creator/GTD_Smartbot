
import logging
from sqlalchemy import text
from app.db.session import engine, SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def cleanup_duplicates():
    with engine.connect() as conn:
        with conn.begin():
            logger.info("Identifying duplicate emails...")
            # Using ROW_NUMBER top-down approach for SQL Server
            # Find all row IDs where the email is not the latest for that email
            find_dupes = text("""
                WITH CTE AS (
                    SELECT id, email,
                           ROW_NUMBER() OVER (PARTITION BY email ORDER BY created_at DESC) as rn
                    FROM leads
                    WHERE email IS NOT NULL
                )
                SELECT id FROM CTE WHERE rn > 1
            """)
            
            dupe_ids = conn.execute(find_dupes).fetchall()
            
            if not dupe_ids:
                logger.info("No duplicates found.")
                return

            logger.info(f"Found {len(dupe_ids)} duplicate records. Deleting...")
            
            # Delete by ID
            for (lid,) in dupe_ids:
                conn.execute(text("DELETE FROM leads WHERE id = :lid"), {"lid": lid})
            
            logger.info("Cleanup successful.")

if __name__ == "__main__":
    cleanup_duplicates()
