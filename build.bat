@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

echo [1/4] Installing dependencies...
%PY% -m pip install -r requirements.txt
if errorlevel 1 (echo [FAIL] Dependency install failed & exit /b 1)

echo [2/4] Generating icon...
%PY% make_icon.py
if errorlevel 1 (echo [FAIL] Icon generation failed & exit /b 1)

echo [3/4] Building folder app (onedir)...
%PY% -m PyInstaller --noconfirm --clean BigScreenTerminal.spec
if errorlevel 1 (echo [FAIL] PyInstaller build failed & exit /b 1)

echo [4/4] Testing packaged executable...
%PY% verify_build.py dist\BigScreenTerminal\BigScreenTerminal.exe
if errorlevel 1 (echo [FAIL] Packaged executable self-test failed & exit /b 1)

echo.
echo Done. Output: dist\BigScreenTerminal\BigScreenTerminal.exe
echo.
echo Note: onedir build has NO runtime self-extraction, so it is far less
echo likely to be flagged by antivirus than single-file builds.
endlocal
