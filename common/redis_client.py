import os
import redis.asyncio as redis
from typing import Optional, Any
import json
import logging
import asyncio
from datetime import datetime, timedelta
from functools import wraps

# Logger setup
logger = logging.getLogger("common.redis")

# Redis configuration from config or environment
try:
    from .config import config as app_config
    REDIS_URL = app_config.redis.url
    SOCKET_TIMEOUT = app_config.redis.socket_timeout
    SOCKET_CONNECT_TIMEOUT = app_config.redis.socket_connect_timeout
    HEALTH_CHECK_INTERVAL = app_config.redis.health_check_interval
    CIRCUIT_BREAKER_THRESHOLD = app_config.redis.circuit_breaker_threshold
    CIRCUIT_BREAKER_TIMEOUT = app_config.redis.circuit_breaker_timeout
except ImportError:
    # Fallback
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    SOCKET_TIMEOUT = int(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))
    SOCKET_CONNECT_TIMEOUT = int(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", "5"))
    HEALTH_CHECK_INTERVAL = int(os.getenv("REDIS_HEALTH_CHECK_INTERVAL", "30"))
    CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("REDIS_CIRCUIT_BREAKER_THRESHOLD", "5"))
    CIRCUIT_BREAKER_TIMEOUT = int(os.getenv("REDIS_CIRCUIT_BREAKER_TIMEOUT", "60"))

class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open."""
    pass

class CircuitBreaker:
    """Simple circuit breaker pattern for Redis operations."""
    def __init__(self, failure_threshold: int = CIRCUIT_BREAKER_THRESHOLD, recovery_timeout: int = CIRCUIT_BREAKER_TIMEOUT):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def record_success(self):
        """Reset circuit breaker on success."""
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_failure_time = None
    
    def record_failure(self):
        """Record a failure and potentially open the circuit."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.error(f"Circuit breaker OPEN after {self.failure_count} failures")
    
    def can_attempt(self) -> bool:
        """Check if we should attempt the operation."""
        if self.state == "CLOSED":
            return True
        
        if self.state == "OPEN":
            # Check if recovery timeout has passed
            if self.last_failure_time:
                elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if elapsed >= self.recovery_timeout:
                    self.state = "HALF_OPEN"
                    logger.info("Circuit breaker entering HALF_OPEN state")
                    return True
            return False
        
        # HALF_OPEN state - allow one attempt
        return True

def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 30.0):
    """Decorator for exponential backoff retry logic."""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(self, *args, **kwargs)
                except (redis.ConnectionError, redis.TimeoutError, OSError) as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        # Exponential backoff with jitter
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        jitter = delay * 0.1  # 10% jitter
                        import random
                        actual_delay = delay + random.uniform(-jitter, jitter)
                        
                        logger.warning(
                            f"Redis operation failed (attempt {attempt + 1}/{max_retries + 1}), "
                            f"retrying in {actual_delay:.2f}s: {e}"
                        )
                        await asyncio.sleep(actual_delay)
                    else:
                        logger.error(f"Redis operation failed after {max_retries + 1} attempts: {e}")
            
            raise last_exception
        return wrapper
    return decorator

