from abc import ABC, abstractmethod
from typing import Optional, List
import logging
from playwright.async_api import Page, BrowserContext, Playwright

from ..schema import UniversalListing

logger = logging.getLogger("harvester.scraper")

class BaseScraper(ABC):
    """
    Abstract Base Class for all platform scrapers.
    """
    
    def __init__(self, platform_name: str):
        self.platform_name = platform_name
        self.logger = logging.getLogger(f"harvester.scraper.{platform_name}")

    @abstractmethod
    async def scrape(self, url: str, context: BrowserContext) -> Optional[UniversalListing]:
        """
        Main method to scrape a listing URL.
        Must be implemented by subclasses.
        """
        pass

    async def _safe_get_text(self, page: Page, selector: str) -> Optional[str]:
        """Helper to safely extract text content."""
        try:
            if await page.locator(selector).count() > 0:
                return await page.locator(selector).first.inner_text()
            return None
        except Exception:
            return None
