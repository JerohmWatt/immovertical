"""
DRY refactoring: Centralized listing field mapping logic.
Eliminates duplication from engine.py
"""
from typing import Dict, Any, Optional
from common.models import Listing

# Field mapping configuration
SIMPLE_FIELD_MAPPING = {
    # Financial
    "price": "price",
    "cadastral_income": "cadastral_income",
    
    # Spatial
    "surface_habitable": "surface_habitable",
    "surface_terrain": "surface_terrain",
    "rooms": "rooms",
    "bathrooms": "bathrooms",
    "room_count": "room_count",
    "facades": "facades",
    "floor": "floor",
    "garden_surface": "garden_surface",
    "terrace_surface": "terrace_surface",
    
    # Location
    "latitude": "latitude",
    "longitude": "longitude",
    "city": "city",
    "postal_code": "postal_code",
    
    # Property details
    "type": "property_type",
    "subType": "property_subtype",
    "condition": "condition",
    "construction_year": "construction_year",
    "renovation_year": "renovation_year",
    
    # Energy
    "energy_label": "energy_class",
    "energy_score": "epc_score",
    "energy_report_ref": "epc_reference",
    
    # Other
    "description": "description",
    "images": "images",
}

# Nested field mapping for complex structures
NESTED_FIELD_MAPPING = {
    "address": {
        "city": "city",
        "postal_code": "postal_code",
    }
}


def apply_extra_data(listing: Listing, extra: Dict[str, Any]) -> Listing:
    """
    Apply extra_data fields to a Listing object.
    Eliminates duplication of if "field" in extra_data checks.
    
    Args:
        listing: Listing object to update
        extra: Dictionary of extra data fields
    
    Returns:
        Updated listing object
    """
    # Apply simple field mappings
    for source_key, target_attr in SIMPLE_FIELD_MAPPING.items():
        if source_key in extra and extra[source_key] is not None:
            setattr(listing, target_attr, extra[source_key])
    
    # Apply nested field mappings
    for parent_key, field_map in NESTED_FIELD_MAPPING.items():
        if parent_key in extra and isinstance(extra[parent_key], dict):
            parent_data = extra[parent_key]
            for source_key, target_attr in field_map.items():
                if source_key in parent_data and parent_data[source_key] is not None:
                    setattr(listing, target_attr, parent_data[source_key])
    
    # Store everything in raw_data
    listing.raw_data = extra
    
    return listing


def extract_century21_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract and normalize Century21 API fields to common format.
    
    Args:
        item: Raw Century21 API item
    
    Returns:
        Normalized dictionary ready for apply_extra_data
    """
    price_data = item.get("price") or {}
    rooms_data = item.get("rooms") or {}
    surface_data = item.get("surface") or {}
    habitable_data = surface_data.get("habitableSurfaceArea") or {}
    garden_data = surface_data.get("surfaceAreaGarden") or {}
    total_surface_data = surface_data.get("totalSurfaceArea") or {}
    desc_data = item.get("description") or {}
    loc_data = item.get("location") or {}
    energy_data = item.get("energySpecifications") or {}
    energy_score = energy_data.get("energyScore") or {}
    energy_consumption = energy_data.get("totalEnergyConsumption") or {}
    address_data = item.get("address") or {}
    amenities_data = item.get("amenities") or {}
    
    # Construct Image URLs
    raw_images = item.get("images") or []
    image_urls = [
        f"https://images.prd.cloud.century21.be/api/v1/images/{img['name']}" 
        for img in raw_images if isinstance(img, dict) and "name" in img
    ]
    
    return {
        # Core fields
        "price": price_data.get("amount"),
        "rooms": rooms_data.get("numberOfBedrooms"),
        "surface_habitable": habitable_data.get("value"),
        "surface_terrain": total_surface_data.get("value") or garden_data.get("value"),
        "description": desc_data.get("fr") or desc_data.get("en") or desc_data.get("nl"),
        "latitude": loc_data.get("latitude"),
        "longitude": loc_data.get("longitude"),
        
        # Rich metadata
        "reference": item.get("reference"),
        "type": item.get("type"),
        "subType": item.get("subType"),
        "condition": item.get("condition"),
        "energy_label": energy_data.get("energyLabel"),
        "energy_score": energy_score.get("value"),
        "energy_total_consumption": energy_consumption.get("value"),
        "energy_report_ref": energy_data.get("energyReportReference"),
        "address": {
            "city": address_data.get("city"),
            "postal_code": address_data.get("postalCode"),
            "street": address_data.get("street"),
            "number": address_data.get("number"),
            "region": address_data.get("region"),
        },
        "amenities": amenities_data,
        "floor_number": item.get("floorNumber"),
        "has_parking": item.get("hasParking"),
        "date_posted": item.get("datePosted"),
        "images": image_urls,
    }


def extract_immoweb_fields(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract and normalize Immoweb fields to common format.
    
    Args:
        item: Raw Immoweb item from JSON
    
    Returns:
        Normalized dictionary ready for apply_extra_data
    """
    prop = item.get("property", {})
    loc = prop.get("location", {})
    trans = item.get("transaction", {})
    sale = trans.get("sale", {})
    
    # Extract images
    media = item.get("media", {})
    images_list = media.get("pictures", [])
    image_urls = [
        img.get("mediumUrl") or img.get("smallUrl") 
        for img in images_list 
        if isinstance(img, dict)
    ]
    
    return {
        "price": sale.get("price"),
        "rooms": prop.get("bedroomCount"),
        "surface_habitable": prop.get("netHabitableSurface"),
        "surface_terrain": prop.get("landSurface"),
        "latitude": loc.get("latitude"),
        "longitude": loc.get("longitude"),
        "description": item.get("title"),
        "address": {
            "city": loc.get("locality"),
            "postal_code": loc.get("postalCode"),
            "street": loc.get("street"),
            "number": loc.get("number"),
            "region": loc.get("region"),
        },
        "energy_label": item.get("transaction", {}).get("certificates", {}).get("epcScore"),
        "type": prop.get("type"),
        "subtype": prop.get("subtype"),
        "images": image_urls,
    }


def construct_century21_url(platform_id: str, address_data: Dict[str, Any]) -> str:
    """Construct Century21 URL from data."""
    city_slug = address_data.get("city", "belgium").lower().replace(" ", "-")
    return f"https://www.century21.be/fr/properiete/a-vendre/maison/{city_slug}/{platform_id}"


def construct_immoweb_url(platform_id: str, prop: Dict[str, Any], loc: Dict[str, Any]) -> str:
    """Construct Immoweb URL from data."""
    type_label = prop.get("type", "maison").lower()
    subtype_label = prop.get("subtype", "a-vendre").lower()
    locality = loc.get("locality", "belgique").lower().replace(" ", "-")
    postcode = loc.get("postalCode", "0000")
    return f"https://www.immoweb.be/fr/annonce/{type_label}/{subtype_label}/{locality}/{postcode}/{platform_id}"
