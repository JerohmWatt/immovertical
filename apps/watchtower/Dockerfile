FROM python:3.10-slim

WORKDIR /app

# Installation des dépendances système pour psycopg2 (Postgres)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copie des requirements (à créer à la racine ou dans le dossier app)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# On expose le port de FastAPI
EXPOSE 8000

# Le dossier /common et /apps seront montés via volumes pour le dev