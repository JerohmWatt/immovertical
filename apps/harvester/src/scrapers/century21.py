import json
import re
import asyncio
import random
from typing import Optional
from playwright.async_api import BrowserContext
from playwright_stealth import stealth_async

from .base import BaseScraper
from ..schema import (
    UniversalListing, 
    FinancialData, 
    SpatialData, 
    EnergyData, 
    StateData, 
    LocationData
)

class Century21Scraper(BaseScraper):
    """
    Scraper implementation for Century21 using their internal JSON data.
    """
    
    def __init__(self):
        super().__init__("century21")

    async def scrape(self, url: str, context: BrowserContext) -> Optional[UniversalListing]:
        page = await context.new_page()
        await stealth_async(page)
        try:
            self.logger.info(f"Navigating to {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Anti-bot
            title = await page.title()
            if "century21.be" == title or "Robot" in title:
                self.logger.info("Detected possible bot challenge (title='century21.be'). Waiting 10s...")
                await asyncio.sleep(10)

            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except: pass

            title = await page.title()
            self.logger.info(f"Page title: {title}")

            if "Forbidden" in title or "Attention" in title or "Access Denied" in title or "Robot" in title:
                self.logger.error(f"Possible bot detection on {url}. Title: {title}")
                return None

            content = await page.content()
            raw_data = None
            
            # Pattern 1: __NEXT_DATA__
            next_data_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', content, re.DOTALL)
            if next_data_match:
                try:
                    full_json = json.loads(next_data_match.group(1))
                    self.logger.info("✅ Found __NEXT_DATA__")
                    props = full_json.get("props", {})
                    page_props = props.get("pageProps", {})
                    
                    # Try various paths for Century21 data
                    raw_data = page_props.get("listing")
                    if not raw_data:
                        raw_data = page_props.get("initialState", {}).get("listing", {}).get("data")
                    if not raw_data:
                        raw_data = props.get("initialProps", {}).get("listing")
                    if not raw_data:
                        # Try dehydratedState (Next.js hydration)
                        dehydrated = page_props.get("dehydratedState", {})
                        queries = dehydrated.get("queries", [])
                        for q in queries:
                            if isinstance(q, dict):
                                state_data = q.get("state", {})
                                listing_data = state_data.get("data")
                                if listing_data and isinstance(listing_data, dict):
                                    raw_data = listing_data
                                    break
                    
                    if raw_data:
                        self.logger.info(f"✅ Extracted listing data with {len(raw_data)} keys")
                    else:
                        self.logger.warning(f"⚠️ Found __NEXT_DATA__ but no listing. Keys in pageProps: {list(page_props.keys())}")
                        
                except Exception as e:
                    self.logger.warning(f"Failed to parse __NEXT_DATA__: {e}")
            else:
                self.logger.warning("⚠️ No __NEXT_DATA__ script tag found")

            if not raw_data:
                # Pattern 2: Global variable fallback
                match = re.search(r'window\.__listing_data__\s*=\s*({.*?});', content, re.DOTALL)
                if match:
                    try:
                        raw_data = json.loads(match.group(1))
                        self.logger.info("✅ Found window.__listing_data__")
                    except: pass

            if not raw_data:
                # Pattern 3: Try to extract from window object via JS
                try:
                    raw_data = await page.evaluate("""() => {
                        // Try window.__NEXT_DATA__
                        if (window.__NEXT_DATA__) {
                            const props = window.__NEXT_DATA__.props || {};
                            const pageProps = props.pageProps || {};
                            return pageProps.listing || pageProps.initialState?.listing?.data || props.initialProps?.listing;
                        }
                        // Try any global listing variable
                        if (window.listing) return window.listing;
                        if (window.__listing) return window.__listing;
                        return null;
                    }""")
                    if raw_data:
                        self.logger.info("✅ Extracted via window.evaluate")
                except Exception as e:
                    self.logger.warning(f"Failed to evaluate JS: {e}")

            if not raw_data:
                self.logger.error(f"Could not extract Century21 payload. Length: {len(content)}")
                # Save HTML for debugging
                if len(content) < 50000:
                    with open("/tmp/c21_debug.html", "w", encoding="utf-8") as f:
                        f.write(content)
                    self.logger.info("💾 Saved debug HTML to /tmp/c21_debug.html")
                return None

            return self._parse_payload(raw_data, url)

        except Exception as e:
            self.logger.error(f"Failed to scrape {url}: {e}")
            return None
        finally:
            await page.close()

    def _parse_payload(self, data: dict, url: str) -> UniversalListing:
        """
        Maps Century21 raw JSON to UniversalListing schema.
        """
        if not isinstance(data, dict):
             raise ValueError(f"Expected dict for data, got {type(data)}")

        # Century21 structure (estimated based on previous JSON extraction)
        address_data = data.get("address", {}) or {}
        energy_data = data.get("energy", {}) or {}
        
        # Financial
        price_data = data.get("price", {}) or {}
        financial = FinancialData(
            price=price_data.get("amount"),
            cadastral_income=data.get("cadastralIncome"),
        )

        # Spatial
        spatial = SpatialData(
            habitable_surface=data.get("netHabitableSurface"),
            land_surface=data.get("landSurface"),
            bedroom_count=data.get("bedroomCount"),
            bathroom_count=data.get("bathroomCount"),
            room_count=data.get("roomCount"),
            has_garden=bool(data.get("hasGarden")),
            has_terrace=bool(data.get("hasTerrace")),
            facade_count=data.get("facadeCount")
        )

        # Energy
        energy_score = energy_data.get("primaryEnergyConsumption", {}) or {}
        energy = EnergyData(
            epc_score=energy_score.get("value"),
            energy_class=energy_data.get("energyLabel"),
            certificate_number=energy_data.get("energyReportReference")
        )
        
        # State
        state = StateData(
            construction_year=data.get("constructionYear"),
            condition=data.get("condition"),
        )

        # Location
        location = LocationData(
            street=address_data.get("street"),
            number=address_data.get("number"),
            postal_code=address_data.get("postalCode"),
            city=address_data.get("city"),
            latitude=address_data.get("latitude"),
            longitude=address_data.get("longitude"),
            country=address_data.get("countryCode", "BE").upper()
        )

        # Images
        raw_images = data.get("images") or []
        img_list = []
        for img in raw_images:
            if isinstance(img, dict) and "name" in img:
                img_list.append(f"https://images.prd.cloud.century21.be/api/v1/images/{img['name']}")
        
        source_id = str(data.get("id"))
        
        return UniversalListing(
            source_platform="century21",
            source_id=source_id,
            url=url,
            title=data.get("title") or f"Bien Century21 {source_id}",
            description=data.get("description"),
            property_type=data.get("type", "UNKNOWN"),
            property_subtype=data.get("subType"),
            image_urls=img_list,
            financial=financial,
            spatial=spatial,
            energy=energy,
            state=state,
            location=location,
            raw_payload=data
        )
