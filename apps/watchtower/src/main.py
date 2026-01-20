import logging
import asyncio
import re
import httpx
from fastapi import FastAPI, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, desc, func
import uvicorn
import os

# Assuming 'common' is available in PYTHONPATH
from common.models import Listing
from common.database import get_session, async_session_factory
from common.redis_client import redis_client
from .scouts import SCOUTS
from .utils import extract_platform_id
from datetime import datetime, timedelta

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("watchtower")

app = FastAPI(title="Immo-Bé Watchtower - Truth Engine Sentinel")

# Scout state and safety locks
scout_lock = asyncio.Lock()
last_run_time = None
last_run_new_count = 0

# Templates configuration
# Resolve templates path relative to this file
templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
templates = Jinja2Templates(directory=templates_dir)

# Browser-like headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

class DetectRequest(BaseModel):
    url: str
    platform_id: str
    platform_name: str

async def process_detection(url: str, platform_id: str, platform_name: str, session: AsyncSession) -> bool:
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

@app.post("/detect")
async def detect(request: DetectRequest, session: AsyncSession = Depends(get_session)):
    """
    Endpoint to detect a new listing.
    """
    logger.info(f"Detection request received: {request.platform_id} on {request.platform_name}")
    try:
        created = await process_detection(request.url, request.platform_id, request.platform_name, session)
        if created:
            return {"message": "Detected and queued"}
        else:
            return {"message": "Already known"}
    except Exception as e:
        logger.error(f"Error during detection: {str(e)}")
        await session.rollback()
        raise HTTPException(status_code=500, detail="Internal Server Error")

async def process_scout_page(platform: str, scout: dict, html: str) -> int:
    """
    Extract links and IDs from a scout page and process them.
    Returns the number of new listings found.
    """
    # Extract links using Regex
    links = re.findall(scout["link_pattern"], html)
    unique_links = list(set(links))
    
    logger.info(f"Found {len(unique_links)} potential links on {platform}")

    new_count = 0
    for url in unique_links:
        # Extract platform_id from URL using our utility
        platform_id = extract_platform_id(platform, url, scout["id_pattern"])
        
        if platform_id:
            # Process each link (using a fresh session)
            async with async_session_factory() as session:
                created = await process_detection(url, platform_id, platform, session)
                if created:
                    new_count += 1
        else:
            logger.warning(f"Could not extract ID from URL: {url} (Platform: {platform})")
    
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
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30.0) as client:
                search_urls = scout.get("search_urls", [scout.get("search_url")])
                
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

@app.on_event("startup")
async def startup_event():
    """
    Start the background scouts loop on app startup.
    """
    # Initialize DB (if needed, although usually handled by migration or init_db)
    # await init_db()
    
    # Start the loop as a background task
    asyncio.create_task(scouts_loop())
    logger.info("Background scouts loop started.")

# --- UI ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/all", response_class=HTMLResponse)
async def all_listings_view(request: Request, session: AsyncSession = Depends(get_session)):
    statement = select(Listing).order_by(desc(Listing.created_at))
    result = await session.execute(statement)
    listings = result.scalars().all()
    return templates.TemplateResponse("all_listings.html", {"request": request, "listings": listings})

@app.get("/ui/stats")
async def ui_stats(session: AsyncSession = Depends(get_session)):
    global last_run_time, last_run_new_count
    
    # Total listings
    try:
        total_stmt = select(func.count()).select_from(Listing)
        total_res = await session.execute(total_stmt)
        total_count = total_res.scalar() or 0
    except Exception as e:
        logger.error(f"Error fetching total count: {e}")
        total_count = "Error"
    
    # Queue length from Redis
    try:
        if not redis_client.client:
            await redis_client.connect()
        queue_len = await redis_client.client.llen("scrape_queue")
    except Exception as e:
        logger.error(f"Error fetching redis queue: {e}")
        queue_len = "?"

    # Last scan info
    last_scan_str = last_run_time.strftime('%H:%M:%S') if last_run_time else "Jamais"
    new_found = last_run_new_count if last_run_time else 0

    return HTMLResponse(content=f"""
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
            <p class="text-sm font-medium text-slate-500 uppercase">Annonces Totales</p>
            <p class="text-3xl font-bold">{total_count}</p>
        </div>
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
            <p class="text-sm font-medium text-slate-500 uppercase">File d'attente Scrape</p>
            <p class="text-3xl font-bold text-indigo-600">{queue_len}</p>
        </div>
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
            <p class="text-sm font-medium text-slate-500 uppercase">Dernier Scan</p>
            <p class="text-lg font-semibold">{last_scan_str} <span class="text-xs font-normal text-slate-400">({new_found} trouvés)</span></p>
        </div>
    """)

