# github_yukle.ps1 - Projeyi GitHub'a guvenli sekilde yukler.
# GITHUB_YUKLE.bat ile calistirilir.
#   1) Git ve GitHub CLI yoksa winget ile kurar
#   2) GitHub girisi (tarayicida, sen onaylarsin)
#   3) Gizli dosyalarin depoya girmedigini KONTROL eder, varsa durur
#   4) Commit atar ve "akdeniz-lms-indirici" adli depoya gonderir

$ErrorActionPreference = "Continue"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here
$RepoName = "akdeniz-lms-indirici"
$RepoDesc = "Akdeniz Universitesi Moodle LMS icin otomatik ders dosyasi indirici + Telegram bildirimleri (Python, Playwright, Oracle Cloud)"

function Add-ToPath($dir) { if ((Test-Path $dir) -and ($env:Path -notlike "*$dir*")) { $env:Path = "$dir;$env:Path" } }
function Ensure-Tool($cmd, $wingetId, $dir) {
    Add-ToPath $dir
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "==> $cmd bulunamadi, kuruluyor ($wingetId)..." -ForegroundColor Yellow
        winget install -e --id $wingetId --silent --accept-package-agreements --accept-source-agreements
        Add-ToPath $dir
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd kurulamadi. Pencereyi kapatip GITHUB_YUKLE.bat'i tekrar calistir." }
    }
    Write-Host "    $cmd hazir." -ForegroundColor Green
}

Write-Host "==> 1/5 Araclar kontrol ediliyor"
Ensure-Tool "git" "Git.Git" "C:\Program Files\Git\cmd"
Ensure-Tool "gh"  "GitHub.cli" "C:\Program Files\GitHub CLI"

Write-Host "==> 2/5 GitHub girisi"
& gh auth status *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "    Ekranda cikan 8 haneli kodu kopyala, Enter'a bas; acilan tarayicida kodu girip onayla." -ForegroundColor Cyan
    & gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) { throw "GitHub girisi tamamlanamadi." }
}
& gh auth setup-git | Out-Null
$login = (& gh api user --jq .login).Trim()
$uid   = (& gh api user --jq .id).Trim()
Write-Host "    Giris yapildi: $login" -ForegroundColor Green

Write-Host "==> 3/5 Git deposu hazirlaniyor"
if (-not (Test-Path (Join-Path $Here ".git"))) { & git init -b main | Out-Null }
& git config user.name "Bayram Ozkan"
# E-posta adresin gizli kalsin diye GitHub'in noreply adresi kullanilir
& git config user.email "$uid+$login@users.noreply.github.com"
& git add -A

Write-Host "==> 4/5 Guvenlik kontrolu"
$staged = @(& git diff --cached --name-only) + @(& git ls-files)
$bad = $staged | Where-Object { $_ -match '(^|/)gizli_ayarlar\.json$|bulut_baglanti\.json$|\.key$|\.pem$|\.db$|\.log$|^tarayici_profili/|_sonuc\.txt$' }
if ($bad) {
    Write-Host "DURDURULDU: Su gizli dosyalar depoya girecekti:" -ForegroundColor Red
    $bad | Sort-Object -Unique | ForEach-Object { Write-Host "   $_" -ForegroundColor Red }
    & git reset -q
    exit 1
}
& git grep --cached -q -E "[0-9]{8,10}:[A-Za-z0-9_-]{35}"
if ($LASTEXITCODE -eq 0) {
    Write-Host "DURDURULDU: Kodun icinde Telegram token'a benzeyen bir deger var:" -ForegroundColor Red
    & git grep --cached -l -E "[0-9]{8,10}:[A-Za-z0-9_-]{35}"
    & git reset -q
    exit 1
}
Write-Host "    Temiz: sifre/token iceren dosya yok. Yuklenecek dosyalar:" -ForegroundColor Green
& git diff --cached --name-only | ForEach-Object { Write-Host "      $_" }

& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    $msg = @"
Ilk surum: Akdeniz LMS otomatik dosya indirici

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PdXBRKtsCDZ3HnAJ653j7Z
"@
    & git commit -q -m $msg
}

Write-Host "==> 5/5 GitHub'a gonderiliyor"
& git remote get-url origin *> $null
if ($LASTEXITCODE -ne 0) {
    & gh repo view "$login/$RepoName" *> $null
    if ($LASTEXITCODE -ne 0) {
        & gh repo create $RepoName --public --description $RepoDesc --source . --remote origin
        if ($LASTEXITCODE -ne 0) { throw "Depo olusturulamadi." }
    } else {
        & git remote add origin "https://github.com/$login/$RepoName.git"
    }
}
& git push -u origin main
if ($LASTEXITCODE -ne 0) { throw "Gonderme (push) basarisiz." }

$url = "https://github.com/$login/$RepoName"
Write-Host ""
Write-Host "TAMAM! Projen yayinda: $url" -ForegroundColor Green
"OK $url" | Out-File (Join-Path $Here "github_sonuc.txt") -Encoding utf8
Start-Process $url
