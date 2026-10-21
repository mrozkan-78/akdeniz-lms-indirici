# bulut_log.ps1 — Bulut sunucusundaki son 40 log satırını ve servis durumunu gösterir.
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$c = Get-Content (Join-Path $Here "bulut_baglanti.json") -Raw | ConvertFrom-Json
& ssh -i $c.key -o StrictHostKeyChecking=accept-new "$($c.user)@$($c.ip)" `
  "echo 'Servis:' `$(systemctl is-active moodle-indirici); echo; tail -n 40 ~/moodle-indirici/moodle_indirici.log"
