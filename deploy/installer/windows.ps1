$ErrorActionPreference = 'Stop'
$base = 'https://150.158.11.154/chives-install'
$root = if ($env:CHIVES_INSTALL_HOME) { $env:CHIVES_INSTALL_HOME } else { Join-Path $env:LOCALAPPDATA 'Chives' }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Write-Host "`n  CHIVES  /  安装向导" -ForegroundColor Cyan
Write-Host "  Windows · $root`n  uv · Python 3.12 · Node.js · Chromium · Chives 本地服务`n"
Write-Host '  [1/6] 检查分发服务，准备 Python 环境…'
function Fetch($url, $out) {
    & curl.exe --fail --show-error --progress-bar --retry 2 $url -o $out
    if ($LASTEXITCODE -ne 0) { throw "下载失败 $url" }
}
$work = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString())
$null = New-Item -ItemType Directory -Path $work
try {
    $status = & curl.exe -sS --max-time 15 "$base/status"
    if ($LASTEXITCODE -ne 0) { throw '无法连接安装服务' }
    if ($status -ne 'enabled') { throw "$status" }
    $version = (& curl.exe -fsS "$base/assets/uv-version")
    if ($version -notmatch '^\d+\.\d+\.\d+$') { throw '无法读取 uv 版本' }
    $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    $cpu = switch ($arch) { AMD64 {'x86_64'} ARM64 {'aarch64'} default { throw "不支持 $arch" } }
    $tools = Join-Path $root 'tools'
    $null = New-Item -ItemType Directory -Force -Path $tools
    $uv = Join-Path $tools "uv-$version-$cpu.exe"
    if (!(Test-Path $uv)) {
        $url = "$base/assets/uv/$version/uv-$cpu-pc-windows-msvc.zip"
        Fetch $url "$work/uv.zip"
        $sum = & curl.exe -fsS "$url.sha256"
        if ($LASTEXITCODE -ne 0 -or (Get-FileHash "$work/uv.zip").Hash -ne ($sum -split '\s+')[0]) { throw 'uv 校验失败' }
        Expand-Archive "$work/uv.zip" "$work/extracted"
        $exe = Get-ChildItem "$work/extracted" -Filter uv.exe -Recurse | Select-Object -First 1
        $tmp = Join-Path $tools ([Guid]::NewGuid().ToString())
        Copy-Item $exe.FullName $tmp
        try { if (!(Test-Path $uv)) { Move-Item $tmp $uv } } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
    } else { Write-Host "  已复用 uv $version" }
    Fetch "$base/install.py" "$work/install.py"
    $env:CHIVES_UV = $uv
    $env:PYTHONUTF8 = '1'
    $env:UV_NO_CONFIG = '1'
    $env:UV_PYTHON_INSTALL_MIRROR = "$base/assets/python"
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $tools 'python'
    $env:UV_MANAGED_PYTHON = '1'
    & $uv python install 3.12 --upgrade --no-bin --no-registry
    if ($LASTEXITCODE -ne 0) { throw 'Python 环境准备失败' }
    & $uv run --no-project --python 3.12 python "$work/install.py" "$root"
    if ($LASTEXITCODE -ne 0) { throw 'Chives 安装未完成，请查看上方提示。' }
} finally { Remove-Item -Recurse -Force -LiteralPath $work }
