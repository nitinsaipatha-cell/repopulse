@echo off
setlocal
cd /d "%~dp0"
set "NODE_ENV="

echo === RepoPulse start (Windows, no Docker) ===
echo.

if not exist "backend\.venv\Scripts\python.exe" (
  echo ERROR: backend\.venv not found. Run setup.bat first.
  exit /b 1
)
if not exist "frontend\node_modules\vite" (
  echo ERROR: frontend\node_modules not found. Run setup.bat first.
  exit /b 1
)

rem Load values from .env into this environment. The backend reads process
rem environment variables, not .env itself, and child processes inherit these.
if exist ".env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do (
    if not "%%a"=="" set "%%a=%%b"
  )
)

echo Backend  -^> http://localhost:8000
echo Frontend -^> http://localhost:5173
echo Stop each server with Ctrl+C in its own window.
echo.

start "RepoPulse Backend" /d "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

start "RepoPulse Frontend" /d "%~dp0frontend" cmd /k "npm run dev"

endlocal
exit /b 0
