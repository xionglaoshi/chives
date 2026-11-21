# Windows PowerShell 5.1 and PowerShell 7. All state is local to this invocation.
& {
    $ErrorActionPreference = 'Stop'
    $repo = 'xionglaoshi/chives'
    $tempDir = $null
    $installLock = $null
    $routeArgs = @('--noproxy', '*')
    $networkArgs = @('-q', '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '8')
    function Show-Step([int]$number, [string]$title) {
        $bar = ('#' * ($number - 1)) + ('-' * (7 - $number))
        Write-Host ("`n  [{0}/6] [{1}] {2}%  {3}" -f $number, $bar, [math]::Floor(($number-1)*100/6), $title)
    }
    function Get-Download([string]$url, [string]$path, [string]$title) {
        Write-Host "    下载 $title（已收字节 / 当前速率）"
        & curl.exe @networkArgs @routeArgs -fL --retry 2 --speed-time 90 --speed-limit 1 -o $path -w '\n    %{size_download} bytes, %{speed_download} B/s\n' $url | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "$title 下载失败" }
    }
    $oldProxy = $env:CHIVES_SETUP_PROXY
    $oldUtf8 = $env:PYTHONUTF8
    try {
        $banner = @'
   ███ █ █ ███ █ █ ███ ███
   █   █ █  █  █ █ █   █
   █   ███  █  █ █ ██  ███     CHIVES-AGENT
   █   █ █  █  █ █ █     █
   ███ █ █ ███  █  ███ ███
'@
        if ([Console]::IsOutputRedirected -or (Test-Path Env:NO_COLOR)) { Write-Host $banner } else { Write-Host $banner -ForegroundColor Green -BackgroundColor Black }
        Write-Host "`n  老韭菜 · 本地安装向导`n  从仓库取得 Chives 源码，复用本机工具，缺少的组件从官方来源下载。"
        Write-Host '  共六步：检查本机 → 选择网络 → 下载源码 → 准备运行环境 → 安装依赖并构建 → 启动工作台'
        Show-Step 1 '检查平台和安装目录'
        if ($env:OS -ne 'Windows_NT') { throw 'Linux、macOS 和 WSL2 请运行 installer.sh' }
        $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
        switch ($arch) { 'AMD64' { $arch = 'x64' } 'ARM64' { $arch = 'x64'; Write-Host '    Windows ARM64 使用 Windows 11 的 x64 兼容运行环境。' } default { throw "暂不支持 $arch" } }
        $root = Join-Path $HOME '.chives'
        if ($env:CHIVES_INSTALL_HOME) { $root = $env:CHIVES_INSTALL_HOME }
        elseif (!(Test-Path -LiteralPath $root) -and (Test-Path -LiteralPath "$env:LOCALAPPDATA\Chives\releases")) { $root = "$env:LOCALAPPDATA\Chives" }
        if (![IO.Path]::IsPathRooted($root)) { throw '安装目录须为独立的绝对路径' }
        $root = [IO.Path]::GetFullPath($root)
        if ($root.TrimEnd('\') -in @($HOME.TrimEnd('\'), [IO.Path]::GetPathRoot($root).TrimEnd('\'))) { throw '请选择独立安装目录' }
        if ((Test-Path -LiteralPath "$root\.git") -or (Test-Path -LiteralPath "$root\package.json")) { throw "检测到源码安装 $root，请按 INSTALL.md 更新。" }
        Get-Command curl.exe, tar.exe -ErrorAction Stop | Out-Null
        Write-Host "    ✓ Windows/$arch · $root"
        $python = $null
        $probeCode = "import ctypes,ensurepip,platform,ssl,struct,sys,venv; print(sys.executable) if sys.implementation.name=='cpython' and sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 and ('arm64' if platform.machine().lower() in ('arm64','aarch64') else 'x64')==sys.argv[1] else sys.exit(1)"
        $pyDir = Join-Path $root "tools\cpython-3.12.13-20260510-windows-$arch"
        foreach ($cmd in @('py.exe','python3.12.exe','python.exe','python3.exe',"$pyDir\python.exe")) {
            $exe = Get-Command $cmd -ErrorAction SilentlyContinue | Select-Object -First 1
            if (!$exe -or $exe.Source -like '*\Microsoft\WindowsApps\python*.exe') { continue }
            $argsPy = @('-I', '-c', $probeCode, $arch)
            if ($cmd -eq 'py.exe') { $argsPy = @('-3.12') + $argsPy }
            $result = & $exe.Source @argsPy
            if ($LASTEXITCODE -eq 0 -and $result -and (Test-Path -LiteralPath $result)) { $python = $result; break }
        }
        if ($python) { Write-Host "    ✓ 复用 Python 3.12 · $python" } else { Write-Host '    缺少兼容的 Python 3.12，将从 Astral 的 CPython 分发下载。' }
        foreach ($tool in @('node.exe', 'npm.cmd', 'pnpm.cmd')) {
            $found = Get-Command $tool -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { Write-Host "    已检测到 $tool · $($found.Source)" }
            else { Write-Host "    $tool 未就绪，将按仓库要求补齐。" }
        }
        Show-Step 2 '验证通往 GitHub 的网络'
        $probe = "https://github.com/$repo"
        $systemProxy = $null
        try {
            $uri = [Net.WebRequest]::GetSystemWebProxy().GetProxy([uri]$probe)
            if ($uri.AbsoluteUri -ne $probe) { $systemProxy = $uri.AbsoluteUri }
        } catch {}
        $candidates = @($env:HTTPS_PROXY, $env:ALL_PROXY, $env:HTTP_PROXY, $systemProxy, 'http://127.0.0.1:7897', 'http://127.0.0.1:7890', 'http://127.0.0.1:10809', 'socks5h://127.0.0.1:1080')
        $route = '直连'
        foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
            # A non-matching NO_PROXY entry also works with legacy PowerShell's empty-argument handling.
            $via = @('--proxy', $candidate, '--noproxy', 'localhost,127.0.0.1')
            & curl.exe @networkArgs @via --connect-timeout 2 --max-time 4 -fILs -o NUL $probe
            if ($LASTEXITCODE -eq 0) { $routeArgs = $via; $route = '代理'; break }
        }
        Write-Host "    ✓ 已选择$route"
        Show-Step 3 '下载 GitHub main 分支源码'
        $tempDir = Join-Path $root ('.setup.' + [Guid]::NewGuid().ToString('N'))
        [IO.Directory]::CreateDirectory((Join-Path $root 'tools')) | Out-Null
        try {
            $installLock = [IO.File]::Open((Join-Path $root '.source-install.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
        } catch { throw '已有安装正在进行，请稍后重试。' }
        [IO.Directory]::CreateDirectory($tempDir) | Out-Null
        $archive = Join-Path $tempDir 'main.tar.gz'
        Get-Download "https://codeload.github.com/$repo/tar.gz/refs/heads/main" $archive 'Chives 源码'
        & tar.exe -xzf $archive -C $tempDir chives-main/deploy/installer/source.py chives-main/deploy/installer/install.py
        if ($LASTEXITCODE -ne 0) { throw '仓库安装引擎解包失败' }
        Write-Host '    ✓ 源码和安装引擎已就绪'
        Show-Step 4 '准备 Python、Node.js 和 npm'
        if (!$python) {
            $url = 'https://github.com/astral-sh/python-build-standalone/releases/download/20260510/cpython-3.12.13%2B20260510-x86_64-pc-windows-msvc-install_only_stripped.tar.gz'
            $pyArchive = Join-Path $tempDir 'python.tar.gz'
            Get-Download $url $pyArchive 'CPython 3.12'
            if ((Get-FileHash -LiteralPath $pyArchive -Algorithm SHA256).Hash -ne '24168aff2e7d93784c6a436124c4ebb79b076a4e289bde4902c08333507b71d0') { throw 'CPython 的 SHA-256 不匹配' }
            & tar.exe -xzf $pyArchive -C $tempDir
            if ($LASTEXITCODE -ne 0) { throw 'Python 解包失败' }
            if (Test-Path -LiteralPath $pyDir) { throw "已有无法使用的 Python 目录，请检查 $pyDir" }
            [IO.Directory]::Move("$tempDir\python", $pyDir)
            $python = "$pyDir\python.exe"
        }
        $env:CHIVES_SETUP_PROXY = if ($route -eq '代理') { $candidate } else { $null }
        $env:PYTHONUTF8 = '1'
        & $python -X utf8 -I -u "$tempDir\chives-main\deploy\installer\source.py" $root $archive "windows-$arch"
        if ($LASTEXITCODE -ne 0) { throw "Chives 安装程序退出码 $LASTEXITCODE，请查看上方提示。" }
    } finally {
        if ($installLock) { $installLock.Dispose() }
        $env:CHIVES_SETUP_PROXY = $oldProxy
        $env:PYTHONUTF8 = $oldUtf8
        if ($tempDir -and (Test-Path -LiteralPath $tempDir)) { Remove-Item -LiteralPath $tempDir -Recurse -Force }
    }
}
