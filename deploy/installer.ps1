# ASCII entry point for both Windows PowerShell 5.1 and PowerShell 7.
& {
    param($entryPath)
    $ErrorActionPreference = 'Stop'
    if ($entryPath) {
        $local = Join-Path (Split-Path -Parent $entryPath) 'installer/windows.ps1'
        if (Test-Path -LiteralPath $local -PathType Leaf) { & $local; return }
    }
    $url = 'https://raw.githubusercontent.com/xionglaoshi/chives/main/deploy/installer/windows.ps1'
    $response = Invoke-WebRequest -UseBasicParsing -Uri $url -ErrorAction Stop
    $source = [Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray()).TrimStart([char]0xFEFF)
    & ([ScriptBlock]::Create($source))
} $MyInvocation.MyCommand.Path
