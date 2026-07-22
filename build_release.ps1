$ErrorActionPreference = 'Stop'

$repoRoot = $PSScriptRoot
$initContent = Get-Content -LiteralPath (Join-Path $repoRoot '__init__.py') -Raw
$versionMatch = [regex]::Match(
    $initContent,
    '(?m)["'']version["'']\s*:\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)'
)
if (-not $versionMatch.Success) {
    throw 'Could not read bl_info.version from __init__.py'
}

$version = '{0}.{1}.{2}' -f $versionMatch.Groups[1].Value,
    $versionMatch.Groups[2].Value,
    $versionMatch.Groups[3].Value
$releaseDirectory = Join-Path $repoRoot 'releases'
$archivePath = Join-Path $releaseDirectory ("QuickSnap-$version.zip")
$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    'quicksnap-release-' + [guid]::NewGuid().ToString('N')
)
$addonRoot = Join-Path $stageRoot 'QuickSnap'

$runtimeFiles = @(
    '__init__.py',
    'addon_updater.py',
    'addon_updater_ops.py',
    'CHANGELOG.md',
    'LICENSE.md',
    'README.md',
    'quicksnap.py',
    'quicksnap_render.py',
    'quicksnap_shader_gpu_module.py',
    'quicksnap_shader_legacy.py',
    'quicksnap_snapdata.py',
    'quicksnap_utils.py'
)
$requiredEntries = @(
    'QuickSnap/__init__.py',
    'QuickSnap/quicksnap.py',
    'QuickSnap/quicksnap_utils.py',
    'QuickSnap/quicksnap_snapdata.py',
    'QuickSnap/icons/QUICKSNAP_POINTS.tif'
)

try {
    New-Item -ItemType Directory -Path $addonRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $releaseDirectory -Force | Out-Null

    foreach ($file in $runtimeFiles) {
        Copy-Item -LiteralPath (Join-Path $repoRoot $file) -Destination $addonRoot
    }
    $stageIcons = Join-Path $addonRoot 'icons'
    New-Item -ItemType Directory -Path $stageIcons | Out-Null
    Copy-Item -Path (Join-Path $repoRoot 'icons\*.tif') -Destination $stageIcons

    if (Test-Path -LiteralPath $archivePath) {
        Remove-Item -LiteralPath $archivePath
    }
    Compress-Archive -LiteralPath $addonRoot -DestinationPath $archivePath -CompressionLevel Optimal

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        $entries = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
        foreach ($required in $requiredEntries) {
            if ($entries -notcontains $required) {
                throw "Release archive is missing $required"
            }
        }
    }
    finally {
        $archive.Dispose()
    }

    Write-Output "Built and validated: $archivePath"
}
finally {
    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
}
