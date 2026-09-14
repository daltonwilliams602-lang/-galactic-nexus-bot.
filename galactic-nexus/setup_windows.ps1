param([string]$Config = "config.local.json")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path $Config)) { Copy-Item config.example.json $Config }
if (-not (Test-Path .venv\Scripts\python.exe)) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python environment setup failed." }
}
.\.venv\Scripts\python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
.\.venv\Scripts\python -m unittest discover -s tests -q
if ($LASTEXITCODE -ne 0) { throw "Checks failed. Do not start the bot yet." }
Write-Host "Setup passed. Open Start-Nexus.cmd next."
