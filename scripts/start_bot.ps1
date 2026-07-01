# Inicia el bot autonomo de Telegram en segundo plano
$botDir = "C:\Users\miroi\Desktop\oficialRyu_Bot"
$logFile = "$botDir\servers\bot.log"

# Matar instancias previas
Get-Process -Name python* -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "telegram_bot_auto" } | Stop-Process -Force

# Iniciar bot en background
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "python"
$psi.Arguments = "servers/telegram_bot_auto.py"
$psi.WorkingDirectory = $botDir
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true

$proc = [System.Diagnostics.Process]::Start($psi)
Write-Host "Bot iniciado (PID: $($proc.Id))"
Write-Host "Log: $logFile"

# Mostrar PID para referencia
$proc.Id | Out-File -FilePath "$botDir\servers\bot.pid"
