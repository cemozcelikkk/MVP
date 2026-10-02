#!/bin/sh
set -eu
umask 077
name="backup-$(date -u +%Y%m%dT%H%M%SZ)-$$"
temporary="/backups/.$name"
mkdir -p "$temporary"
pg_dump --format=custom --file="$temporary/database.dump"
pg_restore --list "$temporary/database.dump" >/dev/null
tar -czf "$temporary/uploads.tar.gz" -C /uploads .
tar -tzf "$temporary/uploads.tar.gz" >/dev/null
psql -At -v ON_ERROR_STOP=1 -c 'SELECT version_num FROM alembic_version' > "$temporary/migration.txt"
date -u > "$temporary/created-at.txt"
(cd "$temporary" && sha256sum database.dump uploads.tar.gz migration.txt created-at.txt > SHA256SUMS)
mv "$temporary" "/backups/$name"
echo "Backup verified: $name (database + uploads)"
