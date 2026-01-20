import sys
import os
import asyncio
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

# Ajout du chemin racine au PYTHONPATH
root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_path not in sys.path:
    sys.path.insert(0, root_path)

try:
    from common.database import engine
except ImportError as e:
    print(f"ERREUR: Impossible d'importer 'common.database'.")
    print(f"Détail : {e}")
    print(f"PYTHONPATH actuel : {sys.path}")
    sys.exit(1)

async def check_gis():
    print("=== Immo-Bé : PostGIS & SRID 31370 Diagnostic ===")
    
    try:
        async with engine.connect() as conn:
            print("[+] Connexion à la base de données : OK")
            
            # 1. Vérification/Création de l'extension PostGIS
            print("[+] Vérification de l'extension PostGIS...")
            try:
                # On utilise une transaction pour l'extension
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
                await conn.commit()
                print("    - Extension PostGIS : OK (Active)")
            except Exception as e:
                print(f"    - ERREUR Extension : {e}")
                print("\nDiagnostic : Problème de droits (Superuser requis) ou driver incompatible.")
                return

            # 2. Test du SRID 31370 (Lambert 72)
            print("[+] Test de géométrie (Namur - Lambert 72)...")
            try:
                # Namur (185000, 128000) et un point à 1km à l'Est (186000, 128000)
                query = text("""
                    SELECT 
                        postgis_full_version() as version,
                        ST_Distance(
                            ST_SetSRID(ST_Point(185000, 128000), 31370),
                            ST_SetSRID(ST_Point(186000, 128000), 31370)
                        ) as distance;
                """)
                
                result = await conn.execute(query)
                row = result.fetchone()
                
                if row:
                    version = row[0]
                    distance = row[1]
                    print(f"    - PostGIS Version : {version.split(' ')[0]}")
                    print(f"    - Distance calculée (Namur East 1km) : {distance:.2f}m")
                    
                    if abs(distance - 1000) < 0.1:
                        print("    - Précision SRID 31370 : OK")
                    else:
                        print(f"    - ATTENTION : Distance incorrecte ({distance}m). Vérifiez la définition du SRID 31370.")
                
            except ProgrammingError as e:
                if "31370" in str(e).lower() or "spatial_ref_sys" in str(e).lower():
                    print("    - ERREUR SRID : Le SRID 31370 est manquant ou invalide dans 'spatial_ref_sys'.")
                    print("    - Solution : INSERT INTO spatial_ref_sys ... (Lambert 72 definition required).")
                else:
                    print(f"    - ERREUR SQL/Driver : {e}")
                return
            except Exception as e:
                print(f"    - ERREUR GÉOMÉTRIE : {e}")
                return

            print("\n[SUCCESS] PostGIS est prêt pour la 'Truth Engine' d'Immo-Bé.")

    except OperationalError as e:
        print(f"\n[!] ERREUR DE CONNEXION : {e}")
        print("\nDiagnostic possible :")
        print("1. Le container 'db' n'est pas lancé (docker-compose up -d db).")
        print("2. DATABASE_URL est incorrect (vérifiez .env).")
        print("3. Le driver 'asyncpg' n'est pas installé (pip install asyncpg).")
    except Exception as e:
        print(f"\n[!] ERREUR CRITIQUE : {e}")

if __name__ == "__main__":
    if os.name == 'nt': # Windows fix for ProactorEventLoop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(check_gis())
