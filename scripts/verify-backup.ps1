param(
    [Parameter(Mandatory=$true)][string]$BackupPath,
    [string]$Container = "karavantr_postgres",
    [string]$DatabaseUser = "karavantr"
)
$ErrorActionPreference = "Stop"
$resolvedBackup = (Resolve-Path -LiteralPath $BackupPath).Path
$verificationDatabase = "karavantr_restorecheck_" + [Guid]::NewGuid().ToString("N")
$containerBackup = "/tmp/" + [System.IO.Path]::GetFileName($resolvedBackup)
& docker cp $resolvedBackup "${Container}:$containerBackup"
if ($LASTEXITCODE -ne 0) { throw "Backup copy failed" }
& docker exec $Container createdb -U $DatabaseUser $verificationDatabase
if ($LASTEXITCODE -ne 0) { throw "Isolated database creation failed" }
# Retain this isolated database for inspection. This script never drops/replaces a database.
& docker exec $Container pg_restore -U $DatabaseUser -d $verificationDatabase --no-owner --exit-on-error $containerBackup
if ($LASTEXITCODE -ne 0) { throw "Restore failed; isolated database retained: $verificationDatabase" }
& docker exec $Container psql -U $DatabaseUser -d $verificationDatabase -v ON_ERROR_STOP=1 -c "SELECT version_num FROM alembic_version; SELECT count(*) AS spots FROM spots; SELECT count(*) AS users FROM users;"
if ($LASTEXITCODE -ne 0) { throw "Restore check failed" }
Write-Output "Restore verified in isolated database: $verificationDatabase"
