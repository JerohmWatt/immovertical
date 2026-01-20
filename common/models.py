from typing import Optional, Dict, Any
from decimal import Decimal
from sqlmodel import SQLModel, Field, JSON
from sqlalchemy import Column, Float, Boolean, String
from geoalchemy2 import Geometry

class Listing(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Identification
    source_id: str = Field(index=True)  # ID unique plateforme (ex: 10567832)
    platform: str  # immoweb, zimmo, etc.
    url: Optional[str] = None
    
    # Status & Workflow Flags
    status: str = Field(default="PENDING")
    is_scraped: bool = Field(default=False)
    is_enriched: bool = Field(default=False)
    math_computed: bool = Field(default=False)
    ai_audited: bool = Field(default=False)
    
    # Data Ingestion (WGS84 buffer for Harvester)
    latitude: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    longitude: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    
    # Spatial Data (Lambert 72 for Enricher/Math)
    # Using SRID 31370 as mandated
    geom: Any = Field(default=None, sa_column=Column(Geometry("POINT", srid=31370)))
    
    # Core Data
    price: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    surface_habitable: Optional[int] = None
    description: Optional[str] = None
    images: Optional[Any] = Field(default=None, sa_column=Column(JSON))
    
    # Metrics
    math_metrics: Optional[Dict] = Field(default=None, sa_column=Column(JSON))
    trust_score: Optional[int] = None
