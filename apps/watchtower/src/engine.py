import logging
import asyncio
import re
import httpx
import json
import base64
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from common.models import Listing
from common.database import async_session_factory
from common.redis_client import redis_client
from .scouts import SCOUTS
from .utils import extract_platform_id

logger = logging.getLogger("watchtower.engine")

# Scout state and safety locks
scout_lock = asyncio.Lock()
last_run_time = None
last_run_new_count = 0

# Browser-like headers (Base)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
}

async def process_detection(
    url: str, 
    platform_id: str, 
    platform_name: str, 
    session: AsyncSession,
    extra_data: dict = None
) -> bool:
    """
    Core logic to check if a listing exists, create it if not, and push to queue.
    Returns True if a new listing was created, False otherwise.
    """
    statement = select(Listing).where(Listing.source_id == platform_id)
    result = await session.execute(statement)
    existing_listing = result.scalar_one_or_none()

    if existing_listing:
        logger.info(f"Listing {platform_id} already exists in database (ID: {existing_listing.id}).")
        return False

    # Create new Listing entry
    new_listing = Listing(
        source_id=platform_id,
        platform=platform_name,
        url=url,
        status="PENDING",
        is_scraped=False
    )

    # Populate extra fields if provided
    if extra_data:
        if "price" in extra_data:
            new_listing.price = extra_data["price"]
        if "surface_habitable" in extra_data:
            new_listing.surface_habitable = extra_data["surface_habitable"]
        if "surface_terrain" in extra_data:
            new_listing.surface_terrain = extra_data["surface_terrain"]
        if "rooms" in extra_data:
            new_listing.rooms = extra_data["rooms"]
        if "description" in extra_data:
            new_listing.description = extra_data["description"]
        if "latitude" in extra_data:
            new_listing.latitude = extra_data["latitude"]
        if "longitude" in extra_data:
            new_listing.longitude = extra_data["longitude"]
        if "images" in extra_data:
            new_listing.images = extra_data["images"]
        
        # Store everything else in raw_data
        new_listing.raw_data = extra_data

    session.add(new_listing)
    await session.commit()
    await session.refresh(new_listing)

    logger.info(f"New listing created: ID {new_listing.id} for source_id {new_listing.source_id}")

    # Push to Redis scrape_queue
    payload = {
        "listing_id": new_listing.id,
        "url": new_listing.url,
        "platform": new_listing.platform
    }
    
    await redis_client.push_to_queue("scrape_queue", payload)
    logger.info(f"URL {new_listing.url} pushed to Redis 'scrape_queue'")

    return True