@app.get("/ui/listings")
async def ui_listings(session: AsyncSession = Depends(get_session)):
    statement = select(Listing).order_by(desc(Listing.created_at)).limit(10)
    result = await session.execute(statement)
    listings = result.scalars().all()
    
    html_rows = ""
    for l in listings:
        status_color = "bg-yellow-100 text-yellow-800" if l.status == "PENDING" else "bg-green-100 text-green-800"
        html_rows += f"""
        <tr class="border-b border-slate-50 hover:bg-slate-50/50 transition">
            <td class="px-6 py-4 font-mono text-xs text-slate-600">{l.source_id}</td>
            <td class="px-6 py-4 font-medium">{l.platform}</td>
            <td class="px-6 py-4">
                <span class="px-2 py-1 rounded-full text-[10px] font-bold uppercase {status_color}">{l.status}</span>
            </td>
            <td class="px-6 py-4">
                <a href="{l.url}" target="_blank" class="text-indigo-600 hover:underline truncate block max-w-xs">🔗 Voir l'annonce</a>
            </td>
            <td class="px-6 py-4 text-xs text-slate-500">{l.created_at.strftime('%H:%M:%S')}</td>
        </tr>
        """
    return HTMLResponse(content=html_rows or '<tr><td colspan="5" class="px-6 py-8 text-center text-slate-400 italic">Aucune annonce détectée.</td></tr>')

@app.post("/ui/manual-detect")
async def ui_manual_detect(url: str = Form(...), session: AsyncSession = Depends(get_session)):
    # Very basic Immoweb ID extraction for the form
    platform = "immoweb"
    id_pattern = r"/(\d+)"
    platform_id = extract_platform_id(platform, url, id_pattern)
    
    if not platform_id:
        return HTMLResponse(content='<p class="text-red-600 font-bold">❌ ID non trouvé dans l\'URL.</p>')
    
    try:
        res = await process_detection(url, platform_id, platform, session)
        msg = "✅ Déjà connue" if res["message"] == "Already known" else "🚀 Détectée et ajoutée"
        return HTMLResponse(content=f'<p class="text-green-600 font-bold">{msg} (ID: {platform_id})</p>')
    except Exception as e:
        return HTMLResponse(content=f'<p class="text-red-600 font-bold">❌ Erreur: {str(e)}</p>')

@app.post("/ui/run-scouts")
async def ui_run_scouts():
    if scout_lock.locked():
        return HTMLResponse(content='<p class="text-amber-600 font-bold">⚠️ Scan déjà en cours...</p>')
    
    # Manual run ignores cooldown
    asyncio.create_task(run_scouts(ignore_cooldown=True))
    return HTMLResponse(content='<p class="text-green-600 font-bold animate-bounce">📡 Scan lancé manuellement...</p>')

@app.post("/ui/clear-listings")
async def ui_clear_listings(session: AsyncSession = Depends(get_session)):
    from sqlmodel import delete
    try:
        statement = delete(Listing)
        result = await session.execute(statement)
        await session.commit()
        return HTMLResponse(content=f'<p class="text-amber-600 font-bold text-xs uppercase tracking-widest">🗑️ {result.rowcount} annonces supprimées.</p>')
    except Exception as e:
        return HTMLResponse(content=f'<p class="text-red-600 font-bold text-xs">❌ Erreur DB: {str(e)}</p>')

@app.post("/ui/clear-redis")
async def ui_clear_redis():
    try:
        if not redis_client.client:
            await redis_client.connect()
        await redis_client.client.delete("scrape_queue")
        return HTMLResponse(content='<p class="text-amber-600 font-bold text-xs uppercase tracking-widest">🧹 File Redis vidée.</p>')
    except Exception as e:
        return HTMLResponse(content=f'<p class="text-red-600 font-bold text-xs">❌ Erreur Redis: {str(e)}</p>')

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
