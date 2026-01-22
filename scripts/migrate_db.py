import asyncio
import sys
import os
from sqlalchemy import text

# Ajout du dossier parent au chemin Python pour trouver 'common'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.database import engine

async def migrate():
    columns = [
        ("city", "VARCHAR"),
        ("postal_code", "VARCHAR"),
        ("property_type", "VARCHAR"),
        ("property_subtype", "VARCHAR"),
        ("bathrooms", "INTEGER"),
        ("facades", "INTEGER"),
        ("construction_year", "INTEGER"),
        ("condition", "VARCHAR"),
        ("energy_class", "VARCHAR"),
        ("epc_score", "INTEGER"),
        ("cadastral_income", "INTEGER"),
        ("is_public_sale", "BOOLEAN DEFAULT FALSE"),
        ("is_viager", "BOOLEAN DEFAULT FALSE"),
        ("annuity_bouquet", "NUMERIC(14,2)"),
        ("annuity_monthly", "NUMERIC(14,2)"),
        ("room_count", "INTEGER"),
        ("toilet_count", "INTEGER"),
        ("floor", "INTEGER"),
        ("garden_surface", "INTEGER"),
        ("terrace_surface", "INTEGER"),
        ("kitchen_type", "VARCHAR"),
        ("renovation_year", "INTEGER"),
        ("heating_type", "VARCHAR"),
        ("is_furnished", "BOOLEAN DEFAULT FALSE"),
        ("epc_reference", "VARCHAR"),
        ("co2_emissions", "INTEGER"),
    ]
    
    print("🚀 Démarrage de la migration des colonnes...")
    for col_name, col_type in columns:
        try:
            async with engine.begin() as conn:
                # On tente d'ajouter la colonne. Si elle existe déjà, ça passera dans le except.
                await conn.execute(text(f"ALTER TABLE listing ADD COLUMN {col_name} {col_type}"))
                print(f"✅ Colonne ajoutée : {col_name}")
        except Exception as e:
            if "already exists" in str(e).lower():
                print(f"ℹ️ Colonne déjà présente : {col_name}")
            else:
                print(f"❌ Erreur sur {col_name}: {e}")
    print("🏁 Migration terminée !")

if __name__ == "__main__":
    asyncio.run(migrate())
