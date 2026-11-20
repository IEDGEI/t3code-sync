param(
    [string]$InstallDir,
    [string]$T3Exe,
    [string]$PythonExe,
    [string]$NodeExe,
    [string]$T3Home,
    [string]$CodexHome,
    [string]$ShortcutDir,
    [switch]$SkipExistingShortcuts,
    [switch]$Preview
)
$ErrorActionPreference = 'Stop'
$sourceDir = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$codeDir = Join-Path $sourceDir 'src'
. (Join-Path $PSScriptRoot 'shortcut.ps1')

function Resolve-Executable([string]$Given, [string]$CommandName, [string[]]$Fallbacks) {
    if ($Given) {
        if (-not (Test-Path -LiteralPath $Given -PathType Leaf)) { throw "Executable not found: $Given" }
        return (Resolve-Path -LiteralPath $Given).Path
    }
    $paths = @((Get-Command $CommandName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)) + $Fallbacks
    foreach ($path in $paths) {
        if ($path -and $path -notlike '*\Microsoft\WindowsApps\*' -and (Test-Path -LiteralPath $path -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $path).Path
        }
    }
    throw "$CommandName was not found. Install its runtime or specify its executable path."
}

function Resolve-T3Executable([string]$Given, [string]$T3DataRoot) {
    if ($Given) {
        if (-not (Test-Path -LiteralPath $Given -PathType Leaf)) { throw "T3 executable not found: $Given" }
        return (Resolve-Path -LiteralPath $Given).Path
    }
    $candidates = New-Object 'System.Collections.Generic.List[string]'
    $commandFile = Join-Path $T3DataRoot 'bin\t3.cmd'
    if (Test-Path -LiteralPath $commandFile) {
        $text = Get-Content -LiteralPath $commandFile -Raw -Encoding UTF8
        foreach ($match in [regex]::Matches($text, '(?im)^if exist "([^"]+\.exe)" goto run\s*$')) {
            $candidates.Add($match.Groups[1].Value)
        }
    }
    $launcherTargets = @($candidates | Where-Object { $_ -and ([IO.Path]::GetFileName($_) -like 'T3 Code*.exe') -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Sort-Object -Unique)
    if ($launcherTargets.Count -eq 1) { return (Resolve-Path -LiteralPath $launcherTargets[0]).Path }
    if ($launcherTargets.Count -gt 1) { throw 'The T3 launcher names several executables. Specify -T3Exe explicitly.' }
    foreach ($process in @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'T3 Code*' })) {
        try { if ($process.Path) { $candidates.Add($process.Path) } } catch {}
    }
    foreach ($folder in @('T3 Code (Beta)', 'T3 Code', 't3code')) {
        foreach ($filename in @('T3 Code (Beta).exe', 'T3 Code.exe')) {
            $candidates.Add((Join-Path $env:LOCALAPPDATA "Programs\$folder\$filename"))
        }
    }
    foreach ($registryRoot in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall')) {
        foreach ($entry in @(Get-ItemProperty -Path "$registryRoot\*" -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like 'T3 Code*' })) {
            if ($entry.DisplayIcon -match '^"?(.+?\.exe)"?(?:,\d+)?$') { $candidates.Add($Matches[1]) }
            if ($entry.InstallLocation) { $candidates.Add((Join-Path $entry.InstallLocation 'T3 Code (Beta).exe')) }
        }
    }
    foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
        if (-not $folder -or -not (Test-Path -LiteralPath $folder)) { continue }
        foreach ($link in @(Get-ChildItem -LiteralPath $folder -Filter '*T3*.lnk' -File -Recurse -ErrorAction SilentlyContinue)) {
            $shortcut = Read-T3Shortcut $link.FullName
            foreach ($value in @($shortcut.TargetPath, $shortcut.IconLocation)) {
                if ($value -match '^"?(.+?T3 Code[^\\]*\.exe)"?(?:,\d+)?$') { $candidates.Add($Matches[1]) }
            }
        }
    }
    $found = @($candidates | Where-Object { $_ -and ([IO.Path]::GetFileName($_) -like 'T3 Code*.exe') -and (Test-Path -LiteralPath $_ -PathType Leaf) } | ForEach-Object { (Resolve-Path -LiteralPath $_).Path } | Sort-Object -Unique)
    if ($found.Count -eq 0) { throw 'T3 Code was not found. Open T3 once, or specify -T3Exe "C:\path\T3 Code (Beta).exe".' }
    if ($found.Count -gt 1) { throw ('Several T3 installations were found. Specify -T3Exe: ' + ($found -join ', ')) }
    return $found[0]
}

if (-not $T3Home) { $T3Home = if ($env:T3CODE_HOME) { $env:T3CODE_HOME } else { Join-Path $env:USERPROFILE '.t3' } }
if (-not $CodexHome) { $CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' } }
$T3Home = [IO.Path]::GetFullPath($T3Home)
$CodexHome = [IO.Path]::GetFullPath($CodexHome)
if (-not $InstallDir) { $InstallDir = Join-Path $T3Home 'tools\codex-autosync' }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$pythonFallbacks = @(Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe') -File -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName)
$PythonExe = Resolve-Executable -Given $PythonExe -CommandName 'python.exe' -Fallbacks $pythonFallbacks
$pythonwExe = Join-Path (Split-Path -Parent $PythonExe) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwExe)) { throw 'pythonw.exe is required alongside python.exe.' }
$NodeExe = Resolve-Executable -Given $NodeExe -CommandName 'node.exe' -Fallbacks @((Join-Path $env:ProgramFiles 'nodejs\node.exe'))
$T3Exe = Resolve-T3Executable -Given $T3Exe -T3DataRoot $T3Home

