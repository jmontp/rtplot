param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$build = Join-Path $repo '.build\windows'
$dist = Join-Path $repo 'dist'
New-Item -ItemType Directory -Force $build, $dist | Out-Null
# Keep build caches and one-file extraction on the repository's drive.
$env:TEMP = Join-Path $build 'temp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $build 'pip-cache'
$env:PYINSTALLER_CONFIG_DIR = Join-Path $build 'pyinstaller-cache'
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
Push-Location $repo
try {
    $commit = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve repository HEAD' }
    $archive = Join-Path $build 'source.zip'
    & git archive --format=zip --output=$archive HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Cannot archive committed source' }
    $source = Join-Path $build 'source'
    if (Test-Path $source) { Remove-Item -Recurse -Force $source }
    Expand-Archive -Path $archive -DestinationPath $source
    $venv = Join-Path $build 'venv'
    $buildPython = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $buildPython)) {
        & $Python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Creating the build environment failed (Python 3.9-3.12 required)' }
    }
    & $buildPython -m pip install "$source[browser]" pyinstaller
    if ($LASTEXITCODE -ne 0) { throw 'Installing build dependencies failed' }
    & $buildPython -m PyInstaller (Join-Path $source 'packaging\rtplot-server.spec') --noconfirm --distpath $dist --workpath (Join-Path $build 'work')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    $exe = Join-Path $dist 'rtplot-server.exe'
    $receipt = [ordered]@{
        source_commit = $commit
        source_archive_sha256 = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLower()
        executable = 'rtplot-server.exe'
        executable_sha256 = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
        python = (& $buildPython --version | Out-String).Trim()
        dependencies = @(& $buildPython -m pip freeze)
        built_utc = (Get-Date).ToUniversalTime().ToString('o')
    }
    $receipt | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $dist 'build-provenance.json')
    & $buildPython (Join-Path $PSScriptRoot 'verify-windows-build.py')
    if ($LASTEXITCODE -ne 0) { throw 'Packaged source verification failed' }
    Write-Host "Built committed source $commit -> $exe"
} finally { Pop-Location }
