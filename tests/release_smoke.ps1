param(
    [string] $Executable = (Join-Path $PSScriptRoot '..\dist\LunaGrammar.exe'),
    [switch] $CheckApi,
    [string] $MetricsOutput
)

$ErrorActionPreference = 'Stop'
$binary = (Resolve-Path -LiteralPath $Executable).Path
$previousLocalAppData = $env:LOCALAPPDATA
$workingFolder = [IO.Path]::GetTempPath()
$env:LOCALAPPDATA = Join-Path $workingFolder ("LunaReleaseTest-" + [guid]::NewGuid())
$logPath = Join-Path $env:LOCALAPPDATA 'LunaGrammar\luna-grammar.log'
$metrics = @()

function Invoke-Luna([string[]] $Arguments) {
    $command = Start-Process -FilePath $binary -ArgumentList $Arguments -WorkingDirectory $workingFolder -PassThru -Wait -WindowStyle Hidden
    return $command.ExitCode
}

try {
    if ((Invoke-Luna @('--check', '--diagnostic')) -ne 0) {
        throw "Packaged local setup check failed. See $logPath"
    }
    if ($CheckApi -and (Invoke-Luna @('--check-api', '--diagnostic')) -ne 0) {
        throw "Packaged model metadata check failed. See $logPath"
    }
    for ($cycle = 1; $cycle -le 2; $cycle++) {
        $priorReady = @(Select-String -LiteralPath $logPath -Pattern 'Luna Grammar is listening').Count
        $startupTimer = [Diagnostics.Stopwatch]::StartNew()
        $listener = Start-Process -FilePath $binary -ArgumentList '--diagnostic' -WorkingDirectory $workingFolder -PassThru -WindowStyle Hidden
        $ready = $false
        try {
            $deadline = [DateTime]::UtcNow.AddSeconds(25)
            do {
                $listener.Refresh()
                if ($listener.HasExited) { throw "Listener exited early. See $logPath" }
                $ready = @(Select-String -LiteralPath $logPath -Pattern 'Luna Grammar is listening').Count -gt $priorReady
                if (-not $ready) { Start-Sleep -Milliseconds 150 }
            } until ($ready -or [DateTime]::UtcNow -gt $deadline)
            if (-not $ready) { throw "Listener did not register the shortcut. See $logPath" }
            $startupTimer.Stop()
            $idleTimer = [Diagnostics.Stopwatch]::StartNew()
            $beforeCpu = (Get-Process -Name LunaGrammar | ForEach-Object { $_.TotalProcessorTime.TotalMilliseconds } | Measure-Object -Sum).Sum
            Start-Sleep -Milliseconds 1500
            $idleTimer.Stop()
            $afterProcesses = @(Get-Process -Name LunaGrammar)
            $afterCpu = ($afterProcesses | ForEach-Object { $_.TotalProcessorTime.TotalMilliseconds } | Measure-Object -Sum).Sum
            $workingBytes = ($afterProcesses | Measure-Object -Property WorkingSet64 -Sum).Sum
            $metrics += [pscustomobject]@{
                cycle = $cycle
                startup_ready_ms = [Math]::Round($startupTimer.Elapsed.TotalMilliseconds, 2)
                idle_cpu_one_core_percent = [Math]::Round(100 * ($afterCpu - $beforeCpu) / $idleTimer.Elapsed.TotalMilliseconds, 3)
                working_set_mib = [Math]::Round($workingBytes / 1MB, 2)
                process_count = $afterProcesses.Count
            }
            if ((Invoke-Luna @('--diagnostic')) -ne 1) {
                throw "Duplicate instance was not rejected. See $logPath"
            }
            if (-not (Select-String -LiteralPath $logPath -Pattern 'Luna Grammar is already running')) {
                throw "Duplicate exit was not attributed to the mutex. See $logPath"
            }
        } finally {
            $listener.Refresh()
            if ($ready -and -not $listener.HasExited) {
                if ((Invoke-Luna @('--stop')) -ne 0 -or -not $listener.WaitForExit(20000)) {
                    throw "Listener did not exit after stop. See $logPath"
                }
            }
        }
        if ($listener.ExitCode -ne 0) { throw "Unclean listener exit. See $logPath" }
    }
    if ((Invoke-Luna @('--check')) -ne 0) { throw "Hotkey was not released. See $logPath" }
    $trayAdded = @(Select-String -LiteralPath $logPath -Pattern 'event=tray.icon_added').Count
    if ($trayAdded -lt 2) { throw "The packaged listener could not register both tray icons. See $logPath" }
    Write-Output "PASS: packaged checks, duplicate rejection, and two clean start/stop cycles. Tray registrations: $trayAdded."
    Write-Output "Log: $logPath"
    if ($MetricsOutput) {
        $metrics | ConvertTo-Json | Set-Content -LiteralPath $MetricsOutput -Encoding utf8
        $metrics | Format-Table | Out-String | Write-Output
    }
} finally {
    $env:LOCALAPPDATA = $previousLocalAppData
}
