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
async def ui_scrape_queue(session: AsyncSession = Depends(get_session)):
    try:
        items = await redis_client.get_queue_items("scrape_queue")
        if not items:
            return HTMLResponse(content='<div class="p-4 text-center text-slate-400 italic">La file d\'attente est vide.</div>')
        
        # Limit to first 10 items
        display_items = items[:10]
        total_count = len(items)
        
        html = '<div class="space-y-2">'
        for idx, item in enumerate(display_items):
            platform = item.get("platform", "Unknown")
            url = item.get("url", "#")
            listing_id = item.get("listing_id")
            
            # Fetch listing details to show source_id
            source_id = "?"
            if listing_id:
                try:
                    stmt = select(Listing).where(Listing.id == listing_id)
                    result = await session.execute(stmt)
                    listing = result.scalar_one_or_none()
                    if listing:
                        source_id = listing.source_id
                except:
                    pass
            
            html += f"""
            <div class="flex items-center justify-between bg-slate-50 p-3 rounded-lg border border-slate-100">
                <div class="flex flex-col min-w-0 flex-1">
                    <div class="flex items-center space-x-2">
                        <span class="text-[10px] font-bold text-indigo-600 uppercase">{platform}</span>
                        <span class="text-[9px] text-slate-400 font-mono">#{source_id}</span>
                    </div>
                    <span class="text-xs truncate text-slate-600">{url[:60]}...</span>
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
        
        # Show count if more items
        if total_count > 10:
            html += f'<div class="mt-3 text-center text-xs text-slate-500 italic">Affichage de 10 sur {total_count} éléments en attente</div>'
        
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

@router.get("/ui/listing-row/{listing_id}")
async def ui_listing_row(listing_id: int, session: AsyncSession = Depends(get_session)):
    """
    Get a single listing row HTML (used for polling updates)
    """
    try:
        statement = select(Listing).where(Listing.id == listing_id)
        result = await session.execute(statement)
        listing = result.scalar_one_or_none()
        
        if not listing:
            return HTMLResponse(content='<tr><td colspan="6" class="px-8 py-4 text-center text-red-600">Listing not found</td></tr>')
        
        # Don't enable polling if status is final (SCANNED, FAILED, ERROR)
        enable_polling = listing.status == "SCRAPING"
        return _render_listing_row(listing, enable_polling=enable_polling)
        
    except Exception as e:
        logger.error(f"Error fetching listing row {listing_id}: {e}")
        return HTMLResponse(content=f'<tr><td colspan="6" class="px-8 py-4 text-center text-red-600">Error: {str(e)}</td></tr>')

@router.post("/ui/harvest-listing")
async def ui_harvest_listing(listing_id: int = Form(...), session: AsyncSession = Depends(get_session), request: Request = None):
    """
    Trigger harvest for a specific listing by pushing it to scrape_queue
    """
    try:
        # Get the listing
        statement = select(Listing).where(Listing.id == listing_id)
        result = await session.execute(statement)
        listing = result.scalar_one_or_none()
        
        if not listing:
            logger.error(f"Listing {listing_id} not found")
            return HTMLResponse(content='<tr><td colspan="6" class="px-8 py-4 text-center text-red-600">Listing not found</td></tr>')
        
        # Only allow harvesting FAILED or ERROR listings (not SCANNED)
        if listing.status not in ["PENDING", "FAILED", "ERROR"]:
            logger.warning(f"Listing {listing_id} is {listing.status}, not eligible for harvest")
            return _render_listing_row(listing)
        
        # Push directly to active_scrape_queue for immediate processing
        payload = {
            "listing_id": listing.id,
            "url": listing.url,
            "platform": listing.platform
        }
        
        if not redis_client.client:
            await redis_client.connect()
        
        await redis_client.push_to_queue("active_scrape_queue", payload)
        logger.info(f"Listing {listing_id} ({listing.source_id}) pushed to active_scrape_queue for immediate harvest")
        
        # Update status to SCRAPING (in progress)
        listing.status = "SCRAPING"
        listing.updated_at = datetime.now()
        session.add(listing)
        await session.commit()
        
        # Return updated row HTML with polling enabled
        return _render_listing_row(listing, enable_polling=True)
        
    except Exception as e:
        logger.error(f"Error harvesting listing {listing_id}: {e}")
        return HTMLResponse(content=f'<tr><td colspan="6" class="px-8 py-4 text-center text-red-600">Error: {str(e)}</td></tr>')

def _render_listing_row(l: Listing, enable_polling: bool = False) -> HTMLResponse:
    """Helper function to render a single listing row for the all_listings table"""
    
    # Status badge
    if l.status == "PENDING":
        status_badge = '<span class="px-3 py-1 rounded-lg text-[10px] font-black uppercase bg-amber-100 text-amber-600 border border-amber-200">En attente</span>'
    elif l.status == "SCANNED":
        status_badge = '<span class="px-3 py-1 rounded-lg text-[10px] font-black uppercase bg-emerald-100 text-emerald-600 border border-emerald-200">Moissonné</span>'
    elif l.status == "SCRAPING":
        status_badge = '<span class="px-3 py-1 rounded-lg text-[10px] font-black uppercase bg-blue-100 text-blue-600 border border-blue-200 animate-pulse">🔄 En cours</span>'
    elif l.status in ["FAILED", "ERROR"]:
        status_badge = '<span class="px-3 py-1 rounded-lg text-[10px] font-black uppercase bg-red-100 text-red-600 border border-red-200">Échec</span>'
    else:
        status_badge = f'<span class="px-3 py-1 rounded-lg text-[10px] font-black uppercase bg-indigo-100 text-indigo-600 border border-indigo-200 animate-pulse">{l.status}</span>'
    
    # Energy class badge
    energy_badge = ""
    if l.energy_class:
        color_class = ""
        if l.energy_class in ['A','B','C']:
            color_class = "bg-green-100 text-green-700"
        elif l.energy_class in ['D','E']:
            color_class = "bg-amber-100 text-amber-700"
        else:
            color_class = "bg-red-100 text-red-700"
        energy_badge = f'<span class="text-[10px] font-black px-1.5 py-0.5 rounded {color_class}">PEB {l.energy_class}</span>'
    
    # Harvest button (for PENDING, FAILED, ERROR)
    harvest_button = ""
    if l.status in ["PENDING", "FAILED", "ERROR"]:
        harvest_button = f'''
        <button hx-post="/ui/harvest-listing" 
                hx-vals='{{"listing_id": {l.id}}}'
                hx-target="closest tr"
                hx-swap="outerHTML"
                class="bg-green-600 text-white px-4 py-2 rounded-xl text-xs font-black hover:bg-green-700 transition shadow-lg shadow-green-200 uppercase tracking-widest">
            <i class="fa-solid fa-bolt mr-1"></i> Harvest
        </button>
        '''
    
    price_display = f'{l.price:,.0f}'.replace(',', ' ') + ' <span class="text-xs">€</span>' if l.price else 'N/C'
    
    # Add polling attributes if status is SCRAPING
    polling_attrs = ''
    if enable_polling or l.status == "SCRAPING":
        polling_attrs = f'hx-get="/ui/listing-row/{l.id}" hx-trigger="every 3s" hx-swap="outerHTML"'
    
    html = f'''
    <tr class="group hover:bg-indigo-50/40 transition-colors" {polling_attrs}>
        <td class="px-8 py-6">
            <div class="flex flex-col">
                <span class="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1">{l.platform}</span>
                <span class="font-mono text-xs font-bold text-indigo-600 group-hover:underline">#{l.source_id}</span>
            </div>
        </td>
        <td class="px-8 py-6">
            <div class="flex flex-col">
                <span class="font-black text-slate-900 uppercase tracking-tighter">{l.property_type or "BIEN"}</span>
                <span class="text-sm text-slate-500 font-medium italic">à {l.city or "Inconnue"}</span>
            </div>
        </td>
        <td class="px-8 py-6">
            {status_badge}
        </td>
        <td class="px-8 py-6">
            <div class="flex items-center gap-4 text-slate-600">
                <div class="flex items-center gap-1.5" title="Surface Habitable">
                    <i class="fa-solid fa-maximize text-[10px] opacity-40"></i>
                    <span class="text-sm font-bold">{f"{l.surface_habitable}m²" if l.surface_habitable else "-"}</span>
                </div>
                <div class="flex items-center gap-1.5" title="Chambres">
                    <i class="fa-solid fa-bed text-[10px] opacity-40"></i>
                    <span class="text-sm font-bold">{l.rooms if l.rooms else "-"}</span>
                </div>
                <div class="flex items-center gap-1.5" title="Label PEB">
                    {energy_badge}
                </div>
            </div>
        </td>
        <td class="px-8 py-6">
            <div class="text-lg font-black text-slate-900 tracking-tighter">
                {price_display}
            </div>
        </td>
        <td class="px-8 py-6 text-right">
            <div class="flex justify-end items-center gap-3">
                {harvest_button}
                <a href="/listing/{l.id}" class="bg-slate-900 text-white px-5 py-2 rounded-xl text-xs font-black hover:bg-indigo-600 transition shadow-lg shadow-slate-200 uppercase tracking-widest">
                    Explorer
                </a>
                <a href="{l.url}" target="_blank" class="w-10 h-10 flex items-center justify-center rounded-xl bg-slate-100 text-slate-400 hover:bg-white hover:text-indigo-600 hover:shadow-md transition-all border border-transparent hover:border-slate-200">
                    <i class="fa-solid fa-external-link"></i>
                </a>
            </div>
        </td>
    </tr>
    '''
    
    return HTMLResponse(content=html)

@router.get("/ui/scraping-status")
async def ui_scraping_status(session: AsyncSession = Depends(get_session)):
    """
    Shows what's currently being scraped and the last results.
    """
    try:
        # 1. Get active scraping tasks from active_scrape_queue
        if not redis_client.client:
            await redis_client.connect()
        active_tasks = await redis_client.get_queue_items("active_scrape_queue", 0, 4)  # Get up to 5 items
        
        # 2. Get pending tasks from scrape_queue (first 3)
        pending_tasks = await redis_client.get_queue_items("scrape_queue", 0, 2)  # Get up to 3 items
        
        # 3. Last 5 Scanned/Failed listings
        statement = select(Listing).where(Listing.status.in_(["SCANNED", "FAILED", "ERROR", "SCRAPING"])).order_by(desc(Listing.updated_at)).limit(5)
        result = await session.execute(statement)
        recent_listings = result.scalars().all()
        
        html = '<div class="space-y-4">'
        
        # Section: Active (Harvesting) - Only this one
        html += '<div><h3 class="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-2">⚡ En cours de harvest</h3>'
        if active_tasks:
            html += '<div class="space-y-2">'
            for task in active_tasks[:5]:  # Show max 5 active tasks
                # Get listing info for source_id
                listing_id = task.get('listing_id')
                source_id = '?'
                if listing_id:
                    try:
                        stmt = select(Listing).where(Listing.id == listing_id)
                        result = await session.execute(stmt)
                        listing = result.scalar_one_or_none()
                        if listing:
                            source_id = listing.source_id
                    except:
                        pass
                
                html += f"""
                <div class="bg-indigo-50 border border-indigo-100 p-2.5 rounded-xl flex items-center justify-between animate-pulse">
                    <div class="flex flex-col min-w-0">
                        <div class="flex items-center space-x-2">
                            <span class="text-[10px] font-bold text-indigo-600 uppercase">{task.get('platform', 'Unknown')}</span>
                            <span class="text-[9px] text-indigo-400 font-mono">#{source_id}</span>
                        </div>
                        <span class="text-xs truncate text-indigo-900">{task.get('url', 'N/A')[:45]}...</span>
                    </div>
                    <span class="text-[9px] bg-indigo-200 text-indigo-700 px-2 py-0.5 rounded-full font-bold">SCRAPING...</span>
                </div>
                """
            html += '</div>'
        else:
            html += '<p class="text-xs text-slate-400 italic bg-slate-50 p-3 rounded-xl border border-dashed">Aucun harvest actif</p>'
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

        # Add harvest button for PENDING items
        harvest_button = ""
        if l.status == "PENDING":
            harvest_button = f'''
                <button hx-post="/ui/harvest-listing" 
                        hx-vals='{{"listing_id": {l.id}}}'
                        hx-target="#listings-table"
                        class="text-green-600 hover:text-green-800 font-bold text-xs bg-green-50 px-2 py-1 rounded">
                    ⚡ Harvest
                </button>
            '''

        html_rows += f"""
        <tr class="border-b border-slate-50 hover:bg-slate-50/50 transition">
            <td class="px-6 py-4 font-mono text-xs text-slate-600">{l.source_id}</td>
            <td class="px-6 py-4 font-medium">{l.platform}</td>
            <td class="px-6 py-4">
                <span class="px-2 py-1 rounded-full text-[10px] font-bold uppercase {status_color}">{l.status}</span>
                {error_indicator}
            </td>
            <td class="px-6 py-4">
                <div class="flex items-center space-x-2">
                    {harvest_button}
                    <a href="/listing/{l.id}" class="text-indigo-600 hover:text-indigo-800 font-bold text-xs bg-indigo-50 px-2 py-1 rounded">📄 Détails</a>
                    <a href="{l.url}" target="_blank" class="text-slate-400 hover:text-indigo-600 text-xs">🔗</a>
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
            # Force push to Redis even if exists and update status
            payload = {
                "listing_id": existing.id,
                "url": url,
                "platform": existing.platform
            }
            if not redis_client.client:
                await redis_client.connect()
            
            # Update listing status to PENDING
            existing.status = "PENDING"
            existing.updated_at = datetime.now()
            session.add(existing)
            await session.commit()
            
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

