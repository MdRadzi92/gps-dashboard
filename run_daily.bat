@echo off
REM Daily job for a laptop: runs at most once per day (first time it is triggered)
REM 1) analyse GPS files in inbox\   2) upload visits to Lark Base
cd /d "%~dp0"
if not exist logs mkdir logs

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%i

if exist logs\last_ok.txt (
  set /p LASTOK=<logs\last_ok.txt
) else (
  set LASTOK=none
)
if "%LASTOK%"=="%TODAY%" (
  echo Already ran OK today (%TODAY%), skipping.
  exit /b 0
)

echo ===== %date% %time% ===== >> logs\run.log

python analyze_visits.py >> logs\run.log 2>&1
if errorlevel 1 goto fail

python upload_to_lark.py >> logs\run.log 2>&1
if errorlevel 1 goto fail

python build_site_data.py >> logs\run.log 2>&1
if errorlevel 1 goto fail

REM publish dashboard data to GitHub Pages (only if this folder is a git repo)
if exist .git (
  git add docs/data.json >> logs\run.log 2>&1
  git commit -m "data %TODAY%" >> logs\run.log 2>&1
  git push >> logs\run.log 2>&1
)

echo %TODAY%> logs\last_ok.txt
echo RESULT: OK >> logs\run.log
exit /b 0

:fail
echo RESULT: FAILED - see messages above >> logs\run.log
exit /b 1
