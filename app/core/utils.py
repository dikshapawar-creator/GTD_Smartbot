import re
import hashlib
from typing import Dict, Any
from fastapi import Request

def get_client_ip(request: Request) -> str:
    """
    Extracts the client IP address with priority given to forwarded headers.
    """
    headers = request.headers

    x_forwarded_for = headers.get("x-forwarded-for")
    if x_forwarded_for and x_forwarded_for.lower() != "unknown":
        # Usually leftmost IP is the original client
        ip = x_forwarded_for.split(",")[0].strip()
        if ip:
            return ip

    cf_ip = headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    x_real_ip = headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()

    if request.client:
        return request.client.host

    return "127.0.0.1"

def get_visitor_metadata(request: Request) -> Dict[str, str]:
    """
    Basic User-Agent parsing to extract browser, OS, and device type.
    """
    ua_string = request.headers.get("user-agent", "Unknown")
    
    # Very simple parsing logic (can be replaced by 'user-agents' library if needed)
    metadata = {
        "user_agent": ua_string,
        "browser": "Other",
        "os": "Other",
        "device_type": "Desktop"
    }

    ua_lower = ua_string.lower()

    # Browser
    if "chrome" in ua_lower: metadata["browser"] = "Chrome"
    elif "firefox" in ua_lower: metadata["browser"] = "Firefox"
    elif "safari" in ua_lower and "chrome" not in ua_lower: metadata["browser"] = "Safari"
    elif "edge" in ua_lower: metadata["browser"] = "Edge"

    # OS
    if "windows" in ua_lower: metadata["os"] = "Windows"
    elif "macintosh" in ua_lower: metadata["os"] = "MacOS"
    elif "linux" in ua_lower: metadata["os"] = "Linux"
    elif "android" in ua_lower: metadata["os"] = "Android"
    elif "iphone" in ua_lower or "ipad" in ua_lower: metadata["os"] = "iOS"

    # Device
    if any(m in ua_lower for m in ["mobi", "android", "iphone", "ipad"]):
        metadata["device_type"] = "Mobile"

    return metadata

def generate_visitor_fingerprint(ip: str, user_agent: str) -> str:
    """
    Generates a unique, privacy-respecting fingerprint for a visitor.
    Hash is truncated to 8 characters for readability.
    """
    raw_str = f"{ip}|{user_agent}"
    return hashlib.sha256(raw_str.encode()).hexdigest()[:12]
