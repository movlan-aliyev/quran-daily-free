# One-shot setup: pip install, .env (if missing), scheduled task at 10:30 daily.
# You must add SMTP_PASSWORD to .env (Outlook app password or use Gmail/SendGrid — see README).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== pip install ==" -ForegroundColor Cyan
python -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Write-Host "== creating .env (add SMTP_PASSWORD) ==" -ForegroundColor Cyan
    $envBody = @"
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=robert.movlan@outlook.com
SMTP_PASSWORD=
MAIL_FROM=robert.movlan@outlook.com
MAIL_TO=robert.movlan@outlook.com
CHUNK_SIZE=20
"@
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText("$PSScriptRoot\.env", $envBody, $utf8NoBom)
} else {
    Write-Host "== .env already exists; not overwriting ==" -ForegroundColor Yellow
}

Write-Host "== register scheduled task ==" -ForegroundColor Cyan
& "$PSScriptRoot\register_scheduled_task.ps1"

Write-Host ""
Write-Host "Done. If .env is new: set SMTP_PASSWORD, save, then run:  python send_daily_quran.py" -ForegroundColor Green
