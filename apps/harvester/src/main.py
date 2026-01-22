import asyncio
import logging
import os
import sys
import urllib.request
import json as std_json
from playwright.async_api import async_playwright, Browser, BrowserContext
from typing import Optional, Dict, Any
from datetime import datetime
import random

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from common.redis_client import redis_client
from common.database import async_session_factory
from common.models import Listing
from .scrapers import get_scraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("harvester")

# Configuration
MAX_WORKERS = int(os.getenv("HARVESTER_WORKERS", "3"))
MAX_RETRY_COUNT = int(os.getenv("HARVESTER_MAX_RETRIES", "5"))
SCRAPE_TIMEOUT = int(os.getenv("HARVESTER_TIMEOUT", "120"))  # seconds
BROWSER_RECONNECT_DELAY = 10

async def get_browser_instance(p) -> Optional[Browser]:
    """Connect to Chrome with retry logic for multiple hosts."""
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
                    browser = await p.chromium.connect_over_cdp(ws_url)
                    logger.info(f"✅ Connected to Chrome at {host}")
                    return browser
        except Exception as e:
            logger.debug(f"Failed to connect to Chrome at {host}: {e}")
            continue
    return None

async def smart_delay(base: float = 2.0, jitter: float = 1.0):
    """Smart delay with jitter to avoid anti-bot detection."""
    actual_delay = base + random.uniform(-jitter, jitter)
    await asyncio.sleep(max(0.1, actual_delay))

async def should_retry(error: Exception, retry_count: int) -> bool:
    """
    Determine if an error is retriable.
    
    Retriable errors: Network issues, timeouts, temporary blocks (403, 503)
    Non-retriable: 404, parsing errors on valid responses
    """
    error_str = str(error).lower()
    
    # Non-retriable errors
    if "404" in error_str or "not found" in error_str:
        return False
    if "invalid" in error_str or "parsing" in error_str:
        return False
    
    # Retriable errors (network, timeout, anti-bot)
    if any(keyword in error_str for keyword in ["timeout", "connection", "403", "503", "closed", "target"]):
        return retry_count < MAX_RETRY_COUNT
    
    # Default: retry if under limit
    return retry_count < MAX_RETRY_COUNT

def calculate_retry_delay(retry_count: int, base: float = 5.0, max_delay: float = 300.0) -> float:
    """Calculate exponential backoff delay with jitter."""
    delay = min(base * (2 ** retry_count), max_delay)
    jitter = delay * 0.2  # 20% jitter
    return delay + random.uniform(-jitter, jitter)

async def process_scrape_task(
    task: Dict[str, Any], 
    context: BrowserContext,
    session
) -> bool:
    """
    Process a single scrape task.
    Returns True on success, False on failure.
    """
    url = task.get("url")
    platform = task.get("platform")
    listing_id = task.get("listing_id")
    retry_count = task.get("retry_count", 0)
    
    logger.info(f"🎯 Processing listing {listing_id} from {platform} (attempt {retry_count + 1})")
    
    try:
        # Add smart delay to avoid anti-bot
        await smart_delay(base=1.0, jitter=0.5)
        
        # Apply timeout to scrape operation
        scraper = get_scraper(platform)
        result = await asyncio.wait_for(
            scraper.scrape(url, context),
            timeout=SCRAPE_TIMEOUT
        )
        
        if result:
            # Update listing with scraped data
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
                l.rooms = result.spatial.bedroom_count
                l.room_count = result.spatial.room_count
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
                l.last_error = None  # Clear previous errors
                
                await session.commit()
                logger.info(f"✅ Listing {listing_id} fully enriched and saved")
                return True
            else:
                logger.error(f"❌ Listing {listing_id} not found in database")
                return False
        else:
            logger.warning(f"⚠️ Scraper returned empty result for listing {listing_id}")
            raise ValueError("Empty scrape result")
            
    except asyncio.TimeoutError:
        error_msg = f"Timeout after {SCRAPE_TIMEOUT}s"
        logger.error(f"⏱️ {error_msg} for listing {listing_id}")
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"💥 Error processing listing {listing_id}: {error_msg}")
        raise

