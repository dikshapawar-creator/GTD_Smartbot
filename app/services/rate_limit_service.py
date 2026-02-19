"""
RateLimitService — Simple per-session rate limiting.
Max 30 messages per minute.
Uses an in-memory sliding window (stateless across restarts).
"""
import time
import logging
from collections import deque
from typing import Dict

logger = logging.getLogger(__name__)

# Max messages allowed in the window
MAX_REQUESTS = 30
# Window size in seconds
WINDOW_SECONDS = 60

# In-memory storage: { session_id: deque([timestamps]) }
_windows: Dict[str, deque] = {}

def is_rate_limited(session_id: str) -> bool:
    """
    Returns True if the session has exceeded the rate limit.
    """
    now = time.time()
    
    if session_id not in _windows:
        _windows[session_id] = deque()
    
    window = _windows[session_id]
    
    # Remove timestamps older than the window
    while window and window[0] < now - WINDOW_SECONDS:
        window.popleft()
    
    if len(window) >= MAX_REQUESTS:
        logger.warning({
            "event": "rate_limit_exceeded",
            "session_id": session_id,
            "requests_in_window": len(window)
        })
        return True
    
    # Add current timestamp
    window.append(now)
    return False

def cleanup_old_windows():
    """Optional: Periodic cleanup of stale sessions from memory."""
    now = time.time()
    stale_keys = [
        sid for sid, window in _windows.items() 
        if not window or window[-1] < now - (WINDOW_SECONDS * 5)
    ]
    for sid in stale_keys:
        del _windows[sid]
