param(
    [string]$ExePath = "C:/Program Files (x86)/Steam/steamapps/common/Slay the Spire 2/SlayTheSpire2.exe",
    [int]$Attempts = 40,
    [int]$DelaySeconds = 2,
    [switch]$EnableDebugActions,
    [int]$ApiPort = 8080,
    [switch]$KeepExistingProcesses,
    [string]$AppId = "2868840",
    [switch]$SkipSteamAppIdFile,
    [switch]$DisableSteamLaunch,
    [string]$SteamExecutablePath = ""
)

$ErrorActionPreference = "Stop"

function Wait-ForHealth {
    param(
        [int]$MaxAttempts,
        [int]$SleepSeconds,
        [System.Diagnostics.Process]$Process = $null,
        [string]$BaseUrl,
        [scriptblock]$FailureProbe = $null
    )

    for ($i = 0; $i -lt $MaxAttempts; $i++) {
        Start-Sleep -Seconds $SleepSeconds

        if ($null -ne $FailureProbe) {
            $failure = & $FailureProbe
            if ($failure) {
                throw $failure
            }
        }

        try {
            $response = Invoke-WebRequest -Uri ($BaseUrl.TrimEnd("/") + "/health") -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                return
            }
        } catch {
        }

        if ($null -ne $Process) {
            try {
                if ($Process.HasExited) {
                    throw "Game process exited before /health became ready."
                }
            } catch [System.InvalidOperationException] {
            }
        }
    }

    if ($null -ne $FailureProbe) {
        $failure = & $FailureProbe
        if ($failure) {
            throw $failure
        }
    }

    throw "Timed out waiting for /health."
}

function Wait-ForPortRelease {
    param(
        [int]$MaxAttempts,
        [int]$SleepSeconds,
        [int]$Port
    )

    for ($i = 0; $i -lt $MaxAttempts; $i++) {
        try {
            $listenerActive = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop).Count -gt 0
        } catch {
            $listenerActive = $false
        }

        if (-not $listenerActive) {
            return
        }

        Start-Sleep -Seconds $SleepSeconds
    }
}

function Ensure-SteamAppIdFile {
    param(
        [string]$GameRoot,
        [string]$AppId,
        [switch]$SkipSteamAppIdFile
    )

    if ($SkipSteamAppIdFile) {
        return
    }

    $appIdFile = Join-Path $GameRoot "steam_appid.txt"
    if (-not (Test-Path $appIdFile) -or ((Get-Content -Path $appIdFile -Raw).Trim() -ne $AppId)) {
        Set-Content -Path $appIdFile -Value $AppId -Encoding ascii -NoNewline
    }
}

function Enable-ModsInSettings {
    $roots = @(
        (Join-Path $env:APPDATA "SlayTheSpire2\steam"),
        (Join-Path $env:APPDATA "SlayTheSpire2\default")
    )

    foreach ($root in $roots) {
        if (-not (Test-Path $root)) {
            continue
        }

        Get-ChildItem -Path $root -Recurse -Filter settings.save -File -ErrorAction SilentlyContinue | ForEach-Object {
            try {
                $json = Get-Content -Path $_.FullName -Raw | ConvertFrom-Json
                $json.mod_settings = [pscustomobject]@{ mods_enabled = $true }
                $json | ConvertTo-Json -Depth 20 | Set-Content -Path $_.FullName -Encoding utf8
            } catch {
            }
        }
    }
}

function Get-SteamExecutable {
    param([string]$PreferredPath)

    $candidates = @()
    if ($PreferredPath) {
        $candidates += $PreferredPath
    }

    foreach ($registryPath in @("HKCU:\Software\Valve\Steam", "HKLM:\Software\WOW6432Node\Valve\Steam")) {
        if (-not (Test-Path $registryPath)) {
            continue
        }
        foreach ($propertyName in @("SteamExe", "SteamPath", "InstallPath")) {
            try {
                $value = (Get-ItemProperty -Path $registryPath -Name $propertyName -ErrorAction Stop).$propertyName
                if ($value) {
                    if ($value -like "*.exe") {
                        $candidates += $value
                    } else {
                        $candidates += (Join-Path $value "steam.exe")
                    }
                }
            } catch {
            }
        }
    }

    $candidates += @(
        "C:\Program Files (x86)\Steam\steam.exe",
        "C:\Program Files\Steam\steam.exe"
    )

    foreach ($candidate in $candidates | Where-Object { $_ }) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return ""
}

function Get-LatestGameProcess {
    param([string]$ProcessName = "SlayTheSpire2")

    try {
        return Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Sort-Object StartTime -Descending | Select-Object -First 1
    } catch {
        return $null
    }
}

function Wait-ForGameProcess {
    param(
        [datetime]$NotBefore,
        [int]$MaxAttempts = 20,
        [int]$SleepSeconds = 1,
        [string]$ProcessName = "SlayTheSpire2"
    )

    for ($i = 0; $i -lt $MaxAttempts; $i++) {
        $proc = Get-LatestGameProcess -ProcessName $ProcessName
        if ($null -ne $proc) {
            if ($proc.StartTime -ge $NotBefore.AddSeconds(-2)) {
                return $proc
            }
        }
        Start-Sleep -Seconds $SleepSeconds
    }

    return $null
}

function Get-LatestGodotLog {
    $logDir = Join-Path $env:APPDATA "SlayTheSpire2\logs"
    if (-not (Test-Path $logDir)) {
        return $null
    }

    try {
        return Get-ChildItem -Path $logDir -Filter "godot*.log" -File -ErrorAction Stop |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
    } catch {
        return $null
    }
}

