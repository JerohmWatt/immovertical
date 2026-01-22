"""
IMMO-BÉ ARCHITECTURE CORE
=========================
Role: Truth Engine
System: Distributed Real Estate Sentinel
Author: Architecte Senior
Date: 2026-01-21

Ce fichier définit les structures fondamentales et la logique métier
du système distribué Immo-Bé. Il ne contient pas tout le code de production,
mais les primitives architecturales qui gouvernent le système.
"""

import logging
import json
from enum import Enum
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
from abc import ABC, abstractmethod

# -----------------------------------------------------------------------------
# DEPENDENCIES (Simulation des libs externes)
# -----------------------------------------------------------------------------
from pydantic import BaseModel, Field, validator
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
# import redis
# from shapely.ops import transform
# from pyproj import Transformer

logger = logging.getLogger("immo-be.core")

# -----------------------------------------------------------------------------
# 1. DATA LIFECYCLE & STATE MANAGEMENT
# -----------------------------------------------------------------------------
class ListingStatus(str, Enum):
    """
    Machine à états finis (FSM) d'un bien immobilier dans le système.
    Philosophie: On ne passe à l'étape suivante que si la vérité est vérifiée.
    """
    PENDING = "PENDING"       # Découvert par le Scout, URL capturée.
    SCRAPED = "SCRAPED"       # Données brutes extraites par le Harvester.
    ENRICHED = "ENRICHED"     # Géolocalisation précise et cadastre ajoutés.
    ANALYZED = "ANALYZED"     # Audité par le Brain (Math & AI).
    FAILED = "FAILED"         # Rejeté (Erreur technique ou Dead Letter).

class ListingCore(BaseModel):
    """
    Objet central transitant dans le pipeline.
    Utilise Pydantic pour garantir l'intégrité des données à chaque étape.
    """
    source_id: str
    platform: str
    url: str
    status: ListingStatus = ListingStatus.PENDING
    
    # Géolocalisation stricte (EPSG:31370 requis pour la phase ENRICHED)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    lambert_x: Optional[float] = None
    lambert_y: Optional[float] = None
    
    # Métadonnées
    price: Optional[float] = None
    raw_data: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('platform')
    def validate_platform(cls, v):
        allowed = ['immoweb', 'zimmo', 'century21']
        if v not in allowed:
            raise ValueError(f"Platform {v} non supportée par le Truth Engine")
        return v

# -----------------------------------------------------------------------------
# 2. GIS LOGIC & SPATIAL DISPATCH
# -----------------------------------------------------------------------------
class GeoEngine:
    """
    Moteur de vérité spatiale.
    Règle d'or: Tout ce qui entre doit finir en Lambert 72 (EPSG:31370).
    """
    
    def __init__(self):
        # Initialisation unique des transformateurs (Lourd en chargement)
        # self.transformer = Transformer.from_crs("EPSG:4326", "EPSG:31370", always_xy=True)
        pass

    def wgs84_to_lambert72(self, lat: float, lon: float) -> Tuple[float, float]:
        """
        Convertit GPS (WGS84) vers coordonnées Belges (Lambert 72).
        Utilisé par l'Enricher avant d'interroger les API régionales.
        """
        # Simulation de la conversion pyproj
        # x, y = self.transformer.transform(lon, lat)
        # return x, y
        return (150000.0, 160000.0) # Stub pour l'exemple

    def dispatch_region_api(self, postal_code: str) -> str:
        """
        Routeur intelligent pour choisir la source de vérité cadastrale.
        """
        code = int(postal_code)
        if 1000 <= code <= 1299:
            return "URBIS_API" # Bruxelles
        elif 1300 <= code <= 1499:
            return "WALONMAP_API" # Wallonie
        # ... logique complexe de frontières
        return "GEOPUNT_API" # Flandre par défaut

