"""
Timezone utility functions for proper IST handling.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

# IST is UTC+5:30
IST_OFFSET = timedelta(hours=5, minutes=30)

def utc_to_ist(utc_dt: Optional[datetime]) -> Optional[datetime]:
    """Convert UTC datetime to IST datetime."""
    if not utc_dt:
        return None
    return utc_dt + IST_OFFSET

def ist_to_utc(ist_dt: Optional[datetime]) -> Optional[datetime]:
    """Convert IST datetime to UTC datetime."""
    if not ist_dt:
        return None
    return ist_dt - IST_OFFSET

def format_ist_datetime(utc_dt: Optional[datetime], format_str: str = '%d %b, %I:%M %p IST') -> str:
    """Convert UTC datetime to formatted IST string."""
    if not utc_dt:
        return ""
    ist_dt = utc_to_ist(utc_dt)
    return ist_dt.strftime(format_str)

def format_ist_time(utc_dt: Optional[datetime]) -> str:
    """Convert UTC datetime to IST time string (e.g., '07:02 AM IST')."""
    if not utc_dt:
        return ""
    ist_dt = utc_to_ist(utc_dt)
    return ist_dt.strftime('%I:%M %p IST')

def get_current_ist() -> datetime:
    """Get current IST datetime."""
    return datetime.utcnow() + IST_OFFSET

def get_current_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.utcnow()