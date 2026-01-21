from typing import Optional, Dict, Any, List
from decimal import Decimal
from datetime import datetime
from sqlmodel import SQLModel, Field, JSON, Column, DateTime
from sqlalchemy import Float, Boolean, String, text, Integer
from geoalchemy2 import Geometry
import json

class Listing(SQLModel, table=True):
    """
    Core Listing model for the 'Truth Engine'.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Identification
    source_id: str = Field(index=True, description="Unique platform ID")
    platform: str = Field(index=True, description="immoweb, zimmo, etc.")
    url: Optional[str] = Field(default=None)
    
    # Workflow
    status: str = Field(default="PENDING", index=True)
    is_scraped: bool = Field(default=False)
    
    # Localisation
    latitude: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    longitude: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    city: Optional[str] = Field(default=None, index=True)
    postal_code: Optional[str] = Field(default=None, index=True)
    
    # Caractéristiques principales
    property_type: Optional[str] = Field(default=None, index=True) # HOUSE, APARTMENT
    property_subtype: Optional[str] = Field(default=None)
    price: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    
    # Financial details
    cadastral_income: Optional[int] = None
    is_public_sale: bool = Field(default=False)
    is_viager: bool = Field(default=False)
    annuity_bouquet: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    annuity_monthly: Optional[Decimal] = Field(default=None, max_digits=14, decimal_places=2)
    
    # Détails techniques
    surface_habitable: Optional[int] = None
    surface_terrain: Optional[int] = None
    rooms: Optional[int] = None # Bedrooms
    room_count: Optional[int] = None # Total rooms
    bathrooms: Optional[int] = None
    toilet_count: Optional[int] = None
    facades: Optional[int] = None
    floor: Optional[int] = None
    garden_surface: Optional[int] = None
    terrace_surface: Optional[int] = None
    kitchen_type: Optional[str] = None
    
    # State & Construction
    construction_year: Optional[int] = None
    renovation_year: Optional[int] = None
    condition: Optional[str] = None # AS_NEW, GOOD, TO_RENOVATE
    heating_type: Optional[str] = None
    is_furnished: bool = Field(default=False)
    
    # Énergie
    energy_class: Optional[str] = Field(default=None, index=True) # A, B, C...
    epc_score: Optional[int] = None # kWh/m²
    epc_reference: Optional[str] = None
    co2_emissions: Optional[int] = None
    
    # Contenu
    description: Optional[str] = None
    images: List[str] = Field(default=[], sa_column=Column(JSON))
    
    # Stockage JSON complet (pour ne rien perdre)
    raw_data: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    
    # Métriques et erreurs
    last_error: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=True), server_default=text("now()")))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")))

    class Config:
        arbitrary_types_allowed = True


class ScanHistory(SQLModel, table=True):
    """
    Audit log for chaque passage de scout.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: str = Field(index=True, description="Identifiant unique du run (ex: timestamp)")
    platform: str = Field(index=True)
    new_listings_count: int = Field(default=0)
    status: str = Field(default="SUCCESS") # SUCCESS, FAILED
    error_message: Optional[str] = None
    duration_seconds: Optional[float] = None
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=text("now()"))
    )