function Get-StartupFailureSummary {
    param(
        [string]$BaseUrl,
        [datetime]$NotBefore
    )

    $logFile = Get-LatestGodotLog
    if ($null -eq $logFile) {
        return $null
    }
    if ($logFile.LastWriteTime -lt $NotBefore.AddSeconds(-2)) {
        return $null
    }

    try {
        $logText = Get-Content -Path $logFile.FullName -Raw -Encoding utf8
    } catch {
        return $null
    }

    $summary = $null
    if ($logText -match "No appID found") {
        $summary = "Game startup failed: Steamworks could not find a valid app ID for this launch."
    } elseif ($logText -match "Steam remote storage async read request returned invalid API call") {
        $summary = "Game startup failed: Steam cloud storage returned an invalid API call while reading profile.save."
    } elseif ($logText -match "Encountered error on game startup") {
        $summary = "Game startup failed during initialization. Check the latest godot log for details."
    }

    if (-not $summary) {
        return $null
    }

    try {
        $stateResponse = Invoke-RestMethod -Uri ($BaseUrl.TrimEnd("/") + "/state") -TimeoutSec 2
        $state = if ($stateResponse.data) { $stateResponse.data } else { $stateResponse }
        if ($state.screen -eq "MODAL") {
            return $summary
        }
    } catch {
        return $summary
    }

    return $null
}

function Start-GameViaSteam {
    param(
        [string]$AppId,
        [string]$SteamExecutablePath
    )

    $steamExe = Get-SteamExecutable -PreferredPath $SteamExecutablePath
    $launchStartedAt = Get-Date

    if ($steamExe) {
        Start-Process -FilePath $steamExe -ArgumentList @("-applaunch", $AppId) | Out-Null
        $proc = Wait-ForGameProcess -NotBefore $launchStartedAt -MaxAttempts 12 -SleepSeconds 1
        if ($null -ne $proc) {
            return $proc
        }

        try {
            Start-Process -FilePath $steamExe -ArgumentList @("--", "steam://rungameid/$AppId") | Out-Null
        } catch {
        }
        $proc = Wait-ForGameProcess -NotBefore $launchStartedAt -MaxAttempts 12 -SleepSeconds 1
        if ($null -ne $proc) {
            return $proc
        }
    }

    try {
        Start-Process -FilePath "explorer.exe" -ArgumentList @("steam://rungameid/$AppId") | Out-Null
        $proc = Wait-ForGameProcess -NotBefore $launchStartedAt -MaxAttempts 12 -SleepSeconds 1
        if ($null -ne $proc) {
            return $proc
        }
    } catch {
    }

    return $null
}

$baseUrl = "http://127.0.0.1:$ApiPort"
$gameRoot = Split-Path -Path $ExePath -Parent

Ensure-SteamAppIdFile -GameRoot $gameRoot -AppId $AppId -SkipSteamAppIdFile:$SkipSteamAppIdFile
Enable-ModsInSettings

if (-not $KeepExistingProcesses) {
    $existing = Get-Process -Name "SlayTheSpire2" -ErrorAction SilentlyContinue
    if ($existing) {
        Stop-Process -Id $existing.Id -Force
        Start-Sleep -Seconds 2
        Wait-ForPortRelease -MaxAttempts 10 -SleepSeconds 1 -Port $ApiPort
    }
}

$proc = $null
$launchMode = "direct_exe"
$canUseSteamLaunch = (-not $DisableSteamLaunch) -and (-not $EnableDebugActions) -and ($ApiPort -eq 8080)
$launchStartedAt = Get-Date

if ($canUseSteamLaunch) {
    $proc = Start-GameViaSteam -AppId $AppId -SteamExecutablePath $SteamExecutablePath
    if ($null -ne $proc) {
        $launchMode = "steam"
    } else {
        $proc = $null
        $launchMode = "direct_exe_fallback"
    }
}

if ($launchMode -ne "steam") {
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $ExePath
    $startInfo.WorkingDirectory = $gameRoot
    $startInfo.UseShellExecute = $false

    if ($EnableDebugActions) {
        $startInfo.EnvironmentVariables["STS2_ENABLE_DEBUG_ACTIONS"] = "1"
    } else {
        $startInfo.EnvironmentVariables.Remove("STS2_ENABLE_DEBUG_ACTIONS")
    }

    $startInfo.EnvironmentVariables["STS2_API_PORT"] = [string]$ApiPort
    $startInfo.EnvironmentVariables["SteamAppId"] = $AppId
    $startInfo.EnvironmentVariables["SteamGameId"] = $AppId
    $startInfo.EnvironmentVariables["STEAM_APP_ID"] = $AppId
    $proc = [System.Diagnostics.Process]::Start($startInfo)
}

Wait-ForHealth `
    -MaxAttempts $Attempts `
    -SleepSeconds $DelaySeconds `
    -Process $proc `
    -BaseUrl $baseUrl `
    -FailureProbe { Get-StartupFailureSummary -BaseUrl $baseUrl -NotBefore $launchStartedAt }

if ($null -eq $proc) {
    try {
        $proc = Get-Process -Name "SlayTheSpire2" -ErrorAction SilentlyContinue | Sort-Object StartTime -Descending | Select-Object -First 1
    } catch {
        $proc = $null
    }
}

[pscustomobject]@{
    pid = if ($proc) { $proc.Id } else { $null }
    launch_mode = $launchMode
    debug_actions_enabled = [bool]$EnableDebugActions
    api_port = $ApiPort
    base_url = $baseUrl
    health = "ready"
} | ConvertTo-Json -Compress
