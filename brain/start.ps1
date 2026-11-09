Set-Location $PSScriptRoot
Write-Host "Starting Pizza Agent Brain on http://127.0.0.1:8000..." -ForegroundColor Green
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