@router.get("/harvest-history", response_class=HTMLResponse)
async def harvest_history_view(
    request: Request, 
    session: AsyncSession = Depends(get_session),
    page: int = 1,
    platform: str = None,
    status: str = None
):
    """Page d'historique des harvests avec filtres et pagination"""
    per_page = 50
    offset = (page - 1) * per_page
    
    # Build query with filters
    statement = select(Listing).where(Listing.is_scraped == True)
    
    if platform:
        statement = statement.where(Listing.platform == platform)
    if status:
        statement = statement.where(Listing.status == status)
    
    statement = statement.order_by(desc(Listing.updated_at)).limit(per_page).offset(offset)
    
    result = await session.execute(statement)
    listings = result.scalars().all()
    
    # Get total count for pagination
    count_stmt = select(func.count()).select_from(Listing).where(Listing.is_scraped == True)
    if platform:
        count_stmt = count_stmt.where(Listing.platform == platform)
    if status:
        count_stmt = count_stmt.where(Listing.status == status)
    
    total_result = await session.execute(count_stmt)
    total_count = total_result.scalar()
    total_pages = (total_count + per_page - 1) // per_page
    
    # Calculate stats
    stats_scanned = select(func.count()).select_from(Listing).where(Listing.status == "SCANNED")
    stats_failed = select(func.count()).select_from(Listing).where(Listing.status.in_(["FAILED", "ERROR"]))
    
    scanned_result = await session.execute(stats_scanned)
    failed_result = await session.execute(stats_failed)
    
    scanned_count = scanned_result.scalar()
    failed_count = failed_result.scalar()
    total_scanned = scanned_count + failed_count
    success_rate = round((scanned_count / total_scanned * 100) if total_scanned > 0 else 0, 1)
    
    stats = {
        "total_scanned": total_scanned,
        "success": scanned_count,
        "failed": failed_count,
        "success_rate": success_rate
    }
    
    return templates.TemplateResponse("harvest_history.html", {
        "request": request,
        "listings": listings,
        "stats": stats,
        "page": page,
        "total_pages": total_pages,
        "filter_platform": platform,
        "filter_status": status
    })

@router.get("/scout-urls", response_class=HTMLResponse)
async def scout_urls_view(request: Request):
    """Page listant les URLs utilisées par les scouts"""
    from .scouts import SCOUTS
    
    return templates.TemplateResponse("scout_urls.html", {
        "request": request,
        "scouts": SCOUTS
    })
