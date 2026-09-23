# Installation explicite : cree .venv puis telecharge Pillow depuis PyPI.
# Ne telecharge ni Python, ni moteur CUDA, ni modeles.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvDirectory = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvDirectory 'Scripts\python.exe'

function Find-BasePython {
    $candidates = @()
    if ($env:QWEN_PYTHON) { $candidates += @{ Path = $env:QWEN_PYTHON; Prefix = @() } }
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
        if (Test-Path -LiteralPath $bundledPython) { $candidates += @{ Path = $bundledPython; Prefix = @() } }
    }
    $probe = 'import sys, venv; assert sys.version_info >= (3, 10); print(sys.executable)'
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
    throw 'Installez Python 3.10 ou plus avec le module venv, puis relancez ce script. Vous pouvez aussi definir QWEN_PYTHON avec son chemin.'
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    $basePython = Find-BasePython
    Write-Output "Creation de $venvDirectory avec $basePython"
    & $basePython -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Creation du venv impossible. Utilisez une installation standard de Python avec venv et ensurepip.' }
}
& $venvPython -c 'import sys; assert sys.version_info >= (3, 10)'
if ($LASTEXITCODE -ne 0) { throw 'Le venv existant doit utiliser Python 3.10 ou plus.' }
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Installation de Pillow impossible. Consultez les erreurs affichees ci-dessus.' }
Write-Output 'Version de Pillow :'
& $venvPython -c 'import PIL; print(PIL.__version__)'
if ($LASTEXITCODE -ne 0) { throw 'Pillow est indisponible dans le venv.' }
Write-Output 'Installation terminee. Double-cliquez sur Lancer.vbs pour ouvrir l interface.'
