"""
Database optimization script.
Creates missing indexes and analyzes query performance.
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from common.database import engine

# Indexes to create for optimal performance
INDEXES_TO_CREATE = [
    # Composite index for status filtering + created_at sorting (frequent query pattern)
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_listings_status_created 
    ON listing(status, created_at DESC);
    """,
    
    # Composite index for platform + status queries
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_listings_platform_status 
    ON listing(platform, status);
    """,
    
    # Index for is_scraped flag filtering
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_listings_is_scraped 
    ON listing(is_scraped) WHERE is_scraped = true;
    """,
    
    # Composite index for date range queries on updated_at
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_listings_updated_at_desc 
    ON listing(updated_at DESC);
    """,
    
    # Index for energy class filtering (frequently queried)
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_listings_energy_class 
    ON listing(energy_class) WHERE energy_class IS NOT NULL;
    """,
    
    # Composite index for price range queries with property type
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_listings_type_price 
    ON listing(property_type, price) WHERE price IS NOT NULL;
    """,
    
    # Spatial index already exists via geom column (SRID 31370)
    # But let's ensure it's properly indexed
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_listings_geom_gist 
    ON listing USING GIST(geom);
    """,
    
    # ScanHistory indexes for monitoring queries
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scan_history_batch_platform 
    ON scanhistory(batch_id, platform);
    """,
    
    """
    CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scan_history_created_desc 
    ON scanhistory(created_at DESC);
    """,
]

# Queries to analyze for performance
ANALYZE_QUERIES = [
    "SELECT COUNT(*) FROM listing WHERE status = 'PENDING';",
    "SELECT * FROM listing WHERE status = 'SCANNED' ORDER BY created_at DESC LIMIT 50;",
    "SELECT * FROM listing WHERE platform = 'immoweb' AND status IN ('PENDING', 'FAILED') LIMIT 100;",
    "SELECT * FROM listing WHERE is_scraped = true AND energy_class IS NOT NULL;",
    "SELECT * FROM scanhistory WHERE batch_id = (SELECT MAX(batch_id) FROM scanhistory);",
]


async def create_indexes():
    """Create performance indexes."""
    print("🔧 Creating database indexes...")
    
    async with engine.begin() as conn:
        for i, index_sql in enumerate(INDEXES_TO_CREATE, 1):
            try:
                print(f"\n[{i}/{len(INDEXES_TO_CREATE)}] Creating index...")
                print(f"SQL: {index_sql.strip()[:100]}...")
                
                await conn.execute(text(index_sql))
                print("✅ Success")
            except Exception as e:
                error_msg = str(e)
                if "already exists" in error_msg:
                    print("ℹ️  Index already exists, skipping")
                else:
                    print(f"❌ Error: {error_msg}")
    
    print("\n✅ All indexes processed")


async def analyze_queries():
    """Analyze query performance with EXPLAIN ANALYZE."""
    print("\n📊 Analyzing query performance...")
    
    async with engine.connect() as conn:
        for i, query in enumerate(ANALYZE_QUERIES, 1):
            print(f"\n[{i}/{len(ANALYZE_QUERIES)}] Analyzing: {query[:80]}...")
            
            try:
                # Run EXPLAIN ANALYZE
                explain_query = f"EXPLAIN ANALYZE {query}"
                result = await conn.execute(text(explain_query))
                rows = result.fetchall()
                
                print("📈 Query plan:")
                for row in rows:
                    print(f"  {row[0]}")
                    
            except Exception as e:
                print(f"❌ Error: {e}")


async def get_table_stats():
    """Get table statistics."""
    print("\n📊 Database statistics:")
    
    async with engine.connect() as conn:
        # Listing table stats
        result = await conn.execute(text("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'PENDING') as pending,
                COUNT(*) FILTER (WHERE status = 'SCANNED') as scanned,
                COUNT(*) FILTER (WHERE status = 'FAILED') as failed,
                COUNT(*) FILTER (WHERE is_scraped = true) as scraped_count
            FROM listing;
        """))
        row = result.fetchone()
        
        print("\n📋 Listing Table:")
        print(f"  Total: {row[0]}")
        print(f"  Pending: {row[1]}")
        print(f"  Scanned: {row[2]}")
        print(f"  Failed: {row[3]}")
        print(f"  Scraped: {row[4]}")
        
        # Index usage stats
        result = await conn.execute(text("""
            SELECT 
                schemaname,
                tablename,
                indexname,
                idx_scan as scans,
                idx_tup_read as tuples_read,
                idx_tup_fetch as tuples_fetched
            FROM pg_stat_user_indexes
            WHERE schemaname = 'public'
            ORDER BY idx_scan DESC
            LIMIT 10;
        """))
        
        print("\n📊 Top 10 Most Used Indexes:")
        rows = result.fetchall()
        if rows:
            for row in rows:
                print(f"  {row[2]}: {row[3]} scans, {row[4]} reads")
        else:
            print("  No index usage statistics available yet")


async def vacuum_analyze():
    """Run VACUUM ANALYZE to update statistics."""
    print("\n🧹 Running VACUUM ANALYZE...")
    
    # VACUUM cannot run in transaction, use autocommit
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT").execute(
            text("VACUUM ANALYZE listing;")
        )
        await conn.execution_options(isolation_level="AUTOCOMMIT").execute(
            text("VACUUM ANALYZE scanhistory;")
        )
    
    print("✅ VACUUM ANALYZE completed")


async def main():
    """Main optimization routine."""
    print("=" * 60)
    print("🚀 Database Optimization Script")
    print("=" * 60)
    
    try:
        # Step 1: Create indexes
        await create_indexes()
        
        # Step 2: Update statistics
        await vacuum_analyze()
        
        # Step 3: Get table stats
        await get_table_stats()
        
        # Step 4: Analyze queries (optional, can be slow)
        if "--analyze" in sys.argv:
            await analyze_queries()
        else:
            print("\nℹ️  Skipping query analysis. Run with --analyze flag to enable.")
        
        print("\n" + "=" * 60)
        print("✅ Optimization complete!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error during optimization: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
