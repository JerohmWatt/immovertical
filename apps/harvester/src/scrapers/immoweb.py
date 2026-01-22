import json
import re
import asyncio
from typing import Optional
from playwright.async_api import BrowserContext
from .base import BaseScraper
from ..schema import (
    UniversalListing, FinancialData, SpatialData, 
    EnergyData, StateData, LocationData
)

class ImmowebScraper(BaseScraper):
    def __init__(self):
        super().__init__("immoweb")

    async def scrape(self, url: str, context: BrowserContext) -> Optional[UniversalListing]:
        page = await context.new_page()
        try:
            self.logger.info(f"🚀 [Immoweb] Navigation : {url}")
            await page.goto(url, wait_until="load", timeout=60000)
            await asyncio.sleep(2)
            
            raw_data = await self._extract_json_logic(page)
            if not raw_data or not raw_data.get("classified"):
                return None

            return self._parse_payload(raw_data["classified"], url)
        except Exception as e:
            self.logger.error(f"💥 Erreur: {e}")
            return None
        finally:
            await page.close()

    async def _extract_json_logic(self, page) -> Optional[dict]:
        try:
            return await page.evaluate("""() => {
                const w = window;
                const c = (w.__INITIAL_STATE__ && w.__INITIAL_STATE__.classified) ? w.__INITIAL_STATE__.classified : (w.classified || w.__INITIAL_STATE__);
                return c ? { classified: c } : null;
            }""")
        except: return None

    def _parse_payload(self, data: dict, url: str) -> UniversalListing:
        p = data.get("property", {}) or {}
        t = data.get("transaction", {}) or {}
        sale = t.get("sale", {}) or {}
        cert = t.get("certificates", {}) or {}
        loc = p.get("location", {}) or {}
        b = p.get("building", {}) or {}
        energy = p.get("energy", {}) or {}
        annuity = sale.get("annuity", {}) or {}
        
        # Gestion spéciale Prix (Viager, Public Sale, etc.)
        price = sale.get("price") or (data.get("price") or {}).get("mainValue")
        
        return UniversalListing(
            source_platform="immoweb",
            source_id=f"IMMOWEB-{data.get('id')}",
            url=url,
            title=p.get("title"),
            description=p.get("description"),
            property_type=p.get("type"),
            property_subtype=p.get("subtype"),
            image_urls=[pic["largeUrl"] for pic in (data.get("media") or {}).get("pictures", []) if pic and isinstance(pic, dict) and "largeUrl" in pic],
            financial=FinancialData(
                price=price,
                cadastral_income=sale.get("cadastralIncome"),
                is_public_sale=bool(t.get("isPublicSale")),
                is_viager=bool(sale.get("isViager")),
                annuity_bouquet=annuity.get("bouquet"),
                annuity_monthly=annuity.get("monthlyAmount")
            ),
            spatial=SpatialData(
                habitable_surface=p.get("netHabitableSurface"),
                land_surface=(p.get("land") or {}).get("surface") or p.get("landSurface"),
                bedroom_count=p.get("bedroomCount"),
                bathroom_count=p.get("bathroomCount"),
                toilet_count=p.get("toiletCount"),
                room_count=p.get("roomCount"),
                kitchen_type=(p.get("kitchen") or {}).get("type"),
                has_garden=bool(p.get("hasGarden")),
                garden_surface=p.get("gardenSurface"),
                has_terrace=bool(p.get("hasTerrace")),
                terrace_surface=p.get("terraceSurface"),
                floor=p.get("floor"),
                facade_count=(b.get("facadeCount"))
            ),
            energy=EnergyData(
                epc_score=cert.get("primaryEnergyConsumptionPerSqm"),
                energy_class=cert.get("epcScore"),
                certificate_number=cert.get("reportNumber"),
                co2_emissions=cert.get("co2Emissions"),
                epc_reference=cert.get("epcReference")
            ),
            state=StateData(
                construction_year=b.get("constructionYear"),
                renovation_year=b.get("renovationYear"),
                condition=b.get("condition"),
                heating_type=energy.get("heatingType"),
                is_furnished=bool(sale.get("isFurnished"))
            ),
            location=LocationData(
                street=loc.get("street"),
                number=loc.get("number"),
                postal_code=loc.get("postalCode") or data.get("zip"),
                city=loc.get("locality") or data.get("city"),
                latitude=loc.get("latitude"),
                longitude=loc.get("longitude")
            ),
            raw_payload=data
        )