class RedisClient:
    """
    Async Redis client for managing task queues and caching.
    Features: Circuit breaker, exponential backoff, fallback queue.
    """
    def __init__(self, url: str = REDIS_URL):
        self.url = url
        self.client: Optional[redis.Redis] = None
        self.circuit_breaker = CircuitBreaker()
        self._fallback_queue_path = "/tmp/redis_fallback_queue.json"
        self._connection_lock = asyncio.Lock()

    @retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=30.0)
    async def connect(self) -> None:
        """Initialize the connection pool with retry logic."""
        async with self._connection_lock:
            if not self.client:
                if not self.circuit_breaker.can_attempt():
                    raise CircuitBreakerOpen("Circuit breaker is OPEN, Redis unavailable")
                
                try:
                    self.client = redis.from_url(
                        self.url, 
                        decode_responses=True,
                        socket_connect_timeout=SOCKET_CONNECT_TIMEOUT,
                        socket_timeout=SOCKET_TIMEOUT,
                        retry_on_timeout=True,
                        health_check_interval=HEALTH_CHECK_INTERVAL
                    )
                    # Test connection
                    await self.client.ping()
                    self.circuit_breaker.record_success()
                    logger.info(f"✅ Connected to Redis at {self.url}")
                except Exception as e:
                    self.circuit_breaker.record_failure()
                    self.client = None
                    raise

    async def disconnect(self) -> None:
        """Close the connection pool."""
        async with self._connection_lock:
            if self.client:
                try:
                    await self.client.close()
                except Exception as e:
                    logger.warning(f"Error closing Redis connection: {e}")
                finally:
                    self.client = None
                    logger.info("Disconnected from Redis")
    
    async def _ensure_connected(self) -> bool:
        """Ensure Redis is connected, return False if unavailable."""
        if not self.client:
            try:
                await self.connect()
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                return False
        
        # Verify connection is alive
        try:
            await self.client.ping()
            return True
        except Exception as e:
            logger.warning(f"Redis ping failed: {e}")
            self.client = None
            return False

    def _save_to_fallback(self, queue_name: str, data: Any):
        """Save to local fallback queue if Redis is unavailable."""
        try:
            import os
            fallback_data = {}
            
            if os.path.exists(self._fallback_queue_path):
                with open(self._fallback_queue_path, 'r') as f:
                    fallback_data = json.load(f)
            
            if queue_name not in fallback_data:
                fallback_data[queue_name] = []
            
            fallback_data[queue_name].append(data)
            
            with open(self._fallback_queue_path, 'w') as f:
                json.dump(fallback_data, f)
            
            logger.warning(f"💾 Saved to fallback queue: {queue_name}")
        except Exception as e:
            logger.error(f"Failed to save to fallback queue: {e}")
    
    async def _restore_from_fallback(self):
        """Restore items from fallback queue to Redis."""
        try:
            import os
            if not os.path.exists(self._fallback_queue_path):
                return
            
            with open(self._fallback_queue_path, 'r') as f:
                fallback_data = json.load(f)
            
            for queue_name, items in fallback_data.items():
                for item in items:
                    try:
                        await self.push_to_queue(queue_name, item)
                        logger.info(f"♻️ Restored item from fallback to {queue_name}")
                    except Exception as e:
                        logger.error(f"Failed to restore item: {e}")
                        return  # Stop restoration if Redis fails again
            
            # Clear fallback file after successful restoration
            os.remove(self._fallback_queue_path)
            logger.info("✅ Fallback queue fully restored and cleared")
            
        except Exception as e:
            logger.error(f"Error during fallback restoration: {e}")

    @retry_with_backoff(max_retries=2, base_delay=0.5, max_delay=5.0)
    async def push_to_queue(self, queue_name: str, data: Any) -> int:
        """
        Push data to a list (queue) with retry and fallback.
        Data is serialized to JSON.
        """
        if not await self._ensure_connected():
            # Use fallback queue
            self._save_to_fallback(queue_name, data)
            return 0
        
        try:
            payload = json.dumps(data)
            result = await self.client.lpush(queue_name, payload)
            
            # Try to restore fallback queue on successful push
            asyncio.create_task(self._restore_from_fallback())
            
            return result
        except Exception as e:
            logger.error(f"Failed to push to Redis queue {queue_name}: {e}")
            self._save_to_fallback(queue_name, data)
            raise

    @retry_with_backoff(max_retries=2, base_delay=0.5, max_delay=5.0)
    async def pop_from_queue(self, queue_name: str, timeout: int = 0) -> Optional[Any]:
        """
        Pop data from a list (queue) using blocking pop (BRPOP).
        Returns deserialized JSON data or None.
        """
        if not await self._ensure_connected():
            return None
        
        try:
            # brpop returns (queue_name, data)
            result = await self.client.brpop(queue_name, timeout=timeout)
            if result:
                _, data = result
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to pop from Redis queue {queue_name}: {e}")
            return None

    @retry_with_backoff(max_retries=2, base_delay=0.5, max_delay=5.0)
    async def get_queue_items(self, queue_name: str, start: int = 0, end: int = -1) -> list[Any]:
        """
        Get items from a list (queue) without popping them.
        """
        if not await self._ensure_connected():
            return []
        
        try:
            items = await self.client.lrange(queue_name, start, end)
            return [json.loads(i) for i in items]
        except Exception as e:
            logger.error(f"Failed to get queue items from {queue_name}: {e}")
            return []

    @retry_with_backoff(max_retries=2, base_delay=0.5, max_delay=5.0)
    async def remove_from_queue(self, queue_name: str, data: Any) -> int:
        """
        Remove a specific item from the queue.
        """
        if not await self._ensure_connected():
            return 0
        
        try:
            payload = json.dumps(data)
            return await self.client.lrem(queue_name, 0, payload)
        except Exception as e:
            logger.error(f"Failed to remove from Redis queue {queue_name}: {e}")
            return 0

    @retry_with_backoff(max_retries=2, base_delay=0.5, max_delay=5.0)
    async def set_cache(self, key: str, value: Any, expire: int = 3600) -> bool:
        """Set a value in cache with an expiration time (seconds)."""
        if not await self._ensure_connected():
            return False
        
        try:
            payload = json.dumps(value)
            return await self.client.set(key, payload, ex=expire)
        except Exception as e:
            logger.error(f"Failed to set cache key {key}: {e}")
            return False

    @retry_with_backoff(max_retries=2, base_delay=0.5, max_delay=5.0)
    async def get_cache(self, key: str) -> Optional[Any]:
        """Get a value from cache."""
        if not await self._ensure_connected():
            return None
        
        try:
            data = await self.client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Failed to get cache key {key}: {e}")
            return None
    
    async def health_check(self) -> dict:
        """
        Health check for monitoring.
        Returns status and circuit breaker state.
        """
        try:
            if await self._ensure_connected():
                latency_start = datetime.utcnow()
                await self.client.ping()
                latency = (datetime.utcnow() - latency_start).total_seconds() * 1000
                
                return {
                    "status": "healthy",
                    "circuit_breaker": self.circuit_breaker.state,
                    "latency_ms": round(latency, 2)
                }
            else:
                return {
                    "status": "unhealthy",
                    "circuit_breaker": self.circuit_breaker.state,
                    "error": "Cannot connect to Redis"
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "circuit_breaker": self.circuit_breaker.state,
                "error": str(e)
            }

# Singleton instance for shared use
redis_client = RedisClient()
