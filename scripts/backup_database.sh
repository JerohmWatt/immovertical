#!/bin/bash
#
# Database backup script for Immo-Bé
# Usage: ./backup_database.sh [daily|weekly|monthly]
#

set -e

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/var/backups/immovertical}"
RETENTION_DAYS_DAILY=7
RETENTION_DAYS_WEEKLY=30
RETENTION_DAYS_MONTHLY=365

# Database connection
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-immovertical}"
DB_USER="${POSTGRES_USER:-postgres}"

# Backup type (daily, weekly, monthly)
BACKUP_TYPE="${1:-daily}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/${BACKUP_TYPE}_${DB_NAME}_${TIMESTAMP}.sql.gz"

# Create backup directory
mkdir -p "${BACKUP_DIR}"

echo "🔒 Starting ${BACKUP_TYPE} backup..."
echo "📂 Backup location: ${BACKUP_FILE}"

# Perform backup
pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" \
    --format=plain --no-owner --no-acl \
    | gzip > "${BACKUP_FILE}"

# Verify backup
if [ -f "${BACKUP_FILE}" ]; then
    SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    echo "✅ Backup successful: ${SIZE}"
else
    echo "❌ Backup failed!"
    exit 1
fi

# Cleanup old backups based on type
echo "🧹 Cleaning up old ${BACKUP_TYPE} backups..."

case "${BACKUP_TYPE}" in
    daily)
        find "${BACKUP_DIR}" -name "daily_*.sql.gz" -mtime +${RETENTION_DAYS_DAILY} -delete
        ;;
    weekly)
        find "${BACKUP_DIR}" -name "weekly_*.sql.gz" -mtime +${RETENTION_DAYS_WEEKLY} -delete
        ;;
    monthly)
        find "${BACKUP_DIR}" -name "monthly_*.sql.gz" -mtime +${RETENTION_DAYS_MONTHLY} -delete
        ;;
esac

echo "✅ Cleanup complete"

# List recent backups
echo ""
echo "📊 Recent backups:"
ls -lh "${BACKUP_DIR}" | tail -10

echo ""
echo "🎉 Backup process complete!"
