#!/bin/sh
set -eu
name="${1:?Pass the backup directory name}"
case "$name" in backup-*) ;; *) echo "Invalid backup name" >&2; exit 1 ;; esac
case "$name" in *[!a-zA-Z0-9_-]*) echo "Invalid backup name" >&2; exit 1 ;; esac
directory="/backups/$name"
(cd "$directory" && sha256sum -c SHA256SUMS)
database="restorecheck_$(date -u +%Y%m%dT%H%M%S)_$$"
createdb "$database"
pg_restore --dbname="$database" --no-owner --exit-on-error "$directory/database.dump"
psql --dbname="$database" -v ON_ERROR_STOP=1 -c 'SELECT version_num FROM alembic_version; SELECT count(*) AS spots FROM spots; SELECT count(*) AS users FROM users;'
mkdir -p "$directory/restore-check-uploads"
tar -xzf "$directory/uploads.tar.gz" -C "$directory/restore-check-uploads"
echo "Restore verified. Isolated database retained: $database; photos: $directory/restore-check-uploads"