async def process_scout_page(platform: str, scout: dict, content: str) -> int:
    """
    Extract links and IDs from a scout page (HTML or JSON) and process them.
    Returns the number of new listings found.
    """
    new_count = 0
    processed_ids = set()
    
    if scout.get("method") == "json":
        try:
            data = json.loads(content)
            # Century 21 specific logic
            if platform == "century21":
                for item in data.get("data", []):
                    platform_id = item.get("id")
                    if not platform_id:
                        continue
                    
                    processed_ids.add(platform_id)
                    
                    # Extract extra data safely and exhaustively
                    price_data = item.get("price") or {}
                    rooms_data = item.get("rooms") or {}
                    surface_data = item.get("surface") or {}
                    habitable_data = surface_data.get("habitableSurfaceArea") or {}
                    garden_data = surface_data.get("surfaceAreaGarden") or {}
                    total_surface_data = surface_data.get("totalSurfaceArea") or {}
                    desc_data = item.get("description") or {}
                    loc_data = item.get("location") or {}
                    energy_data = item.get("energySpecifications") or {}
                    energy_score = energy_data.get("energyScore") or {}
                    energy_consumption = energy_data.get("totalEnergyConsumption") or {}
                    address_data = item.get("address") or {}
                    amenities_data = item.get("amenities") or {}
                    
                    extra = {
                        # Core fields for Listing model
                        "price": price_data.get("amount"),
                        "rooms": rooms_data.get("numberOfBedrooms"),
                        "surface_habitable": habitable_data.get("value"),
                        "surface_terrain": total_surface_data.get("value") or garden_data.get("value"),
                        "description": desc_data.get("fr") or desc_data.get("en") or desc_data.get("nl"),
                        "latitude": loc_data.get("latitude"),
                        "longitude": loc_data.get("longitude"),
                        
                        # Rich metadata for raw_data
                        "reference": item.get("reference"),
                        "type": item.get("type"),
                        "subType": item.get("subType"),
                        "condition": item.get("condition"),
                        "energy_label": energy_data.get("energyLabel"),
                        "energy_score": energy_score.get("value"),
                        "energy_total_consumption": energy_consumption.get("value"),
                        "energy_report_ref": energy_data.get("energyReportReference"),
                        "address": {
                            "city": address_data.get("city"),
                            "postal_code": address_data.get("postalCode"),
                            "street": address_data.get("street"),
                            "number": address_data.get("number"),
                            "region": address_data.get("region"),
                        },
                        "amenities": amenities_data,
                        "floor_number": item.get("floorNumber"),
                        "has_parking": item.get("hasParking"),
                        "date_posted": item.get("datePosted"),
                    }
                    
                    # Construct Image URLs
                    raw_images = item.get("images") or []
                    extra["images"] = [
                        f"https://images.prd.cloud.century21.be/api/v1/images/{img['name']}" 
                        for img in raw_images if isinstance(img, dict) and "name" in img
                    ]
                    
                    # Construct URL (using their 'properiete' typo as observed in browser)
                    city_slug = address_data.get("city", "belgium").lower().replace(" ", "-")
                    url = f"https://www.century21.be/fr/properiete/a-vendre/maison/{city_slug}/{platform_id}"
                    
                    async with async_session_factory() as session:
                        created = await process_detection(url, platform_id, platform, session, extra_data=extra)
                        if created:
                            new_count += 1
            else:
                logger.warning(f"JSON method not implemented for platform: {platform}")
        except Exception as e:
            logger.error(f"Error parsing JSON for {platform}: {str(e)}")
            
    else:
        # Hybrid Method (JSON + Regex fallback)
        if platform == "immoweb":
            try:
                # 1. Rich extraction from JSON in HTML
                json_pattern = r":results='(\[.*?\])'"
                match = re.search(json_pattern, content, re.DOTALL)
                if not match:
                    json_pattern = r':results="(\[.*?\])"'
                    match = re.search(json_pattern, content, re.DOTALL)

                if match:
                    raw_json = match.group(1).replace("&quot;", '"')
                    data = json.loads(raw_json)
                    
                    for item in data:
                        platform_id = str(item.get("id"))
                        if not platform_id:
                            continue
                        
                        # Mark as processed to avoid double counting via regex
                        processed_ids.add(platform_id)
                            
                        # Extract rich data
                        prop = item.get("property", {})
                        loc = prop.get("location", {})
                        trans = item.get("transaction", {})
                        sale = trans.get("sale", {})
                        
                        extra = {
                            "price": sale.get("price"),
                            "rooms": prop.get("bedroomCount"),
                            "surface_habitable": prop.get("netHabitableSurface"),
                            "surface_terrain": prop.get("landSurface"),
                            "latitude": loc.get("latitude"),
                            "longitude": loc.get("longitude"),
                            "description": item.get("title"),
                            "address": {
                                "city": loc.get("locality"),
                                "postal_code": loc.get("postalCode"),
                                "street": loc.get("street"),
                                "number": loc.get("number"),
                                "region": loc.get("region"),
                            },
                            "energy_label": item.get("transaction", {}).get("certificates", {}).get("epcScore"),
                            "type": prop.get("type"),
                            "subtype": prop.get("subtype"),
                        }
                        
                        media = item.get("media", {})
                        images = media.get("pictures", [])
                        if images:
                            extra["images"] = [img.get("mediumUrl") or img.get("smallUrl") for img in images if isinstance(img, dict)]

                        # Construct URL
                        type_label = prop.get("type", "maison").lower()
                        subtype_label = prop.get("subtype", "a-vendre").lower()
                        locality = loc.get("locality", "belgique").lower().replace(" ", "-")
                        postcode = loc.get("postalCode", "0000")
                        url = f"https://www.immoweb.be/fr/annonce/{type_label}/{subtype_label}/{locality}/{postcode}/{platform_id}"
                        
                        async with async_session_factory() as session:
                            created = await process_detection(url, platform_id, platform, session, extra_data=extra)
                            if created:
                                new_count += 1
                    
                    logger.info(f"JSON extraction for {platform} processed {len(data)} items.")
                
            except Exception as e:
                logger.error(f"Error during {platform} rich extraction: {str(e)}")

        # 2. Always fallback/complement with Regex to catch everything else
        links = re.findall(scout["link_pattern"], content)
        unique_links = list(set(links))
        
        logger.info(f"Scanning {len(unique_links)} links via regex for {platform}")

        for url in unique_links:
            platform_id = extract_platform_id(platform, url, scout["id_pattern"])
            
            # Process only if not already handled by JSON extraction
            if platform_id and platform_id not in processed_ids:
                async with async_session_factory() as session:
                    created = await process_detection(url, platform_id, platform, session)
                    if created:
                        new_count += 1
    
    return new_count

