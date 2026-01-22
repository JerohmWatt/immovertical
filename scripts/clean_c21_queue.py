"""
Script to clean Century21 items from scrape_queue and mark them as SCANNED
Since Century21 API already provides all data, scraping is redundant.
"""
import asyncio
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.redis_client import redis_client
from common.database import async_session_factory
from common.models import Listing

async def main():
    print("🔍 Checking scrape_queue for Century21 items...")
    await redis_client.connect()
    
    items = await redis_client.get_queue_items("scrape_queue")
    print(f"Found {len(items)} items in queue")
    
    c21_count = 0
    for item in items:
        if item.get("platform") == "century21":
            listing_id = item.get("listing_id")
            print(f"\n📦 Century21 item found: Listing ID {listing_id}")
            
            # Update listing to SCANNED
            async with async_session_factory() as session:
                listing = await session.get(Listing, listing_id)
                if listing:
                    listing.status = "SCANNED"
                    listing.is_scraped = True
                    await session.commit()
                    print(f"   ✅ Marked listing {listing_id} as SCANNED (source_id: {listing.source_id})")
                else:
                    print(f"   ⚠️ Listing {listing_id} not found in database")
            
            # Remove from queue
            await redis_client.remove_from_queue("scrape_queue", item)
            print(f"   🗑️ Removed from scrape_queue")
            c21_count += 1
    
    print(f"\n✅ Processed {c21_count} Century21 items")
    print(f"📊 Remaining items in queue: {len(items) - c21_count}")

if __name__ == "__main__":
    asyncio.run(main())
