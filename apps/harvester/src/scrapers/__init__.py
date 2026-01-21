from .immoweb import ImmowebScraper
from .century21 import Century21Scraper
from .base import BaseScraper

def get_scraper(platform: str) -> BaseScraper:
    """Factory to return the correct scraper based on platform name."""
    if platform == "immoweb":
        return ImmowebScraper()
    if platform == "century21":
        return Century21Scraper()
    # Add other platforms here...
    raise ValueError(f"No scraper found for platform: {platform}")
