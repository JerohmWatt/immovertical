import logging
import asyncio
from fastapi import FastAPI
import uvicorn

from .routes import router
from .engine import scouts_loop

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("watchtower")

app = FastAPI(title="Immo-Bé Watchtower - Truth Engine Sentinel")

# Include routes
app.include_router(router)

@app.on_event("startup")
async def startup_event():
    """
    Start the background scouts loop on app startup.
    """
    # Start the loop as a background task
    asyncio.create_task(scouts_loop())
    logger.info("Background scouts loop started.")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
