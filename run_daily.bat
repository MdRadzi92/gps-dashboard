@echo off
REM Daily job: analyse GPS files in inbox\ then upload visits to Lark Base
cd /d "%~dp0"
if not exist logs mkdir logs
echo ===== %date% %time% ===== >> logs\run.log

python analyze_visits.py >> logs\run.log 2>&1
if errorlevel 1 goto fail

python upload_to_lark.py >> logs\run.log 2>&1
if errorlevel 1 goto fail

echo RESULT: OK >> logs\run.log
exit /b 0

:fail
echo RESULT: FAILED - see messages above >> logs\run.log
exit /b 1
