import os
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Placeholder tokens that indicate user hasn't configured properly
_PLACEHOLDER_TOKENS = [
    "YOUR_TOKEN",
    "YOUR_LONG_LIVED_TOKEN",
    "your_token",
    "your_long_lived_token",
    "mock_token",
    "test_token",
    "<token>",
    "TOKEN_HERE",
]


def _validate_ha_url(url: str) -> str:
    """Validate Home Assistant URL format and log warnings."""
    if not url:
        logger.warning("HA_URL is empty, using default http://localhost:8123")
        return "http://localhost:8123"

    parsed = urlparse(url)

    # Check for valid scheme
    if parsed.scheme not in ("http", "https"):
        logger.warning(f"HA_URL has invalid scheme '{parsed.scheme}', expected http or https")

    # Check for hostname
    if not parsed.netloc:
        logger.warning(f"HA_URL '{url}' appears to be missing hostname")

    return url


def _validate_ha_token(token: str) -> str:
    """Validate Home Assistant token and log warnings for common issues."""
    if not token:
        logger.warning("HA_TOKEN is not set. API calls will fail without authentication.")
        return token

    # Check for placeholder tokens
    if token in _PLACEHOLDER_TOKENS:
        logger.warning(
            f"HA_TOKEN appears to be a placeholder value. "
            "Please set a valid Home Assistant Long-Lived Access Token."
        )

    # Basic sanity check - HA tokens are typically long
    if len(token) < 100:
        logger.debug("HA_TOKEN is shorter than typical HA tokens (usually 100+ chars)")

    return token


# Home Assistant configuration with validation
HA_URL: str = _validate_ha_url(os.environ.get("HA_URL", "http://localhost:8123"))
HA_TOKEN: str = _validate_ha_token(os.environ.get("HA_TOKEN", ""))

def get_ha_headers() -> dict:
    """Return the headers needed for Home Assistant API requests"""
    headers = {
        "Content-Type": "application/json",
    }
    
    # Only add Authorization header if token is provided
    if HA_TOKEN:
        headers["Authorization"] = f"Bearer {HA_TOKEN}"
    
    return headers
