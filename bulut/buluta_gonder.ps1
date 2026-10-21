# buluta_gonder.ps1 — Moodle İndirici'yi bulut sunucusuna gönderip kurar.
# BULUTA_GONDER.bat ile çalıştırılır. Windows'un kendi ssh/scp araçlarını kullanır.
#
# Akış:
#  1. Sunucu IP'si ve Oracle'dan indirdiğin özel anahtar (.key) sorulur
#  2. Anahtar güvenli bir yere kopyalanır, izinleri düzeltilir
#  3. Bilgisayardaki Telegram gönderimi geçici olarak kapatılır (çift mesaj olmasın)
#  4. Betik, ayarlar ve indirme geçmişi sunucuya kopyalanır, kurulum çalıştırılır
#  5. Başarılıysa: telefona artık sunucu gönderir; bilgisayar sadece Masaüstüne indirir
#     Başarısızsa: bilgisayardaki Telegram gönderimi eski hâline döner

$ErrorActionPreference = "Stop"
$Here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir  = Split-Path -Parent $Here            # Documents\MoodleIndirici
$Conn    = Join-Path $Here "bulut_baglanti.json"
$Secrets = Join-Path $AppDir "gizli_ayarlar.json"
$Task    = "Moodle Indirici"

function Set-PcTelegram([bool]$on) {
    $j = Get-Content $Secrets -Raw -Encoding UTF8 | ConvertFrom-Json
    $j | Add-Member -NotePropertyName telegram_aktif -NotePropertyValue $on -Force
    $txt = $j | ConvertTo-Json
    [IO.File]::WriteAllText($Secrets, $txt, (New-Object Text.UTF8Encoding $false))
    schtasks /End /TN $Task | Out-Null
    Start-Sleep 2
    schtasks /Run /TN $Task | Out-Null
}

# --- 1) Bağlantı bilgileri (daha önce girildiyse hatırlanır) ---
$c = $null
if (Test-Path $Conn) { $c = Get-Content $Conn -Raw | ConvertFrom-Json }
if (-not $c) {
    $ip = Read-Host "Sunucunun Genel (Public) IP adresi"
    $user = Read-Host "Kullanıcı adı [Enter = ubuntu]"
    if (-not $user) { $user = "ubuntu" }
    Write-Host "Oracle'dan indirdiğin ÖZEL anahtar dosyasını (.key) seç..."
    Add-Type -AssemblyName System.Windows.Forms
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Title = "Sunucunun özel SSH anahtarını seç (ssh-key-....key)"
    $dlg.InitialDirectory = Join-Path $env:USERPROFILE "Downloads"
    $dlg.Filter = "Anahtar dosyaları (*.key;*.pem)|*.key;*.pem|Tüm dosyalar (*.*)|*.*"
    if ($dlg.ShowDialog() -ne "OK") { throw "Anahtar seçilmedi." }

    # --- 2) Anahtarı ~/.ssh altına kopyala ve izinlerini sadece sana ait yap ---
    $sshDir = Join-Path $env:USERPROFILE ".ssh"
    New-Item -ItemType Directory -Force $sshDir | Out-Null
    $key = Join-Path $sshDir "moodle_bulut.key"
    Copy-Item $dlg.FileName $key -Force
    icacls $key /inheritance:r /grant:r "$($env:USERNAME):(R)" | Out-Null

    $c = [pscustomobject]@{ ip = $ip.Trim(); user = $user.Trim(); key = $key }
    $c | ConvertTo-Json | Set-Content $Conn -Encoding UTF8
}
$target = "$($c.user)@$($c.ip)"
$sshOpts = @("-i", $c.key, "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=20")

Write-Host "`nSunucuya bağlanılıyor: $target" -ForegroundColor Cyan
& ssh @sshOpts $target "mkdir -p ~/moodle-kurulum"
if ($LASTEXITCODE -ne 0) { throw "Sunucuya bağlanılamadı. IP'yi ve anahtarı kontrol et (bulut_baglanti.json silinirse yeniden sorulur)." }

# --- 3) Bilgisayarın Telegram gönderimini geçici kapat ---
Write-Host "Bilgisayardaki Telegram gönderimi geçici olarak kapatılıyor..."
Set-PcTelegram $false

# --- 4) Dosyaları gönder ve kur ---
$files = @(
    (Join-Path $AppDir "moodle_indirici.py"),
    $Secrets,
    (Join-Path $Here "kurulum_bulut.sh")
)
$db = Join-Path $AppDir "indirilenler.db"
if (Test-Path $db) {
    # Çalışan betik kilitlemesin diye önce kopyasını al
    $dbCopy = Join-Path $env:TEMP "indirilenler.db"
    Copy-Item $db $dbCopy -Force
    $files += $dbCopy
}
Write-Host "Dosyalar gönderiliyor..."
& scp @sshOpts $files "${target}:~/moodle-kurulum/"
if ($LASTEXITCODE -ne 0) { Set-PcTelegram $true; throw "Dosyalar gönderilemedi." }

Write-Host "Sunucuda kurulum başlıyor (ilk seferde 5-10 dk sürebilir)...`n" -ForegroundColor Cyan
& ssh @sshOpts $target "sed -i 's/\r$//' ~/moodle-kurulum/kurulum_bulut.sh && bash ~/moodle-kurulum/kurulum_bulut.sh"
$code = $LASTEXITCODE

# --- 5) Sonuç ---
if ($code -eq 0) {
    Write-Host "`nBAŞARILI! Telefonuna artık bulut sunucusu gönderecek (bilgisayar kapalıyken de)." -ForegroundColor Green
    Write-Host "Bilgisayarın açıkken dosyaları yine Masaüstüne indirmeye devam edecek."
} else {
    Write-Host "`nSunucuda giriş/kurulum tamamlanamadı (kod $code)." -ForegroundColor Yellow
    Write-Host "Bilgisayardaki Telegram gönderimi eski hâline getiriliyor; hiçbir şey kaçmaz."
    Set-PcTelegram $true
}
