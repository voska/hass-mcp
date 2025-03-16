import os
from typing import Optional

# Home Assistant configuration
HA_URL: str = os.environ.get("HA_URL", "http://localhost:8123")
HA_TOKEN: str = os.environ.get("HA_TOKEN", "")

def get_ha_headers() -> dict:
    """Return the headers needed for Home Assistant API requests"""
    headers = {
        "Content-Type": "application/json",
    }
    
    # Only add Authorization header if token is provided
    if HA_TOKEN:
        headers["Authorization"] = f"Bearer {HA_TOKEN}"
    
    return headers