async def run_scouts(ignore_cooldown: bool = False):
    """
    Scan all defined scouts for new listings.
    Enforces a cooldown for automatic runs but allows manual override.
    Always prevents concurrent runs.
    """
    global last_run_time, last_run_new_count
    
    if scout_lock.locked():
        logger.warning("Scout scan already in progress. Ignoring request.")
        return

    async with scout_lock:
        now = datetime.now()
        
        # Cooldown check only if not ignored (manual run)
        if not ignore_cooldown and last_run_time and (now - last_run_time) < timedelta(minutes=55):
            wait_time = timedelta(minutes=60) - (now - last_run_time)
            logger.warning(f"Cooldown active. Please wait {wait_time.total_seconds() / 60:.1f} minutes.")
            return

        logger.info(f"Starting scouts scan... {'(Manual override)' if ignore_cooldown else ''}")
        last_run_time = now
        total_new = 0
        
        for platform, scout in SCOUTS.items():
            # Use a fresh client per platform to avoid session/cookie tracking issues
            platform_headers = HEADERS.copy()
            if platform == "century21":
                platform_headers["Origin"] = "https://www.century21.be"
                platform_headers["Referer"] = "https://www.century21.be/"
            elif platform == "immoweb":
                platform_headers["Origin"] = "https://www.immoweb.be"
                platform_headers["Referer"] = "https://www.immoweb.be/"
                # Immoweb is sensitive to Accept header
                platform_headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"

            async with httpx.AsyncClient(headers=platform_headers, follow_redirects=True, timeout=30.0) as client:
                search_urls = scout.get("search_urls", [])
                
                # Special handling for Century 21 dynamic filter
                if platform == "century21":
                    # Generate dynamic filter for "yesterday" (la veille)
                    yesterday = datetime.now() - timedelta(days=1)
                    iso_date = yesterday.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                    
                    c21_filter = {
                        "bool": {
                            "filter": {
                                "bool": {
                                    "must": [
                                        {"bool": {"should": [
                                            {"match": {"address.countryCode": "be"}},
                                            {"match": {"address.countryCode": "fr"}},
                                            {"match": {"address.countryCode": "it"}},
                                            {"match": {"address.countryCode": "lu"}}
                                        ]}},
                                        {"match": {"listingType": "FOR_SALE"}},
                                        {"range": {"price.amount": {"lte": 300000}}},
                                        {"bool": {"should": {"match": {"type": "HOUSE"}}}},
                                        {"range": {"creationDate": {"lte": iso_date}}}
                                    ]
                                }
                            }
                        }
                    }
                    filter_b64 = base64.b64encode(json.dumps(c21_filter, separators=(',', ':')).encode()).decode()
                    
                    # Update the URL with the fresh filter
                    base_api = "https://api.prd.cloud.century21.be/api/v2/properties"
                    params = {
                        "facets": "elevator,condition,floorNumber,garden,habitableSurfaceArea,listingType,numberOfBedrooms,parking,price,subType,surfaceAreaGarden,swimmingPool,terrace,totalSurfaceArea,type",
                        "filter": filter_b64,
                        "pageSize": "24",
                        "sort": "-creationDate"
                    }
                    # Construct URL with params
                    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
                    search_urls = [f"{base_api}?{query_string}"]

                for url in search_urls:
                    if not url:
                        continue
                    try:
                        logger.info(f"Scanning {platform} at {url}...")
                        response = await client.get(url)
                        
                        if response.status_code == 403:
                            logger.error(f"Access denied (403) for {platform} at {url}. Anti-bot triggered.")
                            continue
                            
                        response.raise_for_status()
                        new_on_page = await process_scout_page(platform, scout, response.text)
                        total_new += new_on_page
                        
                        # Small random delay between URLs of the same platform
                        await asyncio.sleep(2.0)

                    except Exception as e:
                        logger.error(f"Error scanning {platform} at {url}: {str(e)}")

        last_run_new_count = total_new
        logger.info(f"Scouts scan completed. {total_new} new listings found.")

async def scouts_loop():
    """
    Repeated task to run scouts every hour.
    """
    while True:
        try:
            await run_scouts()
        except Exception as e:
            logger.error(f"Critical error in scouts loop: {str(e)}")
        
        logger.info("Scouts loop waiting for 1 hour...")
        await asyncio.sleep(3600)  # 3600 seconds = 1 hour
