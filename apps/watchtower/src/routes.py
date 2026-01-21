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
        queue_len = await redis_client.client.llen("scrape_queue")
    except Exception as e:
        logger.error(f"Error fetching redis queue: {e}")
        queue_len = "?"

    # Last scan info
    last_scan_str = engine.last_run_time.strftime('%H:%M:%S') if engine.last_run_time else "Jamais"
    new_found = engine.last_run_new_count if engine.last_run_time else 0

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

@router.get("/ui/listings")
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
                <div class="flex items-center space-x-3">
                    <a href="/listing/{l.id}" class="text-indigo-600 hover:text-indigo-800 font-bold text-xs bg-indigo-50 px-2 py-1 rounded">📄 Détails</a>
                    <a href="{l.url}" target="_blank" class="text-slate-400 hover:text-indigo-600">🔗 Lien</a>
                </div>
            </td>
            <td class="px-6 py-4 text-xs text-slate-500">{l.created_at.strftime('%H:%M:%S')}</td>
        </tr>
        """
    return HTMLResponse(content=html_rows or '<tr><td colspan="5" class="px-6 py-8 text-center text-slate-400 italic">Aucune annonce détectée.</td></tr>')

@router.post("/ui/manual-detect")
async def ui_manual_detect(url: str = Form(...), session: AsyncSession = Depends(get_session)):
    # Very basic Immoweb ID extraction for the form
    platform = "immoweb"
    id_pattern = r"/(\d+)"
    platform_id = extract_platform_id(platform, url, id_pattern)
    
    if not platform_id:
        return HTMLResponse(content='<p class="text-red-600 font-bold">❌ ID non trouvé dans l\'URL.</p>')
    
    try:
        res = await engine.process_detection(url, platform_id, platform, session)
        msg = "✅ Déjà connue" if not res else "🚀 Détectée et ajoutée"
        return HTMLResponse(content=f'<p class="text-green-600 font-bold">{msg} (ID: {platform_id})</p>')
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