$pythonInfo = & $PythonExe -B -c 'import json,sys; print(json.dumps(list(sys.version_info[:3])))'
if ($LASTEXITCODE -ne 0) { throw 'Python could not start.' }
$pythonVersion = $pythonInfo | ConvertFrom-Json
if ($pythonVersion[0] -lt 3 -or ($pythonVersion[0] -eq 3 -and $pythonVersion[1] -lt 9)) { throw 'Python 3.9 or newer is required.' }
$previousWarnings = $env:NODE_NO_WARNINGS
try {
    $env:NODE_NO_WARNINGS = '1'
    $nodeInfo = & $NodeExe (Join-Path $PSScriptRoot 'check-runtime.cjs')
    if ($LASTEXITCODE -ne 0) { throw 'Node.js 22.13+ with node:sqlite is required.' }
    $nodeVersion = $nodeInfo | ConvertFrom-Json
    if ([version]$nodeVersion.node -lt [version]'22.13.0' -or [version]$nodeVersion.sqlite -lt [version]'3.43.0') { throw 'A newer Node.js runtime is required.' }
} finally { $env:NODE_NO_WARNINGS = $previousWarnings }

$database = Join-Path $T3Home 'userdata\statev2.sqlite'
if (-not (Test-Path -LiteralPath $database -PathType Leaf)) { throw 'Open T3 and import the desired Codex conversations before installing auto-sync.' }
if (-not (Test-Path -LiteralPath (Join-Path $CodexHome 'state_5.sqlite') -PathType Leaf)) { throw 'Local Codex history was not found. Open Codex first, or specify -CodexHome.' }
$schemaResult = & $PythonExe -B -c 'import sys,pathlib;sys.path.insert(0,sys.argv[1]);import autosync;db=autosync.readonly(pathlib.Path(sys.argv[2]));autosync.verify_schema(db);db.close();print(True)' $codeDir $database
if ($LASTEXITCODE -ne 0) { throw 'Unsupported T3 database schema. Nothing was installed or changed.' }
if ($schemaResult -ne 'True') { throw 'T3 compatibility check returned an unexpected result.' }

if (-not $ShortcutDir) { $ShortcutDir = [Environment]::GetFolderPath('Desktop') }
if (-not $ShortcutDir -or -not (Test-Path -LiteralPath $ShortcutDir -PathType Container)) { throw 'The shortcut folder could not be located.' }
$ShortcutDir = [IO.Path]::GetFullPath($ShortcutDir)
$desktopShortcut = Join-Path $ShortcutDir 'T3 Code (Auto Sync).lnk'
$stateDir = Join-Path $T3Home 'codex-autosync'
$config = [ordered]@{ t3_home=$T3Home; t3_exe=$T3Exe; codex_home=$CodexHome; state_dir=$stateDir; node_exe=$NodeExe }
$shortcutPaths = New-Object 'System.Collections.Generic.List[string]'
$shortcutPaths.Add($desktopShortcut)
if (-not $SkipExistingShortcuts) {
    foreach ($folder in @($ShortcutDir, (Split-Path -Parent $T3Exe))) {
        foreach ($link in @(Get-ChildItem -LiteralPath $folder -Filter '*.lnk' -File -ErrorAction SilentlyContinue)) {
            $shortcut = Read-T3Shortcut $link.FullName
            if ($shortcut.TargetPath -eq $T3Exe -and -not $shortcut.Arguments) { $shortcutPaths.Add($link.FullName) }
        }
    }
}
$shortcutPaths = @($shortcutPaths | Sort-Object -Unique)
if ($Preview) {
    [ordered]@{ preview=$true; installDir=$InstallDir; python=$pythonwExe; node=$nodeVersion; shortcuts=$shortcutPaths; config=$config } | ConvertTo-Json -Depth 5
    exit 0
}

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$installFiles = [ordered]@{
    'src\autosync.py'='autosync.py'; 'src\writer.cjs'='writer.cjs';
    'README.md'='README.md'; 'README.ko.md'='README.ko.md'; 'LICENSE'='LICENSE';
    'docs\THIRD_PARTY_NOTICES.md'='docs\THIRD_PARTY_NOTICES.md';
    'licenses\T3-CODE-MIT.txt'='licenses\T3-CODE-MIT.txt';
    'docs\RECOVERY.md'='docs\RECOVERY.md'
}
foreach ($entry in $installFiles.GetEnumerator()) {
    $source = Join-Path $sourceDir $entry.Key
    $destination = Join-Path $InstallDir $entry.Value
    if ([IO.Path]::GetFullPath($source) -ne [IO.Path]::GetFullPath($destination)) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $InstallDir 'config.json'), ($config | ConvertTo-Json), $utf8)
$backupDir = Join-Path $stateDir 'shortcut-backups'
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
foreach ($shortcutPath in $shortcutPaths) {
    if (Test-Path -LiteralPath $shortcutPath) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-ffff'
        Copy-Item -LiteralPath $shortcutPath -Destination (Join-Path $backupDir "$stamp-$([IO.Path]::GetFileName($shortcutPath))")
    }
    $arguments = '"' + (Join-Path $InstallDir 'autosync.py') + '" --launch'
    [T3Sync.Shortcuts]::Save($shortcutPath, $pythonwExe, $arguments, $InstallDir, $T3Exe)
}
[ordered]@{ installed=$InstallDir; desktopShortcut=$desktopShortcut; shortcuts=$shortcutPaths; state=$stateDir; shortcutBackups=$backupDir } | ConvertTo-Json -Depth 4
