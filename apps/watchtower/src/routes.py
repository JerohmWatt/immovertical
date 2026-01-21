import logging
import asyncio
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, desc, func
from datetime import datetime

from common.models import Listing, ScanHistory
from common.database import get_session
from common.redis_client import redis_client
from .utils import extract_platform_id
from .dependencies import templates
from . import engine

logger = logging.getLogger("watchtower.routes")

router = APIRouter()

class DetectRequest(BaseModel):
    url: str
    platform_id: str
    platform_name: str
    extra_data: Optional[Dict[str, Any]] = None

@router.post("/detect")
async def detect(request: DetectRequest, session: AsyncSession = Depends(get_session)):
    """
    Endpoint to detect a new listing.
    """
    logger.info(f"Detection request received: {request.platform_id} on {request.platform_name}")
    try:
        created = await engine.process_detection(
            request.url, 
            request.platform_id, 
            request.platform_name, 
            session,
            extra_data=request.extra_data
        )
        if created:
            return {"message": "Detected and queued"}
        else:
            return {"message": "Already known"}
    except Exception as e:
        logger.error(f"Error during detection: {str(e)}")
        await session.rollback()
        raise HTTPException(status_code=500, detail="Internal Server Error")

# --- UI ROUTES ---

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@router.get("/all", response_class=HTMLResponse)
async def all_listings_view(request: Request, session: AsyncSession = Depends(get_session)):
    statement = select(Listing).order_by(desc(Listing.created_at))
    result = await session.execute(statement)
    listings = result.scalars().all()
    return templates.TemplateResponse("all_listings.html", {"request": request, "listings": listings})

@router.get("/listing/{listing_id}", response_class=HTMLResponse)
async def listing_details(listing_id: int, request: Request, session: AsyncSession = Depends(get_session)):
    statement = select(Listing).where(Listing.id == listing_id)
    result = await session.execute(statement)
    listing = result.scalar_one_or_none()
    
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
        
    return templates.TemplateResponse("listing_details.html", {"request": request, "l": listing})

@router.get("/history", response_class=HTMLResponse)
async def scan_history_view(request: Request, session: AsyncSession = Depends(get_session)):
    # Fetch last 100 entries
    statement = select(ScanHistory).order_by(desc(ScanHistory.created_at)).limit(100)
    result = await session.execute(statement)
    entries = result.scalars().all()
    
    # Group by batch_id to show per-run results
    history = {}
    for e in entries:
        bid = e.batch_id or "legacy"
        if bid not in history:
            history[bid] = {
                "time": e.created_at,
                "platforms": {}
            }
        history[bid]["platforms"][e.platform] = {
            "count": e.new_listings_count,
            "status": e.status,
            "error": e.error_message
        }
    
    # Sort history by time descending
    sorted_history = sorted(history.values(), key=lambda x: x["time"], reverse=True)
    
    return templates.TemplateResponse("history.html", {"request": request, "history": sorted_history})

@router.get("/ui/stats")
async def ui_stats(session: AsyncSession = Depends(get_session)):
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
        pending_len = await redis_client.client.llen("scrape_queue")
        active_len = await redis_client.client.llen("active_scrape_queue")
    except Exception as e:
        logger.error(f"Error fetching redis queue: {e}")
        pending_len = "?"
        active_len = "?"

    # Last scan info
    last_scan_str = engine.last_run_time.strftime('%H:%M:%S') if engine.last_run_time else "Jamais"
    new_found = engine.last_run_new_count if engine.last_run_time else 0

    return HTMLResponse(content=f"""
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
            <p class="text-sm font-medium text-slate-500 uppercase">Annonces Totales</p>
            <p class="text-3xl font-bold">{total_count}</p>
        </div>
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
            <p class="text-sm font-medium text-slate-500 uppercase">Queue (Attente)</p>
            <p class="text-3xl font-bold text-amber-500">{pending_len}</p>
        </div>
        <div class="bg-white p-6 rounded-xl shadow-sm border border-slate-200">
            <p class="text-sm font-medium text-slate-500 uppercase">Queue (Active)</p>
            <p class="text-3xl font-bold text-indigo-600">{active_len}</p>
        </div>
    """)

@router.get("/ui/scrape-queue")
async def ui_scrape_queue():
    try:
        items = await redis_client.get_queue_items("scrape_queue")
        if not items:
            return HTMLResponse(content='<div class="p-4 text-center text-slate-400 italic">La file d\'attente est vide.</div>')
        
        html = '<div class="space-y-2">'
        for idx, item in enumerate(items):
            platform = item.get("platform", "Unknown")
            url = item.get("url", "#")
            
            html += f"""
            <div class="flex items-center justify-between bg-slate-50 p-3 rounded-lg border border-slate-100">
                <div class="flex flex-col min-w-0">
                    <span class="text-[10px] font-bold text-indigo-600 uppercase">{platform}</span>
                    <span class="text-xs truncate text-slate-600">{url}</span>
                </div>
                <button hx-post="/ui/trigger-scrape" 
                        hx-vals='{{"index": {idx}}}'
                        hx-target="#scrape-queue-container"
                        class="ml-4 bg-indigo-600 text-white text-[10px] font-bold px-3 py-1.5 rounded hover:bg-indigo-700 transition flex-shrink-0">
                    ⚡ SCRAPER
                </button>
            </div>
            """
        html += '</div>'
        return HTMLResponse(content=html)
    except Exception as e:
        return HTMLResponse(content=f'<p class="text-red-500">Erreur: {str(e)}</p>')

