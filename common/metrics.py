"""
Centralized Prometheus metrics for monitoring.
"""
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest
from typing import Optional
import time

# Create a registry for metrics
registry = CollectorRegistry()

# ========== WATCHTOWER METRICS ==========

# Scout metrics
scout_runs_total = Counter(
    'scout_runs_total',
    'Total number of scout runs',
    ['platform', 'status'],
    registry=registry
)

scout_listings_found = Counter(
    'scout_listings_found_total',
    'Total number of new listings found by scouts',
    ['platform'],
    registry=registry
)

scout_duration_seconds = Histogram(
    'scout_duration_seconds',
    'Duration of scout runs in seconds',
    ['platform'],
    registry=registry
)

# Listing metrics
listings_created_total = Counter(
    'listings_created_total',
    'Total number of listings created',
    ['platform'],
    registry=registry
)

listings_by_status = Gauge(
    'listings_by_status',
    'Number of listings by status',
    ['status'],
    registry=registry
)

# Queue metrics
queue_length = Gauge(
    'queue_length',
    'Length of Redis queues',
    ['queue_name'],
    registry=registry
)

# ========== HARVESTER METRICS ==========

# Scrape metrics
scrapes_total = Counter(
    'scrapes_total',
    'Total number of scrape attempts',
    ['platform', 'status'],
    registry=registry
)

scrape_duration_seconds = Histogram(
    'scrape_duration_seconds',
    'Duration of scrape operations in seconds',
    ['platform'],
    buckets=(1, 5, 10, 30, 60, 120, 300),
    registry=registry
)

scrape_retries_total = Counter(
    'scrape_retries_total',
    'Total number of scrape retries',
    ['platform', 'retry_count'],
    registry=registry
)

# Worker metrics
active_workers = Gauge(
    'active_workers',
    'Number of active harvester workers',
    registry=registry
)

# ========== INFRASTRUCTURE METRICS ==========

# Redis metrics
redis_connection_errors = Counter(
    'redis_connection_errors_total',
    'Total number of Redis connection errors',
    registry=registry
)

redis_latency_seconds = Histogram(
    'redis_latency_seconds',
    'Redis operation latency in seconds',
    ['operation'],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1),
    registry=registry
)

redis_circuit_breaker_state = Gauge(
    'redis_circuit_breaker_state',
    'Redis circuit breaker state (0=CLOSED, 1=HALF_OPEN, 2=OPEN)',
    registry=registry
)

# Database metrics
db_connection_errors = Counter(
    'db_connection_errors_total',
    'Total number of database connection errors',
    registry=registry
)

db_query_duration_seconds = Histogram(
    'db_query_duration_seconds',
    'Database query duration in seconds',
    ['operation'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 5, 10),
    registry=registry
)

# ========== HELPER CLASSES ==========

class MetricsTimer:
    """Context manager for timing operations with Prometheus histograms."""
    
    def __init__(self, histogram: Histogram, labels: Optional[dict] = None):
        self.histogram = histogram
        self.labels = labels or {}
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, *args):
        duration = time.time() - self.start_time
        if self.labels:
            self.histogram.labels(**self.labels).observe(duration)
        else:
            self.histogram.observe(duration)
    
    async def __aenter__(self):
        self.start_time = time.time()
        return self
    
    async def __aexit__(self, *args):
        duration = time.time() - self.start_time
        if self.labels:
            self.histogram.labels(**self.labels).observe(duration)
        else:
            self.histogram.observe(duration)


def export_metrics() -> bytes:
    """Export all metrics in Prometheus format."""
    return generate_latest(registry)


def update_circuit_breaker_state(state: str):
    """Update circuit breaker state metric."""
    state_map = {
        "CLOSED": 0,
        "HALF_OPEN": 1,
        "OPEN": 2
    }
    redis_circuit_breaker_state.set(state_map.get(state, -1))
