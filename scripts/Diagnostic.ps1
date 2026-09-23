$ErrorActionPreference = 'Continue'
$projectRoot = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $projectRoot 'data\logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logPath = Join-Path $logDirectory ('diagnostic-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.txt')
Start-Transcript -LiteralPath $logPath | Out-Null
try {
    Get-Date
    Write-Output "Dossier du projet : $projectRoot"
    Get-CimInstance Win32_OperatingSystem | Select-Object Caption,TotalVisibleMemorySize,FreePhysicalMemory
    Get-PSDrive -PSProvider FileSystem | Select-Object Name,Free
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { nvidia-smi }
    else { Write-Output 'nvidia-smi est introuvable. Verifiez le pilote NVIDIA.' }
    $config = Get-Content -Raw -LiteralPath (Join-Path $projectRoot 'config.json') | ConvertFrom-Json
    $cli = Join-Path $projectRoot $config.sd_cli
    if (Test-Path -LiteralPath $cli -PathType Leaf) {
        & $cli --version
        & $cli --list-devices
    } else { Write-Output "MOTEUR MANQUANT : $cli" }
    $config.models.PSObject.Properties | ForEach-Object {
        $modelPath = Join-Path $projectRoot $_.Value
        if (Test-Path -LiteralPath $modelPath -PathType Leaf) { Get-Item -LiteralPath $modelPath | Select-Object Name,Length }
        else { Write-Output "MODELE MANQUANT : $modelPath" }
    }
    try {
        $state = Invoke-RestMethod -Uri 'http://127.0.0.1:8766/api/state' -TimeoutSec 2
        Write-Output "Racine du serveur sur le port 8766 : $($state.root)"
        Write-Output "Traitement actif : $($state.active_job)"
    } catch { Write-Output "Interface indisponible sur le port 8766 : $($_.Exception.Message)" }
} finally {
    Stop-Transcript | Out-Null
}
Write-Output "Diagnostic enregistre: $logPath"
