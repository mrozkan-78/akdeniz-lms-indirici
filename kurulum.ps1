# kurulum.ps1 — Moodle İndirici kurulumu
# Bu klasörde sağ tık > "PowerShell ile Çalıştır" veya:
#   powershell -ExecutionPolicy Bypass -File .\kurulum.ps1
# Yaptıkları:
#   1) Python kurulu mu kontrol eder (yoksa winget ile kurar)
#   2) requirements.txt içindeki kütüphaneleri kurar (kuruluysa atlar)
#   3) Oturum açılışında pythonw ile sessiz başlayan bir Görev Zamanlayıcı görevi oluşturur

$ErrorActionPreference = "Stop"
$Here     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script   = Join-Path $Here "moodle_indirici.py"
$TaskName = "Moodle Indirici"

# --- 1) Python ---
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py -or $py -like "*WindowsApps*") {
    # WindowsApps altındaki 'python' gerçek kurulum değil, Store kısayoludur
    $py = (Get-Command py -ErrorAction SilentlyContinue).Source
    if ($py) { $py = (& py -3 -c "import sys;print(sys.executable)").Trim() }
}
if (-not $py) {
    Write-Host "Python bulunamadı, winget ile kuruluyor..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    $py = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
}
$pyw = Join-Path (Split-Path $py) "pythonw.exe"
Write-Host "Python: $py"

# --- 2) Kütüphaneler (zaten kuruluysa pip tekrar indirmez) ---
& $py -m pip install --user -r (Join-Path $Here "requirements.txt")

# --- 3) Görev Zamanlayıcı ---
# Çalışan eski görev varsa durdur (güncelleme sırasında)
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$action   = New-ScheduledTaskAction -Execute $pyw -Argument "`"$Script`"" -WorkingDirectory $Here
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
            -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Akdeniz LMS ders dosyalarını Masaüstü\Moodle_Dosyalari klasörüne indirir." -Force | Out-Null

Write-Host "Görev oluşturuldu: '$TaskName' (her oturum açılışında sessizce başlar)." -ForegroundColor Green
Write-Host "Şimdi başlatmak için: Start-ScheduledTask -TaskName '$TaskName'"
