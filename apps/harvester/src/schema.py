from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl

class EnergyData(BaseModel):
    """Energy Performance Certificate data"""
    epc_score: Optional[float] = Field(None, description="kWh/m²/year")
    energy_class: Optional[str] = Field(None, description="Label (A++, A, B, ...)")
    certificate_number: Optional[str] = Field(None, description="Unique PEB/EPC ID")
    co2_emissions: Optional[float] = Field(None, description="kg CO2/m²/year")
    epc_reference: Optional[str] = None

class FinancialData(BaseModel):
    """Price and costs"""
    price: Optional[float] = Field(None, description="Listing price in EUR")
    cadastral_income: Optional[float] = Field(None, description="Revenu Cadastral")
    monthly_charges: Optional[float] = Field(None, description="Monthly costs")
    is_public_sale: bool = False
    is_viager: bool = False
    annuity_bouquet: Optional[float] = None
    annuity_monthly: Optional[float] = None

class SpatialData(BaseModel):
    """Physical dimensions and layout"""
    habitable_surface: Optional[float] = Field(None, description="Living area in m²")
    land_surface: Optional[float] = Field(None, description="Plot size in m²")
    bedroom_count: Optional[int] = None
    bathroom_count: Optional[int] = None
    toilet_count: Optional[int] = None
    room_count: Optional[int] = None
    kitchen_type: Optional[str] = None
    has_garden: bool = False
    garden_surface: Optional[float] = None
    has_terrace: bool = False
    terrace_surface: Optional[float] = None
    floor: Optional[int] = None
    facade_count: Optional[int] = None

class StateData(BaseModel):
    """Condition and Age"""
    construction_year: Optional[int] = None
    renovation_year: Optional[int] = None
    condition: Optional[str] = Field(None, description="As new, Good, To renovate...")
    heating_type: Optional[str] = None
    is_furnished: bool = False

class LocationData(BaseModel):
    """Geographic information"""
    street: Optional[str] = None
    number: Optional[str] = None
    box: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: str = "BE"
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class UniversalListing(BaseModel):
    """
    Platform-Agnostic Data Structure for Real Estate Listings.
    Designed to feed 'Math Brain' (stats) and 'AI Brain' (semantic analysis).
    """
    # Metadata
    source_platform: str
    source_id: str
    url: str
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Text Content (For AI Brain)
    title: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = []
    
    # Categorization
    property_type: str = Field(..., description="HOUSE, APARTMENT, etc.")
    property_subtype: Optional[str] = None

    # Images (Local paths after download or remote URLs)
    image_urls: List[str] = []
    local_image_paths: List[str] = []
    
    # Structured Data Clusters (For Math Brain)
    financial: FinancialData = Field(default_factory=FinancialData)
    spatial: SpatialData = Field(default_factory=SpatialData)
    energy: EnergyData = Field(default_factory=EnergyData)
    state: StateData = Field(default_factory=StateData)
    location: LocationData = Field(default_factory=LocationData)

    # Raw Fallback
    raw_payload: Dict[str, Any] = Field(default_factory=dict, description="Original JSON/Data from platform")
