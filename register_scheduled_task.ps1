# Creates a Windows Scheduled Task: daily at 10:30 (uses your PC's local timezone).
# Set Windows to Eastern Time, or edit -At to match your offset.
# Run in PowerShell:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#                      .\register_scheduled_task.ps1

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $here "send_daily_quran.py"

$python = $null
foreach ($cmd in @("python", "py")) {
    $g = Get-Command $cmd -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($g) {
        if ($cmd -eq "py") {
            $python = (& py -3 -c "import sys; print(sys.executable)").Trim()
        } else {
            $python = $g.Source
        }
        break
    }
}
if (-not $python -or -not (Test-Path $python)) {
    Write-Error "Python 3 not found. Install from python.org and ensure 'python' is on PATH."
    exit 1
}

$arg = "`"$scriptPath`""
$action = New-ScheduledTaskAction -Execute $python -Argument $arg -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Daily -At "10:30"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

$taskName = "QuranDailyStudyEmail"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "Daily Quran email (quran-daily-free)" | Out-Null

Write-Host "Scheduled task '$taskName' created: daily at 10:30 (this PC's clock timezone)."
Write-Host "Ensure .env exists in: $here"
Write-Host "Test once:  $python $scriptPath"
