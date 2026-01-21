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

async def queue_mover():
    """
    Background task to automatically move items from scrape_queue to active_scrape_queue
    This ensures harvester always has work to do
    """
    while True:
        try:
            # Check if active queue is empty or has few items
            active_len = await redis_client.client.llen("active_scrape_queue")
            
            # Keep active queue filled with up to 5 items
            if active_len < 5:
                items_to_move = 5 - active_len
                for _ in range(items_to_move):
                    # Move one item from scrape_queue to active_scrape_queue
                    item = await redis_client.pop_from_queue("scrape_queue", timeout=0)
                    if item:
                        await redis_client.push_to_queue("active_scrape_queue", item)
                        logger.info(f"📬 Moved to active queue: {item.get('platform')} - {item.get('url', 'N/A')[:50]}")
                    else:
                        break  # No more items in scrape_queue
            
            await asyncio.sleep(5)  # Check every 5 seconds
        except Exception as e:
            logger.error(f"Error in queue_mover: {e}")
            await asyncio.sleep(10)

async def main():
    logger.info("🚀 Harvester starting...")
    await redis_client.connect()
    
    # Queue mover is disabled - use manual trigger from UI only
    # asyncio.create_task(queue_mover())
    logger.info("📬 Manual mode: Use UI buttons to trigger scraping")

    async with async_playwright() as p:
        browser = None
        context = None
        
        while True:
            # Reconnect browser if needed
            if not browser or not context:
                try:
                    logger.info("🔄 Connecting to Chrome...")
                    browser = await get_browser_instance(p)
                    if not browser:
                        logger.error("❌ Chrome not found. Retrying in 10s...")
                        await asyncio.sleep(10)
                        continue
                    context = browser.contexts[0] if browser.contexts else await browser.new_context()
                    logger.info("✅ Browser connected successfully")
                except Exception as e:
                    logger.error(f"Failed to connect browser: {e}")
                    await asyncio.sleep(10)
                    continue
            
            task = await redis_client.pop_from_queue("active_scrape_queue", timeout=30)
            if not task: continue

            url, platform, listing_id = task.get("url"), task.get("platform"), task.get("listing_id")
            logger.info(f"🎯 Processing listing {listing_id} from {platform}...")

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
                            logger.info(f"✅ Listing {listing_id} fully enriched and saved")
                        else:
                            logger.error(f"❌ Listing {listing_id} not found in database")
                else:
                    logger.warning(f"⚠️ Scraper returned empty result for listing {listing_id}")
                    # Mark as FAILED
                    async with async_session_factory() as session:
                        l = await session.get(Listing, listing_id)
                        if l:
                            l.status = "FAILED"
                            await session.commit()
                            
            except Exception as e:
                error_msg = str(e)
                logger.error(f"💥 Error processing listing {listing_id}: {error_msg}")
                
                # Mark listing as FAILED
                try:
                    async with async_session_factory() as session:
                        l = await session.get(Listing, listing_id)
                        if l:
                            l.status = "ERROR"
                            await session.commit()
                            logger.info(f"Marked listing {listing_id} as ERROR")
                except Exception as db_error:
                    logger.error(f"Failed to update listing status: {db_error}")
                
                # If browser connection error, reset for reconnection
                if "closed" in error_msg.lower() or "target" in error_msg.lower():
                    logger.warning("🔌 Browser connection lost, will reconnect on next task")
                    browser = None
                    context = None

if __name__ == "__main__":
    asyncio.run(main())
