@echo off
rem Double-click to run P2E Bridge locally with DEMO keys (for testing only; never use these keys for real data).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo .venv not found. Run once:  python -m venv .venv  and  .venv\Scripts\python -m pip install -r requirements-dev.txt
  pause
  exit /b 1
)
set P2E_DEMO_ACCOUNT=admin
set P2E_API_KEYS=planner:demo-planner-key-123456,supervisor:demo-supervisor-key-1234,admin:demo-admin-key-12345678
echo.
echo  P2E Bridge is starting at http://localhost:8000
echo  On the sign-in page press "Fill demo credentials", then set "As of" to 2026-09-16
echo  Keep this window open while you use the app. Close it to stop the server.
echo.
start "" http://localhost:8000
".venv\Scripts\python.exe" -m uvicorn p2e.main:app --port 8000
pause