# -----------------------------------------------------------------------------
# 3. RESILIENCE & QUEUE MANAGEMENT
# -----------------------------------------------------------------------------
class QueueManager:
    """
    Abstraction sur Redis pour gérer la fiabilité.
    Gère les Dead Letter Queues (DLQ) pour ne jamais perdre un lead.
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.DLQ_SUFFIX = "_dlq"

    def push_safe(self, queue: str, item: ListingCore):
        """Push atomique dans la queue."""
        self.redis.lpush(queue, item.json())

    def consume_safe(self, queue: str) -> Optional[ListingCore]:
        """
        Lecture bloquante (BRPOP) pour concurrence.
        Redis garantit qu'un seul worker reçoit le message, évitant les doublons.
        """
        # Dans un vrai système prod, on utiliserait RPOPLPUSH pour transactionnalité
        # Ici on simule un BRPOP simple
        data = self.redis.brpop(queue, timeout=5)
        if data:
            return ListingCore.parse_raw(data[1])
        return None

    def send_to_dlq(self, original_queue: str, item: ListingCore, error: str):
        """
        Envoie les messages "poison" dans une DLQ pour inspection manuelle.
        """
        dlq_name = f"{original_queue}{self.DLQ_SUFFIX}"
        error_wrapper = {
            "original_data": item.dict(),
            "error": str(error),
            "timestamp": datetime.utcnow().isoformat()
        }
        self.redis.lpush(dlq_name, json.dumps(error_wrapper))
        logger.critical(f"Item moved to DLQ {dlq_name}: {error}")

# -----------------------------------------------------------------------------
# 4. WORKER LOGIC (CONCURRENCY & RETRY)
# -----------------------------------------------------------------------------
class Worker(ABC):
    """
    Classe de base pour Harvester, Enricher, Brain.
    """
    def __init__(self, queue_mgr: QueueManager):
        self.queue = queue_mgr

    @abstractmethod
    def process(self, item: ListingCore) -> ListingCore:
        pass

    def run(self, input_queue: str, output_queue: str):
        """
        Boucle principale du worker.
        """
        while True:
            item = self.queue.consume_safe(input_queue)
            if not item:
                continue

            try:
                # Exécution de la logique métier avec Retry policy
                processed_item = self._execute_with_retry(item)
                
                # Transition d'état et push vers étape suivante
                self.queue.push_safe(output_queue, processed_item)
                
            except Exception as e:
                # Échec définitif après retries -> DLQ
                logger.error(f"Processing failed for {item.source_id}: {e}")
                self.queue.send_to_dlq(input_queue, item, str(e))

    @retry(
        stop=stop_after_attempt(3), 
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(ConnectionError) # On ne retry que les erreurs transitoires
    )
    def _execute_with_retry(self, item: ListingCore):
        """
        Wrapper tenacity pour la logique résiliente.
        Si ce wrapper lève une exception, c'est que les 3 tentatives ont échoué.
        """
        return self.process(item)

# -----------------------------------------------------------------------------
# 5. IMPLEMENTATION EXAMPLES
# -----------------------------------------------------------------------------

class Harvester(Worker):
    """
    Responsable: PENDING -> SCRAPED
    Scrape le HTML, extrait les données brutes.
    """
    def process(self, item: ListingCore) -> ListingCore:
        # Simulation scrape
        logger.info(f"Scraping {item.url}...")
        
        # Si erreur réseau ici -> Tenacity retry automatiquement
        # Si le parsing HTML change (erreur logique) -> Pas de retry -> DLQ direct
        
        item.raw_data = {"price_scraped": 450000, "lat": 50.8503, "lon": 4.3517}
        item.latitude = 50.8503
        item.longitude = 4.3517
        item.status = ListingStatus.SCRAPED
        return item

class Enricher(Worker):
    """
    Responsable: SCRAPED -> ENRICHED
    Conversion WGS84 -> Lambert72 et enrichissement cadastral.
    """
    def __init__(self, queue_mgr: QueueManager):
        super().__init__(queue_mgr)
        self.geo_engine = GeoEngine()

    def process(self, item: ListingCore) -> ListingCore:
        logger.info(f"Enriching {item.source_id}...")
        
        # 1. Validation Spatiale
        if not item.latitude or not item.longitude:
            raise ValueError("Missing coordinates for enrichment")

        # 2. Conversion GIS (Le cœur du Truth Engine)
        lx, ly = self.geo_engine.wgs84_to_lambert72(item.latitude, item.longitude)
        item.lambert_x = lx
        item.lambert_y = ly
        
        # 3. Appel API Régionale (Simulé)
        # region_api = self.geo_engine.dispatch_region_api("1000")
        # cadastre_data = call_external_api(region_api, lx, ly)
        
        item.is_enriched = True
        item.status = ListingStatus.ENRICHED
        return item

# -----------------------------------------------------------------------------
# EXEMPLE D'ORCHESTRATION (Main)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Simulation simple
    class MockRedis:
        def lpush(self, q, d): print(f"Redis PUSH {q}: {d}")
        def brpop(self, q, timeout): return None # Bloque en prod
        
    queue = QueueManager(MockRedis())
    
    # Création d'un listing initial
    listing = ListingCore(
        source_id="12345", 
        platform="immoweb", 
        url="https://immoweb.be/..."
    )
    
    print(f"Initial Status: {listing.status}")
    # En production, les workers tourneraient dans des conteneurs séparés
    # harvester.run("queue_scouts", "queue_enricher")
    # enricher.run("queue_enricher", "queue_brain")