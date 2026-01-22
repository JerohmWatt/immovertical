#!/bin/bash
#
# Database restore script for Immo-Bé
# Usage: ./restore_database.sh <backup_file>
#

set -e

if [ -z "$1" ]; then
    echo "❌ Error: Backup file required"
    echo "Usage: $0 <backup_file.sql.gz>"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "❌ Error: Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

# Database connection
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-immovertical}"
DB_USER="${POSTGRES_USER:-postgres}"

echo "⚠️  WARNING: This will OVERWRITE the current database!"
echo "Database: ${DB_NAME}"
echo "Backup: ${BACKUP_FILE}"
echo ""
read -p "Are you sure? (type 'yes' to continue): " CONFIRM

if [ "${CONFIRM}" != "yes" ]; then
    echo "❌ Restore cancelled"
    exit 0
fi

echo "🔄 Starting database restore..."

# Drop existing connections
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres <<EOF
SELECT pg_terminate_backend(pg_stat_activity.pid)
FROM pg_stat_activity
WHERE pg_stat_activity.datname = '${DB_NAME}'
  AND pid <> pg_backend_pid();
EOF

# Drop and recreate database
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres <<EOF
DROP DATABASE IF EXISTS ${DB_NAME};
CREATE DATABASE ${DB_NAME};
EOF

# Restore from backup
echo "📥 Restoring from backup..."
gunzip -c "${BACKUP_FILE}" | psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}"

# Re-enable PostGIS extension
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" <<EOF
CREATE EXTENSION IF NOT EXISTS postgis;
EOF

echo "✅ Database restore complete!"
echo ""
echo "🔍 Verifying restore..."
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -c "\dt"

echo ""
echo "🎉 Restore process complete!"
