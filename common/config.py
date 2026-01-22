"""
Centralized configuration using pydantic-settings.
All environment variables and configuration in one place.
"""
import os
from pydantic_settings import BaseSettings
from typing import Optional


class DatabaseConfig(BaseSettings):
    """Database configuration."""
    url: str
    pool_size: int = 20
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 3600
    echo: bool = False
    
    class Config:
        env_prefix = "DATABASE_"
        case_sensitive = False


class RedisConfig(BaseSettings):
    """Redis configuration."""
    url: str = "redis://localhost:6379/0"
    socket_timeout: int = 5
    socket_connect_timeout: int = 5
    health_check_interval: int = 30
    
    # Circuit breaker settings
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 60
    
    class Config:
        env_prefix = "REDIS_"
        case_sensitive = False


class WatchtowerConfig(BaseSettings):
    """Watchtower service configuration."""
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    
    # Scout settings
    scout_cooldown_minutes: int = 55
    scout_request_timeout: int = 30
    scout_delay_between_urls: float = 2.0
    
    # Listings
    listings_page_size: int = 50
    
    # Logging
    log_level: str = "INFO"
    log_json: bool = False
    
    class Config:
        env_prefix = "WATCHTOWER_"
        case_sensitive = False


class HarvesterConfig(BaseSettings):
    """Harvester service configuration."""
    workers: int = 3
    max_retries: int = 5
    timeout: int = 120  # seconds
    
    # Browser settings
    browser_reconnect_delay: int = 10
    max_browser_reconnect_attempts: int = 5
    
    # Retry settings
    retry_base_delay: float = 5.0
    retry_max_delay: float = 300.0
    
    # Smart delay settings (anti-bot)
    scrape_delay_base: float = 1.0
    scrape_delay_jitter: float = 0.5
    
    # Logging
    log_level: str = "INFO"
    log_json: bool = False
    
    class Config:
        env_prefix = "HARVESTER_"
        case_sensitive = False


class Config:
    """Main configuration aggregator."""
    
    def __init__(self):
        # Database URL is required
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            # Dev fallback only if explicitly allowed
            if os.getenv("ALLOW_DEV_DEFAULTS", "false").lower() == "true":
                database_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/immovertical"
            else:
                raise RuntimeError("DATABASE_URL environment variable must be set")
        
        self.database = DatabaseConfig(url=database_url)
        self.redis = RedisConfig()
        self.watchtower = WatchtowerConfig()
        self.harvester = HarvesterConfig()
    
    @property
    def service_name(self) -> str:
        """Auto-detect service name from environment or default."""
        return os.getenv("SERVICE_NAME", "immovertical")


# Global config instance
config = Config()
