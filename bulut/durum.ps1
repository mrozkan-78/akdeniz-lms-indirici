# durum.ps1 — Bilgisayar ve bulut sunucusunun durumunu durum_sonuc.txt dosyasına yazar.
# Şifre veya token YAZDIRMAZ.
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$App  = Split-Path -Parent $Here
$out  = New-Object System.Collections.Generic.List[string]
$j = Get-Content (Join-Path $App "gizli_ayarlar.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$out.Add("PC telegram_aktif: " + $(if ($null -eq $j.telegram_aktif) { "(yok = acik)" } else { $j.telegram_aktif }))
$out.Add("PC gorev: " + ((schtasks /Query /TN "Moodle Indirici" /FO LIST | Select-String "Durum|Status") -join " "))
$c = Get-Content (Join-Path $Here "bulut_baglanti.json") -Raw | ConvertFrom-Json
$out.Add("Sunucu: $($c.user)@$($c.ip)")
$r = & ssh -i $c.key -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "$($c.user)@$($c.ip)" `
  "echo SERVIS: `$(systemctl is-active moodle-indirici); echo ARCH: `$(uname -m); echo DISK: `$(df -h ~ | tail -1); python3 -c \`"import json;d=json.load(open('/home/$($c.user)/moodle-indirici/gizli_ayarlar.json'));print('BULUT telegram_aktif:',d.get('telegram_aktif'),'| chat bagli:',bool(d.get('telegram_chat_id')))\`"; echo; echo '--- son log ---'; tail -n 30 ~/moodle-indirici/moodle_indirici.log" 2>&1
$out.AddRange([string[]]$r)
[IO.File]::WriteAllLines((Join-Path $Here "durum_sonuc.txt"), $out, (New-Object Text.UTF8Encoding $false))
