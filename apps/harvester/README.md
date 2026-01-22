# Harvester - Enrichment Engine

Le **Moissonneur** est responsable de l'extraction profonde des données. Il prend le relais du Watchtower pour transformer une simple URL en un audit complet.

## Philosophie : "Truth Engine"
On ne se contente pas des titres. Le Harvester va chercher les détails techniques cachés dans les pages de détails pour alimenter le moteur d'audit.

## Fonctionnement Technique

### 1. Consommation de la file (`main.py`)
- Écoute en continu la file Redis `scrape_queue`.
- Gère la résilience : si le Harvester tombe, les tâches restent dans Redis.

### 2. Pilotage de Navigateur (Playwright)
- Utilise **Playwright** pour gérer le rendu JavaScript et contourner les protections simples.
- **Technique du Chrome Externe** : Tente de se connecter à une instance Chrome existante (port 9222) pour bénéficier d'un profil "réel" (cookies, historique) avant de basculer sur un navigateur headless interne.

### 3. Scrapers Spécifiques (`scrapers/`)
Chaque plateforme a son propre scraper dédié qui implémente la logique d'extraction :
- `immoweb.py` : Extraction des données structurées, des images haute résolution, et des scores PEB.
- `century21.py` : Extraction via les données API déjà collectées ou via la page.

### 4. Mise à jour du "Truth"
Une fois le scraping réussi :
1. Les données sont mappées sur le modèle `Listing`.
2. Le statut passe à `SCANNED`.
3. `is_scraped` est mis à `True`.
4. L'objet complet est sauvegardé dans `raw_data` (JSON) pour archivage.

## Stockage des Images
Le Harvester télécharge ou référence les images originales pour permettre l'audit visuel ultérieur.
