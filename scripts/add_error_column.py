import asyncio
import os
import sys

# Add common to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text
from common.database import engine

async def add_column():
    print("Adding 'last_error' column to 'listing' table...")
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TABLE listing ADD COLUMN last_error VARCHAR;"))
            print("Successfully added 'last_error' column.")
        except Exception as e:
            if "already exists" in str(e):
                print("Column 'last_error' already exists.")
            else:
                print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(add_column())
