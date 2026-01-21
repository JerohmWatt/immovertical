import asyncio
import logging
import os
import sys
import urllib.request
import json as std_json
from playwright.async_api import async_playwright

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from common.redis_client import redis_client
from common.database import async_session_factory
from common.models import Listing
from .scrapers import get_scraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("harvester")

async def get_browser_instance(p):
    targets = ["host.docker.internal", "192.168.31.185", "localhost"]
    for host in targets:
        try:
            url = f"http://{host}:9222/json/version"
            req = urllib.request.Request(url)
            req.add_header('Host', 'localhost:9222')
            with urllib.request.urlopen(req, timeout=2) as resp:
                ws_url = std_json.loads(resp.read().decode()).get("webSocketDebuggerUrl")
                if ws_url:
                    ws_url = ws_url.replace("localhost", host).replace("127.0.0.1", host)
                    return await p.chromium.connect_over_cdp(ws_url)
        except: continue
    return None

async def main():
    logger.info("🚀 Harvester starting...")
    await redis_client.connect()

    async with async_playwright() as p:
        browser = await get_browser_instance(p)
        if not browser: return logger.error("❌ Chrome not found.")
        
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        
        while True:
            task = await redis_client.pop_from_queue("active_scrape_queue", timeout=30)
            if not task: continue

            url, platform, listing_id = task.get("url"), task.get("platform"), task.get("listing_id")
            logger.info(f"Processing {listing_id}...")

            try:
                scraper = get_scraper(platform)
                result = await scraper.scrape(url, context)
                
                if result:
                    async with async_session_factory() as session:
                        l = await session.get(Listing, listing_id)
                        if l:
                            # MAPPING GÉNÉRIQUE
                            l.status = "SCANNED"
                            l.is_scraped = True
                            l.price = result.financial.price
                            l.description = result.description
                            l.images = result.image_urls
                            
                            # Localisation
                            l.city = result.location.city
                            l.postal_code = result.location.postal_code
                            l.latitude = result.location.latitude
                            l.longitude = result.location.longitude
                            
                            # Caractéristiques
                            l.property_type = result.property_type
                            l.property_subtype = result.property_subtype
                            l.surface_habitable = result.spatial.habitable_surface
                            l.surface_terrain = result.spatial.land_surface
                            l.rooms = result.spatial.bedroom_count # Bedrooms
                            l.room_count = result.spatial.room_count # Total rooms
                            l.bathrooms = result.spatial.bathroom_count
                            l.toilet_count = result.spatial.toilet_count
                            l.facades = result.spatial.facade_count
                            l.floor = result.spatial.floor
                            l.garden_surface = result.spatial.garden_surface
                            l.terrace_surface = result.spatial.terrace_surface
                            l.kitchen_type = result.spatial.kitchen_type
                            
                            # État et Énergie
                            l.energy_class = result.energy.energy_class
                            l.epc_score = result.energy.epc_score
                            l.epc_reference = result.energy.epc_reference or result.energy.certificate_number
                            l.co2_emissions = result.energy.co2_emissions
                            l.construction_year = result.state.construction_year
                            l.renovation_year = result.state.renovation_year
                            l.condition = result.state.condition
                            l.heating_type = result.state.heating_type
                            l.is_furnished = result.state.is_furnished
                            
                            # Financial Extras
                            l.cadastral_income = result.financial.cadastral_income
                            l.is_public_sale = result.financial.is_public_sale
                            l.is_viager = result.financial.is_viager
                            l.annuity_bouquet = result.financial.annuity_bouquet
                            l.annuity_monthly = result.financial.annuity_monthly
                            
                            l.raw_data = result.model_dump(mode='json')
                            await session.commit()
                            logger.info(f"✅ Listing {listing_id} fully enriched.")
                else:
                    logger.warning(f"⚠️ Failed to scrape {url}")
            except Exception as e:
                logger.error(f"💥 Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
