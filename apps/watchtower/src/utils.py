import re
import logging
from typing import Optional

logger = logging.getLogger("watchtower.utils")

def extract_platform_id(platform: str, url: str, pattern: str) -> Optional[str]:
    """
    Extract the platform-specific ID from a URL.
    For Immoweb, the ID is typically the last numeric part of the path.
    """
    try:
        matches = re.findall(pattern, url)
        if not matches:
            return None
        
        # For Immoweb, if multiple matches (like postcode + ID), the ID is usually the last one
        if platform == "immoweb":
            return matches[-1]
        
        return matches[0]
    except Exception as e:
        logger.error(f"Error extracting ID for {platform} from {url}: {e}")
        return None
