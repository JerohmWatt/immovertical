# Watchtower - Discovery Engine (Scouting)

La **Tour de Guet** est le point d'entrée du système Immo-Bé. Son rôle est de surveiller les plateformes immobilières pour détecter de nouvelles opportunités.

## Philosophie : "Discovery First"
Le Watchtower ne cherche pas à extraire toutes les données immédiatement. Il se concentre sur la rapidité et la détection :
1. **Discovery** : Scanner les listes de résultats.
2. **Deduplication** : Vérifier en base de données via le `source_id`.
3. **Queueing** : Envoyer les nouvelles pépites au `harvester` via Redis.

## Fonctionnement Technique

### 1. La Boucle de Scouting (`engine.py`)
- Une tâche de fond (`scouts_loop`) s'exécute toutes les heures.
- Un mécanisme de **cooldown** (55 min) évite les scans trop fréquents tout en permettant un forçage manuel via l'API.
- Un **Lock** (`scout_lock`) garantit qu'une seule instance de scan tourne à la fois.

### 2. Stratégies par Plateforme (`scouts.py`)
Chaque plateforme a sa propre méthode d'extraction :
- **Immoweb** : Méthode hybride.
    - Extraction riche depuis le JSON injecté dans le HTML (`:results`).
    - Fallback via Regex pour capturer les liens que le JSON aurait raté.
- **Century 21** : Appel direct à leur API interne.
    - Génération dynamique d'un filtre encodé en Base64 (ex: filtres sur la date de création, le prix max, etc.).

### 3. Cycle de vie d'une détection
Quand un bien est trouvé :
1. `process_detection` vérifie l'existence via `source_id`.
2. Si nouveau : Création d'un objet `Listing` avec le statut `PENDING`.
3. Envoi d'un message dans la file Redis `scrape_queue`.

## Monitoring
Chaque run est loggé dans la table `ScanHistory` :
- Nombre de nouveaux biens trouvés.
- Durée du scan par plateforme.
- Erreurs éventuelles (Anti-bot 403, timeout, etc.).
