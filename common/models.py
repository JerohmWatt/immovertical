from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime
from sqlmodel import SQLModel, Field, JSON, Column, DateTime
from sqlalchemy import Float, Boolean, String, text
from geoalchemy2 import Geometry
import json

class Listing(SQLModel, table=True):
    """
    Core Listing model for the 'Truth Engine'.
    Stored in Lambert 72 (EPSG:31370).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Identification
    source_id: str = Field(index=True, description="Unique platform ID (e.g. 10567832)")
    platform: str = Field(index=True, description="immoweb, zimmo, etc.")
    url: Optional[str] = Field(default=None)
    
    # Status & Workflow Flags
    status: str = Field(default="PENDING", index=True)
    is_scraped: bool = Field(default=False)
    is_enriched: bool = Field(default=False)
    math_computed: bool = Field(default=False)
    ai_audited: bool = Field(default=False)
    
    # Raw Data Ingestion (WGS84 for Harvester compatibility)
    latitude: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    longitude: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    
    # Spatial Data (Lambert 72 - EPSG:31370 as mandated by .cursorrules)
    # This is the 'Truth' location
    geom: Any = Field(
        default=None, 
        sa_column=Column(Geometry(geometry_type="POINT", srid=31370, spatial_index=True))
    )
    
    # Property Details
    price: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    surface_habitable: Optional[int] = None
    surface_terrain: Optional[int] = None
    rooms: Optional[int] = None
    description: Optional[str] = None
    
    # Flexible Storage for Images and Raw Attributes
    images: List[str] = Field(default=[], sa_column=Column(JSON))
    raw_data: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    
    # Analysis Metrics
    math_metrics: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    ai_analysis: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    trust_score: Optional[int] = Field(default=None, ge=0, le=100)
    
    # Timestamps
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=text("now()"))
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(
            DateTime(timezone=True), 
            server_default=text("now()"), 
            onupdate=text("now()")
        )
    )

    class Config:
        arbitrary_types_allowed = True