@router.post("/ui/trigger-scrape")
async def ui_trigger_scrape(index: int = Form(...)):
    try:
        # Get item by index
        items = await redis_client.get_queue_items("scrape_queue")
        if index >= len(items):
            return await ui_scrape_queue()
            
        item = items[index]
        
        # Move from scrape_queue to active_scrape_queue
        await redis_client.remove_from_queue("scrape_queue", item)
        await redis_client.push_to_queue("active_scrape_queue", item)
        
        # Return refreshed queue
        return await ui_scrape_queue()
    except Exception as e:
        logger.error(f"Error triggering scrape: {e}")
        return HTMLResponse(content=f'<p class="text-red-500">Erreur: {str(e)}</p>')

@router.get("/ui/scraping-status")
async def ui_scraping_status(session: AsyncSession = Depends(get_session)):
    """
    Shows what's currently being scraped and the last results.
    """
    try:
        # 1. Current Task
        current_task = await redis_client.get_cache("active_scraping_task")
        
        # 2. Last 5 Scanned/Failed listings
        statement = select(Listing).where(Listing.status.in_(["SCANNED", "FAILED", "ERROR", "SCRAPING"])).order_by(desc(Listing.updated_at)).limit(5)
        result = await session.execute(statement)
        recent_listings = result.scalars().all()
        
        html = '<div class="space-y-4">'
        
        # Section: Active
        html += '<div><h3 class="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2">⚡ En cours</h3>'
        if current_task:
            html += f"""
            <div class="bg-indigo-50 border border-indigo-100 p-3 rounded-xl flex items-center justify-between animate-pulse">
                <div class="flex flex-col min-w-0">
                    <span class="text-[10px] font-bold text-indigo-600 uppercase">{current_task.get('platform')}</span>
                    <span class="text-xs truncate text-indigo-900">{current_task.get('url')}</span>
                </div>
                <span class="text-[10px] bg-indigo-200 text-indigo-700 px-2 py-0.5 rounded-full font-bold">SCRAPING...</span>
            </div>
            """
        else:
            html += '<p class="text-xs text-slate-400 italic bg-slate-50 p-3 rounded-xl border border-dashed">Aucun scrape actif.</p>'
        html += '</div>'
        
        # Section: Recent Results
        html += '<div><h3 class="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2">🏁 Derniers résultats</h3>'
        if recent_listings:
            html += '<div class="space-y-2">'
            for l in recent_listings:
                status_class = "text-green-600 bg-green-50 border-green-100" if l.status == "SCANNED" else "text-red-600 bg-red-50 border-red-100"
                if l.status == "SCRAPING": status_class = "text-indigo-600 bg-indigo-50 border-indigo-100"
                
                price_info = f"{l.price} €" if l.price else "Pas de prix"
                surface_info = f"{l.surface_habitable} m²" if l.surface_habitable else ""
                
                error_html = ""
                if l.status in ["FAILED", "ERROR"] and l.last_error:
                    error_html = f"""
                    <div class="mt-1.5 p-1.5 bg-red-100/50 rounded text-[9px] text-red-800 font-medium italic border border-red-200">
                        ⚠ {l.last_error[:100]}...
                    </div>
                    """

                html += f"""
                <div class="bg-white border p-2.5 rounded-lg text-xs shadow-sm">
                    <div class="flex items-center justify-between">
                        <div class="flex flex-col min-w-0">
                            <div class="flex items-center space-x-2">
                                <span class="font-bold text-slate-700">{l.platform}</span>
                                <span class="text-[10px] text-slate-400 font-mono">#{l.source_id}</span>
                            </div>
                            <div class="flex items-center space-x-2 mt-0.5">
                                <span class="font-medium text-indigo-600">{price_info}</span>
                                <span class="text-slate-400">|</span>
                                <span class="text-slate-500">{surface_info}</span>
                            </div>
                        </div>
                        <span class="text-[9px] font-black uppercase px-2 py-0.5 rounded border {status_class}">{l.status}</span>
                    </div>
                    {error_html}
                </div>
                """
            html += '</div>'
        else:
            html += '<p class="text-xs text-slate-400 italic">Aucun résultat récent.</p>'
        html += '</div>'
        
        html += '</div>'
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(f"Error in scraping-status: {e}")
        return HTMLResponse(content=f'<p class="text-red-500 text-xs">Erreur: {str(e)}</p>')

