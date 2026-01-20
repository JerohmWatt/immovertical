import os
import redis.asyncio as redis
from typing import Optional, Any
import json
import logging

# Logger setup
logger = logging.getLogger("common.redis")

# Redis configuration from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

class RedisClient:
    """
    Async Redis client for managing task queues and caching.
    """
    def __init__(self, url: str = REDIS_URL):
        self.url = url
        self.client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Initialize the connection pool."""
        if not self.client:
            self.client = redis.from_url(self.url, decode_responses=True)
            logger.info(f"Connected to Redis at {self.url}")

    async def disconnect(self) -> None:
        """Close the connection pool."""
        if self.client:
            await self.client.close()
            self.client = None
            logger.info("Disconnected from Redis")

    async def push_to_queue(self, queue_name: str, data: Any) -> int:
        """
        Push data to a list (queue).
        Data is serialized to JSON.
        """
        if not self.client:
            await self.connect()
        
        payload = json.dumps(data)
        return await self.client.lpush(queue_name, payload)

    async def pop_from_queue(self, queue_name: str, timeout: int = 0) -> Optional[Any]:
        """
        Pop data from a list (queue) using blocking pop (BRPOP).
        Returns deserialized JSON data or None.
        """
        if not self.client:
            await self.connect()
        
        # brpop returns (queue_name, data)
        result = await self.client.brpop(queue_name, timeout=timeout)
        if result:
            _, data = result
            return json.loads(data)
        return None

    async def set_cache(self, key: str, value: Any, expire: int = 3600) -> bool:
        """Set a value in cache with an expiration time (seconds)."""
        if not self.client:
            await self.connect()
        
        payload = json.dumps(value)
        return await self.client.set(key, payload, ex=expire)

    async def get_cache(self, key: str) -> Optional[Any]:
        """Get a value from cache."""
        if not self.client:
            await self.connect()
        
        data = await self.client.get(key)
        return json.loads(data) if data else None

# Singleton instance for shared use
redis_client = RedisClient()
