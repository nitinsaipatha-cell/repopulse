@echo off
setlocal
cd /d "%~dp0"
set "NODE_ENV="

echo === RepoPulse setup (Windows, no Docker) ===
echo.

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created .env from .env.example.
  echo Edit .env to add a GitHub token if you want higher rate limits.
) else (
  echo .env already exists - left unchanged.
)
echo.

rem --- Python detection: prefer the pinned 3.12, then newer versions ---
set "PY="
for %%v in (3.12 3.13 3.14 3.11) do if not defined PY (
  py -%%v -V >nul 2>&1 && set "PY=py -%%v"
)
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo ERROR: Python not found. Install Python 3.12 or newer, then rerun.
  exit /b 1
)
echo Python command: %PY%

echo.
echo [1/3] Creating backend virtualenv and installing dependencies...
pushd backend
%PY% -m venv .venv
if errorlevel 1 (
  echo ERROR: could not create backend\.venv
  popd
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 (
  echo ERROR: pip install failed
  popd
  exit /b 1
)
popd

echo.
echo [2/3] Installing frontend dependencies...
pushd frontend
call npm ci --include=dev
if errorlevel 1 (
  echo ERROR: npm ci failed
  popd
  exit /b 1
)
popd

echo.
echo [3/3] Setup complete. Run start.bat to launch the app.
endlocal
exit /b 0