@router.get("/ui/listings")
async def ui_listings(session: AsyncSession = Depends(get_session)):
    statement = select(Listing).order_by(desc(Listing.created_at)).limit(10)
    result = await session.execute(statement)
    listings = result.scalars().all()
    
    html_rows = ""
    for l in listings:
        status_color = "bg-yellow-100 text-yellow-800" if l.status == "PENDING" else "bg-green-100 text-green-800"
        if l.status in ["FAILED", "ERROR"]:
            status_color = "bg-red-100 text-red-800"
        
        error_indicator = ""
        if l.last_error:
            error_indicator = f'<div class="text-[9px] text-red-500 mt-1 italic truncate max-w-[150px]" title="{l.last_error}">⚠ {l.last_error}</div>'

        html_rows += f"""
        <tr class="border-b border-slate-50 hover:bg-slate-50/50 transition">
            <td class="px-6 py-4 font-mono text-xs text-slate-600">{l.source_id}</td>
            <td class="px-6 py-4 font-medium">{l.platform}</td>
            <td class="px-6 py-4">
                <span class="px-2 py-1 rounded-full text-[10px] font-bold uppercase {status_color}">{l.status}</span>
                {error_indicator}
            </td>
            <td class="px-6 py-4">
                <div class="flex items-center space-x-3">
                    <a href="/listing/{l.id}" class="text-indigo-600 hover:text-indigo-800 font-bold text-xs bg-indigo-50 px-2 py-1 rounded">📄 Détails</a>
                    <a href="{l.url}" target="_blank" class="text-slate-400 hover:text-indigo-600">🔗 Lien</a>
                </div>
            </td>
            <td class="px-6 py-4 text-xs text-slate-500">{l.created_at.strftime('%H:%M:%S')}</td>
        </tr>
        """
    return HTMLResponse(content=html_rows or '<tr><td colspan="5" class="px-6 py-8 text-center text-slate-400 italic">Aucune annonce détectée.</td></tr>')

@router.post("/ui/manual-scrape")
async def ui_manual_scrape(url: str = Form(...), session: AsyncSession = Depends(get_session)):
    """
    Manually push a URL to the scrape_queue for immediate processing by Harvester.
    """
    # Very basic Immoweb ID extraction for the form
    platform = "immoweb"
    if "century21" in url:
        platform = "century21"
    
    id_pattern = r"/(\d+)"
    if platform == "century21":
         # C21 IDs are often just numbers at the end or in path
         # Let's rely on standard extraction
         pass

    platform_id = extract_platform_id(platform, url, id_pattern)
    
    if not platform_id:
        return HTMLResponse(content='<p class="text-red-600 font-bold">❌ ID non trouvé dans l\'URL.</p>')
    
    try:
        # Check if exists
        statement = select(Listing).where(Listing.source_id == platform_id)
        result = await session.execute(statement)
        existing = result.scalar_one_or_none()
        
        if existing:
            # Force push to Redis even if exists
            payload = {
                "listing_id": existing.id,
                "url": url,
                "platform": existing.platform
            }
            if not redis_client.client:
                await redis_client.connect()
            await redis_client.push_to_queue("scrape_queue", payload)
            return HTMLResponse(content=f'<p class="text-blue-600 font-bold">🔄 Annonce connue (ID: {platform_id}). Forçage du scrape envoyé ! 🚀</p>')
        else:
            # New one - process_detection handles DB creation AND Redis push
            await engine.process_detection(url, platform_id, platform, session)
            return HTMLResponse(content=f'<p class="text-green-600 font-bold">🚀 Nouvelle annonce (ID: {platform_id}) détectée et envoyée au scraping !</p>')
            
    except Exception as e:
        return HTMLResponse(content=f'<p class="text-red-600 font-bold">❌ Erreur: {str(e)}</p>')

@router.post("/ui/run-scouts")
async def ui_run_scouts():
    if engine.scout_lock.locked():
        return HTMLResponse(content='<p class="text-amber-600 font-bold">⚠️ Scan déjà en cours...</p>')
    
    # Manual run ignores cooldown
    asyncio.create_task(engine.run_scouts(ignore_cooldown=True))
    return HTMLResponse(content='<p class="text-green-600 font-bold animate-bounce">📡 Scan lancé manuellement...</p>')

@router.post("/ui/clear-listings")
async def ui_clear_listings(session: AsyncSession = Depends(get_session)):
    from sqlmodel import delete
    try:
        statement = delete(Listing)
        result = await session.execute(statement)
        await session.commit()
        return HTMLResponse(content=f'<p class="text-amber-600 font-bold text-xs uppercase tracking-widest">🗑️ {result.rowcount} annonces supprimées.</p>')
    except Exception as e:
        return HTMLResponse(content=f'<p class="text-red-600 font-bold text-xs">❌ Erreur DB: {str(e)}</p>')

@router.post("/ui/clear-redis")
async def ui_clear_redis():
    try:
        if not redis_client.client:
            await redis_client.connect()
        await redis_client.client.delete("scrape_queue")
        return HTMLResponse(content='<p class="text-amber-600 font-bold text-xs uppercase tracking-widest">🧹 File Redis vidée.</p>')
    except Exception as e:
        return HTMLResponse(content=f'<p class="text-red-600 font-bold text-xs">❌ Erreur Redis: {str(e)}</p>')
