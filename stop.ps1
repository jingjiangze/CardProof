$ErrorActionPreference = "Stop"

try {
  Invoke-WebRequest -Method Post -UseBasicParsing -Uri "http://127.0.0.1:4173/api/shutdown" | Out-Null
  Write-Host "Stop request sent." -ForegroundColor Green
} catch {
  Write-Host "Could not reach the running app on 127.0.0.1:4173." -ForegroundColor Yellow
}
