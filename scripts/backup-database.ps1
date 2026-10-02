param(
    [string]$Container = "karavantr_postgres",
    [string]$Database = "karavantr_db",
    [string]$DatabaseUser = "karavantr",
    [string]$OutputDirectory = "C:\MVP\backups"
)
$ErrorActionPreference = "Stop"
$backupDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
$backupName = "karavantr-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".dump"
$containerFile = "/tmp/" + $backupName
$backupPath = Join-Path $backupDirectory $backupName
& docker exec $Container pg_dump -U $DatabaseUser -d $Database -Fc -f $containerFile
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
& docker cp "${Container}:$containerFile" $backupPath
if ($LASTEXITCODE -ne 0) { throw "Backup copy failed" }
& docker exec $Container pg_restore --list $containerFile | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Backup archive validation failed" }
Get-Item -LiteralPath $backupPath | Select-Object FullName, Length
