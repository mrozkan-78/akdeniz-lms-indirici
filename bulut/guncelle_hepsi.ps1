# guncelle_hepsi.ps1 — Yeni moodle_indirici.py'yi hem bulut sunucusuna hem bu
# bilgisayara uygular, ikisini de yeniden başlatır ve durumu durum_sonuc.txt'ye yazar.
# Ayarlar (gizli_ayarlar.json) ve indirme geçmişi DOKUNULMADAN kalır.
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$App  = Split-Path -Parent $Here
$c = Get-Content (Join-Path $Here "bulut_baglanti.json") -Raw | ConvertFrom-Json
$t = "$($c.user)@$($c.ip)"
$o = @("-i", $c.key, "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=20")

Write-Host "1) Sunucu güncelleniyor..."
& scp @o (Join-Path $App "moodle_indirici.py") "${t}:~/moodle-indirici/moodle_indirici.py"
& ssh @o $t "sudo systemctl restart moodle-indirici && echo '   servis yeniden başladı'"

Write-Host "2) Bilgisayardaki görev yeniden başlatılıyor..."
schtasks /End /TN "Moodle Indirici" | Out-Null
Start-Sleep 3
schtasks /Run /TN "Moodle Indirici" | Out-Null

Write-Host "3) İlk giriş için 90 sn bekleniyor, sonra durum yazılacak..."
Start-Sleep 90
& (Join-Path $Here "durum.ps1")
Write-Host "Bitti. Sonuç: bulut\durum_sonuc.txt"
