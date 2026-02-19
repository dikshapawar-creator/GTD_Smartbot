"""
GeoService — Enterprise IP-based geolocation and proxy handling.
Supports X-Forwarded-For, X-Real-IP, and robust client IP extraction.
"""
import logging
import httpx
import ipaddress
from typing import Tuple, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


def extract_client_ip(
    forwarded_for: Optional[str] = None,
    real_ip: Optional[str] = None,
    remote_addr: str = "127.0.0.1"
) -> str:
    """
    Enterprise-grade IP extraction logic.
    Priority: X-Forwarded-For (leftmost) > X-Real-IP > Remote Addr
    """
    if forwarded_for:
        # Take the first IP in the comma-separated list
        ip = forwarded_for.split(",")[0].strip()
        if ip:
            return ip
    if real_ip:
        return real_ip.strip()
    return remote_addr


def is_valid_public_ip(ip_str: str) -> bool:
    """
    Validates if an IP is a valid public IPv4/IPv6 address.
    Ignores private/internal ranges for geolocation purposes.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
        # Check if it's private, loopback, or reserved
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            return False
        return True
    except ValueError:
        return False


def lookup_ip_geo(ip_address: str) -> Tuple[str, str, str]:
    """
    Perform synchronous IP geolocation lookup with structured logging.
    Returns (country, city, timezone).
    """
    if not is_valid_public_ip(ip_address):
        logger.info({
            "event": "geo_lookup_skipped",
            "ip": ip_address,
            "reason": "internal_or_invalid_ip"
        })
        return ("Unknown", "Unknown", "UTC")

    url = settings.IP_API_URL.format(ip=ip_address)
    try:
        with httpx.Client(timeout=3.0) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        if data.get("error"):
            logger.warning({
                "event": "geo_lookup_error",
                "ip": ip_address,
                "api_error": data.get("reason", "unknown")
            })
            return ("Unknown", "Unknown", "UTC")

        country = data.get("country_name", "Unknown")
        city = data.get("city", "Unknown")
        timezone = data.get("timezone", "UTC")

        logger.info({
            "event": "geo_lookup_success",
            "ip": ip_address,
            "country": country,
            "city": city,
            "timezone": timezone
        })
        return (country, city, timezone)

    except Exception as e:
        logger.error({
            "event": "geo_lookup_exception",
            "ip": ip_address,
            "error": str(e)
        })
        return ("Unknown", "Unknown", "UTC")