async def handle_scrape_failure(
    task: Dict[str, Any],
    error: Exception,
    session
):
    """Handle scrape failure with retry logic."""
    listing_id = task.get("listing_id")
    retry_count = task.get("retry_count", 0)
    error_msg = str(error)
    
    # Update listing with error
    try:
        l = await session.get(Listing, listing_id)
        if l:
            l.last_error = error_msg[:500]  # Truncate long errors
            
            if await should_retry(error, retry_count):
                # Schedule retry
                retry_count += 1
                delay = calculate_retry_delay(retry_count)
                
                l.status = "PENDING"  # Back to pending for retry
                await session.commit()
                
                logger.warning(
                    f"🔄 Scheduling retry {retry_count}/{MAX_RETRY_COUNT} for listing {listing_id} "
                    f"in {delay:.1f}s: {error_msg[:100]}"
                )
                
                # Re-queue with incremented retry count
                retry_task = {**task, "retry_count": retry_count}
                await asyncio.sleep(delay)
                await redis_client.push_to_queue("active_scrape_queue", retry_task)
            else:
                # Max retries reached or non-retriable error
                l.status = "FAILED"
                await session.commit()
                logger.error(
                    f"❌ Listing {listing_id} marked as FAILED after {retry_count} retries: {error_msg[:100]}"
                )
    except Exception as db_error:
        logger.error(f"Failed to update listing status: {db_error}")

async def worker(worker_id: int, p):
    """
    Worker coroutine that processes scrape tasks.
    Each worker has its own browser context to avoid interference.
    """
    logger.info(f"🔧 Worker {worker_id} starting...")
    browser: Optional[Browser] = None
    context: Optional[BrowserContext] = None
    reconnect_attempts = 0
    max_reconnect_attempts = 5
    
    while True:
        try:
            # Ensure browser connection
            if not browser or not context:
                if reconnect_attempts >= max_reconnect_attempts:
                    logger.error(f"Worker {worker_id}: Max reconnect attempts reached, waiting 60s...")
                    await asyncio.sleep(60)
                    reconnect_attempts = 0
                
                try:
                    logger.info(f"Worker {worker_id}: Connecting to Chrome...")
                    browser = await get_browser_instance(p)
                    if not browser:
                        reconnect_attempts += 1
                        logger.warning(f"Worker {worker_id}: Chrome not found, retry {reconnect_attempts}/{max_reconnect_attempts}")
                        await asyncio.sleep(BROWSER_RECONNECT_DELAY)
                        continue
                    
                    context = browser.contexts[0] if browser.contexts else await browser.new_context()
                    reconnect_attempts = 0  # Reset on success
                    logger.info(f"✅ Worker {worker_id}: Browser connected")
                except Exception as e:
                    reconnect_attempts += 1
                    logger.error(f"Worker {worker_id}: Browser connection failed: {e}")
                    await asyncio.sleep(BROWSER_RECONNECT_DELAY)
                    continue
            
            # Pop task from queue (non-blocking with timeout)
            task = await redis_client.pop_from_queue("active_scrape_queue", timeout=30)
            if not task:
                # No tasks, wait a bit
                await asyncio.sleep(5)
                continue
            
            # Process task in a database session
            async with async_session_factory() as session:
                try:
                    success = await process_scrape_task(task, context, session)
                    if not success:
                        await handle_scrape_failure(task, Exception("Processing failed"), session)
                except Exception as e:
                    await handle_scrape_failure(task, e, session)
                    
                    # If browser error, reset connection
                    error_str = str(e).lower()
                    if any(keyword in error_str for keyword in ["closed", "target", "browser", "context"]):
                        logger.warning(f"Worker {worker_id}: Browser error detected, resetting connection")
                        browser = None
                        context = None
                        
        except asyncio.CancelledError:
            logger.info(f"Worker {worker_id} cancelled, shutting down...")
            break
        except Exception as e:
            logger.error(f"Worker {worker_id} unexpected error: {e}")
            await asyncio.sleep(5)  # Prevent tight error loop

async def main():
    logger.info(f"🚀 Harvester starting with {MAX_WORKERS} workers...")
    logger.info(f"⚙️ Config: MAX_RETRY={MAX_RETRY_COUNT}, TIMEOUT={SCRAPE_TIMEOUT}s")
    
    await redis_client.connect()
    logger.info("✅ Redis connected")

    async with async_playwright() as p:
        # Create worker tasks
        workers = [
            asyncio.create_task(worker(i, p))
            for i in range(MAX_WORKERS)
        ]
        
        logger.info(f"✅ {MAX_WORKERS} workers started")
        
        # Wait for workers (runs indefinitely)
        try:
            await asyncio.gather(*workers)
        except KeyboardInterrupt:
            logger.info("Shutting down workers...")
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

if __name__ == "__main__":
    asyncio.run(main())
