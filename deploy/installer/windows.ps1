& {
    $ErrorActionPreference = 'Stop'
    if ($PSCommandPath) {
        $entry = Join-Path (Split-Path $PSCommandPath) '..\installer.ps1'
        if (Test-Path -LiteralPath $entry) { & $entry; return }
    }
    Invoke-Expression (Invoke-RestMethod -ErrorAction Stop 'https://raw.githubusercontent.com/xionglaoshi/chives/main/deploy/installer.ps1')
}
