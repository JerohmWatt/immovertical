"""
Centralized logging configuration with structured logging support.
"""
import logging
import sys
import os
from typing import Any
import structlog
from datetime import datetime

def configure_logging(
    service_name: str,
    level: str = "INFO",
    json_logs: bool = None
) -> structlog.BoundLogger:
    """
    Configure structured logging for a service.
    
    Args:
        service_name: Name of the service (e.g., "watchtower", "harvester")
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_logs: Force JSON format. If None, uses env var LOG_JSON (defaults to False in dev)
    
    Returns:
        Configured structlog logger
    """
    if json_logs is None:
        json_logs = os.getenv("LOG_JSON", "false").lower() == "true"
    
    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper())
    )
    
    # Shared processors for all logs
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    
    if json_logs:
        # Production: JSON output
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
        ]
    else:
        # Development: Human-readable colored output
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True)
        ]
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Create and return logger with service name bound
    logger = structlog.get_logger(service_name)
    logger = logger.bind(service=service_name)
    
    return logger


class CorrelationContext:
    """Context manager for correlation ID tracking across async operations."""
    
    def __init__(self, correlation_id: str):
        self.correlation_id = correlation_id
    
    def __enter__(self):
        structlog.contextvars.bind_contextvars(correlation_id=self.correlation_id)
        return self
    
    def __exit__(self, *args):
        structlog.contextvars.unbind_contextvars("correlation_id")
    
    async def __aenter__(self):
        structlog.contextvars.bind_contextvars(correlation_id=self.correlation_id)
        return self
    
    async def __aexit__(self, *args):
        structlog.contextvars.unbind_contextvars("correlation_id")


def generate_correlation_id() -> str:
    """Generate a unique correlation ID for request tracing."""
    from uuid import uuid4
    return str(uuid4())


def bind_correlation_id(correlation_id: str = None):
    """
    Bind a correlation ID to the current context.
    If no ID provided, generates a new one.
    """
    if correlation_id is None:
        correlation_id = generate_correlation_id()
    
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    return correlation_id


def get_correlation_id() -> str:
    """Get the current correlation ID from context, or generate new one."""
    try:
        import structlog.contextvars
        ctx = structlog.contextvars._get_context()
        return ctx.get("correlation_id", generate_correlation_id())
    except:
        return generate_correlation_id()
