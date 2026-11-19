#!/usr/bin/env bash
# Weekly pg_dump of the warehouse (the crime data). Keeps the 8 newest dumps.
# Credentials come from inside the container, so no password is stored in this script.
set -euo pipefail
DEST="${BACKUP_DIR:-$HOME/backups}"
mkdir -p "$DEST"
FILE="$DEST/cpd_insights_$(date +%Y%m%d_%H%M%S).sql.gz"
docker exec cpd_warehouse sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' | gzip > "$FILE"
# a dump that is nearly empty means something went wrong
[ "$(stat -c %s "$FILE")" -gt 10000 ] || { echo "backup suspiciously small: $FILE" >&2; exit 1; }
ls -1t "$DEST"/cpd_insights_*.sql.gz | tail -n +9 | xargs -r rm --
echo "$(date -Is) wrote $FILE ($(du -h "$FILE" | cut -f1))"
