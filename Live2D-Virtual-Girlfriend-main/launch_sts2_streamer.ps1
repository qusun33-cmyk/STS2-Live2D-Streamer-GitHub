param(
    [string]$RepoRoot = "F:\codex\workspace\Live2D-Virtual-Girlfriend-main",
    [string]$Sts2RepoRoot = "F:\codex\workspace\STS2-Agent-main",
    [string]$GameExe = "F:\SteamLibrary\steamapps\common\Slay the Spire 2\SlayTheSpire2.exe",
    [string]$GameRoot = "F:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [string]$AvatarConfigPath = "F:\codex\workspace\Live2D-Virtual-Girlfriend-main\config.sts2_streamer.toml",
    [string]$StreamerConfigPath = "F:\codex\workspace\Live2D-Virtual-Girlfriend-main\integrations\sts2_streamer\config.toml",
    [string]$PythonExe = "C:\Users\YTSM\AppData\Roaming\uv\python\cpython-3.11.12-windows-x86_64-none\python.exe",
    [string]$VenvPath = "F:\codex\workspace\Live2D-Virtual-Girlfriend-main\.venv-sts2-streamer",
    [switch]$BuildMod,
    [string]$DotnetRoot = "F:\codex\tools\dotnet9",
    [string]$GodotExe = "F:\codex\tools\Godot_v4.5.1-stable_mono_win64\Godot_v4.5.1-stable_mono_win64\Godot_v4.5.1-stable_mono_win64_console.exe"
)

$ErrorActionPreference = "Stop"

function Ensure-Config {
    param([string]$TargetPath, [string]$ExamplePath)
    if (-not (Test-Path -LiteralPath $TargetPath)) {
        Copy-Item -LiteralPath $ExamplePath -Destination $TargetPath -Force
    }
}

function Ensure-Venv {
    if (-not (Test-Path -LiteralPath $VenvPath)) {
        uv venv $VenvPath --python $PythonExe
    }

    $venvPython = Join-Path $VenvPath "Scripts\python.exe"
    uv pip install --python $venvPython -r (Join-Path $RepoRoot "requirements.sts2_streamer.txt")
    return $venvPython
}

if ($BuildMod) {
    $env:PATH = "$DotnetRoot;$env:PATH"
    $env:STS2_DATA_DIR = Join-Path $GameRoot "data_sts2_windows_x86_64"
    powershell -ExecutionPolicy Bypass -File (Join-Path $Sts2RepoRoot "scripts\build-mod.ps1") `
        -Configuration Debug `
        -ProjectRoot $Sts2RepoRoot `
        -GameRoot $GameRoot `
        -GodotExe $GodotExe
}

$venvPython = Ensure-Venv

if (-not (Test-Path -LiteralPath $GameExe)) {
    throw "Game executable not found: $GameExe"
}

try {
    Invoke-WebRequest -Uri "http://127.0.0.1:8080/health" -UseBasicParsing -TimeoutSec 3 | Out-Null
} catch {
    powershell -ExecutionPolicy Bypass -File (Join-Path $Sts2RepoRoot "scripts\start-game-session.ps1") -ExePath $GameExe | Out-Null
}

$env:LIVE2D_CONFIG_PATH = $AvatarConfigPath
Push-Location $RepoRoot
try {
    & $venvPython (Join-Path $RepoRoot "main_sts2_streamer.py")
}
finally {
    Pop-Location
}
