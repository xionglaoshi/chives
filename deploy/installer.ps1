# Windows PowerShell 5.1 and PowerShell 7. All state is local to this invocation.
& {
    $ErrorActionPreference = 'Stop'
    $repo = 'xionglaoshi/chives'
    $tempDir = $null
    $routeArgs = @('--noproxy', '*')
    $networkArgs = @('-q', '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '8')
    function Show-Step([int]$number, [string]$title) {
        $bar = ('#' * ($number - 1)) + ('-' * (7 - $number))
        Write-Host ("`n  [{0}/6] [{1}] {2}%  {3}" -f $number, $bar, [math]::Floor(($number-1)*100/6), $title)
    }
    function Get-Bundle([string]$name) {
        $sum = & curl.exe @networkArgs @routeArgs -fsSL --retry 2 "$base/$name.sha256"
        if ($LASTEXITCODE -ne 0 -or [string]$sum -notmatch '^([a-f0-9]{64})(?:\s|$)') { throw "GitHub 缺少有效的 $name 校验文件，请检查发行版 $tag。" }
        $digest = $Matches[1]
        $path = Join-Path $cache "$digest-$name"
        if ((Test-Path -LiteralPath $path -PathType Leaf) -and ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -eq $digest)) {
            Write-Host "    ✓ 复用已校验的 $name"
            return $path
        }
        Write-Host "    下载 $name（curl 显示百分比、已收字节及当前速率）"
        $file = Join-Path $tempDir $name
        & curl.exe @networkArgs @routeArgs -fL --retry 2 --speed-time 60 --speed-limit 1 -o $file -w '\n    %{size_download} bytes, %{speed_download} B/s\n' "$base/$name" | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "$name 下载失败，可重新运行向导。" }
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $digest) { throw "$name 的 SHA-256 不匹配" }
        Move-Item -LiteralPath $file -Destination $path -Force
        return $path
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
        Write-Host "`n  老韭菜 · 本地安装向导`n  将从 GitHub 安装 Chives 工作台、DSH、Python、Node.js 和 Chromium。"
        Write-Host '  共六步：检查本机 → 选择网络 → 下载校验 → 解包 → 配置环境 → 启动工作台'
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
        foreach ($cmd in @('py.exe','python3.12.exe','python.exe','python3.exe')) {
            $exe = Get-Command $cmd -ErrorAction SilentlyContinue | Select-Object -First 1
            if (!$exe -or $exe.Source -like '*\Microsoft\WindowsApps\python*.exe') { continue }
            $argsPy = @('-I', '-c', $probeCode, $arch)
            if ($cmd -eq 'py.exe') { $argsPy = @('-3.12') + $argsPy }
            $result = & $exe.Source @argsPy
            if ($LASTEXITCODE -eq 0 -and $result -and (Test-Path -LiteralPath $result)) { $python = $result; break }
        }
        if ($python) { Write-Host "    ✓ 复用 Python 3.12 · $python" } else { Write-Host '    缺少兼容的 Python 3.12，将使用 GitHub 运行时。' }
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
        $tag = & curl.exe @networkArgs @routeArgs -fsSL --retry 2 --max-time 30 "https://raw.githubusercontent.com/$repo/main/deploy/installer/channel"
        if ($LASTEXITCODE -ne 0) { throw '无法从 GitHub 读取发布清单，请检查网络和 main 分支的安装入口。' }
        if ($tag -ceq 'disabled') { throw '维护者已暂停便捷安装' }
        if ($tag -cnotmatch '^installer-[0-9]+(\.[0-9]+)+$') { throw 'GitHub 发布清单格式错误' }
        $base = "https://github.com/$repo/releases/download/$tag"
        Write-Host "    ✓ GitHub $route · $tag"
        Show-Step 3 '下载并验证平台文件'
        $cache = Join-Path $root 'cache\installer'
        $tempDir = Join-Path $root ('.setup.' + [Guid]::NewGuid().ToString('N'))
        [IO.Directory]::CreateDirectory($cache) | Out-Null
        [IO.Directory]::CreateDirectory($tempDir) | Out-Null
        $boot = Get-Bundle "bootstrap-windows-$arch.tar.gz"
        & tar.exe -xzf $boot -C $tempDir
        if ($LASTEXITCODE -ne 0) { throw '安装工具解包失败' }
        $existingPython = Join-Path $root "releases\$tag-windows-$arch\python\python.exe"
        if (!$python -and (Test-Path -LiteralPath $existingPython -PathType Leaf)) {
            $python = $existingPython
            Write-Host '    ✓ 复用 Chives 已安装的 Python'
        }
        if (!$python) {
            $archive = Get-Bundle "python-windows-$arch.tar.gz"
            & tar.exe -xzf $archive -C $tempDir
            if ($LASTEXITCODE -ne 0) { throw 'Python 解包失败' }
            $python = "$tempDir\python\python.exe"
        }
        $env:CHIVES_SETUP_PROXY = if ($route -eq '代理') { $candidate } else { $null }
        $env:PYTHONUTF8 = '1'
        & $python -X utf8 -I -u "$tempDir\install.py" install $root $tag "windows-$arch"
        if ($LASTEXITCODE -ne 0) { throw "Chives 安装程序退出码 $LASTEXITCODE，请查看上方提示。" }
    } finally {
        $env:CHIVES_SETUP_PROXY = $oldProxy
        $env:PYTHONUTF8 = $oldUtf8
        if ($tempDir -and (Test-Path -LiteralPath $tempDir)) { Remove-Item -LiteralPath $tempDir -Recurse -Force }
    }
}
