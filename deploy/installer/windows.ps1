$ErrorActionPreference = 'Stop'
$base = 'https://150.158.11.154/chives-install'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$statusFile = [IO.Path]::GetTempFileName()
try {
    & curl.exe -sS --max-time 15 "$base/status" -o $statusFile
    if ($LASTEXITCODE -ne 0) { throw 'Chives install server is unreachable.' }
    $status = [IO.File]::ReadAllText($statusFile, [Text.Encoding]::UTF8)
    if ($status.Trim() -ne 'enabled') { throw $status }
} finally { Remove-Item -LiteralPath $statusFile -ErrorAction SilentlyContinue }
$root = if ($env:CHIVES_INSTALL_HOME) { $env:CHIVES_INSTALL_HOME } else { Join-Path $env:LOCALAPPDATA 'Chives' }
$tools = Join-Path $root 'tools'
$null = New-Item -ItemType Directory -Force -Path $tools
$work = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString())
$null = New-Item -ItemType Directory -Path $work
try {
    Invoke-WebRequest -UseBasicParsing "$base/install.py" -OutFile "$work\install.py"
    if (!(Test-Path "$tools\uv.exe")) {
        Invoke-WebRequest -UseBasicParsing 'https://astral.sh/uv/install.ps1' -OutFile "$work\uv-install.ps1"
        $env:UV_UNMANAGED_INSTALL = $tools
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$work\uv-install.ps1"
        if ($LASTEXITCODE -ne 0) { throw 'uv installation failed.' }
    }
    $env:UV_NO_CONFIG = "1"
    & "$tools\uv.exe" run --no-project --python 3.12 python "$work\install.py" "$root"
    if ($LASTEXITCODE -ne 0) { throw 'Chives installation failed. See the detailed output above.' }
} finally { Remove-Item -Recurse -Force -LiteralPath $work }
