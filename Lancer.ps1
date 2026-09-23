$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$logDirectory = Join-Path $projectRoot 'data\logs'
$url = 'http://127.0.0.1:8766'

function Find-PythonRuntime {
    $candidates = @()
    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) {
        $candidates += @{ Path = $venvPython; Prefix = @() }
    }
    if ($env:QWEN_PYTHON) {
        $candidates += @{ Path = $env:QWEN_PYTHON; Prefix = @() }
    }
    foreach ($name in @('py.exe', 'python.exe', 'python3.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command -and $command.Source -notlike '*\Microsoft\WindowsApps\*') {
            $prefix = @()
            if ($name -eq 'py.exe') { $prefix = @('-3') }
            $candidates += @{ Path = $command.Source; Prefix = $prefix }
        }
    }
    if ($env:USERPROFILE) {
        $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (Test-Path -LiteralPath $bundledPython) {
            $candidates += @{ Path = $bundledPython; Prefix = @() }
        }
    }
    $probe = 'import sys; assert sys.version_info >= (3, 10); import PIL; print(sys.executable)'
    foreach ($candidate in $candidates) {
        try {
            $executable = $candidate.Path
            $arguments = @($candidate.Prefix) + @('-c', $probe)
            $reportedPath = @(& $executable @arguments 2>$null)
            if ($LASTEXITCODE -eq 0 -and $reportedPath.Count -gt 0) {
                $reportedPath = $reportedPath[-1].Trim()
                if (Test-Path -LiteralPath $reportedPath -PathType Leaf) { return $reportedPath }
            }
        } catch { }
    }
    throw 'Python 3.10 ou plus avec Pillow est requis. Lancez scripts\Installer-Python.ps1 une fois, ou indiquez un interpreteur compatible dans QWEN_PYTHON.'
}

function Test-ProjectServer {
    try {
        $state = Invoke-RestMethod -Uri "$url/api/state" -TimeoutSec 2
    } catch {
        if ($_.Exception.Response) {
            throw "Le port 8766 est utilise par un autre service. Fermez-le avant de lancer ce projet."
        }
        return $false
    }
    if (-not $state.root) {
        throw "Le port 8766 repond sans identifier le dossier du projet. Lancement refuse."
    }
    $runningRoot = [System.IO.Path]::GetFullPath([string]$state.root).TrimEnd('\')
    if (-not [string]::Equals($runningRoot, $projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Une autre installation utilise le port 8766 : $runningRoot. Fermez son serveur avant de lancer $projectRoot."
    }
    return $true
}

try {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    if (-not (Test-ProjectServer)) {
        $pythonRuntime = Find-PythonRuntime
        $serverPath = Join-Path $projectRoot 'app\server.py'
        $outLog = Join-Path $logDirectory 'server-8766-stdout.log'
        $errLog = Join-Path $logDirectory 'server-8766-stderr.log'
        $serverArgs = '-X utf8 -u "' + $serverPath + '" --root "' + $projectRoot + '" --port 8766 --no-browser'
        $serverProc = Start-Process -FilePath $pythonRuntime -ArgumentList $serverArgs -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
        $ready = $false
        for ($attempt = 0; $attempt -lt 50; $attempt++) {
            Start-Sleep -Milliseconds 200
            if (Test-ProjectServer) { $ready = $true; break }
            $serverProc.Refresh()
            if ($serverProc.HasExited) { break }
        }
        if (-not $ready) { throw "L'interface n'a pas demarre. Consultez data\logs\server-8766-stderr.log." }
    }
    Start-Process $url
} catch {
    $message = $_.Exception.Message
    try { $_ | Out-File -LiteralPath (Join-Path $logDirectory 'launcher-error.log') -Append -Encoding utf8 } catch { }
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($message, 'Qwen Image local') | Out-Null
    exit 1
}
